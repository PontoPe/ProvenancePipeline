# Session report — 2026-07-30

Autonomous session. Scope was the cluster half: Kyverno bootstrap, the
`verifyImages` policy, policy tests, the demo recording, and the docs. The
previous session's report is
[session-report-2026-07-29.md](session-report-2026-07-29.md).

Everything in scope landed. One significant assumption in the existing design
turned out to be backwards, and correcting it is the main content below.

## What works

A Kubernetes cluster now refuses images it cannot trace to this pipeline.

- Cluster: `kate-node-01`, kubeadm v1.34.10, Debian 13, Calico, single node.
- Kyverno v1.18.2, four controllers `1/1` under PSA `restricted` with a namespace
  `default-deny-all` plus four scoped allows. Nothing relaxed to make them start.
- `ClusterPolicy verify-provenance`, two rules, `Enforce`, `failurePolicy: Fail`.
- `kyverno test tests/ --registry` — 9 assertions, green.
- `docs/img/demo.gif`, and `docs/evidence/admission-enforcement.md` generated
  from the same script so they cannot drift.

Verified, not assumed:

| Case | Result |
|---|---|
| our image, signed, by digest | admitted, pod reaches `Running` and serves |
| `busybox` by digest, unsigned | denied |
| `reg.kyverno.io/kyverno/kyverno`, genuinely Sigstore-signed by Kyverno's workflow | denied |
| our image by tag instead of digest | denied, `missing digest for …:latest` |
| our signed image, policy pinned to a **different workflow in the same repo** | denied |
| our signed image, policy pinned to a **different OIDC issuer** | denied |

The last two are what make the first four mean anything. Without them a green
result only shows the policy did not get in the way.

## The thing that was wrong

**ADR-005 had the enforcement story exactly backwards, and it took having a
cluster to find out.**

It said: the `cosign attest --type slsaprovenance1` copy is what the cluster
enforces, and GitHub's is the one Kyverno cannot verify. Reality on GHCR:

- GHCR's referrers API answers **HTTP 404**.
- go-containerregistry, which Kyverno uses, falls back to the `sha256-<digest>`
  tag index.
- In that index, only GitHub's descriptor carries `artifactType`. The three
  written by cosign carry `application/vnd.oci.empty.v1+json`, their config
  media type.
- Kyverno's `fetchBundles` skips any descriptor lacking the
  `application/vnd.dev.sigstore.bundle` prefix. One bundle survives: GitHub's.

Proved by pinning `buildDefinition.buildType` two ways against the same image —
GitHub's value admits, cosign's denies.

`cosign verify-attestation` returns all four, because it reads each referrer
manifest rather than trusting the index descriptors. That asymmetry — same
registry, same image, two tools disagreeing about what is attached — is the
finding, and it is visible in the committed evidence file rather than merely
described.

ADR-009 records it. ADR-005's *decision* to attest twice is what saved the
project; only its explanation of which copy mattered was wrong. The stale claim
was corrected where it also appeared, in B4 and in the handoff, rather than left
to contradict the new ADR.

### What this cost, and the judgement call

Pinning cosign's attestation — what the brief instructed, and what every existing
document said to do — produces a policy that denies every image. The options were
to enforce what is actually verifiable, or to change CI so cosign's copy becomes
verifiable and enforce that.

I did the first, because the second is a CI change plus a release plus
re-verification, layered on enforcement that had not yet been shown to work at
all. But the policy is written so that choice is not load-bearing: it pins
`runDetails.builder.id`, the workflow repository and the ref, which are
**identical in both provenance documents**, and deliberately does not pin
`buildType`. If cosign's bundle later becomes discoverable, the policy keeps
working unchanged.

The remaining exposure is B5.

## What is broken, and I did not fix it

**B5 — enforcement depends on the repository staying public.**

`release.yml:220` gates `actions/attest-build-provenance` on
`if: steps.meta.outputs.private != 'true'`. That step now writes the only bundle
Kyverno can discover. Make the repository private again and every image built
afterwards is denied at admission, for reasons nobody will connect to a
visibility toggle weeks earlier.

The gate itself is correct — GitHub's attestations API genuinely refuses
user-owned private repos, which is B4. What is wrong is the coupling, and B4's
old note that the step "degrades cleanly" is true of CI and false of the cluster.

Not fixed because the fix is a CI change plus a release run, and the honest
sequencing was to land verified enforcement first. The route is in BLOCKED.md:
pin **cosign 2.x** in CI, whose default is the legacy `.sig`/`.att` layout that
Kyverno reads through its ordinary `type: Cosign` path with no referrers API
involved. That restores ADR-005's original intent and removes the dependency.

## Decisions taken in your absence

1. **`type: SigstoreBundle` instead of the default `Cosign`.** Forced by the
   registry, not preferred. cosign 3.x writes only the new bundle format and
   there are no legacy tags to read. Confirmed `cosign sign --help` on 3.1.2 has
   no `--new-bundle-format` rather than trusting memory — the brief suggested
   such a flag exists, and at this version it does not.
2. **`buildType` deliberately not pinned.** Above.
3. **Rule 2 is opt-in by namespace label.** The rule requiring *every* image to
   carry our signature applies only to namespaces labelled
   `provenancepipeline.io/admission: enforced`. Cluster-wide it would deny the
   KateClusters workloads in `app`, `observability`, `logging` and `falco` on
   their next restart — breaking someone else's cluster to make a point. Stated
   in the policy file and the README as the limitation it is.
4. **The NetworkPolicy ships here** (ADR-008), and applies the cluster's posture
   to the `kyverno` namespace rather than relaxing anything.
5. **Upstream Kyverno pinned by sha256, enforced rather than documented**
   (ADR-010), all five images by digest. `kubectl apply -k` alone no longer
   works; the Makefile runs the verified fetch first.
6. **A test case was removed rather than made to pass.** The tag-refusal case
   emits a `pass` and a `fail` for one resource, and `kyverno test` compares each
   declaration against every response, so it cannot be expressed. It is proved
   against the live cluster instead and the gap is stated at the top of the test
   file. Reshaping the fixture until it went green was the available alternative
   and would have been dishonest.
7. **The demo was re-recorded** after writing the recipe exposed a real defect:
   `asciinema --idle-time-limit` had permanently discarded the genuine
   verification pauses. `docs/demo-recording.md` §2.

## A prediction in the brief that was wrong

The brief warned that the cluster's default-deny egress would block Kyverno, and
that this was the same class of problem as Falco's ruleset fetch. It was not.

KateClusters' default-deny is **per-namespace**, not cluster-wide — there is no
Calico `GlobalNetworkPolicy`, verified. A freshly created `kyverno` namespace
therefore started **fully open**, in both directions. Nothing was blocked.

So `cluster/bootstrap/networkpolicy.yaml` is not unblocking Kyverno from an
inherited deny; it applies the cluster's posture to a namespace that would
otherwise have escaped it. Same file either way, opposite reasoning, and the
comment at the top of the file says so rather than letting the shape imply the
original story.

## For KateClusters — not done here, deliberately

Writing to sibling repos was out of scope. Two things belong there:

1. **Reference `cluster/bootstrap/networkpolicy.yaml`.** KateClusters' posture
   docs imply every namespace gets a default-deny. That is only true of
   namespaces it creates itself; anything installed later escapes it. Either say
   so, or add a Calico `GlobalNetworkPolicy` default-deny so the guarantee is
   structural. The second is the stronger fix, and would have made the brief's
   prediction correct.
2. **`AlwaysPullImages` is enabled** in `--enable-admission-plugins`. Worth
   noting in that repo's hardening docs — it is a real control, and it also means
   no demo there can rely on a warm image cache.

Also worth knowing: `vmrun.exe` lives under `C:\Program Files\VMware\`, not
`Program Files (x86)`, which is what several existing notes claim.

## Time sinks, for the next session

- `sudo -v` inside an `asciinema --command` hangs forever with no prompt to
  answer. Cost one wedged 10-minute run.
- `agg` needs a font installed *and* `--font-family` passed explicitly, and its
  fontdb warning is fontconfig being absent — which also means `fc-list` cannot
  be used to check whether the font is present.
- Kyverno `keyless` attestors are rejected at admission without `rekor.url` or
  `roots`, and the error does not indicate which to add.
- Kyverno attestation conditions evaluate with the **predicate** as the context
  root, so keys are `{{ runDetails.builder.id }}` and never
  `{{ predicate.runDetails.builder.id }}`. The error names the key you wrote, not
  the shape it wanted.
- `kubectl apply -k` on Kyverno needs `--server-side`; the CRDs exceed the
  262144-byte last-applied-configuration annotation limit.

## Honest summary

The project now does what it claimed: a cluster refuses an unsigned image, and
there is a recording of it. **SLSA Build L2, verified at admission** — enforcing
provenance at admission does not raise the build level, it makes the level
operationally meaningful, and those are different claims.

What should not be overstated: the deny-everything rule is opt-in per namespace,
four platform namespaces are excluded from the other rule, and the whole thing
currently rests on a GitHub feature gated on repository visibility. All three are
written down where someone would actually look, not only here.

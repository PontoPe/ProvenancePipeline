# PROGRESS — cluster-side enforcement

Source of truth for what is done and verified. Updated after every numbered step.
If a step is marked done here, do not redo it — confirm the state with the listed
command and move on.

Cluster: `kate-node-01`, kubeadm v1.34.10, Debian 13, Calico, single node,
`192.168.100.127`. Reached with `ssh kate`. `kubectl` needs
`sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf` in a non-interactive shell.

VMware snapshot `pre-kyverno` taken 2026-07-30 before any of this, while powered
off. Revert with:

```bash
& "C:\Program Files\VMware\VMware Workstation\vmrun.exe" revertToSnapshot "C:\Users\Pedro\Documents\Virtual Machines\kate-node-01\kate-node-01.vmx" pre-kyverno
```

Note `vmrun.exe` is under `C:\Program Files\VMware\...`, **not**
`C:\Program Files (x86)\VMware\...` as earlier notes said.

---

## Step 1 — `cluster/bootstrap` (Kyverno install) — DONE, verified

Kyverno v1.18.2 installed via kustomize, all five images pinned by digest, the
upstream manifest pinned by sha256 and the hash enforced at fetch time.

Command that proved it:

```
$ sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kyverno get pods
NAME                                             READY   STATUS    RESTARTS   AGE
kyverno-admission-controller-cfcff554b-kl4p6     1/1     Running   0          90s
kyverno-background-controller-67d887b64b-xg7wn   1/1     Running   0          90s
kyverno-cleanup-controller-6c8f748fc8-s56fd      1/1     Running   0          90s
kyverno-reports-controller-7f9d878cdc-dz2jv      1/1     Running   0          90s
```

All four run under Pod Security Admission `restricted` with a namespace
`default-deny-all` NetworkPolicy plus four scoped allows. Nothing was relaxed to
make them start.

One transient warning during startup, self-resolved once Kyverno minted its
serving cert:

```
Warning  Unhealthy  pod/kyverno-admission-controller-...  Startup probe failed:
Get "https://10.244.220.144:9443/health/liveness": remote error: tls: internal error
```

### Correction to the assumption this step was planned against

The brief predicted "egress default-deny will block Kyverno". It did not, because
KateClusters' deny is **per-namespace**, not cluster-wide — verified:

```
$ kubectl get globalnetworkpolicies.crd.projectcalico.org -A
No resources found
$ kubectl get netpol -A          # default-deny-all exists only in app, attack, falco, logging, observability
```

A freshly created `kyverno` namespace therefore started fully open. The policies
in `cluster/bootstrap/networkpolicy.yaml` are not unblocking Kyverno from an
inherited deny — they apply the cluster's posture to a namespace that would
otherwise have escaped it. Same file, opposite reasoning. Recorded in ADR-008.

Two other cluster facts worth carrying forward:

- The apiserver runs with an `AdmissionConfiguration` whose PodSecurity default is
  `restricted`, so an unlabelled namespace is restricted, not unrestricted.
- `AlwaysPullImages` is in `--enable-admission-plugins`. Every pod pull hits the
  registry, so an unsigned-image demo cannot rely on a warm local cache.

Next: step 2.

---

## Step 2 — prove Kyverno can verify these signatures — DONE, verified

Blocking finding, established before writing any policy. The registry holds
**four** Sigstore bundles for
`ghcr.io/pontope/provenancepipeline@sha256:5d4b03eae45558381b0236be7cacf0cf67d33a3711fb50ec8ab84a0efc692ea4`,
all with manifest-level `artifactType: application/vnd.dev.sigstore.bundle.v0.3+json`:

| referrer digest | DSSE predicateType | what it is | visible to Kyverno |
|---|---|---|---|
| `sha256:89ffb29d…` | `https://sigstore.dev/cosign/sign/v1` | `cosign sign` | **no** |
| `sha256:e4d547ba…` | `https://spdx.dev/Document` | `cosign attest` SBOM | **no** |
| `sha256:63c8a76d…` | `https://slsa.dev/provenance/v1`, buildType `…/ProvenancePipeline/build-types/github-actions/v1` | `cosign attest slsaprovenance1` | **no** |
| `sha256:fe9b28e0…` | `https://slsa.dev/provenance/v1`, buildType `https://actions.github.io/buildtypes/workflow/v1` | `actions/attest-build-provenance` | yes |

Why only one is visible: GHCR's referrers API returns **HTTP 404**, so
go-containerregistry — which Kyverno uses — falls back to the
`sha256-<digest>` tag index. In that index only GitHub's descriptor carries
`artifactType`; the three cosign descriptors carry
`application/vnd.oci.empty.v1+json` (their config media type) instead.
Kyverno's `fetchBundles` skips any descriptor whose artifactType lacks the
`application/vnd.dev.sigstore.bundle` prefix
(`pkg/image/verifiers/cpol/cosign/sigstore.go`), so it sees exactly one bundle:
GitHub's.

Verified with a raw registry walk, anonymous token, no cosign involved:

```
$ curl -sS -o /dev/null -w '%{http_code}\n' -H "$AUTH" \
    https://ghcr.io/v2/pontope/provenancepipeline/referrers/sha256:5d4b03ea…
404
$ curl -sS -H "$AUTH" -H "$ACC" \
    https://ghcr.io/v2/pontope/provenancepipeline/manifests/sha256-5d4b03ea… \
  | jq -r '.manifests[] | "\(.artifactType) \(.digest)"'
application/vnd.oci.empty.v1+json           sha256:63c8a76d…
application/vnd.oci.empty.v1+json           sha256:89ffb29d…
application/vnd.oci.empty.v1+json           sha256:e4d547ba…
application/vnd.dev.sigstore.bundle.v0.3+json sha256:fe9b28e0…
```

This directly inverts ADR-005, which says the cosign copy is the one the cluster
enforces and GitHub's is the one it cannot. On this registry it is the reverse.

### Attempt already made and abandoned — do not repeat

Publishing the legacy `sha256-<digest>.sig` layout from cosign 3.1.2 by flag.
There is no such flag. `cosign sign --help` on 3.1.2 lists `--bundle`,
`--registry-referrers-mode=legacy|oci-1-1` and `--signing-config`, and **no**
`--new-bundle-format`. cosign 3 removed the legacy writer; the format is not
selectable at this version. The remaining lever is the cosign *version*, not a
flag.

### Probe results — `type: SigstoreBundle` works, and both pins are load-bearing

Kyverno v1.18.2 supports the new bundle format through
`verifyImages[].type: SigstoreBundle`. Every case below was run in **Enforce**
with `failurePolicy: Fail`, against the live `latest` digest. `keyless` requires
`rekor.url` or `roots`, or the policy is rejected at admission:

```
spec.rules[0].verifyImages[0].attestors[0].entries[0].keyless: Invalid value: {...}:
Either Rekor URL or roots are required
```

| probe | image | expected | actual |
|---|---|---|---|
| correct subject + issuer | our signed digest | admit | **admitted** |
| correct subject + issuer | `busybox` (unsigned) | deny | **denied** |
| correct subject + issuer | `reg.kyverno.io/kyverno/kyverno` (signed, other identity) | deny | **denied** |
| **wrong subject** (different workflow, same repo) | our signed digest | deny | **denied** |
| **wrong issuer** (`accounts.google.com`) | our signed digest | deny | **denied** |

The last two are the ones that matter: they prove the policy is verifying the
identity rather than merely noticing that a signature exists, and they justify
pinning both values instead of one. Denial message in all cases:

```
sigstore bundle verification failed: no matching signatures found
```

### Which SLSA attestation is actually enforceable — ADR-005 is inverted

Attestation conditions are evaluated with the **predicate as the context root**,
not the in-toto statement. `EvaluateConditions` in
`pkg/engine/internal/utils.go` does `s["predicate"]` and adds that. So keys are
`{{ runDetails.builder.id }}`, never `{{ predicate.runDetails.builder.id }}`.
Getting this wrong produces:

```
failed to resolve predicate.buildDefinition.buildType at path /0/all/0/key:
JMESPath query failed: Unknown key "predicate" in path
```

With the path fixed, pinning `buildDefinition.buildType`:

| pinned buildType | belongs to | result |
|---|---|---|
| `https://actions.github.io/buildtypes/workflow/v1` | `actions/attest-build-provenance` | **admitted** |
| `https://github.com/PontoPe/ProvenancePipeline/build-types/github-actions/v1` | `cosign attest --type slsaprovenance1` | **denied** |

So the cluster can enforce **GitHub's** provenance and **cannot** enforce
cosign's — the exact opposite of what ADR-005 asserts. ADR-009 records this.

Consequence the policy is written around: both predicates agree on
`runDetails.builder.id`, `buildDefinition.externalParameters.workflow.repository`
and `.ref`. The policy pins those three and deliberately does not pin
`buildType`, so it holds against either provenance document and does not have to
be rewritten if cosign's bundle later becomes discoverable.

### Operational coupling this creates — important

`.github/workflows/release.yml:220` gates `actions/attest-build-provenance` on
`if: steps.meta.outputs.private != 'true'`. That step now produces the only
attestation the cluster can enforce. **If the repository is ever made private
again, new images will carry no enforceable provenance and this policy will deny
every one of them.** Previously that step was the optional extra; it is now
load-bearing. Not fixed in this session — see BLOCKED.md B5.

Next: step 3.

---

## Step 3 — `policies/kyverno/verify-images.yaml` — DONE, verified

`ClusterPolicy verify-provenance`, two rules, both `failureAction: Enforce`,
`webhookConfiguration.failurePolicy: Fail`.

- Rule 1 `verify-own-images` — images matching
  `ghcr.io/pontope/provenancepipeline*` in every namespace except `kube-system`,
  `kyverno`, `calico-system`, `tigera-operator`, each justified inline. Requires
  a signature and a SLSA v1 provenance attestation, with three conditions on the
  predicate content.
- Rule 2 `deny-unsigned-in-enforced-namespaces` — in namespaces labelled
  `provenancepipeline.io/admission: enforced`, **every** image must carry our
  signature.

Rule 2 is label-gated rather than cluster-wide, and that is a real limitation
stated in the file: this cluster belongs to KateClusters and runs workloads from
other pipelines in `app`, `observability`, `logging` and `falco`. A cluster-wide
`imageReferences: ["*"]` would deny those on their next restart.

`mutateDigest: false` with `verifyDigest: true`, so a tag is refused rather than
silently resolved to whatever it currently points at.

Verified — policy loaded `READY: True`, `VERIFY IMAGES: 2`:

```
########## 1 signed digest, enforced ns -> expect ADMIT
pod/signed created
########## 2 unsigned busybox, enforced ns -> expect DENY
  deny-unsigned-in-enforced-namespaces: 'failed to verify image docker.io/library/busybox@sha256:9532d8c3…:
    .attestors[0].entries[0].keyless: sigstore bundle verification failed: no matching signatures found'
########## 3 our image by TAG -> expect DENY (no digest)
  deny-unsigned-in-enforced-namespaces: missing digest for ghcr.io/pontope/provenancepipeline:latest
  verify-own-images: missing digest for ghcr.io/pontope/provenancepipeline:latest
########## 4 signed digest in default ns (rule 1 scope) -> expect ADMIT
pod/signed-default created
```

And the admitted pod actually runs, so nothing was mutated into something broken:

```
$ kubectl -n provenance-demo get pods
NAME     READY   STATUS    RESTARTS   AGE
signed   1/1     Running   0          33s
$ kubectl -n provenance-demo logs signed
{"time":"2026-07-30T13:13:56Z","level":"INFO","msg":"listening","addr":":8080",
 "version":"0.0.0-de7395b35bde7fd9d5f1f24020d9de0d6ab546b9",…}
```

Next: step 4 — `tests/`.

---

## Step 4 — `tests/` — DONE, verified

`kyverno test tests/ --registry`, 9 assertions, all green. `--registry` is not
optional: without it the CLI cannot fetch signatures and every case degrades to
an error, so a suite that passes without it has verified nothing. The Makefile
target passes it.

```
│ 1 │ verify-provenance │ verify-own-images                    │ v1/Pod/provenance-demo/signed-digest                     │ Pass │ Ok       │
│ 3 │ verify-provenance │ verify-own-images                    │ v1/Pod/default/signed-digest-other-namespace             │ Pass │ Ok       │
│ 5 │ verify-provenance │ deny-unsigned-in-enforced-namespaces │ v1/Pod/provenance-demo/unsigned-third-party              │ Pass │ Ok       │
│ 7 │ verify-provenance │ deny-unsigned-in-enforced-namespaces │ v1/Pod/provenance-demo/signed-by-another-identity        │ Pass │ Ok       │
│ 9 │ verify-provenance │ deny-unsigned-in-enforced-namespaces │ v1/Pod/default/unsigned-third-party-unenforced-namespace │ Pass │ Excluded │

Test Summary: 9 tests passed and 0 tests failed
```

Tooling installed on the node, both verified before use rather than curl-to-bash:

- `cosign` v3.1.2, sha256 checked against the release `cosign_checksums.txt`.
- `kyverno` CLI v1.18.2 — `cosign verify-blob --bundle checksums.txt.sigstore.json`
  with identity pinned to
  `https://github.com/kyverno/kyverno/.github/workflows/release.yaml@refs/tags/v1.18.2`
  and issuer `https://token.actions.githubusercontent.com` → `Verified OK`, then
  the tarball hashed against that now-trusted checksums file.

### Attempt made and abandoned — do not repeat

Testing the tag-reference denial through `kyverno test`. The rule emits two
responses for that resource, `pass` for the signature over the digest `:latest`
resolves to and `fail` for the missing digest, and the CLI compares each
declared result against *every* response. One declaration gives
`Want fail, got pass`; declaring both gives two mismatches. There is no way to
express it. The case is real and denied on the live cluster, so it is proved in
`docs/evidence/admission-enforcement.md` instead and the gap is stated at the
top of `tests/kyverno-test.yaml`. Do not reshape the fixture to make it green.

Makefile updated: `policy-install` now runs the checksum-verified fetch and uses
`--server-side` (Kyverno's CRDs exceed the 262144-byte last-applied-configuration
annotation limit that a client-side apply writes), and `policy-test` passes
`--registry`.

Next: step 5 — evidence file and the demo recording.

---

## Step 5 — evidence file and demo recording — DONE

- `scripts/demo.sh` — the four admission cases plus `cosign verify-attestation`.
- `scripts/collect-admission-evidence.sh` — runs `demo.sh` and wraps its verbatim
  stdout into `docs/evidence/admission-enforcement.md`. ADR-007 says evidence is
  generated, never transcribed; there is no cluster in CI, so the equivalent
  guarantee is that the evidence file and the recorded GIF are the same script.
- `docs/img/demo.gif` — 957x987, 31 s, 494 KB. `docs/img/demo.cast` is committed
  alongside it so the GIF can be re-rendered without re-running the cluster.

Recorded with `asciinema rec --command`, converted with
`agg --font-family "DejaVu Sans Mono" --idle-time-limit 5 --speed 0.6 --last-frame-duration 6`.

Two things that cost time, for whoever does this next:

- `sudo -v` inside the recorded command hangs forever under `ssh -tt`. sudo is
  NOPASSWD on this node, so just drop it.
- `agg` fails on the headless VM with `Error: no faces matching font family
  options` until `fonts-dejavu-core` is installed, and then still needs
  `--font-family "DejaVu Sans Mono"` passed explicitly.
- The first render was 10 s total with 60 ms frames — unreadable. The
  `--speed`/`--idle-time-limit`/`--last-frame-duration` values above are what
  make it legible; check the per-frame durations rather than assuming.

Also resolved incidentally: **B1 is gone.** `cosign verify` and
`cosign verify-attestation` both succeed from the node with no registry
credentials at all, because the GHCR package is public
(`gh api user/packages/container/provenancepipeline --jq .visibility` → `public`,
103 versions). No `read:packages` scope is needed any more.

Next: step 6 — README, ADRs, handoff, session report.

---

## Step 6 — docs — DONE

- `docs/architecture.md` — ADR-008 (NetworkPolicy ownership), **ADR-009**
  (the cluster enforces GitHub's provenance, correcting ADR-005), ADR-010
  (install integrity). ADR-005's status header now points at ADR-009 rather than
  leaving two documents disagreeing.
- `docs/threat-model.md` — T1/T3/T6/T8 rewritten from "planned" to "enforced,
  and here is the evidence", and **T9 added** for the visibility coupling, with
  its mitigation column honestly reading *None*.
- `README.md` — the GIF at the top, roadmap boxes ticked, layout table, a "what
  is not proven" section that names the label-gated scope and B5, and an SLSA
  section that says **Build L2, verified at admission** and explains why
  enforcement does not raise the level.
- `docs/BLOCKED.md` — B1 and B3 resolved with the resolving output pasted in,
  originals kept collapsed, **B5 added**, and the false claim in B4 corrected in
  place instead of quietly deleted.
- `docs/PROVEhandoff.md`, `CLAUDE.md` — current state, the corrected §3, cluster
  gotchas.
- `docs/session-report.md` — this session. The previous one is now
  `docs/session-report-2026-07-29.md`.
- `docs/demo-recording.md` + `scripts/demo-record.sh` — the recording recipe,
  extracted so the sibling repos do not rediscover it. Writing it exposed that
  the first recording had been made with `asciinema --idle-time-limit`, which
  permanently discards real pauses, so the demo was re-recorded raw.

## Final state, verified 2026-07-30

```
$ kyverno test tests/ --registry
Test Summary: 9 tests passed and 0 tests failed

$ kubectl get clusterpolicy
NAME                ADMISSION   BACKGROUND   READY   AGE   MESSAGE
verify-provenance   true        false        True    38m   Ready

$ kubectl -n kyverno get pods
kyverno-admission-controller-cfcff554b-kl4p6     1/1 Running
kyverno-background-controller-67d887b64b-xg7wn   1/1 Running
kyverno-cleanup-controller-6c8f748fc8-s56fd      1/1 Running
kyverno-reports-controller-7f9d878cdc-dz2jv      1/1 Running

$ kubectl -n kyverno get netpol --no-headers | wc -l
5
```

All six steps done. The one thing left that affects whether enforcement keeps
working is **B5** — see `docs/BLOCKED.md` and step 2 above for why.

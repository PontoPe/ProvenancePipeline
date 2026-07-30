# Architecture — Provenance Pipeline

The high-level diagram lives in the [README](../README.md). This file records
**why**, not what.

## Decisions

Each decision: context, options considered, choice, consequence. Keep them
short; append, never rewrite.

### ADR-001 — A stdlib-only Go service as the workload

- **Status:** accepted (2026-07-29)
- **Context:** the pipeline has to build *something*. The artifact is the point,
  not the app, but the choice of app leaks into everything downstream: the size
  of the SBOM, the CVE surface the gate sees, and whether a CRITICAL finding is
  a real signal or a base-image accident.
- **Options:**
  - A Node or Python service. Realistic, and guarantees a steady stream of
    transitive-dependency CVEs — which would make the gate noisy and tempt
    exactly the "just raise the threshold" move this repo argues against.
  - A Go service with third-party modules (chi, zap). Idiomatic, moderate SBOM.
  - A Go service with **no** third-party modules. 7 packages in the SBOM, all
    attributable to the Go toolchain and the base image.
- **Decision:** stdlib only. `app/go.mod` has no `require` block and there is no
  `go.sum`.
- **Consequences:** the SBOM is small enough to read by eye, and any CVE the
  gate reports is a genuine toolchain or base-image issue rather than noise —
  which is what makes a hard-fail gate sustainable. The cost is that the app
  does not demonstrate dependency management; that is a deliberate trade, and a
  reviewer who wants to see a fat SBOM will not find one here.

### ADR-002 — Base images pinned by digest, multi-stage, distroless nonroot

- **Status:** accepted (2026-07-29)
- **Context:** the runtime image is the largest single contributor to both the
  CVE count and the blast radius of a container escape.
- **Options:**
  - `alpine` runtime — small, but ships a shell, a package manager and musl,
    all of which are attack surface and CVE sources.
  - `scratch` — smallest possible, but no CA bundle, no `/etc/passwd`, no
    timezone data, and nothing to attach a `nonroot` user to.
  - `gcr.io/distroless/static-debian12:nonroot` — no shell, no package manager,
    ships CA certs and a `nonroot` (65532) user.
- **Decision:** multi-stage build. `golang:1.26-alpine` to compile, digest
  `sha256:0178a641…`; `gcr.io/distroless/static-debian12:nonroot` to run, digest
  `sha256:f5b485ea…`. `USER 65532:65532` is restated in the Dockerfile even
  though the base already sets it.
- **Consequences:** the tag → digest pin is the same argument the admission
  policy makes about tags, applied to what this pipeline *consumes* rather than
  what it produces. It is not consistent to refuse mutable tags at admission
  while building on one. The cost is that base updates are now a deliberate
  commit — digests do not drift on their own, which is the point, but it does
  mean a stale pin is a silent liability and needs a bump when the gate flags it.
  The explicit `USER` line means a future base swap cannot silently reintroduce
  root.

### ADR-003 — The vulnerability gate fails at CRITICAL, and never soft-fails

- **Status:** accepted (2026-07-29)
- **Context:** a gate has to sit somewhere between "blocks nothing" and "blocks
  every build", and the honest failure mode of the strict end is that someone
  disables it under deadline pressure.
- **Options:**
  - Fail on HIGH or above. Defensible on paper; in practice HIGH findings with
    no fix available are common in base images, so this converts into either
    constant allowlisting or a disabled gate.
  - Fail on CRITICAL, hard. Blocks the findings nobody argues about.
  - Fail on CRITICAL but with `continue-on-error` / `soft_fail` so the run stays
    green and someone reads the report later. Nobody reads the report later.
- **Decision:** `severity-cutoff: critical`, `fail-build: true`, no
  `continue-on-error`, no allowlist, no ignore file. The threshold is a stated
  judgement, not a hidden one.
- **Consequences:** MEDIUM and HIGH findings ship. That is a real gap and it is
  written down in the threat model (T2) rather than papered over. If a CRITICAL
  ever appears, the fix is to move the base image or update the dependency —
  raising the threshold to clear a build would invalidate the only claim this
  repository makes. The narrow SBOM from ADR-001 is what keeps this affordable.

### ADR-004 — buildx's own attestations are disabled

- **Status:** accepted (2026-07-29)
- **Context:** `docker/build-push-action` attaches SLSA provenance and an SBOM
  as extra manifests in the pushed OCI index by default.
- **Options:**
  - Leave them on and sign the result. The index then holds several subjects,
    the digest cosign signs becomes ambiguous to reason about, and the build
    carries two provenance documents with different formats and trust stories —
    one unsigned.
  - Turn them off and produce signed equivalents explicitly.
- **Decision:** `provenance: false`, `sbom: false`. The SBOM comes from `syft`
  and is attested with cosign; provenance is attested twice, per ADR-005.
- **Consequences:** one subject, one digest, and every attestation on the image
  is signed and identity-bound. Slightly more workflow code in exchange for
  being able to say precisely what is attached and who signed it.

### ADR-005 — SLSA provenance is attested twice, deliberately

- **Status:** accepted (2026-07-29). **Decision stands; its central consequence
  was wrong and is corrected by [ADR-009](#adr-009--the-cluster-enforces-githubs-provenance-not-cosigns).**
  Attesting twice turned out to be what saved the project — but the reason given
  below for *which* copy matters is backwards on GHCR.
- **Context:** the scope called for `actions/attest-build-provenance`. On a
  user-owned private repository it fails outright:
  `Feature not available for user-owned private repositories.` More importantly,
  even where it succeeds, the enforcement target is Kyverno `verifyImages` —
  which speaks cosign and Sigstore, and cannot shell out to `gh attestation
  verify`.
- **Options:**
  - GitHub's attestation only. Verifiable with `gh`, not enforceable by the
    cluster, and unavailable while the repo is private.
  - A cosign `slsaprovenance1` attestation only. Enforceable by Kyverno and in
    public Rekor, but drops the GitHub-native artifact the scope asked for.
  - Both.
- **Decision:** both. The workflow builds a SLSA v1 predicate from the GitHub
  context and attaches it with `cosign attest --type slsaprovenance1`, and also
  runs `actions/attest-build-provenance`, gated on the repository's real
  visibility.
- **Consequences:** the image carries two provenance documents with different
  `buildType`s — this repo's own, and
  `https://actions.github.io/buildtypes/workflow/v1`. Both are visible in the
  evidence file. The cosign one is the copy the future admission policy will
  pin. The duplication is the honest cost of the enforcement target and the
  scope wanting different things; the alternative was to claim GitHub's
  attestation would be enforced at admission, which is not true.

### ADR-006 — The verify job includes a negative control

- **Status:** accepted (2026-07-29)
- **Context:** a verification step that only ever runs against a correctly
  signed artifact cannot distinguish "the signature checks out" from "the
  command silently no-ops".
- **Decision:** the `verify` job also runs `cosign verify` against a digest that
  was never signed and **fails the build if that succeeds**.
- **Consequences:** a green run now proves the verifier can say no. This is the
  command-line rehearsal of the demo the repository is ultimately built around;
  the cluster-side version is roadmap items 4–7.

### ADR-007 — The evidence file is generated by CI, not written by hand

- **Status:** accepted (2026-07-29)
- **Context:** evidence transcribed into a document drifts from reality on the
  next change, and a stale claim in a security repo is worse than no claim.
- **Decision:** the `verify` job captures real stdout of every verification into
  `evidence.md`, uploads it as an artifact, and it is committed verbatim to
  `docs/evidence/supply-chain-verification.md` with the run URL in the header.
- **Consequences:** the evidence can always be regenerated and diffed against
  what is committed. It also means the file is only as fresh as the last time
  someone downloaded and committed it — the run URL in the header is what makes
  that checkable.

### ADR-008 — Kyverno's network policy ships in this repo, not in KateClusters

- **Status:** accepted (2026-07-30)
- **Context:** Kyverno needs egress to GHCR and to the Sigstore TUF endpoint to
  verify anything, and ingress from the API server on 9443 or admission fails
  closed. The cluster is owned by the sibling [KateClusters](../../KateClusters)
  repo, which applies a `default-deny-all` NetworkPolicy to each namespace it
  creates.
- **What was actually found:** the prediction that a cluster-wide default-deny
  would block Kyverno was **wrong**. There is no Calico `GlobalNetworkPolicy`
  and the deny is per-namespace, so a newly created `kyverno` namespace started
  with no NetworkPolicy at all — fully open, in both directions.
- **Options:**
  - Add the allow rules to KateClusters. Rejected: it makes a cluster repo carry
    knowledge of an application repo's dependencies, and this session is not
    permitted to write there anyway.
  - Leave the namespace open, since nothing was blocking Kyverno. Rejected: it
    would leave the enforcement plane as the one namespace on the cluster
    exempt from the cluster's own posture, which is the opposite of the point.
  - Ship `default-deny-all` plus scoped allows in `cluster/bootstrap/`.
- **Decision:** the third. Whoever installs Kyverno owns Kyverno's network
  requirements. Five policies: default-deny, DNS to `kube-system`, the API
  server endpoint on 6443, TCP 443 to `0.0.0.0/0` minus RFC1918 for the registry
  and Sigstore, and ingress on 9443 from the node address. Shape and exclusion
  list copied from KateClusters' `falco/allow-falco-ruleset-fetch` so the two
  repos read the same.
- **Consequences:** a compromised Kyverno pod can reach the public internet on
  443 and nothing on the LAN or in-cluster. The node address is hardcoded, which
  is honest for a known single-node cluster and must be widened to the
  control-plane subnet for a multi-node one. KateClusters should reference this
  policy so the two do not drift; that is recorded in the session report rather
  than done, because writing to the sibling repo was out of scope.

### ADR-009 — The cluster enforces GitHub's provenance, not cosign's

- **Status:** accepted (2026-07-30). Corrects the consequence stated in ADR-005.
- **Context:** ADR-005 concluded that the `cosign attest --type slsaprovenance1`
  copy is "the copy the future admission policy will pin", because Kyverno
  speaks cosign and cannot call `gh attestation verify`. Written before there
  was a cluster to test it on, that turned out to be exactly backwards.
- **What the registry actually contains:** four Sigstore bundles per image, each
  with a manifest-level `artifactType` of
  `application/vnd.dev.sigstore.bundle.v0.3+json` — `cosign sign`, the SBOM
  attestation, cosign's SLSA provenance, and
  `actions/attest-build-provenance`'s SLSA provenance. There are no legacy
  `.sig`/`.att` tags, because cosign 3.x writes only the new bundle format.
- **Why Kyverno sees one of the four:** GHCR's referrers API answers **HTTP
  404**, so go-containerregistry falls back to the `sha256-<digest>` tag index.
  In that index only GitHub's descriptor carries `artifactType`; the three
  written by cosign carry `application/vnd.oci.empty.v1+json`, their config
  media type. Kyverno's `fetchBundles` skips any descriptor without the
  `application/vnd.dev.sigstore.bundle` prefix, so exactly one bundle survives
  the filter — GitHub's. `cosign verify-attestation` returns all four, because
  it reads each referrer manifest rather than trusting the index descriptors.
  That asymmetry is the whole finding.
- **Options:**
  - Publish the legacy layout as well, so `type: Cosign` has something to read.
    **Not available.** `cosign sign --help` on 3.1.2 offers `--bundle`,
    `--registry-referrers-mode=legacy|oci-1-1` and `--signing-config`, and no
    `--new-bundle-format`. cosign 3 removed the legacy writer; the only lever
    left is downgrading cosign in CI, which was not done this session.
  - Pin `buildDefinition.buildType` to GitHub's value. Works today, and locks
    the policy to whichever writer the registry happens to expose.
  - Require a SLSA v1 provenance attestation signed by the pinned identity, and
    assert only on fields both documents agree about.
- **Decision:** the third. The policy pins `runDetails.builder.id`,
  `buildDefinition.externalParameters.workflow.repository` and `.ref` — identical
  in both predicates — and deliberately does not pin `buildType`. Verified
  empirically: pinning GitHub's buildType admits, pinning cosign's denies.
- **Consequences:** enforcement works today and would keep working unchanged if
  cosign's bundle ever became discoverable, so this is not a bet on one writer.
  The uncomfortable part is that `actions/attest-build-provenance` is now
  load-bearing while `.github/workflows/release.yml` still gates it on
  `if: steps.meta.outputs.private != 'true'` — **if the repository is made
  private again, new images carry no enforceable provenance and this policy
  denies every one of them.** Recorded as B5. ADR-005's decision to attest twice
  is vindicated; only its explanation of which copy mattered was wrong.

### ADR-010 — The enforcement plane is installed the way this repo demands of everything else

- **Status:** accepted (2026-07-30)
- **Context:** the usual Kyverno install is `kubectl apply -f` against a release
  URL, or a Helm chart pulling images by tag. A repository whose entire argument
  is "verify provenance before you run it" cannot bootstrap its own admission
  controller that way without undermining itself.
- **Decision:** `cluster/bootstrap/fetch-upstream.sh` downloads the pinned
  v1.18.2 `install.yaml` and **enforces** a sha256 from `upstream.sha256`,
  refusing to install on mismatch. All five controller images are pinned by
  digest through the kustomize `images` transformer. The manifest itself is not
  committed — 5.7 MB of generated CRDs — but the hash is, which is the part that
  carries the guarantee. The `kyverno` CLI used for the tests was installed by
  verifying `checksums.txt` with `cosign verify-blob` against Kyverno's pinned
  release identity, then hashing the tarball against that.
- **Consequences:** `kubectl apply -k cluster/bootstrap` alone no longer works;
  the fetch has to run first, and `make policy-install` does it. A re-cut
  upstream release fails the install loudly instead of silently changing what
  gets deployed. `--server-side` is required because Kyverno's CRDs exceed the
  262144-byte limit on the annotation a client-side apply writes.

## Component detail

| Component | Responsibility | Notes |
|-----------|----------------|-------|
| `app/` | The workload being signed | Go, stdlib only, no third-party modules (ADR-001) |
| `build/Dockerfile` | Reproducible, non-root image | Multi-stage, digest-pinned bases, `-trimpath -buildid=` (ADR-002) |
| `.github/workflows/release.yml` | Build → SBOM → gate → sign → attest → verify | Actions pinned by commit SHA |
| `scripts/collect-evidence.sh` | Local regeneration of the evidence file | Needs registry read; see BLOCKED.md B1 |
| `Makefile` | Local equivalents of every CI step | POSIX; run from Git Bash or WSL |
| `cluster/bootstrap/` | Kyverno install + its network policy | Upstream sha256-enforced, images digest-pinned (ADR-010, ADR-008) |
| `policies/kyverno/` | `verifyImages` enforcement | `Enforce`, `failurePolicy: Fail`, `type: SigstoreBundle` (ADR-009) |
| `tests/` | Policy tests, allow and deny | `kyverno test tests/ --registry` |
| `scripts/demo.sh` | The four admission cases | Recorded as `docs/img/demo.gif`, captured as evidence |

## Open questions

- [ ] Does the SLSA v1 predicate need `byproducts` / `metadata.startedOn` to
      satisfy a strict L2 verifier, or is builder + materials enough for the
      claim being made?
- [ ] Rekor monitoring (T7) has no automation. Worth a scheduled workflow that
      lists entries for the identity and diffs against expected builds?
- [ ] Base image digests are pinned and therefore static. Renovate/Dependabot to
      bump them, or a scheduled `grype` re-scan of the published digest so a new
      CVE against an old image surfaces without a rebuild?

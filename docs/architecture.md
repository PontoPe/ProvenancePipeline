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

- **Status:** accepted (2026-07-29)
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

## Component detail

| Component | Responsibility | Notes |
|-----------|----------------|-------|
| `app/` | The workload being signed | Go, stdlib only, no third-party modules (ADR-001) |
| `build/Dockerfile` | Reproducible, non-root image | Multi-stage, digest-pinned bases, `-trimpath -buildid=` (ADR-002) |
| `.github/workflows/release.yml` | Build → SBOM → gate → sign → attest → verify | Actions pinned by commit SHA |
| `scripts/collect-evidence.sh` | Local regeneration of the evidence file | Needs registry read; see BLOCKED.md B1 |
| `Makefile` | Local equivalents of every CI step | POSIX; run from Git Bash or WSL |
| `policies/kyverno/` | `verifyImages` enforcement | Not written — blocked on a cluster |

## Open questions

- [ ] Does the SLSA v1 predicate need `byproducts` / `metadata.startedOn` to
      satisfy a strict L2 verifier, or is builder + materials enough for the
      claim being made?
- [ ] Rekor monitoring (T7) has no automation. Worth a scheduled workflow that
      lists entries for the identity and diffs against expected builds?
- [ ] Base image digests are pinned and therefore static. Renovate/Dependabot to
      bump them, or a scheduled `grype` re-scan of the published digest so a new
      CVE against an old image surfaces without a rebuild?

# ProvenancePipeline — context for Claude Code

Read this before touching anything. It is the handoff between sessions.

## What this is

A software supply-chain pipeline: build → SBOM → vulnerability scan → keyless signature → SLSA provenance attestation → admission control that refuses anything unsigned. Portfolio artifact for cloud-security roles, positioned as the CKA→CKS bridge.

The deliverable is **the rejection**, not the pipeline. Anyone can show a green CI run. The recorded demo where a cluster refuses an unsigned image is the thing few junior candidates have.

Owner: Pedro (GitHub `PontoPe`). Repo: `github.com/PontoPe/ProvenancePipeline`, private until there is real content.

## Where things stand

Done:

- Scaffolding only. README with architecture diagram + threat model table, `docs/threat-model.md`, `docs/architecture.md` (ADR skeleton), `Makefile`, `.github/workflows/release.yml`, directory tree.
- **No application code, no Dockerfile, no policies written yet.**

Blocked on:

- The admission-control half needs a running cluster. That is [KateClusters](../KateClusters) — a self-hosted Debian box, not yet built either.
- `cosign`, `syft`, `grype` not installed on the workstation. `docker` is (Docker Desktop).

Not blocked:

- The CI half (build → SBOM → scan → sign → attest) runs entirely on GitHub Actions against GHCR. **Start here.** It produces signed artifacts with attestations before any cluster exists, and `cosign verify` proves it from the command line.

Order of work:

1. `app/` + `build/Dockerfile` — a minimal service. Small and boring on purpose; the artifact is the point, not the app.
2. `release.yml` end to end: build → push GHCR → `syft` SBOM → `grype` gate → `cosign sign` keyless → `cosign attest` → `actions/attest-build-provenance`.
3. Verify locally with `make verify` — this is the proof the signature is bound to the expected workflow identity.
4. `cluster/bootstrap` — Kyverno install (needs KateClusters up).
5. `policies/kyverno` — `verifyImages` in **Enforce**, issuer + subject pinned.
6. `tests/` — policy tests covering both the allow and the deny path.
7. Record the demo GIF: signed pod admitted, unsigned pod denied, `cosign verify-attestation` printing provenance.
8. Writeup: what SLSA level this actually reaches, and what it does not. Be honest — overstating it is worse than a lower number.

## Decisions already made — do not relitigate

| Decision | Rationale |
|---|---|
| Keyless signing (Fulcio/Rekor), no key pair | Nothing durable to steal. The GitHub OIDC identity is the trust anchor. |
| Kyverno, not Gatekeeper or the sigstore policy-controller | `verifyImages` is purpose-built for this, and the policy reads clearly in a README. |
| Policy in `Enforce` with `failurePolicy: Fail` | Trades availability for integrity, deliberately. A fail-open admission webhook proves nothing. |
| GHCR as registry | Free, ties naturally to the OIDC identity, no extra account. |
| Digests pinned, tags never trusted | Signatures cover digests; a tag is a mutable pointer. |
| `grype` gate at CRITICAL | A gate that blocks everything gets disabled. Threshold is a judgment call and is documented, not hidden. |

## Conventions

- Actions pinned by SHA, not by tag — the supply-chain repo cannot itself have an unpinned supply chain.
- The `verifyImages` policy pins **both** `--certificate-identity` and `--certificate-oidc-issuer`. Identity alone is forgeable by a different issuer.
- Namespace exclusions in the policy are enumerated and justified in a comment. Excluding `kube-system` is pragmatic; hiding that is not.
- Docs are part of the deliverable. A change to the trust model updates `docs/threat-model.md` in the same commit.
- Commits: Conventional Commits, author `heavensnipe@gmail.com`.

## Environment gotchas

Windows 11, PowerShell 7. These have already cost time on the sibling repo:

- PowerShell `&&` short-circuits — chained checks stop at the first failure and the rest silently never run.
- `winget install` takes one package ID per invocation; passing several fails.
- After any `winget install`, a new terminal is needed for `PATH`.
- Makefiles here assume a POSIX shell. Run them from Git Bash or WSL.
- Installed: docker, kubectl (via Docker Desktop), terraform 1.15.8, trivy 0.72.0. Missing: `cosign`, `syft`, `grype` — `winget install Sigstore.Cosign`, `Anchore.Syft`, `Anchore.Grype`.

## Sibling repos

Under `C:\Users\Pedro\Documents\Coding\`: `AwLZ` (AWS landing zone, in progress), `KateClusters` (the cluster this repo's policies run on), `PontoAntiCrack` (AWS detection and response). Cross-referenced from each README.

## Working style the user expects

- Terse. No preamble, no restating the question. Fragments are fine.
- Security warnings and multi-step procedures get written out clearly, not compressed.
- Verify before claiming: run the linters and the policy tests rather than asserting the code is fine.
- When a recommendation turns out wrong, correct it in one line and move on.

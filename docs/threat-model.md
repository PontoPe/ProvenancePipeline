# Threat model — Provenance Pipeline

## Scope

The path from source commit to a running container: CI build, SBOM, scan, signing, attestation, registry, and admission control. The application's own logic is out of scope; the cluster's runtime hardening lives in [KateClusters](../../KateClusters).

## Assets

| Asset | Why it matters |
|-------|----------------|
| Build workflow (`release.yml`) | Anything it produces is trusted downstream |
| OIDC identity used for keyless signing | It *is* the trust anchor — no key, the identity is the secret |
| Registry (image + `.sig` + `.att`) | Distribution point; write access here is the obvious attack |
| Kyverno `verifyImages` policy | The only thing that turns signatures into enforcement |
| Rekor transparency log entries | Independent evidence a signature existed at a point in time |

## Trust boundaries

1. Developer → CI (crossed by a merged commit)
2. CI → registry (crossed by an authenticated push)
3. Registry → cluster (crossed by an image pull, gated by admission)
4. CI → Sigstore/Fulcio (crossed by an OIDC token exchange)

## Threats

| # | Threat | Likelihood | Impact | Control | Residual risk |
|---|--------|-----------|--------|---------|---------------|
| T1 | Attacker with registry write pushes a malicious image under a known tag | Med | High | Admission verifies a cosign signature bound to this repo's workflow identity; digests pinned, tags untrusted | Requires policy in `Enforce` with no namespace exclusions |
| T2 | Vulnerable dependency ships to prod | High | Med | `grype` gate on CRITICAL; SBOM attestation enables retroactive CVE queries | Gate threshold is a judgment call; MED/HIGH still ship |
| T3 | Build step tampering (compromised action, injected script) | Med | High | SLSA provenance records builder ID + source ref + materials; policy asserts expected builder; actions pinned by SHA | Provenance proves *where*, not that the source was benign |
| T4 | Signing key theft | Low | High | Keyless — ephemeral Fulcio cert, nothing durable to steal | Compromise of the GitHub OIDC identity is equivalent to key theft |
| T5 | Signature replay onto a different artifact | Low | High | Signature covers the image digest | — |
| T6 | Policy bypass via excluded namespace or `kube-system` | Med | High | Exclusions enumerated in the policy and reviewed; background scan reports pre-existing violations | Cluster-critical namespaces are pragmatically excluded — documented, not hidden |
| T7 | Rogue signature goes unnoticed | Low | Med | Rekor transparency log; documented query to list all entries for the identity | No automated monitoring of Rekor yet |
| T8 | Admission webhook unavailable → fail-open | Med | High | Kyverno `failurePolicy: Fail` for the verify policy | Trades availability for integrity — deliberate |

## What this does *not* prove

- It does not prove the code is safe — only that it came from the expected builder and source.
- SLSA level reached is documented honestly in the README rather than claimed.

## Verification

Both the allow path and the deny path have tests (`make policy-test`), and the deny path is the recorded demo.

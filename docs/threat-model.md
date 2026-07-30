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
| T1 | Attacker with registry write pushes a malicious image under a known tag | Med | High | **Enforced.** Admission verifies a Sigstore signature bound to this repo's workflow identity; a tag without a digest is refused outright. Demonstrated in `docs/evidence/admission-enforcement.md` | Exclusions exist and are enumerated in the policy (T6) |
| T2 | Vulnerable dependency ships to prod | High | Med | `grype` gate on CRITICAL; SBOM attestation enables retroactive CVE queries | Gate threshold is a judgment call; MED/HIGH still ship |
| T3 | Build step tampering (compromised action, injected script) | Med | High | **Enforced.** Admission requires a SLSA v1 provenance attestation signed by the pinned identity, and asserts `runDetails.builder.id` and the workflow repo/ref inside the predicate — so a valid signature over someone else's provenance does not pass | Provenance proves *where*, not that the source was benign. The enforceable copy is GitHub's, and it is gated on repo visibility (ADR-009, B5) |
| T4 | Signing key theft | Low | High | Keyless — ephemeral Fulcio cert, nothing durable to steal | Compromise of the GitHub OIDC identity is equivalent to key theft |
| T5 | Signature replay onto a different artifact | Low | High | Signature covers the image digest | — |
| T6 | Policy bypass via excluded namespace or `kube-system` | Med | High | Exclusions enumerated and argued inline in `policies/kyverno/verify-images.yaml`; a test asserts the namespace gate still holds | `kube-system`, `kyverno`, `calico-system`, `tigera-operator` excluded. The deny-all-unsigned rule is **opt-in by namespace label**, so an unlabelled namespace runs third-party images freely. Background scanning is off — image verification needs a registry round trip and only runs at admission |
| T7 | Rogue signature goes unnoticed | Low | Med | Rekor transparency log; documented query to list all entries for the identity | No automated monitoring of Rekor yet |
| T8 | Admission webhook unavailable → fail-open | Med | High | **Enforced.** `webhookConfiguration.failurePolicy: Fail` on the policy, verified live | Trades availability for integrity — deliberate. Kyverno's own namespace is excluded from T6's rule so it cannot deadlock itself |
| T9 | The one enforceable attestation stops being published | Med | High | *None.* `actions/attest-build-provenance` writes the only bundle Kyverno can discover on GHCR, and the workflow gates it on the repository being public | **Open.** Making the repo private denies every subsequently built image at admission. ADR-009, BLOCKED.md B5 |

## What this does *not* prove

- It does not prove the code is safe — only that it came from the expected builder and source.
- SLSA level reached is documented honestly in the README rather than claimed.

## Verification

Both the allow path and the deny path have tests (`make policy-test`), and the deny path is the recorded demo.

# B5 investigation — 2026-11-17 (partial; B5 unresolved)

> Handoff update: the operator refreshed GitHub authorization while this worker
> was closing its initial blocked run. The worker then rechecked that `workflow`
> scope was present and successfully pushed `fix/b5-own-proof`, read back at
> `5fc6492876ffadb898fe94a9165a67a9aad96197` before this documentation update.
> The initial push failure below is historical evidence, no longer an active
> credential blocker. The card needs reactivation by the orchestrator to resume
> the remaining implementation, live matrix and release review; no completion is claimed.

B5 remains **open**. No own-proof-only image was published, no required release
publication gate was enabled, and no new exact-head CI run or PR exists. The
principal repository visibility and production admission policy were not changed.

## Concrete authorization blocker

The authenticated GitHub CLI OAuth grant has `gist, read:org, repo`, not
`workflow` or package scopes. The package metadata API returned HTTP 403:
`You need at least read:packages scope to get a package.`

An actual authorized branch push, containing only the patched Cosign pin, failed:

```text
! [remote rejected] fix/b5-own-proof -> fix/b5-own-proof (refusing to allow an OAuth App to create or update workflow `.github/workflows/release.yml` without `workflow` scope)
```

`git ls-remote --heads origin fix/b5-own-proof` returned no ref. The local security
commit is `b04b56d`; nothing was force-pushed or merged. Publishing through a
GitHub Actions `GITHUB_TOKEN` would not need local package-write scope, but changing
that workflow first requires an authorized GitHub credential with workflow scope.
For direct local GHCR publication, a separately authorized package-write credential
would be required. No tokens were printed or copied into evidence.

Operator recovery: refresh the existing GitHub CLI authorization interactively
with `gh auth refresh -h github.com -s workflow`. Package scopes are needed only
if choosing direct local publication instead of Actions. Do not send tokens in chat.
Then resume this card; push the preserved branch and use reviewed PR/exact-head CI.

## Sources and selected tools

Official GitHub release/advisory APIs and source were consulted during this run:

- [Cosign v3.1.4](https://github.com/sigstore/cosign/releases/tag/v3.1.4), current
  stable release, built with Go 1.27.3. Linux binary SHA-256:
  `424e2c97d0b45fd7a6b608a87f090f35633f4c23ece5f092d48bba11aaf4bbfa`.
- [GHSA-fx35-mq7g-6g98](https://github.com/sigstore/cosign/security/advisories/GHSA-fx35-mq7g-6g98)
  affects Cosign <=3.1.2; patched at 3.1.3. Both workflow installer steps are
  locally updated to SHA `756fe2d284c7292c4e9b62c8a28f1e5629c59532`, explicitly
  requesting v3.1.4. This security update alone does **not** solve B5.
- [Kyverno v1.19.2](https://github.com/kyverno/kyverno/releases/tag/v1.19.2)
  selected for the legacy ClusterPolicy experiment. Current v1.20.0 removes
  legacy policy execution; blindly selecting latest would disable this design.
  1.19.2 also includes fixes for the published forged-annotation and missing-SAN
  verification advisories. This is a compatibility selection, not a claim that
  every dependency is vulnerability-free.
- Kyverno install asset SHA-256:
  `4f785937dc7fe49a0731108b15def1538923c73d9236255bc69d94d498037969`;
  CLI archive: `357eaf1df8bc24ddd5a73979fadeaae6a032e8710f11af264229756e4956bf4a`.
- [ORAS v1.4.0](https://github.com/oras-project/oras/releases/tag/v1.4.0), current
  stable release at observation; verified Linux archive SHA-256
  `d8e1dce2fd8ce996f1d901845b688eb0cf505a6082897606f053825bb47935d1`.
  Older ORAS <1.3.4 has credential-disclosure advisories; do not use 1.3.0 merely
  because its attach syntax was used during source inspection.
- kind v0.33.0, checked against its published checksum; kubectl v1.34.11 checked
  against the official Kubernetes checksum. Tools were installed only under the
  ignored repository `.lab/bin` directory.

Candidate fix: save the original Cosign bundles and publish their unchanged bytes
with ORAS `attach --distribution-spec v1.1-referrers-tag --artifact-type
application/vnd.dev.sigstore.bundle.v0.3+json`. Publish signature and provenance
sequentially, read back the exact bytes/index/manifest, verify identity **and**
issuer/digest/content, then prove actual admission without GitHub's writer.
This remains a candidate, **not** an executed fix. Cosign's v3.1.4 local-save
artifactType fix does not establish corrected remote fallback publication.

## Real baseline and negative admissions

Source/main SHA: `c22c13b65799c3d57fe192d4bd8d3c57716550e4`.
Published baseline (existing release, not built by this investigation):

```text
ghcr.io/pontope/provenancepipeline@sha256:5db4fa5a86b74442bea46af83db05d9f1089aec1ac5dd8839107105a58eb9f3a
```

Its existing release run is
[31914258092](https://github.com/PontoPe/ProvenancePipeline/actions/runs/31914258092).
That historical green run is not CI for the local changes.

Disposable cluster: `prove-lab-b387df5c`, context `kind-prove-lab-b387df5c`, own
kubeconfig, one Kubernetes v1.34.11 node. Node image:
`kindest/node:v1.34.11@sha256:44e222ee2132dab25ff87301682f89eb82c7880ea3a1bf543bfe9708fd08d67d`.
A scoped Docker wrapper enforced memory=4GiB, memory+swap=4GiB, CPU=2 at container
creation; inspected values were 4294967296 / 4294967296 / 2000000000 nanoCPUs.
API and health port-forward bound loopback only. No existing cluster/context used.

The unmodified policy spec was installed in Enforce/Fail, exact main identity and
GitHub issuer retained. Existing signature and both provenance writers are present.

| Test | Observed |
|---|---|
| Existing signed/provenanced digest | Actual Pod admitted, Ready; `/healthz` returned HTTP 200, `ok` |
| Same digest in enforced namespace | Server-side dry-run admitted |
| Unsigned BusyBox digest, enforced namespace | Denied, `no matching signatures` |
| Own image referenced by `latest` | Denied, `missing digest` |
| Expected identity changed to another exact workflow in lab policy | Denied, `no matching signatures` |
| Expected issuer changed to Google in lab policy | Denied, `no matching signatures` |
| Expected provenance repository changed only in lab policy | Denied, `attestation checks failed` |
| Webhook Service endpoints disconnected, webhook objects retained | Denied, `failed calling webhook` |
| Service selector restored | Unsigned negative denied again |
| Lab policy removed | Unsigned server-side dry-run admitted; policy restored afterwards |

Wrong-identity/issuer/content cases above change the verifier's expected values;
they are not newly minted foreign certificates or newly signed bad predicates.
Wrong-subject-digest and own-proof-only publication cases remain unexecuted.

Registry walk still returned HTTP **404** for referrers. Its fallback index has
four descriptors: three Cosign entries advertise `application/vnd.oci.empty.v1+json`,
whereas the GitHub SLSA descriptor advertises the bundle media type. Raw registry
responses are in the adjacent `b5-2026-11-17/` directory. The own/GitHub verified
NDJSON decodes with the new helper; the strict own-writer checker correctly rejects
the mixed-writer array rather than silently filtering the foreign writer.

## Two operational findings — not greenwashed

1. Scaling the admission deployment to zero admitted the covered unsigned
   server-side dry-run. That is **not** a successful fail-closed outage test.
   Graceful controller shutdown can change webhook registration; this result is
   distinct from an endpoint/network outage. Service-endpoint disconnection was
   tested separately and failed closed. The scale-zero exposure still needs
   explanation/mitigation before an operational reliability claim.
2. The offline exact-spec drift checker rejected the fresh, otherwise restored
   v1.19.2 export because the API adds defaulted fields (`admission`, `emitWarning`,
   `validationFailureAction`, and potentially nested defaults). Thus rejection
   of removed/Audit policies does **not** prove a usable drift observer: the
   healthy export also rejects. No baseline hash was silently regenerated or
   defaults stripped to make it green. A reviewed export/defaults contract and
   least-privilege live observer remain required.

Registry outage with warm/cold verifier caches and cache TTL remain **not run**.
Image pulls or a CLI success are not substitutes for those measurements.

## Local changes and verification

- Preserved all pre-existing offline-contract changes; no reset/discard.
- Added `scripts/bundle_publication.py`: strict NDJSON decoder and local
  descriptor/bundle-byte binding checks. These are **not** cryptographic
  verification, not a complete OCI validator, and not a consumer gate.
- Synthetic regression cases written before fixes; independent review found
  duplicate-key ambiguity and missing structure/size checks, then regression
  tests reproduced failures before corrections.
- `make test offline-test offline-policy-check`: passed, including Go vet,
  Go tests with `-race`, and **13** Python tests (with mutation subtests).
- `kyverno test tests/ --registry`: **9 passed**, 0 failed, using v1.19.2.
- Independent initial review completed; its decoder/layout findings were fixed
  and the parent re-ran the suite. A second independent approval was not obtained
  (the run's two-child review/research budget was exhausted); final release
  review remains pending along with the blocked live proof.
- Source `git diff --check` (excluding verbatim raw evidence) and redacted
  full-worktree gitleaks scan: passed. The raw Kyverno log deliberately preserves
  its terminal blank line; an unrestricted whitespace check flags that line.

The lab installation used the checksum-verified upstream manifest, not a newly
production-hardened bootstrap: its controller tags were not converted into
reviewed deployment digest pins here. Do not promote that lab manifest as a
finished bootstrap. Existing production bootstrap was untouched.

## Cleanup and remaining acceptance

The dedicated cluster was destroyed. `kind get clusters` returned none; Docker
listed no `prove-lab-b387df5c` container. All eight pre-existing service containers
remained running, with their original multi-week uptimes. No GHCR writes occurred.
Downloaded tools and evidence remain in ignored `.lab/`; downloaded shared Docker
image caches were retained, not indiscriminately pruned.

Resume after workflow authorization: review/push/PR; publish the own-only image;
prove B5 on the consumer before enabling the required publication gate; run
wrong-digest and freshly signed bad-content cases; warm/cold registry outage;
resolve scale-zero and defaulted-export findings; independent review, exact-head
CI, reexecution, English case/CV/blog source, cleanup and requested deliveries.
The full project is not complete and no CV outcome is claimed for this partial run.

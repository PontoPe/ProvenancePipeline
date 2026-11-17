# Offline verification milestone

> Historical offline milestone below. A subsequent authorized live baseline run
> is recorded in [the 2026-11-17 investigation](evidence/b5-investigation-2026-11-17.md).
> The suite now has 13 tests; a local patched Cosign workflow pin is prepared,
> but GitHub rejected publication for missing workflow authorization. B5 remains
> open. Do not read this milestone's original no-network boundary as describing
> the later live run.

## Outcome and boundary

The local contract checks are implemented and exercised. **B5 remains open.**
No publication, signing, GitHub workflow dispatch, registry access, cluster access,
kubeconfig/secret inspection, or infrastructure mutation was performed. The release
workflow and admission policy are unchanged. Historical July evidence is preserved;
it is not a measurement of the current registry or a current cluster.

This milestone adds a fail-closed **content contract**, not a deployed release gate
or an independent live-enforcement monitor. The integration experiment below is
still required before changing CI or declaring the consumer independent of GitHub.

## Reproduce locally

Requires Python 3.11+ and PyYAML; the tested environment has Python 3.11 and
PyYAML 6.0.3. The application remains Go/stdlib-only. If dependencies are missing,
use a repository-local virtualenv and `tests/offline/requirements.txt`; dependency
installation is separate from the offline test commands.

```sh
make offline-test
make offline-policy-check
python3 scripts/offline_checks.py compatibility-plan
```

The last command deliberately exits **2**, with `status: not-run`,
`b5_resolved: false`, null versions/layout and null observations. It is an
experiment checklist, not an evidence collector or a successful compatibility
result. Do not wrap it with `|| true` in a promotion gate.

`policy` and `publication`: exit 0 means only that the respective local contract
matches; exit 1 rejects missing, malformed, ambiguous or divergent input.
Argument/usage errors exit 2. JSON results go to stdout (usage errors use stderr).

## Policy-spec drift contract

```sh
python3 scripts/offline_checks.py policy policies/kyverno/verify-images.yaml
# Alternatively, consume a separately obtained local policy export:
python3 scripts/offline_checks.py policy /path/to/exported-policies.json
```

Accepts the named ClusterPolicy or a Kubernetes List with exactly one
`ClusterPolicy/verify-provenance`. An empty List detects a missing target; repeated
targets are rejected. Duplicate YAML/JSON keys are rejected. Formatting and
export metadata/status do not bless or invalidate the spec.

The baseline is an independent SHA-256 of canonical JSON `spec` from repository
commit `c22c13b65799c3d57fe192d4bd8d3c57716550e4`:
`819132b1c4cddc0327672bec67483ca3f577f7dd93ed6619477bd2438ee9840f`.
It is not recomputed from the candidate as an expected value. Baseline changes
require review, not automatic regeneration to make a failing test green.

Negative fixtures cover fail-open, disabled admission, missing rule, Audit,
missing digest requirements, tag mutation, missing attestation/conditions,
identity/issuer changes, expanded exclusions and a changed namespace selector.

**Limits:** exact spec equality can reject legitimate defaulted exports or
intentional strengthening. Investigate rather than weakening/normalizing away a
difference. Metadata annotations, separate PolicyExceptions, namespace labels,
webhook objects/selectors, controller readiness, freshness/authenticity of exports
and live negative admission controls are not checked. A stale export can pass.
`live_enforcement_proven` is always false. A future independent observer must
obtain fresh exports with least-privilege read access and run covered negative
controls; this script never invokes kubectl.

Current scope is unchanged: own-image references require provenance; all images
in labelled namespaces require our signature, but rule 2 alone does **not**
require provenance. System namespace exclusions remain explicit in rule 1.

## Publication-content contract

```sh
python3 scripts/offline_checks.py publication /path/to/decoded-own-statements.json \
  --ref 'ghcr.io/pontope/provenancepipeline@sha256:<64 lowercase hex>' \
  --revision '<40 lowercase hex Git commit>'
```

The input is a nonempty array of **decoded own-writer in-toto statements**, not
DSSE envelopes, downloaded unsigned predicates or verifier log text. The test
fixtures are synthetic and constructed in `tests/offline/test_publication.py`.
Every input statement must have:

- in-toto Statement v1 and SLSA provenance v1;
- exactly the expected image name and SHA-256 subject digest (tags rejected);
- the exact main-branch release builder identity;
- the own-writer buildType, exact source repository, ref and workflow path;
- exactly the expected Git dependency URI and source revision.

Missing, empty, mixed/foreign-writer or divergent statements fail. This is a
strict own-writer contract: do not silently filter a foreign statement or empty
verification output into success. It intentionally rejects GitHub's different
buildType, whereas the existing admission policy accepts either writer's shared
fields. This difference exposes B5 rather than hiding it.

**Mandatory external precondition:** a trusted verifier must first validate
signature, certificate **identity AND issuer**, chain/transparency proof and
artifact binding for the exact digest, with exit status propagated and bounded
execution time. Decoding unauthenticated data is not verification. The content
checker cannot validate a certificate from a decoded statement and reports
`cryptographic_verification_performed: false` and
`consumer_compatibility_proven: false`, even on valid content.

No new workflow gate has been enabled. The existing `cosign verify-attestation`
output adapter must be tested against the selected supported version before
integration: current workflow parsing expects `.payload`, while bundle/storage
and verifier output formats can differ. Preserve raw verified output, fail on
empty/invalid decoding, and use shell `set -euo pipefail`; never substitute
`cosign download` output as verified data. CLI verification alone does not prove
that Kyverno discovers the same proof.

## Authorized B5 experiment — prepared, NOT executed

`compatibility-plan` emits the planned positive/negative matrix with no results.
Before executing it, obtain explicit authorization for the lab registry/repository,
publication workflow and disposable cluster/host. Do not change the principal
repository's visibility or reuse the old KateClusters context by assumption.

1. Check current official support/releases/advisories for the publisher and
   consumer; record exact versions, action SHAs and verified binary/container
   digests. Historical Cosign 2.x is a candidate, **not a prescribed downgrade**.
2. Freeze a small publisher × registry-layout × consumer matrix. Record actual
   referrers-API status, fallback-index descriptors and manifest artifactTypes.
   Reproduce the recorded baseline before selecting a maintained combination.
3. Publish equivalent lab images with own signature + own SLSA proof, first with
   and then without the GitHub writer. Capture exact digest, source commit,
   run ID, tool versions, config, raw command output and exit status separately
   from the report. Keep identity/issuer exact and all digest/provenance checks.
4. Verify in a clean runner and perform real Kyverno admission in a disposable
   cluster. Capture both rule scopes; require the own proof **without** GitHub's
   writer to admit and become healthy. A CLI success or bundle descriptor alone
   is insufficient. Not running the GitHub writer does not prove private-registry
   authentication compatibility.
5. Exercise unsigned, wrong identity/issuer, wrong digest/content and tag cases.
   Differentiate cryptographic, predicate and infrastructure failure. A timeout,
   network failure or unrelated denial is not proof of the intended control.
   If a negative unexpectedly admits, fail the harness itself.
6. Measure webhook loss and registry outages separately, with cold and warm
   verifier caches and recorded TTL. Do not infer registry consultation on every
   admission from an image-pull setting.
7. Remove/relax policy only in that lab, detect drift, restore it and read back
   the exact target. Capture restored negative-control denial, then destroy only
   lab resources and record residues. No mutation runner is included here.
8. Only after the own-proof case works, wire the verified-output content gate
   and consumer publication/discovery check into release CI. A failed required
   publication/verification must fail release; GitHub's optional writer must not
   mask it. Review/test this before changing B5's status.

Unknown today: maintained compatible versions/layout, consumer discovery without
GitHub, present registry behavior, actual admission decisions, webhook availability,
cache/outage behavior, drift-observer latency, health and cleanup. No SLSA upgrade,
benchmark or full-project completion is claimed.

## Executed checks on this checkout

- `make offline-test`: **11 tests passed**, including mutation subtests and real
  CLI subprocess exit-code checks. Synthetic fixtures only.
- `make offline-policy-check`: `policy-contract-valid`,
  `live_enforcement_proven: false`, fingerprint above.
- `python3 scripts/offline_checks.py compatibility-plan`: exit **2**, not run;
  all observations and versions remain null.
- Python `ast.parse` syntax check: four checker/test source files parsed.
- `for script in scripts/*.sh cluster/bootstrap/fetch-upstream.sh; do bash -n "$script" || exit; done`: passed for every script.
- `git diff --check`: passed.
- Follow-up authorized host installation: official Go **1.26.11 linux/amd64**, installed under `/usr/local/go` with `go`/`gofmt` symlinks in `/usr/local/bin`. Archive SHA-256 verified against go.dev: `9849f4e04ee35303714e34fbc3ac8ab44ea3e448a95aa182f91e3b9b79c710ec`.
- `GOTOOLCHAIN=local GOMAXPROCS=2 make test offline-test offline-policy-check`: **passed**. Includes `go vet ./...`, `go test -race ./...`, the 11 Python checks, and the policy contract. The earlier missing-Go blocker is resolved; registry/admission acceptance remains pending.
- `make verify` and `make policy-test`: **not run**; these contact a registry.
  `make policy-install`, demos, evidence collectors and workflows: **not run**.

No generated compatibility evidence file was created. Existing evidence was not
rewritten. The previous July documentation describes historical execution, not
new live verification by this offline milestone.

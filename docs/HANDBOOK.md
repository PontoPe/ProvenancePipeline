# Handbook — building the ProvenancePipeline CI half

This is the process document: how the signing-and-attestation half of the
pipeline was built on 2026-07-29, in the order it happened, why each piece is
shaped the way it is, and every wrong turn taken along the way. It is meant to
be read start to finish by someone who wants to understand *how* this was put
together, not just *what* exists.

For the forward-looking state and next steps, read [PROVEhandoff.md](PROVEhandoff.md). For
the terse blow-by-blow, [session-report.md](session-report.md). For the decision
records, [architecture.md](architecture.md). This document overlaps all three on
purpose — it is the connective tissue between them.

---

## 0. Starting point

The repo was scaffolding: a README with an architecture diagram and threat
model, empty `docs/architecture.md` (an ADR skeleton), a `Makefile` with
placeholder targets, a `release.yml` that had never run green, and `.gitkeep`
files standing in for every real directory. No application code, no Dockerfile,
no evidence.

The scope for the session was roadmap steps 1–3 — the application, the
Dockerfile, and the CI workflow through to a passing `verify` job — plus the
Makefile, captured evidence, ADRs, and README updates. Admission control (the
cluster half) was explicitly out of scope because the cluster it targets does
not exist yet.

The session ran unattended: decide, implement, record the decision, iterate CI
until green, do not stop at the first failure.

---

## 1. Toolchain setup

The three Sigstore/Anchore tools were not installed. Installed via winget, one
package per invocation (winget rejects multiple IDs in one call):

```powershell
winget install --id Sigstore.Cosign -e
winget install --id Anchore.Syft   -e
winget install --id Anchore.Grype  -e
```

**First gotcha.** `winget install Sigstore.Cosign` does not create a `cosign`
command on `PATH`. It drops `cosign-windows-amd64.exe` under
`%LOCALAPPDATA%\Microsoft\WinGet\Packages\Sigstore.Cosign_*\` and registers a
command *alias* rather than a shim. From Git Bash that alias does not resolve.
The fix was to copy the real binaries into `~/bin/` with the names the Makefile
expects:

```bash
cp ".../Sigstore.Cosign_*/cosign-windows-amd64.exe" ~/bin/cosign.exe
cp ".../Anchore.Syft_*/syft.exe"                     ~/bin/syft.exe
cp ".../Anchore.Grype_*/grype.exe"                   ~/bin/grype.exe
```

Verified: cosign 3.1.2 / v3.0.6 runtime, syft 1.49.0, grype 0.116.0.

`make` came later and had its own gotcha — see §9.

---

## 2. The application (`app/`)

The workload is a minimal HTTP service in Go, **stdlib only, no third-party
modules**. `app/go.mod` has no `require` block and there is no `go.sum`.

Why this and not something realistic: the choice of app leaks into the SBOM and
the vulnerability gate. A Node or Python service guarantees a stream of
transitive-dependency CVEs, which makes a hard-fail gate noisy and creates
pressure to weaken it — the exact move this repo argues against. A dependency-
free binary produces a 7-package SBOM where every entry is attributable to the
Go toolchain or the base image, so any CRITICAL the gate reports is real signal.
This is ADR-001.

The service itself ([app/main.go](../app/main.go)) is deliberately dull:

- `GET /healthz` → `ok`
- `GET /version` → build info as JSON (version, revision, Go version, os/arch)
- `GET /{$}` → service name + build info

`version` and `revision` are `var` globals set at build time with `-ldflags -X`,
so the running binary can report exactly which commit produced it. The server
has read/write/idle timeouts and graceful shutdown on SIGTERM — not because the
demo needs it, but because a service in a security portfolio should not look
like a toy that ignores its own robustness.

Tests ([app/main_test.go](../app/main_test.go)) cover each route, the build-info
completeness, 404 on an unmatched path, and the port-selection helper.

Two small corrections during writing: `t.Setenv` replaced a manual
`os.Setenv`/error-check pair (cleaner, auto-reverts), and the now-unused `os`
import was dropped. `go vet ./...` and `go test ./...` both pass.

---

## 3. The Dockerfile (`build/`)

[build/Dockerfile](../build/Dockerfile) is multi-stage:

- **Build stage:** `golang:1.26-alpine`, pinned by digest `sha256:0178a641…`.
- **Runtime stage:** `gcr.io/distroless/static-debian12:nonroot`, pinned by
  digest `sha256:f5b485ea…`.

Digests were resolved with `docker buildx imagetools inspect <tag> --format
'{{.Manifest.Digest}}'` and hard-coded as `ARG` defaults with the human-readable
tag in a comment above each.

**Why pin by digest.** A tag is a mutable pointer. The admission policy this
whole repo builds toward refuses mutable tags — so building *on* a mutable tag
would be incoherent. What the pipeline consumes has to be held to the same
standard as what it produces. This is ADR-002.

**Why distroless nonroot.** No shell, no package manager, ships a CA bundle and
a `nonroot` (uid 65532) user. `alpine` would add a shell and musl as attack
surface and CVE sources; `scratch` has no CA certs or user to run as. The
Dockerfile restates `USER 65532:65532` explicitly even though the base already
sets it, so a future base swap cannot silently reintroduce root.

**Reproducibility.** The build runs `go build` with `-trimpath` (strips absolute
paths) and `-ldflags "-s -w -buildid="` (drops the non-deterministic build ID).
Together these make the binary byte-identical across builds of the same source,
which is what makes the provenance falsifiable — if the bits are deterministic,
a claim about where they came from can actually be checked.

A [.dockerignore](../.dockerignore) restricts the build context to `app/` only,
so nothing else in the repo can accidentally be baked into a layer.

The build context is the **repo root**, with `file: build/Dockerfile` — because
the Dockerfile in `build/` needs to `COPY app/`, and a context of `build/` would
not contain the application source. This was one of the scaffolding bugs; see §8.

---

## 4. The CI workflow (`.github/workflows/release.yml`)

Three jobs, chained.

### `test`

Checks out, sets up Go from `app/go.mod`, runs `go vet` and `go test -race`.
`-race` runs here because the runner is Linux with cgo available (it does not on
the Windows workstation — §9).

### `build, sign, attest`

The core. In order:

1. **`meta` step** computes three things and exposes them as job outputs:
   - the lowercase image ref (`github.repository` preserves owner casing and
     GHCR rejects uppercase path segments — another scaffolding bug, §8),
   - the exact signing identity (§the trust anchor, below),
   - `source_date_epoch` from the commit timestamp,
   - and the repo's real `private` flag, used to gate GitHub's attestation.
2. **buildx build + push** to GHCR, tagged with the commit SHA and `latest`.
   Critically, `provenance: false` and `sbom: false` — buildx otherwise attaches
   its own *unsigned* in-toto attestations as extra manifests in the index,
   which muddies the digest cosign signs and ships an unsigned provenance next
   to the signed one. We produce signed equivalents instead. This is ADR-004.
3. **SBOM** via `anchore/sbom-action`, twice — SPDX and CycloneDX.
4. **Vulnerability gate** via `anchore/scan-action`: `severity-cutoff: critical`,
   `fail-build: true`. No `continue-on-error`, no soft-fail, no allowlist. See
   §7 on why this is load-bearing.
5. **`cosign sign`** — keyless. The runner's OIDC token is exchanged with Fulcio
   for an ephemeral certificate; the signature and its transparency-log entry go
   to public Rekor. Nothing durable is stored.
6. **`cosign attest --type spdxjson`** — the SBOM as a signed attestation.
7. **SLSA provenance predicate**, hand-assembled with `jq` from the GitHub
   context (repo, ref, sha, run id, builder id), then attested with
   **`cosign attest --type slsaprovenance1`**.
8. **`actions/attest-build-provenance`** — GitHub's own provenance, gated on the
   repo being public.

### `verify`

Runs on a clean runner and re-checks everything, pinning identity **and** issuer:

- `cosign verify` — the signature.
- `cosign verify-attestation --type spdxjson` — the SBOM attestation.
- `cosign verify-attestation --type slsaprovenance1` — the SLSA provenance.
- `gh attestation verify` — GitHub's provenance (gated on public visibility).
- **A negative control**: `cosign verify` against a digest that was never
  signed, which *must* fail or the whole build fails. This is ADR-006, and it is
  the command-line rehearsal of the demo the project is ultimately about — a
  verifier that never says no is not a verifier.

### The trust anchor

Keyless signing has no key, so this pair is the entire root of trust:

```
identity: https://github.com/PontoPe/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main
issuer:   https://token.actions.githubusercontent.com
```

Both are pinned everywhere, always. Identity alone is forgeable by any other
OIDC issuer Fulcio accepts; issuer alone matches every GitHub workflow on earth.
The `meta` step computes it once and threads it through as an output so CI, the
Makefile, and the future Kyverno policy all reference one string.

### Pinning

Every third-party action is pinned by **commit SHA**, not tag, with the version
in a trailing comment. A supply-chain repo cannot itself have an unpinned supply
chain. SHAs were resolved with:

```bash
gh api repos/OWNER/REPO/git/ref/tags/vX.Y.Z --jq .object.sha
```

---

## 5. The debugging journey

This is the part worth reading. The workflow did not go green on the first push;
it took five CI iterations to get the evidence right, and each failure taught
something.

### Iteration 1 — GitHub's attestation refused a private repo

First real run. `test`, build, SBOM, the grype gate, `cosign sign` and both
`cosign attest` calls all passed. Then `actions/attest-build-provenance` failed:

```
Failed to persist attestation: Feature not available for user-owned private
repositories. To enable this feature, please make this repository public.
```

This is a GitHub platform limit, not a code bug. But chasing it surfaced the
design point that mattered most all session: **even where GitHub's attestation
works, Kyverno cannot verify it.** Kyverno verifies through cosign and Sigstore
and has no way to shell out to `gh attestation verify`. So the cosign
`slsaprovenance1` attestation added in step 7 above is not redundant — it is the
*only* provenance the future admission policy can actually enforce. This became
ADR-005: attest provenance twice, deliberately.

The fix gated the GitHub step on the repo's real visibility
(`if: steps.meta.outputs.private != 'true'`) rather than deleting it, so it
starts working by itself if the repo is ever made public. Which it then was,
mid-session — the owner made the repo public, a `workflow_dispatch` re-run went
fully green including GitHub's provenance and the negative control, and that
path has worked since.

### Iterations 2–4 — capturing evidence that is actually the evidence

The requirement was that `docs/evidence/supply-chain-verification.md` contain
*real captured output*, not prose describing what the output would look like. So
the `verify` job was extended to generate the file itself and upload it as an
artifact (ADR-007 — generated, never transcribed). Three things broke in a row:

**cosign writes to two streams.** The first generated evidence had two empty
attestation sections. Cause: cosign writes its human-readable checklist to
*stderr* and the JSON payload to *stdout*, and folding them together with `2>&1`
fed prose into `jq`. Worse, a defensive `|| true` swallowed the failure so it
looked fine. The fix redirects the streams to separate files and parses only
stdout. Lesson: the `|| true` hid a real bug, and it was only caught by reading
the actual artifact rather than trusting the green check.

**The Rekor index came back null.** cosign v3 no longer prints the log index on
sign and leaves the inlined `Bundle` null. First attempt looked up the index
from Rekor's public API by the sha256 of the signed payload — but the payload
field guess (`.Payload`) matched nothing, silently, because cosign v3 emits
*Sigstore bundles*, not the legacy `{Payload, Bundle}` envelope.

**The envelope format had changed entirely.** Adding a diagnostic line —
`echo "envelope keys: $(jq -r 'keys_unsorted | join(",")' ...)"` — revealed the
real shape: `mediaType, verificationMaterial, dsseEnvelope`. The Rekor entry is
carried *inside* the bundle, at `.verificationMaterial.tlogEntries[]`. So the
whole API round-trip and payload-hash guesswork was unnecessary; reading the
tlog entry straight from the bundle is both correct and simpler. This is why the
step now logs its envelope keys — so the next format change is visible instead
of silent.

After that, the evidence file came out complete: full `cosign verify` output,
both attestation predicates printed in full, four real Rekor log indices, and
the negative control showing `Error: no signatures found`, exit 10.

### The independent local check

The evidence above was produced on a GitHub runner. To prove it independently,
the same transparency-log entries were fetched *from the workstation* against
public Rekor — which needs no registry credentials, and so was possible even
though local `cosign verify` against GHCR was not (see §6). For two of the four
entries:

```bash
curl -sS "https://rekor.sigstore.dev/api/v1/log/entries?logIndex=<N>"
```

The entry body was base64-decoded, the Fulcio certificate extracted, and
inspected with `openssl x509 -text`. The result confirmed:

- the certificate's Subject Alternative Name is *exactly* the pinned identity,
- extension `1.3.6.1.4.1.57264.1.8` (the Fulcio OIDC-issuer claim) is *exactly*
  the pinned issuer.

Those two strings together are the whole trust anchor of a keyless setup, and
this check verified them from a machine that had nothing to do with the build.
That transcript is appended to the evidence file under "Independent check from
the workstation".

---

## 6. Why local `cosign verify` does not work here

`cosign login ghcr.io` with the `gh` token succeeded, but the actual pull failed:

```
GET https://ghcr.io/v2/pontope/provenancepipeline/manifests/latest: DENIED
```

The workstation's `gh` OAuth token carries `gist, read:org, repo, workflow` — no
`read:packages`. GHCR requires a packages scope even for a package attached to a
repo you own. The fix is one interactive command, which an unattended session
could not run:

```bash
gh auth refresh -h github.com -s read:packages
```

This is blocker B1. It is mitigated three ways: the CI `verify` job runs the
identical commands every push, the evidence file is generated from that run, and
the transparency-log half *was* checked locally against public Rekor (§5).

---

## 7. The gate is load-bearing and was never weakened

The single hardest rule of the session: do not weaken the grype gate to get a
green CI. No `continue-on-error`, no `soft_fail`, no raised threshold, no ignore
file. A gate switched off to make a run pass is worse than no gate, because it
also lies — and this repo is sold on exactly that claim.

It never had to be weakened. The stdlib-only Go binary on distroless produces a
7-package SBOM with zero CRITICAL findings, so the gate passes honestly. This is
the ADR-001 → ADR-003 chain paying off: the boring workload is *why* a hard-fail
gate is sustainable. If a CRITICAL ever appears, the fix is to move the base
image or update the dependency, never to move the threshold.

---

## 8. Scaffolding bugs found and fixed

These were in the repo before the session and each would have broken the first
real run:

| Bug | Consequence | Fix |
|-----|-------------|-----|
| `IMAGE: ghcr.io/${{ github.repository }}` | `github.repository` keeps owner casing → `ghcr.io/PontoPe/…`; GHCR rejects uppercase | Fold to lowercase in the `meta` step |
| `context: build` in the build step | Dockerfile is in `build/` but source is in `app/`; context would lack the code | Context = repo root, explicit `file: build/Dockerfile` |
| Actions pinned by tag (`@v4`, `@v3`, …) | Mutable refs, in the repo that argues against mutable refs | All pinned by commit SHA |
| `cosign triangulate --type digest` in the Makefile `sign` target | Returns the *signature tag*, not the image digest → signs the wrong object | Resolve the digest with `imagetools inspect` |
| verify used `--certificate-identity-regexp "^https://…/${repo}/"` | Prefix matches *any* workflow in the repo → a signature from an unrelated workflow passes | Pin the exact identity, computed once, threaded as a job output |

The last one is the most dangerous: it is a verification step that looks strict
but silently accepts signatures it should reject.

---

## 9. The Makefile and the `-race` problem

[Makefile](../Makefile) mirrors every CI step for local use: `test`, `build`,
`sbom`, `scan`, `sign`, `attest`, `verify`, `verify-github`, `evidence`, plus
the (still-blocked) `policy-install`, `policy-test`, `demo`. Verification always
targets a **digest**, never a tag — resolved from the registry if not passed
explicitly — because the signature covers the digest and a tag is mutable.

`make` itself had to be installed. `winget install GnuWin32.Make` fails
unattended with `0x800704c7` — a UAC prompt nobody was there to accept.
`scoop install make` (4.4.1) worked without admin.

Then `make test` failed:

```
go: -race requires cgo; enable cgo by setting CGO_ENABLED=1
```

The workstation has no C toolchain, so `-race` cannot run. The Makefile now
gates the flag on the platform:

```make
ifeq ($(OS),Windows_NT)
RACE :=
else
RACE := -race
endif
```

CI still runs with `-race` on Linux. `make help` and `make test` both pass
locally now.

---

## 10. Everything that did not get done, and why

| Item | Blocker |
|------|---------|
| Local `make verify` | `gh` token lacks `read:packages` (B1) — one interactive command fixes it |
| Local `make build sbom scan` | Docker Desktop process starts but the Linux engine never comes up unattended (B2) |
| Demo GIF | B2, plus `asciinema`/`agg` absent (POSIX-only, needs WSL), plus local keyless signing opens a browser by design (B3) |
| Cluster bootstrap, Kyverno policy, policy tests | No cluster — KateClusters is not built |

Exact errors and fixes in [BLOCKED.md](BLOCKED.md).

---

## 11. The honest assessment

**SLSA Build L2, not L3.** L2 is met: a hosted build platform, provenance signed
with the workflow's own OIDC identity through Fulcio, entries in public Rekor,
and a consumer-side check that pins identity and issuer and fails closed. L3 is
not, and the gap is real: the provenance predicate is assembled by a `jq` step
in the *same job* that builds the image, so anything compromising that job can
write its own provenance and have it signed. Closing it means delegating to
`slsa-framework/slsa-github-generator`, which generates in an isolated context.

And the framing the whole project lives or dies on: **this repo now proves
verifiable provenance. It does not yet prove enforcement.** The rejection — a
cluster refusing an unsigned image — is still the missing deliverable, and it is
the one the project is sold on. Everything built this session is the
prerequisite for it, not a substitute.

---

## 12. Commit trail

The session's work, oldest first:

1. `feat: build, sign and attest the demo service end to end`
2. `fix(ci): skip GitHub attestation while the repo is private`
3. `ci: generate the verification evidence file from the verify job`
4. `fix(ci): separate cosign stderr from stdout, resolve Rekor index by hash`
5. `fix(ci): resolve the signature payload field regardless of key casing`
6. `fix(ci): read the Rekor entry from the Sigstore bundle`
7. `docs: record verification evidence, ADRs and known blockers`
8. `docs: session report, and make test working on Windows`
9. `docs: note the read:packages requirement for local verification`
10. `docs: add project handoff`

The four `fix(ci)` commits in the middle are the debugging journey of §5 made
concrete — each one a failed CI run read, diagnosed, and corrected.

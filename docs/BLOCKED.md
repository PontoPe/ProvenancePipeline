# Blocked

Things attempted in earnest and not finished, with the exact error and what
would unblock them. Kept so the next session does not rediscover them.

Last updated: 2026-07-30.

| ID | State |
|----|-------|
| B1 | **resolved** — the GHCR package is public; no `read:packages` needed |
| B2 | open — Docker Desktop's Linux engine never comes up unattended |
| B3 | **resolved** — the demo is recorded, from the cluster, not from a local build |
| B4 | resolved 2026-07-29 |
| B5 | **open, and it matters** — enforcement depends on the repo staying public |

---

## B1 — `cosign verify` cannot run against GHCR from the workstation

**RESOLVED 2026-07-30.** The package is public, so no registry credential is
needed at all. Verified from the cluster node, which has never been logged in to
any registry:

```console
$ gh api user/packages/container/provenancepipeline --jq .visibility
public

$ cosign verify --certificate-identity "$ID" --certificate-oidc-issuer "$ISSUER" \
    ghcr.io/pontope/provenancepipeline@sha256:5d4b03ea…
Verification for ghcr.io/pontope/provenancepipeline@sha256:5d4b03ea… --
The following checks were performed on each of these signatures:
  - The cosign claims were validated
  - Existence of the claims in the transparency log was verified offline
  - The code-signing certificate was verified using trusted certificate authority certificates
```

`gh auth refresh -s read:packages` is no longer required for `make verify`. The
original write-up is kept below because the failure mode is worth recognising if
the package is ever made private again — which is also B5.

<details>
<summary>Original B1, when the package was private</summary>

**Wanted:** `make verify` executed locally, against the published digest.

**Tried:**

```console
$ gh auth token | cosign login ghcr.io -u PontoPe --password-stdin
logged in via C:\Users\Pedro\.docker\config.json

$ cosign verify --certificate-identity ... --certificate-oidc-issuer ... \
    ghcr.io/pontope/provenancepipeline:latest
Error: GET https://ghcr.io/v2/pontope/provenancepipeline/manifests/latest: DENIED: requested access to the resource is denied
error during command execution: GET https://ghcr.io/v2/pontope/provenancepipeline/manifests/latest: DENIED: requested access to the resource is denied
```

**Cause:** the workstation's `gh` OAuth token carries `gist, read:org, repo,
workflow` — no `read:packages`. GHCR requires a packages scope even for a
package attached to a repository you own. Confirmed:

```console
$ gh api user -i | grep -i x-oauth-scopes
X-Oauth-Scopes: gist, read:org, repo, workflow
```

**Not done because:** `gh auth refresh -s read:packages` is an interactive
device-flow login, and this session ran unattended. Making the GHCR package
public would also fix it and was explicitly left as the owner's decision.

**Unblock:** run one of these interactively —

```bash
gh auth refresh -h github.com -s read:packages
```

Then `make verify` works as written. Nothing in the repo needs to change.

**Mitigated by:** the `verify` job runs the identical commands on a runner
every push, and `docs/evidence/supply-chain-verification.md` is generated from
that run's real output. The transparency-log half *was* verified locally
against public Rekor, which needs no registry credentials — see the last
section of the evidence file.

</details>

---

## B2 — no local Docker daemon this session

**Wanted:** `make build sbom scan` executed locally end to end.

**Tried:** started Docker Desktop, waited 7m30s, then polled again:

```console
$ docker info --format '{{.ServerVersion}}'
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct and if the daemon is running: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

The Docker Desktop process starts but the Linux engine never comes up. Likely
wants an interactive first-run/login step that an unattended session cannot
satisfy.

**Unblock:** open Docker Desktop by hand once, wait for "Engine running", then:

```bash
make build sbom scan
```

`syft` 1.49.0 and `grype` 0.116.0 are installed and working — verified by
`syft --version` / `grype --version`. Only the daemon is missing. The same
three steps run on every CI push, so the pipeline itself is not in doubt.

`make` is also now installed (`scoop install make`, 4.4.1) — `winget install
GnuWin32.Make` fails unattended with `0x800704c7 : The operation was canceled
by the user`, which is the UAC prompt nobody was there to accept. `make help`
and `make test` both run.

---

## B3 — demo GIF not recorded

**RESOLVED 2026-07-30.** `docs/img/demo.gif` exists. All three blockers below
dissolved the same way: the demo was recorded **on the cluster node**, not on the
Windows workstation, so Docker Desktop and WSL never entered into it, and no
local signing was needed because the images were already signed by CI. The
recording shows the thing that actually matters — a pod being denied.

Recorded with `asciinema rec --command`, converted with `agg`. Three snags worth
knowing:

- `sudo -v` inside the recorded command hangs forever under `ssh -tt`. sudo is
  NOPASSWD on this node; drop it.
- `agg` fails on a headless VM with `Error: no faces matching font family
  options` until `fonts-dejavu-core` is installed, and still needs
  `--font-family "DejaVu Sans Mono"` passed explicitly.
- The first render came out 10 s long with 60 ms frames, which is unreadable.
  `--speed 0.6 --idle-time-limit 5 --last-frame-duration 6` gives 31 s. Check the
  per-frame durations rather than trusting the output.

<details>
<summary>Original B3</summary>

**Wanted:** `docs/img/demo.gif` via `asciinema` + `agg`.

**Not done because:** three independent blockers, not one.

1. `asciinema` and `agg` are not installed, and neither has a `winget`
   package that works on Windows — `asciinema` is POSIX-only (it records a
   pty), so this needs WSL regardless.
2. It depends on B2 — there is no local image to demo.
3. **The important one:** local keyless signing is interactive by design.
   `cosign sign` with no key opens a browser for the OIDC flow. A recording
   made unattended would either hang there or need a long-lived credential,
   and generating a key pair to avoid it would contradict the whole premise
   of the repo.

**Unblock:** record it from WSL, on a workstation where a human can complete
the browser flow. Better: wait for the cluster and record the demo that
actually matters — a pod being *denied* — rather than a local re-run of what
CI already proves. That is roadmap items 4–6.

</details>

---

## B4 — `actions/attest-build-provenance` refused a private repository

Resolved during the session, kept for the record because the error message is
worth recognising.

```
Error: Failed to persist attestation: Feature not available for user-owned
private repositories. To enable this feature, please make this repository
public.
```

The repository was made public by the owner mid-session and the step now runs
and is verified. The workflow still gates it on the repository's real
visibility, so it degrades cleanly rather than failing if that is ever
reverted. The cosign `slsaprovenance1` attestation was added in response and
is kept permanently.

> **Correction, 2026-07-30.** The last sentence of this entry used to read "it is
> the copy Kyverno can verify, and it does not depend on repository visibility."
> That is false. On GHCR, Kyverno can discover **only** GitHub's bundle, so the
> visibility gate above is the thing enforcement now depends on. See ADR-009 and
> B5. "Degrades cleanly" was true of the CI run and is not true of the cluster.

---

## B5 — enforcement silently depends on the repository staying public

**Open. This is the one to fix next.**

Kyverno can only discover one of the four Sigstore bundles attached to each
image, and it is the one written by `actions/attest-build-provenance` — see
ADR-009 for the mechanism. That step is gated on repository visibility:

```yaml
# .github/workflows/release.yml:220
- name: Attest build provenance (GitHub)
  if: steps.meta.outputs.private != 'true'
  uses: actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373 # v4.1.1
```

The gate is correct in itself — GitHub's attestations API genuinely refuses
user-owned private repositories, which is B4. The problem is what it now
implies: **if the repository is made private again, every image built after that
point carries no attestation Kyverno can see, and `verify-provenance` denies all
of them.** The failure is not subtle, but it is entirely non-obvious from
reading either file alone, and it couples an admission-control outcome to a
GitHub repository setting.

**Not fixed this session because** the fix is a CI change plus a release run plus
re-verification, and the honest sequencing was to land working enforcement and
document the coupling rather than start a second, larger change on top of an
unverified one.

**Options, in the order they should be tried:**

1. **Pin cosign to 2.x in CI.** cosign 2.x defaults to the legacy
   `sha256-<digest>.sig` / `.att` layout, which Kyverno reads through its
   default `type: Cosign` path with no referrers API involved. That restores
   ADR-005's original intent — enforcing cosign's own attestation — and removes
   the dependency on GitHub's step entirely. Verify the flag names against
   `cosign sign --help` for whichever 2.x is chosen rather than assuming;
   3.1.2 has no `--new-bundle-format`, and 2.x's default is what matters here.
2. **Report it upstream.** cosign writes the fallback-tag referrers index with
   `artifactType` set to the config media type rather than the manifest's own
   `artifactType`, which is what makes its bundles undiscoverable to any
   consumer using `remote.Referrers`. GitHub's writer gets it right in the same
   index, so the two are directly comparable in one artifact.
3. **Fail loudly instead of silently.** At minimum, make the workflow fail the
   run when the attestation step is skipped, rather than producing an image that
   will be refused at admission for reasons nobody will connect to a visibility
   toggle three weeks earlier.

**Do not** "fix" this by relaxing the policy. Dropping the attestation
requirement, or moving the rule to `Audit`, would make the symptom disappear and
the guarantee with it.

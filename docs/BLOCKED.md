# Blocked

Things attempted in earnest and not finished, with the exact error and what
would unblock them. Kept so the next session does not rediscover them.

Last updated: 2026-07-29.

---

## B1 — `cosign verify` cannot run against GHCR from the workstation

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

---

## B3 — demo GIF not recorded

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
is kept permanently — it is the copy Kyverno can verify, and it does not
depend on repository visibility. See ADR-005.

# PROGRESS — cluster-side enforcement

Source of truth for what is done and verified. Updated after every numbered step.
If a step is marked done here, do not redo it — confirm the state with the listed
command and move on.

Cluster: `kate-node-01`, kubeadm v1.34.10, Debian 13, Calico, single node,
`192.168.100.127`. Reached with `ssh kate`. `kubectl` needs
`sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf` in a non-interactive shell.

VMware snapshot `pre-kyverno` taken 2026-07-30 before any of this, while powered
off. Revert with:

```bash
& "C:\Program Files\VMware\VMware Workstation\vmrun.exe" revertToSnapshot "C:\Users\Pedro\Documents\Virtual Machines\kate-node-01\kate-node-01.vmx" pre-kyverno
```

Note `vmrun.exe` is under `C:\Program Files\VMware\...`, **not**
`C:\Program Files (x86)\VMware\...` as earlier notes said.

---

## Step 1 — `cluster/bootstrap` (Kyverno install) — DONE, verified

Kyverno v1.18.2 installed via kustomize, all five images pinned by digest, the
upstream manifest pinned by sha256 and the hash enforced at fetch time.

Command that proved it:

```
$ sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kyverno get pods
NAME                                             READY   STATUS    RESTARTS   AGE
kyverno-admission-controller-cfcff554b-kl4p6     1/1     Running   0          90s
kyverno-background-controller-67d887b64b-xg7wn   1/1     Running   0          90s
kyverno-cleanup-controller-6c8f748fc8-s56fd      1/1     Running   0          90s
kyverno-reports-controller-7f9d878cdc-dz2jv      1/1     Running   0          90s
```

All four run under Pod Security Admission `restricted` with a namespace
`default-deny-all` NetworkPolicy plus four scoped allows. Nothing was relaxed to
make them start.

One transient warning during startup, self-resolved once Kyverno minted its
serving cert:

```
Warning  Unhealthy  pod/kyverno-admission-controller-...  Startup probe failed:
Get "https://10.244.220.144:9443/health/liveness": remote error: tls: internal error
```

### Correction to the assumption this step was planned against

The brief predicted "egress default-deny will block Kyverno". It did not, because
KateClusters' deny is **per-namespace**, not cluster-wide — verified:

```
$ kubectl get globalnetworkpolicies.crd.projectcalico.org -A
No resources found
$ kubectl get netpol -A          # default-deny-all exists only in app, attack, falco, logging, observability
```

A freshly created `kyverno` namespace therefore started fully open. The policies
in `cluster/bootstrap/networkpolicy.yaml` are not unblocking Kyverno from an
inherited deny — they apply the cluster's posture to a namespace that would
otherwise have escaped it. Same file, opposite reasoning. Recorded in ADR-008.

Two other cluster facts worth carrying forward:

- The apiserver runs with an `AdmissionConfiguration` whose PodSecurity default is
  `restricted`, so an unlabelled namespace is restricted, not unrestricted.
- `AlwaysPullImages` is in `--enable-admission-plugins`. Every pod pull hits the
  registry, so an unsigned-image demo cannot rely on a warm local cache.

Next: step 2.

---

## Step 2 — prove Kyverno can verify these signatures — IN PROGRESS

Blocking finding, established before writing any policy. The registry holds
**four** Sigstore bundles for
`ghcr.io/pontope/provenancepipeline@sha256:5d4b03eae45558381b0236be7cacf0cf67d33a3711fb50ec8ab84a0efc692ea4`,
all with manifest-level `artifactType: application/vnd.dev.sigstore.bundle.v0.3+json`:

| referrer digest | DSSE predicateType | what it is | visible to Kyverno |
|---|---|---|---|
| `sha256:89ffb29d…` | `https://sigstore.dev/cosign/sign/v1` | `cosign sign` | **no** |
| `sha256:e4d547ba…` | `https://spdx.dev/Document` | `cosign attest` SBOM | **no** |
| `sha256:63c8a76d…` | `https://slsa.dev/provenance/v1`, buildType `…/ProvenancePipeline/build-types/github-actions/v1` | `cosign attest slsaprovenance1` | **no** |
| `sha256:fe9b28e0…` | `https://slsa.dev/provenance/v1`, buildType `https://actions.github.io/buildtypes/workflow/v1` | `actions/attest-build-provenance` | yes |

Why only one is visible: GHCR's referrers API returns **HTTP 404**, so
go-containerregistry — which Kyverno uses — falls back to the
`sha256-<digest>` tag index. In that index only GitHub's descriptor carries
`artifactType`; the three cosign descriptors carry
`application/vnd.oci.empty.v1+json` (their config media type) instead.
Kyverno's `fetchBundles` skips any descriptor whose artifactType lacks the
`application/vnd.dev.sigstore.bundle` prefix
(`pkg/image/verifiers/cpol/cosign/sigstore.go`), so it sees exactly one bundle:
GitHub's.

Verified with a raw registry walk, anonymous token, no cosign involved:

```
$ curl -sS -o /dev/null -w '%{http_code}\n' -H "$AUTH" \
    https://ghcr.io/v2/pontope/provenancepipeline/referrers/sha256:5d4b03ea…
404
$ curl -sS -H "$AUTH" -H "$ACC" \
    https://ghcr.io/v2/pontope/provenancepipeline/manifests/sha256-5d4b03ea… \
  | jq -r '.manifests[] | "\(.artifactType) \(.digest)"'
application/vnd.oci.empty.v1+json           sha256:63c8a76d…
application/vnd.oci.empty.v1+json           sha256:89ffb29d…
application/vnd.oci.empty.v1+json           sha256:e4d547ba…
application/vnd.dev.sigstore.bundle.v0.3+json sha256:fe9b28e0…
```

This directly inverts ADR-005, which says the cosign copy is the one the cluster
enforces and GitHub's is the one it cannot. On this registry it is the reverse.

### Attempt already made and abandoned — do not repeat

Publishing the legacy `sha256-<digest>.sig` layout from cosign 3.1.2 by flag.
There is no such flag. `cosign sign --help` on 3.1.2 lists `--bundle`,
`--registry-referrers-mode=legacy|oci-1-1` and `--signing-config`, and **no**
`--new-bundle-format`. cosign 3 removed the legacy writer; the format is not
selectable at this version. The remaining lever is the cosign *version*, not a
flag.

Next: run the empirical probe against the live digest and record which policy
shapes actually pass.

#!/usr/bin/env bash
# The demo this repository exists for: a cluster refusing an image it cannot
# prove the origin of.
#
# Run it against the live cluster. `make demo` calls this. It is also what
# collect-admission-evidence.sh captures, so the evidence file and the recording
# can never disagree — neither is transcribed by hand.
#
#   KUBECTL="sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf" ./scripts/demo.sh
#
# Requires `cosign` on PATH and a cluster with policies/kyverno applied.
set -uo pipefail

KUBECTL="${KUBECTL:-kubectl}"
NS="${NS:-provenance-demo}"

IMAGE="${IMAGE:-ghcr.io/pontope/provenancepipeline}"
DIGEST="${DIGEST:-sha256:5d4b03eae45558381b0236be7cacf0cf67d33a3711fb50ec8ab84a0efc692ea4}"
SIGNED="$IMAGE@$DIGEST"
TAGGED="$IMAGE:latest"
UNSIGNED="docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
OTHER_IDENTITY="reg.kyverno.io/kyverno/kyverno@sha256:0a540e2ddf74d0d2d3d45f9ef248d7dbc96576accdbcc6a2dd7eaff9fea56504"

IDENTITY="https://github.com/PontoPe/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"

if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; D=$'\033[2m'; Z=$'\033[0m'
else B=""; G=""; R=""; D=""; Z=""; fi

say()  { printf '\n%s# %s%s\n' "$D" "$*" "$Z"; }
run()  { printf '%s$ %s%s\n' "$B" "$*" "$Z"; eval "$@" 2>&1; }

pod() { # pod <name> <image>
  cat <<YAML
apiVersion: v1
kind: Pod
metadata: {name: $1, namespace: $NS}
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: app
      image: $2
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: {drop: [ALL]}
YAML
}

# try <name> <image> — attempt admission, report what the API server said
try() {
  printf '%s$ kubectl apply -f - <<< "pod %s using %s"%s\n' "$B" "$1" "$2" "$Z"
  if out=$(pod "$1" "$2" | $KUBECTL apply -f - 2>&1); then
    printf '%s%s%s\n' "$G" "$out" "$Z"
  else
    printf '%s%s%s\n' "$R" "$out" "$Z"
  fi
}

$KUBECTL delete pod signed unsigned tagged other-identity -n "$NS" --ignore-not-found >/dev/null 2>&1

say "The policy is in Enforce, and the webhook fails closed."
run "$KUBECTL get clusterpolicy verify-provenance -o jsonpath='{.spec.rules[*].verifyImages[*].failureAction}{\"\\n\"}'"
run "$KUBECTL get clusterpolicy verify-provenance -o jsonpath='{.spec.webhookConfiguration.failurePolicy}{\"\\n\"}'"

say "1/4  Our image, by digest, signed by the release workflow."
try signed "$SIGNED"
sleep 6
run "$KUBECTL get pod signed -n $NS -o wide"

say "2/4  An ordinary public image. Nothing wrong with it — it just is not ours."
try unsigned "$UNSIGNED"

say "3/4  Genuinely Sigstore-signed, by the Kyverno release workflow."
say "     A signature is not enough. It has to be OUR signature."
try other-identity "$OTHER_IDENTITY"

say "4/4  Our image, our signature, referenced by tag instead of digest."
say "     The signature covers a digest. A tag is a mutable pointer to one."
try tagged "$TAGGED"

say "The provenance the cluster just enforced, read back from the registry:"
run "cosign verify-attestation --type slsaprovenance1 \\
    --certificate-identity '$IDENTITY' \\
    --certificate-oidc-issuer '$ISSUER' \\
    $SIGNED 2>/dev/null \\
  | jq -r '.payload | @base64d | fromjson | .predicate
      | {buildType: .buildDefinition.buildType,
         builder: .runDetails.builder.id,
         invocation: .runDetails.metadata.invocationId}'"

say "One pod running. Three refused, before anything was pulled or executed."
run "$KUBECTL get pods -n $NS"

#!/usr/bin/env bash
# Authorized lab only: intentionally invalid proofs, never runnable releases.
set -euo pipefail
: "${REF:?}" "${IDENTITY:?}" "${GITHUB_RUN_ID:?}"
[[ "$REF" =~ ^ghcr\.io/pontope/provenancepipeline@sha256:[0-9a-f]{64}$ ]]
[[ "$IDENTITY" == 'https://github.com/PontoPe/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main' ]]
image=${REF%@*}
media=application/vnd.dev.sigstore.bundle.v0.3+json
mkdir -p negative-fixtures
cp provenance.json negative-fixtures/good-predicate.json
cp signature.bundle.json negative-fixtures/good-signature.bundle.json
cp provenance.bundle.json negative-fixtures/good-provenance.bundle.json
cd negative-fixtures
for kind in cosignonly wrongdigest badpredicate; do
  mkdir "$kind"
  printf 'Intentional B5 negative fixture: %s run %s\n' "$kind" "$GITHUB_RUN_ID" > "$kind/payload.txt"
  timeout 180 oras push --artifact-type application/vnd.provenancepipeline.b5-fixture.v1 \
    --export-manifest "$kind/subject.manifest.json" \
    "$image:b5-$kind-$GITHUB_RUN_ID" "$kind/payload.txt:text/plain" > "$kind/push.log"
  digest="sha256:$(sha256sum "$kind/subject.manifest.json" | cut -d' ' -f1)"
  target="$image@$digest"
  printf '%s\n' "$target" > "$kind/ref.txt"
  if [[ "$kind" == cosignonly ]]; then
    # Native Cosign compatibility control; maintained 3.1.4 layout is discoverable.
    timeout 180 cosign sign --yes --bundle "$kind/signature.bundle.json" "$target"
    timeout 180 cosign attest --yes --type slsaprovenance1 --predicate good-predicate.json \
      --bundle "$kind/provenance.bundle.json" "$target"
    timeout 180 cosign verify-attestation --type slsaprovenance1 \
      --certificate-identity "$IDENTITY" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      "$target" > "$kind/cli-verified.ndjson"
    timeout 90 oras manifest fetch "$image:${digest/:/-}" --output "$kind/index.json"
    continue
  elif [[ "$kind" == badpredicate ]]; then
    jq '.buildDefinition.externalParameters.workflow.repository = "https://github.com/PontoPe/not-this-repository"' good-predicate.json > "$kind/predicate.json"
    timeout 180 cosign sign --yes --bundle "$kind/signature.bundle.json" "$target"
    timeout 180 cosign attest --yes --type slsaprovenance1 --predicate "$kind/predicate.json" \
      --bundle "$kind/provenance.bundle.json" "$target"
  else
    # Same signature bytes but bound to the GOOD image, not this subject digest.
    cp good-signature.bundle.json "$kind/signature.bundle.json"
    cp good-provenance.bundle.json "$kind/provenance.bundle.json"
  fi
  for proof in signature provenance; do
    timeout 180 oras attach --distribution-spec v1.1-referrers-tag --artifact-type "$media" \
      --export-manifest "$kind/$proof.manifest.json" "$target" "$kind/$proof.bundle.json:$media" \
      > "$kind/$proof.attach.log"
  done
  timeout 90 oras manifest fetch "$image:${digest/:/-}" --output "$kind/index.json"
done

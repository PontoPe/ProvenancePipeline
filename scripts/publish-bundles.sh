#!/usr/bin/env bash
# Repackage unchanged Sigstore bytes; never re-sign or trust registry metadata.
set -euo pipefail
: "${REF:?digest reference required}" "${IDENTITY:?exact identity required}" "${REVISION:?source revision required}"
ISSUER=https://token.actions.githubusercontent.com
OUT=${OUT:-publication}
MEDIA=application/vnd.dev.sigstore.bundle.v0.3+json
[[ "$REF" =~ ^ghcr\.io/pontope/provenancepipeline@sha256:[0-9a-f]{64}$ ]]
[[ "$IDENTITY" == 'https://github.com/PontoPe/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main' ]]
[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]]
mkdir -p "$OUT"
image=${REF%@*}
digest=${REF##*@}
# One writer, sequential attachment: fallback-index updates are not transactional.
for kind in signature sbom provenance; do
  bundle="$kind.bundle.json"
  test -s "$bundle"
  timeout 180 oras attach --distribution-spec v1.1-referrers-tag \
    --artifact-type "$MEDIA" --export-manifest "$OUT/$kind.uploaded.json" \
    "$REF" "$bundle:$MEDIA" > "$OUT/$kind.attach.log"
  md="sha256:$(sha256sum "$OUT/$kind.uploaded.json" | cut -d' ' -f1)"
  timeout 90 oras manifest fetch "$image@$md" --output "$OUT/$kind.manifest.json"
  timeout 90 oras manifest fetch "$image:${digest/:/-}" --output "$OUT/$kind.index.json"
  bd="sha256:$(sha256sum "$bundle" | cut -d' ' -f1)"
  timeout 90 oras blob fetch "$image@$bd" --output "$OUT/$kind.bundle.json"
  cmp "$bundle" "$OUT/$kind.bundle.json"
  python3 scripts/bundle_publication.py layout "$OUT/$kind.index.json" \
    "$OUT/$kind.manifest.json" "$OUT/$kind.bundle.json" --subject-digest "$digest" \
    > "$OUT/$kind.layout.json"
done
# All three must remain in the final index, not merely in an intermediate write.
for kind in signature sbom provenance; do
  python3 scripts/bundle_publication.py layout "$OUT/provenance.index.json" \
    "$OUT/$kind.manifest.json" "$OUT/$kind.bundle.json" --subject-digest "$digest"
done
timeout 180 cosign verify --certificate-identity "$IDENTITY" \
  --certificate-oidc-issuer "$ISSUER" "$REF" > "$OUT/signature.verified.json"
timeout 180 cosign verify-attestation --type slsaprovenance1 \
  --certificate-identity "$IDENTITY" --certificate-oidc-issuer "$ISSUER" \
  "$REF" > "$OUT/provenance.verified.ndjson"
python3 scripts/bundle_publication.py decode "$OUT/provenance.verified.ndjson" > "$OUT/statements.json"
python3 scripts/offline_checks.py publication "$OUT/statements.json" \
  --ref "$REF" --revision "$REVISION" > "$OUT/content.json"

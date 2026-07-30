#!/usr/bin/env bash
# Fetch the pinned Kyverno release manifest and refuse to continue unless its
# content hash matches.
#
# Why this exists instead of a kustomize remote resource: a repository whose
# whole argument is "verify provenance before you run it" cannot install its own
# admission controller from an unverified URL. A GitHub release asset is not
# content-addressed — the tag is a mutable pointer, exactly what the policy this
# installs refuses to trust for container images. So the manifest is pinned by
# sha256 here and the hash is enforced, not merely documented.
#
# The manifest itself is not committed: it is 5.7 MB of generated CRDs. The hash
# is committed, which is the part that matters.
set -euo pipefail

KYVERNO_VERSION="${KYVERNO_VERSION:-v1.18.2}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/upstream"
URL="https://github.com/kyverno/kyverno/releases/download/${KYVERNO_VERSION}/install.yaml"

mkdir -p "$DEST"

if [ -f "$DEST/install.yaml" ] && (cd "$DEST" && sha256sum -c "$HERE/upstream.sha256" >/dev/null 2>&1); then
  echo "==> upstream install.yaml already present and matches upstream.sha256"
  exit 0
fi

echo "==> fetching $URL"
curl -fsSL -o "$DEST/install.yaml.tmp" "$URL"

echo "==> verifying sha256 against $HERE/upstream.sha256"
mv "$DEST/install.yaml.tmp" "$DEST/install.yaml"
if ! (cd "$DEST" && sha256sum -c "$HERE/upstream.sha256"); then
  echo "!! checksum mismatch for $URL" >&2
  echo "!! got:      $(cd "$DEST" && sha256sum install.yaml)" >&2
  echo "!! expected: $(cat "$HERE/upstream.sha256")" >&2
  echo "!! refusing to install. Either the release was re-cut or this is tampering." >&2
  rm -f "$DEST/install.yaml"
  exit 1
fi

echo "==> ok: Kyverno ${KYVERNO_VERSION} manifest verified"

#!/usr/bin/env python3
"""Fail-closed output/layout checks; never a substitute for signature verification.

Decoder input MUST be stdout from successful cosign verify-attestation, with
identity AND issuer pinned and verifier exit status propagated by the caller.
Registry descriptor checks prove discoverability only, not authenticity.
"""
import argparse
import base64
import binascii
import hashlib
import json
import re
from pathlib import Path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def load_json(text):
    return json.loads(text, object_pairs_hook=unique_object)

MEDIA = "application/vnd.dev.sigstore.bundle.v0.3+json"


def decode_verified(text):
    statements = []
    try:
        for line in text.splitlines():
            if not line.strip():
                continue
            envelope = load_json(line)
            if not isinstance(envelope, dict) or envelope.get("payloadType") != "application/vnd.in-toto+json":
                raise ValueError("expected verified DSSE envelope NDJSON")
            payload = base64.b64decode(envelope["payload"], validate=True)
            statement = load_json(payload)
            if not isinstance(statement, dict):
                raise ValueError("expected decoded statement object")
            statements.append(statement)
    except (KeyError, TypeError, binascii.Error, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("malformed verified DSSE output") from error
    if not statements:
        raise ValueError("empty verified output")
    return statements


def check_descriptor(index, manifest, manifest_digest, subject_digest, bundle_digest,
                     manifest_size, bundle_size):
    image_media = "application/vnd.oci.image.manifest.v1+json"
    descriptors = index.get("manifests", [])
    matches = [d for d in descriptors if d.get("digest") == manifest_digest
               and d.get("artifactType") == MEDIA
               and d.get("mediaType") == image_media and d.get("size") == manifest_size]
    layers = manifest.get("layers", [])
    config = manifest.get("config", {})
    config_size = config.get("size")
    if (index.get("schemaVersion") != 2 or manifest.get("schemaVersion") != 2
            or manifest.get("mediaType") != image_media
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", config.get("digest", ""))
            or type(config_size) is not int or config_size < 0
            or not isinstance(config.get("mediaType"), str) or not config["mediaType"]
            or len(matches) != 1 or manifest.get("artifactType") != MEDIA
            or manifest.get("subject", {}).get("digest") != subject_digest
            or len(layers) != 1 or layers[0].get("digest") != bundle_digest
            or layers[0].get("mediaType") != MEDIA or layers[0].get("size") != bundle_size):
        raise ValueError("bundle not discoverable or publication binding differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    decode = commands.add_parser("decode")
    decode.add_argument("verified_output", type=Path)
    layout = commands.add_parser("layout")
    layout.add_argument("index", type=Path)
    layout.add_argument("manifest", type=Path)
    layout.add_argument("bundle", type=Path)
    layout.add_argument("--subject-digest", required=True)
    args = parser.parse_args()
    try:
        if args.command == "decode":
            result = decode_verified(args.verified_output.read_text())
        else:
            raw = args.manifest.read_bytes()
            bundle = args.bundle.read_bytes()
            check_descriptor(load_json(args.index.read_text()), load_json(raw),
                             "sha256:" + hashlib.sha256(raw).hexdigest(), args.subject_digest,
                             "sha256:" + hashlib.sha256(bundle).hexdigest(), len(raw), len(bundle))
            result = {"status": "layout-valid", "cryptographic_verification_performed": False,
                      "consumer_compatibility_proven": False}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "rejected", "error": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

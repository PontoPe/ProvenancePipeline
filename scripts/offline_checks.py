#!/usr/bin/env python3
"""Local structural checks. No registry, cryptographic verification or kubectl."""
import hashlib
import json
import re
from pathlib import Path

import yaml

# Reviewed spec at c22c13b65799c3d57fe192d4bd8d3c57716550e4.
# Intentionally independent of the input: changing the candidate cannot bless it.
POLICY_SPEC_SHA256 = "819132b1c4cddc0327672bec67483ca3f577f7dd93ed6619477bd2438ee9840f"


class UniqueLoader(yaml.SafeLoader):
    """Reject ambiguous mappings instead of silently taking the last key."""


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError(f"duplicate mapping key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def check_policy(path):
    policy = yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    if isinstance(policy, dict) and policy.get("kind") == "List":
        candidates = [p for p in policy.get("items", []) if isinstance(p, dict)
                      and p.get("kind") == "ClusterPolicy"
                      and p.get("metadata", {}).get("name") == "verify-provenance"]
        if len(candidates) != 1:
            raise ValueError("expected exactly one ClusterPolicy verify-provenance")
        policy = candidates[0]
    if not isinstance(policy, dict):
        raise ValueError("expected ClusterPolicy verify-provenance")
    if (policy.get("apiVersion"), policy.get("kind"), policy.get("metadata", {}).get("name")) != (
        "kyverno.io/v1", "ClusterPolicy", "verify-provenance"
    ):
        raise ValueError("expected ClusterPolicy verify-provenance")
    actual = hashlib.sha256(json.dumps(policy["spec"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if actual != POLICY_SPEC_SHA256:
        raise ValueError("policy spec drift: reviewed contract differs")
    return {"status": "policy-contract-valid", "live_enforcement_proven": False, "spec_sha256": actual}


IMAGE = "ghcr.io/pontope/provenancepipeline"
REPOSITORY = "https://github.com/PontoPe/ProvenancePipeline"
WORKFLOW = ".github/workflows/release.yml"
IDENTITY = f"{REPOSITORY}/{WORKFLOW}@refs/heads/main"


def check_publication(path, ref, revision):
    """Validate decoded own-writer statements AFTER a separate trusted verifier.

    This function does not establish authenticity or registry discoverability.
    Inputs are intentionally not normalized; tags and malformed tokens fail.
    """
    match = re.fullmatch(re.escape(IMAGE) + r"@sha256:([0-9a-f]{64})", ref)
    if not match or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("expected exact image digest and 40-character Git revision")
    statements = yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    if not isinstance(statements, list) or not statements:
        raise ValueError("expected nonempty array of decoded own-writer statements")
    for statement in statements:
        try:
            predicate = statement["predicate"]
            definition = predicate["buildDefinition"]
            valid = (
                statement["_type"] == "https://in-toto.io/Statement/v1"
                and statement["subject"] == [{"name": IMAGE, "digest": {"sha256": match[1]}}]
                and statement["predicateType"] == "https://slsa.dev/provenance/v1"
                and predicate["runDetails"]["builder"]["id"] == IDENTITY
                and definition["buildType"] == REPOSITORY + "/build-types/github-actions/v1"
                and definition["externalParameters"]["workflow"] == {
                    "repository": REPOSITORY, "ref": "refs/heads/main", "path": WORKFLOW}
                and definition["resolvedDependencies"] == [{
                    "uri": "git+" + REPOSITORY + "@refs/heads/main",
                    "digest": {"gitCommit": revision}}]
            )
        except (KeyError, TypeError):
            valid = False
        if not valid:
            raise ValueError("publication content differs from exact own-writer contract")
    return {"status": "publication-content-valid", "statements_checked": len(statements),
            "cryptographic_verification_performed": False, "consumer_compatibility_proven": False}


def compatibility_plan():
    """Preparation only: no executable registry or cluster operations."""
    expectations = [
        ("baseline-with-github-writer", "admit-and-healthy"),
        ("own-proof-without-github-writer", "admit-and-healthy-required-to-close-B5"),
        ("unsigned", "deny"),
        ("wrong-identity", "deny"),
        ("wrong-issuer", "deny"),
        ("wrong-subject-digest", "deny"),
        ("wrong-provenance-fields", "deny"),
        ("tag-reference", "deny"),
        ("webhook-unavailable", "deny-covered-request"),
        ("registry-unavailable-cold-cache", "deny-if-trust-cannot-be-established"),
        ("registry-unavailable-warm-cache", "measure-with-cache-TTL"),
        ("policy-removed", "detect-drift"),
        ("policy-relaxed", "detect-drift"),
        ("negative-control-unexpectedly-admitted", "experiment-must-fail"),
    ]
    return {"status": "not-run", "b5_resolved": False,
            "versions": {"publisher": None, "consumer": None, "registry_layout": None},
            "cases": [{"id": name, "expected": expected, "observed": None}
                      for name, expected in expectations]}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    policy = commands.add_parser("policy", help="check local policy or exported List against reviewed spec")
    policy.add_argument("path", type=Path)
    publication = commands.add_parser("publication", help="check decoded own-writer statement content, NOT authenticity")
    publication.add_argument("path", type=Path)
    publication.add_argument("--ref", required=True)
    publication.add_argument("--revision", required=True)
    commands.add_parser("compatibility-plan", help="emit unexecuted matrix; exits 2 (not proven)")
    args = parser.parse_args()
    try:
        if args.command == "policy":
            result = check_policy(args.path)
        elif args.command == "publication":
            result = check_publication(args.path, args.ref, args.revision)
        else:
            print(json.dumps(compatibility_plan(), sort_keys=True))
            return 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as error:
        print(json.dumps({"status": "rejected", "error": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

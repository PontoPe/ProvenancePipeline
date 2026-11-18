"""Synthetic fixtures only; never registry or admission evidence."""
import importlib.util
from pathlib import Path
import unittest
import copy
import json
import tempfile
import yaml


def checker():
    spec = importlib.util.spec_from_file_location("offline_checks", ROOT / "scripts/offline_checks.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def temporary_check(content):
    with tempfile.TemporaryDirectory(dir=ROOT / "tests/offline") as directory:
        path = Path(directory) / "policy.yaml"
        path.write_text(content)
        return checker().check_policy(path)

ROOT = Path(__file__).resolve().parents[2]


class PolicyContractTests(unittest.TestCase):
    def test_checked_in_policy_matches_reviewed_contract(self):
        spec = importlib.util.spec_from_file_location("offline_checks", ROOT / "scripts/offline_checks.py")
        self.assertTrue(spec.origin and Path(spec.origin).exists(), "offline checker is missing")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.check_policy(ROOT / "policies/kyverno/verify-images.yaml")
        self.assertEqual(result["status"], "policy-contract-valid")
        self.assertIs(result["live_enforcement_proven"], False)

    def test_relaxed_specs_are_rejected(self):
        original = yaml.safe_load((ROOT / "policies/kyverno/verify-images.yaml").read_text())
        mutations = [
            lambda s: s["webhookConfiguration"].update(failurePolicy="Ignore"),
            lambda s: s.update(admission=False),
            lambda s: s["rules"].pop(),
            lambda s: s["rules"][0]["verifyImages"][0].update(failureAction="Audit"),
            lambda s: s["rules"][0]["verifyImages"][0].update(required=False),
            lambda s: s["rules"][0]["verifyImages"][0].update(verifyDigest=False),
            lambda s: s["rules"][0]["verifyImages"][0].update(mutateDigest=True),
            lambda s: s["rules"][0]["verifyImages"][0].pop("attestations"),
            lambda s: s["rules"][0]["verifyImages"][0]["attestors"][0]["entries"][0]["keyless"].update(subject="*"),
            lambda s: s["rules"][0]["verifyImages"][0]["attestations"][0]["attestors"][0]["entries"][0]["keyless"].update(issuer="https://accounts.google.com"),
            lambda s: s["rules"][0]["verifyImages"][0]["attestations"][0].update(conditions=[]),
            lambda s: s["rules"][0]["exclude"]["any"][0]["resources"]["namespaces"].append("default"),
            lambda s: s["rules"][1]["match"]["any"][0]["resources"]["namespaceSelector"]["matchLabels"].update({"provenancepipeline.io/admission": "disabled"}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                policy = copy.deepcopy(original)
                mutate(policy["spec"])
                with self.assertRaisesRegex(ValueError, "drift"):
                    temporary_check(json.dumps(policy))

    def test_exported_policy_list_is_accepted_without_trusting_status(self):
        policy = yaml.safe_load((ROOT / "policies/kyverno/verify-images.yaml").read_text())
        policy["status"] = {"ready": True}  # Not proof of admission behavior.
        result = temporary_check(json.dumps({"apiVersion": "v1", "kind": "List", "items": [policy]}))
        self.assertIs(result["live_enforcement_proven"], False)

    def test_missing_and_duplicate_target_in_export_are_rejected(self):
        policy = yaml.safe_load((ROOT / "policies/kyverno/verify-images.yaml").read_text())
        for items in ([], [policy, copy.deepcopy(policy)]):
            with self.subTest(count=len(items)), self.assertRaisesRegex(ValueError, "exactly one"):
                temporary_check(json.dumps({"apiVersion": "v1", "kind": "List", "items": items}))

    def test_formatting_and_export_metadata_do_not_change_spec_fingerprint(self):
        policy = yaml.safe_load((ROOT / "policies/kyverno/verify-images.yaml").read_text())
        policy["metadata"]["resourceVersion"] = "synthetic-not-live"
        result = temporary_check(json.dumps(policy, indent=4, sort_keys=True))
        self.assertEqual(result["spec_sha256"], checker().POLICY_SPEC_SHA256)

    def test_duplicate_yaml_keys_are_rejected(self):
        content = (ROOT / "policies/kyverno/verify-images.yaml").read_text()
        content = content.replace("failurePolicy: Fail\n", "failurePolicy: Ignore\n    failurePolicy: Fail\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            temporary_check(content)


if __name__ == "__main__":
    unittest.main()

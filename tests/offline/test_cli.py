"""Exercise real CLI exit codes; all inputs remain local and synthetic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_contracts import ROOT
from test_publication import DIGEST, IMAGE, REVISION, statement


def run(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/offline_checks.py"), *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True, timeout=10,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


class CLITests(unittest.TestCase):
    def test_policy_command_and_missing_input_have_opposite_exit_codes(self):
        result = run("policy", ROOT / "policies/kyverno/verify-images.yaml")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(json.loads(result.stdout)["live_enforcement_proven"], False)
        with tempfile.TemporaryDirectory(dir=ROOT / "tests/offline") as directory:
            for text in ("", "[]", "{broken", '{"kind":"List","items":[]}',
                         '{"kind":"ClusterPolicy","metadata":null}'):
                path = Path(directory) / "invalid.yaml"
                path.write_text(text)
                result = run("policy", path)
                self.assertNotEqual(result.returncode, 0, text)
                self.assertEqual(json.loads(result.stdout)["status"], "rejected")
        result = run("policy", ROOT / "tests/offline/does-not-exist.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "rejected")

    def test_publication_command_rejects_empty_output_and_accepts_exact_content(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests/offline") as directory:
            path = Path(directory) / "statements.json"
            for value, expected in (([statement()], 0), ([], 1)):
                path.write_text(json.dumps(value))
                result = run("publication", path, "--ref", IMAGE + "@sha256:" + DIGEST,
                             "--revision", REVISION)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn("status", json.loads(result.stdout))

    def test_compatibility_plan_is_not_a_successful_experiment(self):
        result = run("compatibility-plan")
        self.assertEqual(result.returncode, 2)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "not-run")
        self.assertIs(plan["b5_resolved"], False)
        self.assertEqual(plan["versions"], {"publisher": None, "consumer": None, "registry_layout": None})
        self.assertTrue(all(row["observed"] is None for row in plan["cases"]))
        self.assertIn("own-proof-without-github-writer", {row["id"] for row in plan["cases"]})


if __name__ == "__main__":
    unittest.main()

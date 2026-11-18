"""Exact reviewed API-defaulted export, not a tolerant drift normalizer."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LiveExportTests(unittest.TestCase):
    def test_reviewed_defaults_only(self):
        spec = importlib.util.spec_from_file_location('checks', ROOT / 'scripts/offline_checks.py')
        assert spec is not None and spec.loader is not None
        checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checks)
        import yaml
        policy = yaml.safe_load((ROOT / 'policies/kyverno/verify-images.yaml').read_text())
        s = policy['spec']
        s.update(admission=True, emitWarning=False, validationFailureAction='Audit')
        for rule in s['rules']:
            rule['skipBackgroundRequests'] = True
            for vi in rule['verifyImages']:
                vi['useCache'] = True
                for group in [vi['attestors'], *[a['attestors'] for a in vi.get('attestations', [])]]:
                    for attestor in group:
                        for entry in attestor['entries']:
                            entry['signatureAlgorithm'] = 'sha256'
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'export.json'
            p.write_text(json.dumps(policy))
            with self.assertRaises(ValueError):
                checks.check_policy(p)
            self.assertEqual(checks.check_policy(p, kyverno119_export=True)['status'], 'policy-contract-valid')
            mutations = []
            for key, value in [('admission', False), ('emitWarning', True), ('validationFailureAction', 'Enforce')]:
                candidate = copy.deepcopy(policy)
                candidate['spec'][key] = value
                mutations.append(candidate)
            for change in ('Audit', 'remove-rule', 'cache', 'unknown'):
                candidate = copy.deepcopy(policy)
                cs = candidate['spec']
                if change == 'Audit':
                    cs['rules'][0]['verifyImages'][0]['failureAction'] = 'Audit'
                elif change == 'remove-rule':
                    cs['rules'].pop()
                elif change == 'cache':
                    cs['rules'][0]['verifyImages'][0]['useCache'] = False
                else:
                    cs['unknown'] = True
                mutations.append(candidate)
            for candidate in mutations:
                p.write_text(json.dumps(candidate))
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    checks.check_policy(p, kyverno119_export=True)

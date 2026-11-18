"""An unexpected admit and unrelated failure must both fail the observer."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))


class ObserverTests(unittest.TestCase):
    def test_negative_control_checks_result_and_reason(self):
        spec = importlib.util.spec_from_file_location('observer', ROOT / 'scripts/check_enforcement.py')
        assert spec is not None and spec.loader is not None
        observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(observer)
        observer.require_negative(1, '', 'sigstore bundle verification failed: no matching signatures found')
        for rc, stdout, stderr in [(0, 'pod created', ''), (1, '', 'connection refused'),
                                   (1, '', 'forbidden: cannot create pods')]:
            with self.subTest(rc=rc, stderr=stderr), self.assertRaises(ValueError):
                observer.require_negative(rc, stdout, stderr)

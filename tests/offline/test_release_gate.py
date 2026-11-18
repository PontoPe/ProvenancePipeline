"""Release wiring assertions; mocks are not a substitute for live publication."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ReleaseGateTests(unittest.TestCase):
    def test_own_publication_is_required_and_precedes_optional_writer(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        job = workflow['jobs']['build-sign-attest']
        steps = job['steps']
        names = [s.get('name', '') for s in steps]
        gate = names.index('publish and verify own bundles')
        optional = workflow['jobs']['optional-github-proof']
        self.assertIn('verify', optional['needs'])
        self.assertNotIn('continue-on-error', steps[gate])
        self.assertIn('refs/heads/main', job['if'])
        for name in ('sign image (keyless)', 'attest SBOM (SPDX)', 'attest SLSA provenance (cosign)'):
            self.assertIn('--bundle', steps[names.index(name)]['run'])
        self.assertIn('skip_github_writer', optional['if'])

    def test_publisher_propagates_remote_and_verifier_failure(self):
        import os
        import subprocess
        import tempfile
        script = ROOT / 'scripts/publish-bundles.sh'
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            mock = path / 'oras'
            mock.write_text('#!/bin/sh\ntouch "$OUT/oras-called"\nexit 73\n')
            (path / 'signature.bundle.json').write_text('{}')
            mock.chmod(0o755)
            result = subprocess.run(['bash', str(script)], cwd=path, env={
                **os.environ, 'PATH': d + ':' + os.environ['PATH'],
                'REF': 'ghcr.io/pontope/provenancepipeline@sha256:' + 'a' * 64,
                'IDENTITY': 'https://github.com/PontoPe/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main',
                'REVISION': 'b' * 40, 'OUT': str(path / 'out')}, capture_output=True)
            self.assertEqual(result.returncode, 73)
            self.assertTrue((path / 'out/oras-called').exists())

    def test_skip_github_writer_also_skips_github_verifier(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        steps = workflow['jobs']['verify']['steps']
        optional = workflow['jobs']['optional-github-proof']
        self.assertIn('skip_github_writer', optional['if'])
        self.assertFalse(any(s.get('name') == 'verify GitHub build provenance' for s in steps))
        self.assertTrue(any(s.get('name') == 'verify own publication content' for s in steps))


if __name__ == '__main__':
    unittest.main()

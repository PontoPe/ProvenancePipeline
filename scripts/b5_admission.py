#!/usr/bin/env python3
"""Authorized disposable-lab admission matrix. Raw output is never synthesized."""
import argparse
import copy
import json
import re
import subprocess
import time
from pathlib import Path

import yaml

from check_enforcement import UNSIGNED

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'ghcr.io/pontope/provenancepipeline@sha256:5db4fa5a86b74442bea46af83db05d9f1089aec1ac5dd8839107105a58eb9f3a'


class Lab:
    def __init__(self, context, out):
        if not re.fullmatch(r'kind-prove-lab-[a-z0-9-]+', context):
            raise ValueError('only a dedicated prove-lab context is allowed')
        self.context = context
        self.k = ['kubectl', '--context', context, '--request-timeout=45s']
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.results = []
        self.base = yaml.safe_load((ROOT / 'policies/kyverno/verify-images.yaml').read_text())
        nodes = self.run('guard-nodes', self.k + ['get', 'nodes', '-o', 'json'])
        names = [n['metadata']['name'] for n in json.loads(nodes.stdout)['items']]
        if names != [context.removeprefix('kind-') + '-control-plane']:
            raise ValueError('context node identity differs from dedicated lab')

    def run(self, name, argv, data=None):
        start = time.monotonic()
        p = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=160)
        (self.out / (name + '.json')).write_text(json.dumps({
            'argv': argv, 'rc': p.returncode, 'seconds': time.monotonic() - start,
            'stdout': p.stdout, 'stderr': p.stderr}, indent=2))
        return p

    def policy(self, obj, name):
        p = self.run(name, self.k + ['apply', '-f', '-'], json.dumps(obj))
        if p.returncode:
            raise ValueError(p.stderr)
        p = self.run(name + '-ready', self.k + ['wait', '--for=condition=Ready',
                     'clusterpolicy/verify-provenance', '--timeout=90s'])
        if p.returncode:
            raise ValueError(p.stderr)

    def probe(self, name, ref, admit, reason='', namespace='prove-lab', real=False):
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': namespace},
               'spec': {'securityContext': {'runAsNonRoot': True, 'runAsUser': 65532,
                                           'seccompProfile': {'type': 'RuntimeDefault'}},
                        'containers': [{'name': 'app', 'image': ref,
                                        'resources': {'limits': {'memory': '64Mi', 'cpu': '100m'}},
                                        'securityContext': {'allowPrivilegeEscalation': False,
                                                            'capabilities': {'drop': ['ALL']}}}]}}
        argv = self.k + ['create'] + ([] if real else ['--dry-run=server']) + ['-f', '-']
        p = self.run(name, argv, json.dumps(pod))
        passed = (p.returncode == 0) == admit and (not reason or reason in p.stdout + p.stderr)
        self.results.append({'case': name, 'passed': passed, 'expected_admit': admit,
                             'required_reason': reason, 'rc': p.returncode})
        (self.out / 'results.json').write_text(json.dumps(self.results, indent=2))
        if not passed:
            raise ValueError(f'{name}: unexpected admission/reason: {p.stdout} {p.stderr}')
        return p

    def changed_expectation(self, name, ref, field, value, reason):
        policy = copy.deepcopy(self.base)
        for rule in policy['spec']['rules']:
            vi = rule['verifyImages'][0]
            for group in [vi['attestors'], *[a['attestors'] for a in vi.get('attestations', [])]]:
                group[0]['entries'][0]['keyless'][field] = value
        self.policy(policy, name + '-policy')
        try:
            # Informer convergence has a deadline; record every API result, not a hidden sleep.
            for attempt in range(20):
                try:
                    self.probe(name + f'-{attempt}', ref, False, reason)
                    break
                except ValueError:
                    if attempt == 19:
                        raise
                    time.sleep(.5)
        finally:
            self.policy(self.base, name + '-restore')
        # Prove recovery before moving on. Failed transient probes remain raw evidence.
        for attempt in range(20):
            try:
                self.probe(name + f'-recovered-{attempt}', ref, True)
                break
            except ValueError:
                if attempt == 19:
                    raise
                time.sleep(.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'ghcr\.io/pontope/provenancepipeline@sha256:[0-9a-f]{64}', args.image):
        parser.error('exact own image digest required')
    lab = Lab(args.context, args.out)
    try:
        lab.probe('baseline-with-github', BASELINE, True)
        lab.probe('own-proof-default', args.image, True, namespace='default')
        lab.probe('own-proof', args.image, True, real=True)
        ready = lab.run('own-proof-ready', lab.k + ['-n', 'prove-lab', 'wait', '--for=condition=Ready', 'pod/own-proof', '--timeout=120s'])
        if ready.returncode:
            raise ValueError(ready.stderr)
        health = lab.run('own-proof-health', lab.k + ['get', '--raw', '/api/v1/namespaces/prove-lab/pods/own-proof:8080/proxy/healthz'])
        if health.returncode or health.stdout.strip() != 'ok':
            raise ValueError('own-proof workload not healthy')
        lab.probe('unsigned', UNSIGNED, False, 'no matching signatures')
        lab.probe('tag', 'ghcr.io/pontope/provenancepipeline:latest', False, 'missing digest')
        # Cosign 3.1.4 native remote descriptors are corrected as well: actual
        # discovery proved this is a compatible positive, unlike July's 3.1.2.
        native = (args.fixtures / 'cosignonly/ref.txt').read_text().strip()
        if not re.fullmatch(r'ghcr\.io/pontope/provenancepipeline@sha256:[0-9a-f]{64}', native):
            raise ValueError('native fixture reference malformed')
        lab.probe('native-314-compatible', native, True)
        for name in ('wrongdigest', 'badpredicate'):
            ref = (args.fixtures / name / 'ref.txt').read_text().strip()
            if not re.fullmatch(r'ghcr\.io/pontope/provenancepipeline@sha256:[0-9a-f]{64}', ref):
                raise ValueError('fixture reference malformed')
            lab.probe(name, ref, False, 'attestation checks failed' if name == 'badpredicate' else 'no matching signatures')
        lab.changed_expectation('wrong-identity', args.image, 'subject',
            'https://github.com/PontoPe/ProvenancePipeline/.github/workflows/foreign.yml@refs/heads/main', 'no matching signatures')
        lab.changed_expectation('wrong-issuer', args.image, 'issuer', 'https://accounts.google.com', 'no matching signatures')
        # Final correct-spec + negative admission, through the restricted observer.
        check = lab.run('restricted-observer', ['python3', str(ROOT / 'scripts/check_enforcement.py'),
                        '--context', args.context, '--out', str(args.out / 'observer')])
        if check.returncode:
            raise ValueError(check.stdout + check.stderr)
    finally:
        lab.policy(lab.base, 'final-policy-restore')
    print(json.dumps({'status': 'admission-matrix-passed', 'health': 'ok', 'image': args.image}))


if __name__ == '__main__':
    main()

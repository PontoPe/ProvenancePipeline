#!/usr/bin/env python3
"""One-shot lab observer: fresh read-only policy export plus dry-run negative.

RBAC identity requires GET for the target policy and namespace, and CREATE Pods
only in prove-lab (Kubernetes RBAC cannot restrict create to dry-run). No policy,
webhook or controller mutation privileges. Impersonation in the lab proves RBAC;
a production observer needs a separately issued restricted credential.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from offline_checks import check_policy

UNSIGNED = 'docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec'


def require_negative(rc, stdout, stderr):
    if rc == 0:
        raise ValueError('UNSIGNED ADMITTED: enforcement failed')
    if 'no matching signatures' not in stdout + stderr:
        raise ValueError('negative inconclusive: denial was not signature verification')


def observe(k, out):
    def run(name, args, data=None):
        started = time.monotonic()
        p = subprocess.run(k + args, input=data, capture_output=True, text=True, timeout=100)
        (out / (name + '.json')).write_text(json.dumps({
            'argv': k + args, 'rc': p.returncode, 'seconds': time.monotonic() - started,
            'stdout': p.stdout, 'stderr': p.stderr}, indent=2))
        return p

    export = run('fresh-policy', ['get', 'clusterpolicy', 'verify-provenance', '-o', 'json'])
    if export.returncode:
        raise ValueError('policy absent or export unavailable')
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'policy.json'
        path.write_text(export.stdout)
        check_policy(path, kyverno119_export=True)
    namespace = run('namespace', ['get', 'namespace', 'prove-lab', '-o', 'json'])
    if namespace.returncode or json.loads(namespace.stdout)['metadata'].get('labels', {}).get('provenancepipeline.io/admission') != 'enforced':
        raise ValueError('negative namespace is not enforced')
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'observer-negative', 'namespace': 'prove-lab'},
           'spec': {'containers': [{'name': 'negative', 'image': UNSIGNED}]}}
    probe = run('negative-admission', ['create', '--dry-run=server', '-f', '-'], json.dumps(pod))
    require_negative(probe.returncode, probe.stdout, probe.stderr)
    return {'status': 'enforcement-observed', 'scope': 'current spec and unsigned dry-run in prove-lab',
            'continuous_monitoring': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'kind-prove-lab-[a-z0-9-]+', args.context):
        parser.error('only an explicitly named disposable prove-lab context is allowed')
    args.out.mkdir(parents=True, exist_ok=True)
    k = ['kubectl', '--context', args.context, '--request-timeout=45s',
         '--as=system:serviceaccount:prove-lab:enforcement-observer']
    try:
        result = observe(k, args.out)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'rejected', 'error': str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())

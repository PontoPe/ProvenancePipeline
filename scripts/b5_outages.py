#!/usr/bin/env python3
"""Scoped outage/drift experiments, ONLY inside the explicitly named kind lab."""
import argparse
import copy
import json
import socket
import time
from pathlib import Path

from b5_admission import Lab, ROOT
from check_enforcement import UNSIGNED


def registry_denied(p):
    message = p.stdout + p.stderr
    return p.returncode != 0 and 'ghcr.io' in message and 'failed calling webhook' not in message and any(
        term in message.lower() for term in ('connection refused', 'connection reset', 'timeout', 'i/o timeout', 'network is unreachable'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    lab = Lab(args.context, args.out)
    k = lab.k
    node = args.context.removeprefix('kind-') + '-control-plane'

    def ok(name, argv, data=None):
        p = lab.run(name, argv, data)
        if p.returncode:
            raise ValueError(p.stdout + p.stderr)
        return p

    def observer(name, expected):
        p = lab.run(name, ['python3', str(ROOT / 'scripts/check_enforcement.py'), '--context', args.context,
                         '--out', str(args.out / name)])
        if (p.returncode == 0) != expected:
            raise ValueError('unexpected drift observer result: ' + p.stdout + p.stderr)
        return p

    observer('healthy-observer', True)
    try:
        policy = copy.deepcopy(lab.base)
        for rule in policy['spec']['rules']:
            rule['verifyImages'][0]['failureAction'] = 'Audit'
        lab.policy(policy, 'audit-policy')
        observer('audit-detected', False)
        ok('policy-remove', k + ['delete', 'clusterpolicy', 'verify-provenance'])
        observer('absence-detected', False)
        # An intentionally removed policy actually admits unsigned: expose the risk.
        for attempt in range(20):
            try:
                lab.probe('absent-policy-control-' + str(attempt), UNSIGNED, True)
                break
            except ValueError:
                if attempt == 19:
                    raise
                time.sleep(.5)
    finally:
        lab.policy(lab.base, 'drift-restore')
    for attempt in range(20):
        p = lab.run('restored-observer-' + str(attempt), ['python3', str(ROOT / 'scripts/check_enforcement.py'),
                    '--context', args.context, '--out', str(args.out / ('restore-' + str(attempt)))])
        if p.returncode == 0:
            break
        if attempt == 19:
            raise ValueError('enforcement did not recover')
        time.sleep(.5)

    pods = json.loads(ok('webhook-pod', k + ['-n', 'kyverno', 'get', 'pods', '-l',
                         'app.kubernetes.io/component=admission-controller', '-o', 'json']).stdout)['items']
    if len(pods) != 1:
        raise ValueError('expected exactly one lab admission controller')
    ip = pods[0]['status']['podIP']
    # Removing Service endpoints does not terminate existing apiserver keep-alive
    # connections. Reject packets to the actual webhook inside ONLY our node.
    webhook_rule = ['-d', ip, '-p', 'tcp', '--dport', '9443', '-m', 'comment',
                    '--comment', 'prove-lab-b5-webhook-outage', '-j', 'REJECT']
    chains = []
    try:
        for chain in ('OUTPUT', 'FORWARD'):
            ok('webhook-block-' + chain, ['docker', 'exec', node, 'iptables', '-I', chain, '1'] + webhook_rule)
            chains.append(chain)
        lab.probe('webhook-outage', UNSIGNED, False, 'failed calling webhook')
    finally:
        for chain in chains:
            ok('webhook-unblock-' + chain, ['docker', 'exec', node, 'iptables', '-D', chain] + webhook_rule)
    for attempt in range(30):
        try:
            lab.probe('webhook-recovered-' + str(attempt), UNSIGNED, False, 'no matching signatures')
            break
        except ValueError:
            if attempt == 29:
                raise
            time.sleep(.2)

    deploy = json.loads(ok('deployment-original', k + ['-n', 'kyverno', 'get', 'deploy', 'kyverno-admission-controller', '-o', 'json']).stdout)
    original_args = deploy['spec']['template']['spec']['containers'][0]['args']
    # A short explicit test TTL allows actual expiry to be measured without claiming
    # the 60m production default was elapsed. More capacity than the default 1000
    # bytes allows the provenance payload to fit. No trust/policy pins are changed.
    configured_args = [a for a in original_args if not a.startswith(('--imageVerifyCacheTTLDuration=', '--imageVerifyCacheMaxSize='))]
    configured_args += ['--imageVerifyCacheTTLDuration=20s', '--imageVerifyCacheMaxSize=1048576']
    rules = []
    ips = sorted({a[4][0] for a in socket.getaddrinfo('ghcr.io', 443, socket.AF_INET, socket.SOCK_STREAM)})
    (args.out / 'registry-addresses.json').write_text(json.dumps(ips))

    def set_args(values, name):
        patch = [{'op': 'replace', 'path': '/spec/template/spec/containers/0/args', 'value': values}]
        ok(name, k + ['-n', 'kyverno', 'patch', 'deploy', 'kyverno-admission-controller', '--type=json', '-p', json.dumps(patch)])
        ok(name + '-ready', k + ['-n', 'kyverno', 'rollout', 'status', 'deploy/kyverno-admission-controller', '--timeout=120s'])

    try:
        set_args(configured_args, 'cache-test-config')
        # Readiness also covers webhook service; bounded probes record any startup race.
        for attempt in range(30):
            try:
                lab.probe('warmup-' + str(attempt), args.image, True)
                break
            except ValueError:
                if attempt == 29:
                    raise
                time.sleep(.5)
        warmed = time.monotonic()
        for ip in ips:
            rule = ['-d', ip, '-p', 'tcp', '--dport', '443', '-m', 'comment', '--comment', 'prove-lab-b5-registry-outage', '-j', 'REJECT']
            ok('registry-block-' + ip, ['docker', 'exec', node, 'iptables', '-I', 'FORWARD', '1'] + rule)
            rules.append(rule)
        # Warm outcome is a measurement, not a promised admit. Preserve it either way.
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'registry-warm', 'namespace': 'prove-lab'},
               'spec': {'containers': [{'name': 'app', 'image': args.image}]}}
        warm = lab.run('registry-warm', k + ['create', '--dry-run=server', '-f', '-'], json.dumps(pod))
        warm_log = ok('registry-warm-controller-log', k + ['-n', 'kyverno', 'logs', 'deploy/kyverno-admission-controller', '--since=2m'])
        counters = ok('registry-packet-counters', ['docker', 'exec', node, 'iptables', '-L', 'FORWARD', '-v', '-n'])
        hits = [line for line in counters.stdout.splitlines() if 'prove-lab-b5-registry-outage' in line]
        if not hits or not any(int(line.split()[0]) > 0 for line in hits):
            raise ValueError('registry fault did not intercept any packets')
        # First-rule predicate gates may deliberately disable cache. If the
        # apiserver deadline expires, retain that as infrastructure fail-closed,
        # not a signature denial. An independent unsigned request below proves
        # the webhook itself remains reachable during the registry fault.
        if warm.returncode != 0 and not (registry_denied(warm) or 'context deadline exceeded' in warm.stderr):
            raise ValueError('unclassified warm-cache outcome')
        lab.probe('registry-warm-webhook-control', UNSIGNED, False, 'no matching signatures')
        elapsed = time.monotonic() - warmed
        # Wait only the remaining explicit TTL with monotonic deadline.
        deadline = warmed + 22
        while time.monotonic() < deadline:
            time.sleep(min(.2, deadline - time.monotonic()))
        pod['metadata']['name'] = 'registry-expired'
        expired = lab.run('registry-expired', k + ['create', '--dry-run=server', '-f', '-'], json.dumps(pod))
        ok('registry-expired-controller-log', k + ['-n', 'kyverno', 'logs', 'deploy/kyverno-admission-controller', '--since=2m'])
        if not (registry_denied(expired) or (expired.returncode != 0 and 'context deadline exceeded' in expired.stderr)):
            raise ValueError('expired-cache registry denial not established')
        lab.probe('registry-expired-webhook-control', UNSIGNED, False, 'no matching signatures')
        # New controller process is a separate cold cache, not just elapsed TTL.
        ok('cold-restart', k + ['-n', 'kyverno', 'rollout', 'restart', 'deploy/kyverno-admission-controller'])
        ok('cold-ready', k + ['-n', 'kyverno', 'rollout', 'status', 'deploy/kyverno-admission-controller', '--timeout=120s'])
        for attempt in range(30):
            try:
                lab.probe('cold-webhook-control-' + str(attempt), UNSIGNED, False, 'no matching signatures')
                break
            except ValueError:
                if attempt == 29:
                    raise
                time.sleep(.5)
        pod['metadata']['name'] = 'registry-cold'
        cold = lab.run('registry-cold', k + ['create', '--dry-run=server', '-f', '-'], json.dumps(pod))
        ok('registry-cold-controller-log', k + ['-n', 'kyverno', 'logs', 'deploy/kyverno-admission-controller', '--since=2m'])
        if not (registry_denied(cold) or (cold.returncode != 0 and 'context deadline exceeded' in cold.stderr)):
            raise ValueError('cold-cache registry denial not established')
        lab.probe('registry-cold-webhook-control', UNSIGNED, False, 'no matching signatures')
        (args.out / 'cache-summary.json').write_text(json.dumps({
            'configured_ttl_seconds': 20, 'default_ttl_seconds': 3600,
            'configured_cache_capacity': 1048576, 'warm_probe_seconds_after_verification': elapsed,
            'warm_rc': warm.returncode, 'expired_rc': expired.returncode, 'cold_rc': cold.returncode,
            'scope': 'GHCR IPv4 HTTPS rejected in own kind node FORWARD chain only'}, indent=2))
    finally:
        for i, rule in enumerate(rules):
            ok('registry-unblock-' + str(i), ['docker', 'exec', node, 'iptables', '-D', 'FORWARD'] + rule)
        set_args(original_args, 'cache-config-restore')
    for attempt in range(30):
        try:
            lab.probe('registry-recovered-' + str(attempt), args.image, True)
            break
        except ValueError:
            if attempt == 29:
                raise
            time.sleep(.5)
    observer('final-observer', True)
    print(json.dumps({'status': 'outage-drift-matrix-passed'}))


if __name__ == '__main__':
    main()

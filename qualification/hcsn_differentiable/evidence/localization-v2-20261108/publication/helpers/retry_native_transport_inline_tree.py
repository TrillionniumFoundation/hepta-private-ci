"""Retain native gh; recover reads and deterministic Git objects after dial failures."""

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import uuid

ROOT = Path('/Users/qianqi/hepta-hcsn-math-closure-20261108-v1/publication')
if os.environ.get('GODEBUG') != 'http2client=0':
    raise RuntimeError('inline-tree transport requires GODEBUG=http2client=0')
EXPECTED_PLAN = '52e1e4baf0b45012031ff3d9d6cb9ec44c7d2cdffd6a4fc2e60d6403abfee253'
EXPECTED_HELPER = '94ba6d816c1b1997ce6ca51f17be28437f5aed594ae3bf4a65053a04658c2e55'
for name, expected in [('plan.json', EXPECTED_PLAN), ('native_publish_inline_tree.py', EXPECTED_HELPER)]:
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
        raise RuntimeError('frozen publication input changed: ' + name)
LOG_ROOT = ROOT / 'transport-recovery-inline-tree-v1'
LOG_ROOT.mkdir(exist_ok=True)
LOG = LOG_ROOT / uuid.uuid4().hex
LOG.mkdir(exist_ok=False)
print(json.dumps({'transport_log_dir': str(LOG)}), flush=True)
native_run = subprocess.run
counter = 0
pattern = re.compile(r'(?P<method>Get|Post) "(?P<url>https://api\.github\.com/[^"\n]+)": (?:dial tcp [0-9.]+:443: (?:i/o timeout|connect: network is unreachable|connect: connection refused)|net/http: TLS handshake timeout)\n?\Z')
plan = json.loads((ROOT / 'plan.json').read_bytes())
allowed_refs = {'refs/heads/' + s['branch'] for s in plan['stages']}


def run(command, *args, **kwargs):
    global counter
    native_api = isinstance(command, list) and command[:2] == ['/opt/homebrew/bin/gh', 'api']
    body_path = Path(command[command.index('--input') + 1]) if native_api and '--input' in command else None
    body_sha = hashlib.sha256(body_path.read_bytes()).hexdigest() if body_path else None
    method = command[command.index('--method') + 1].upper() if native_api and '--method' in command else 'GET'
    endpoint = command[4] if native_api and command[2:3] == ['--method'] else command[2] if native_api else ''
    safe = native_api and method == 'GET'
    if native_api and method == 'POST' and body_path:
        payload = json.loads(body_path.read_bytes())
        prefix = 'repos/TrillionniumFoundation/hepta-private-ci/git/'
        # Repeated immutable object creation produces the same Git object.
        # A duplicate unique ref is rejected by GitHub and then reconciled by
        # the unchanged publisher. Pull-request creation is never replayed.
        safe = (endpoint == prefix + 'blobs' and payload.get('encoding') == 'base64'
                or endpoint == prefix + 'trees' and isinstance(payload.get('tree'), list)
                or endpoint == prefix + 'commits' and bool(payload.get('author', {}).get('date'))
                    and bool(payload.get('committer', {}).get('date'))
                or endpoint == prefix + 'refs' and payload.get('ref') in allowed_refs)
    attempts = 4 if safe else 1
    for attempt in range(1, attempts + 1):
        if body_path and hashlib.sha256(body_path.read_bytes()).hexdigest() != body_sha:
            raise RuntimeError('request body changed before transport recovery')
        # An outer subprocess timeout is not proof of pre-connect failure.
        # Leave it to the original publisher's read-only reconciliation.
        result = native_run(command, *args, **kwargs)
        failure = pattern.fullmatch(result.stderr) if native_api else None
        if (result.returncode == 0 or not safe or failure is None or result.stdout != ''
                or failure['method'].upper() != method
                or failure['url'] != 'https://api.github.com/' + endpoint):
            return result
        counter += 1
        record = {'argv': command, 'attempt': attempt, 'maximum_attempts': attempts,
                  'classification': 'network_failure_on_replay_safe_read_or_git_object', 'stderr': result.stderr,
                  'input_body_sha256': body_sha,
                  'same_command_and_body_on_retry': True,
                  'transmission_outcome': 'not inferred; correctness uses read idempotence or content-addressed/unique-ref semantics',
                  'pull_request_creation_replayed': False}
        path = LOG / f'{counter:04d}.json'
        with path.open('x') as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({'transport_failure': counter, 'attempt': attempt,
                          'classification': record['classification']}), flush=True)
    return result


subprocess.run = run
sys.argv = [str(ROOT / 'native_publish_inline_tree.py'), str(ROOT)]
runpy.run_path(str(ROOT / 'native_publish_inline_tree.py'), run_name='__main__')

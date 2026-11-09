"""Run the already reviewed 010a append once, preserving its actual OS result."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

R = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e')
W = Path('/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e')
S = R / 'append-evidence-increment-010-draft-v2.py'
I = R / 'increment010-two-ready-packet-preparation-v2/DRAFT_INPUTS.json'
P = R / 'evidence-addendum-increment-010a'
O = R / 'evidence-addendum-increment-010a-launch-v1'
SCRIPT_SHA = 'ae6d82fba105ec66a13ee7f5a952bca6c448ad1352f46ee6d078318477d9ec2f'
INPUT_SHA = '0fc8f813c9d06f759aec536265aeb571246eaeda737f736075998d2e186f4dec'
INDEX_SHA = '0cf1005179c11c185da89843f4bd23d41ce61428de620783bf9f87a5642fc2de'
REQUEST_KEY = '898e-qualification-evidence-increment010a-append-v2-once'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def save(name, value):
    with (O / name).open('x') as file:
        file.write(json.dumps(value, indent=2) + '\n')


def main():
    if not __debug__:
        raise RuntimeError('Evidence assertions must remain enabled')
    assert sys.argv[1:] == []
    assert not O.exists() and not O.is_symlink()
    assert not P.exists() and not P.is_symlink()
    script, inputs = S.read_bytes(), I.read_bytes()
    assert len(script) == 29890 and sha(script) == SCRIPT_SHA
    assert len(inputs) == 386917 and sha(inputs) == INPUT_SHA
    argv = ['/usr/bin/python3', str(S), '--inputs', str(I), '--phase',
            'increment-010a', '--expected-index', INDEX_SHA, '--require-clean']
    O.mkdir(mode=0o700, exist_ok=False)
    request = {'request_key': REQUEST_KEY, 'started_at': now(), 'argv': argv,
               'cwd': str(W), 'script': descriptor(S), 'inputs': descriptor(I),
               'outer': descriptor(Path(__file__)), 'automatic_retry': False,
               'extra_timeout_or_signals': False, 'new_native_tests': 0,
               'commit_push_or_PR_change': False}
    save('REQUEST.json', request)
    with (O / 'stdout').open('xb') as stdout, (O / 'stderr').open('xb') as stderr:
        child = subprocess.run(argv, cwd=W, stdout=stdout, stderr=stderr)
    result = {'status': 'NATURALLY_COMPLETED', 'started_at': request['started_at'],
              'finished_at': now(), 'returncode': child.returncode,
              'child_os_exit_code_directly_observed': True,
              'script_sha256': SCRIPT_SHA, 'inputs_sha256': INPUT_SHA,
              'request': descriptor(O / 'REQUEST.json'),
              'stdout': descriptor(O / 'stdout'), 'stderr': descriptor(O / 'stderr'),
              'append_result': descriptor(P / 'RESULT.json') if (P / 'RESULT.json').is_file() else None,
              'script_and_inputs_after_unchanged': S.read_bytes() == script and I.read_bytes() == inputs,
              'automatic_retry': False, 'extra_timeout_or_signals': False,
              'new_native_tests': 0, 'commit_push_or_PR_change': False}
    save('RESULT.json', result)
    print(json.dumps(result), flush=True)
    if not result['script_and_inputs_after_unchanged']:
        raise RuntimeError('Append controller inputs changed')
    raise SystemExit(child.returncode)


if __name__ == '__main__':
    main()

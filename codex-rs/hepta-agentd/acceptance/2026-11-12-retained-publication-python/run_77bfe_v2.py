import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/workspace/scratch/ce434f960ee9/retained-review')
OUTPUT = Path('/workspace/scratch/ce434f960ee9/retained-review-evidence/77bfe-v2')
EXPECTED_HEAD = '77bfe71c6021e8da78ff917db3347f7e7a503d65'
EXPECTED_TREE = '377b386d89bc0f950ed260d8ab6fe58b423a9976'
BASE = 'f8ea08942b68c84ccc105d17371f95ddd372d355'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


def identity():
    return {
        'head': git('rev-parse', 'HEAD'),
        'tree': git('rev-parse', 'HEAD^{tree}'),
        'tracked_status': git('status', '--porcelain', '--untracked-files=no'),
    }


before = identity()
assert before == {'head': EXPECTED_HEAD, 'tree': EXPECTED_TREE, 'tracked_status': ''}, before
OUTPUT.mkdir(parents=True, exist_ok=False)
environment = dict(os.environ)
environment['PYTHONPYCACHEPREFIX'] = str(OUTPUT / 'pycache')
commands = [
    ('retained-source', ['python3', '-m', 'unittest', 'discover', '-s', 'qa/b4-no-bypass', '-p', 'test_retained_publication_source_closure.py', '-v']),
    ('training-source', ['python3', '-m', 'unittest', 'discover', '-s', 'qa/b4-no-bypass', '-p', 'test_original_training_command_source_closure.py', '-v']),
    ('coverage-parser', ['python3', '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_hepta_c_observer_coverage.py', '-v']),
    ('py-compile', ['python3', '-m', 'py_compile', 'qa/b4-no-bypass/test_retained_publication_source_closure.py', 'qa/b4-no-bypass/test_original_training_command_source_closure.py', 'scripts/hepta_c_observer_coverage.py']),
    ('diff-check', ['git', 'diff', '--check', BASE, 'HEAD']),
]
record = {
    'schema': 'hepta.retained-publication.python-review.v1',
    'scope': 'two exact source-control modules, existing coverage parser, Python syntax and whitespace only',
    'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source_before': before,
    'commands': [],
    'rust_executed': False,
    'full_caller_proof_executed': False,
    'authority_granted': False,
}
for name, argv in commands:
    started = time.monotonic()
    path = OUTPUT / f'{name}.log'
    with path.open('xb') as log:
        completed = subprocess.run(argv, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
    raw = path.read_bytes()
    item = {'name': name, 'argv': argv, 'exit_code': completed.returncode, 'elapsed_seconds': round(time.monotonic() - started, 6), 'log_bytes': len(raw), 'log_sha256': hashlib.sha256(raw).hexdigest()}
    record['commands'].append(item)
    print(json.dumps(item), flush=True)
    (OUTPUT / 'progress.json').write_text(json.dumps(record, indent=2) + '\n')
record['source_after'] = identity()
record['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
record['complete'] = True
record['passed'] = record['source_before'] == record['source_after'] and all(item['exit_code'] == 0 for item in record['commands'])
(OUTPUT / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'passed': record['passed'], 'result': str(OUTPUT / 'result.json')}), flush=True)
sys.exit(0 if record['passed'] else 1)

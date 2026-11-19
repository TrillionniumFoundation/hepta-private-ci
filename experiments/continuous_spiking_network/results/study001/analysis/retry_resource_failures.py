"""Serial operational recovery using the unchanged recorded training commands."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

STUDY = Path(__file__).resolve().parents[1]
PACKAGE = STUDY.parents[1]


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def check_source():
    seal = json.loads((PACKAGE / 'SOURCE_SEAL.json').read_text())
    records = {name: hashlib.sha256((PACKAGE/name).read_bytes()).hexdigest()
               for name in seal['files']}
    assert records == seal['files']
    assert hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest() == seal['sha256']
    return seal['sha256']


def main():
    inventory = json.loads((STUDY/'RUNS.json').read_text())
    source = check_source()
    assert source == inventory['source_seal']
    pending = []
    for run in inventory['runs']:
        directory = STUDY/run['run_id']
        if (directory/'RESULT.json').exists():
            continue
        attempts = sorted(directory.glob('EXECUTION_*.json'))
        assert attempts, 'Initial runner must finish every attempted job first'
        previous = json.loads(attempts[-1].read_text())
        assert previous['exit_code'] == -9, 'Recovery restricted to external SIGKILL'
        pending.append((run, directory, previous))
    write(STUDY/'RECOVERY_PLAN.json', {'source_seal': source, 'created_unix': time.time(),
        'workers': 1, 'operation': 'full retraining, no optimizer/RNG continuation',
        'reason': 'reduce memory pressure; controller uses only standard library',
        'runs': [run for run, _, _ in pending]})
    receipts = []
    for run, directory, previous in pending:
        check_source()
        attempt = len(list(directory.glob('execution_*.log'))) + 1
        archive = directory/'failed_attempts'/f'attempt_{attempt-1:02d}'
        archive.mkdir(parents=True, exist_ok=True)
        for name in ('START.json', 'FAILED.json'):
            if (directory/name).exists() and not (archive/name).exists():
                shutil.copy2(directory/name, archive/name)
        if (directory/'checkpoint').exists() and not (archive/'checkpoint').exists():
            shutil.copytree(directory/'checkpoint', archive/'checkpoint')
        assert json.loads((directory/'SPEC.json').read_text()) == run['spec']
        command = previous['command']
        started = time.time()
        with (directory/f'execution_{attempt:02d}.log').open('x') as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        receipt = {'run_id': run['run_id'], 'exit_code': completed.returncode,
            'elapsed_seconds': time.time()-started, 'command': command,
            'status': 'completed' if completed.returncode == 0 and (directory/'RESULT.json').exists() else 'failed',
            'controller': 'post-seal serial operational recovery; scientific source/spec unchanged'}
        write(directory/f'EXECUTION_{attempt:02d}.json', receipt)
        receipts.append(receipt)
        write(STUDY/'PROGRESS_recovery.json', receipts)
        print(json.dumps(receipt), flush=True)
    check_source()
    if any(row['status'] != 'completed' for row in receipts):
        raise SystemExit('Resource failures remain; all attempts retained')


if __name__ == '__main__':
    main()

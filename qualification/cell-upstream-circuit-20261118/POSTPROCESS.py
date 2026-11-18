"""Wait for the real owner exit, then validate and archive immutable originals."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path('/home/qian-qi/work/hepta-e4-matched-upstream-20261118-2e9b/candidate-41d273d')


def main():
    exit_path = ROOT / 'owned-run-1/EXIT.json'
    deadline = time.monotonic() + 1500
    while not exit_path.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError('actual owner exit not yet available; no archive was inferred')
        time.sleep(5)
    owner = json.loads(exit_path.read_text())
    assert owner['wait_returncode'] == 0 and owner['timed_out'] is False
    with (ROOT / 'READOUT_STDOUT.txt').open('xb') as stdout, (ROOT / 'READOUT_STDERR.txt').open('xb') as stderr:
        child = subprocess.Popen(['python3', '-B', str(ROOT / 'READOUT_SOURCE.py')], stdout=stdout, stderr=stderr)
        code = child.wait()
    assert code == 0, 'original readout failed; consult READOUT_STDERR.txt'
    index = json.loads((ROOT / 'INDEX.json').read_text())
    # Readout logs were open while the index was captured. They are operational
    # readout output, not experiment inputs. Exclude only these two mutable logs.
    for name in ('READOUT_STDOUT.txt', 'READOUT_STDERR.txt'):
        if name in index:
            raise ValueError('readout index must exclude its own active output logs')
    archive = ROOT / 'RAW_EVIDENCE.tar.xz'
    names = sorted(index) + ['INDEX.json', 'READOUT.json']
    with tarfile.open(archive, 'w:xz', preset=6) as target:
        for name in names:
            path = ROOT / name
            assert path.is_file() and not path.is_symlink()
            if name in index:
                assert path.stat().st_size == index[name]['bytes']
                assert hashlib.sha256(path.read_bytes()).hexdigest() == index[name]['sha256']
            target.add(path, arcname=name, recursive=False)
    with tarfile.open(archive, 'r:xz') as retained:
        members = retained.getmembers()
        assert len(members) == len(names) and {member.name for member in members} == set(names)
        for member in members:
            assert member.isfile()
            raw = retained.extractfile(member).read()
            assert raw == (ROOT / member.name).read_bytes()
            if member.name in index:
                assert hashlib.sha256(raw).hexdigest() == index[member.name]['sha256']
    receipt = {
        'schema': 'hepta.e4-original-archive.v1', 'source_commit': '41d273d06d0138ab4a747c5dc73bb2ee2a61e9ee',
        'path': 'RAW_EVIDENCE.tar.xz', 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'members': len(names),
        'original_index_entries': len(index), 'all_original_bytes_reverified': True,
        'readout_model_calls': 0, 'readout_verifier_calls': 0,
        'owner_exit_sha256': hashlib.sha256(exit_path.read_bytes()).hexdigest(),
        'readout_sha256': hashlib.sha256((ROOT / 'READOUT.json').read_bytes()).hexdigest(),
    }
    with (ROOT / 'ARCHIVE.json').open('x') as output:
        output.write(json.dumps(receipt, sort_keys=True) + '\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()

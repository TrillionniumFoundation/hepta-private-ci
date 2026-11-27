"""Finish streaming certification and portable replay only after the original cold study releases its lock."""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('root', type=Path)
    cli.add_argument('durable', type=Path)
    args = cli.parse_args()
    root = args.root.resolve()
    durable = args.durable.resolve()
    original = root / 'attention_free'
    audit = durable / 'poststudy'
    audit.mkdir(parents=True, exist_ok=True)
    os.sched_setaffinity(0, {15})
    for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ.update(HEPTA_FLICKR_ROOT=str(root), CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='')
    guard = (audit/'poststudy.lock').open('a')
    fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    deadline = time.monotonic() + 6*3600
    while not (durable/'preserved.json').exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('the original 18-state cold study has not been preserved')
        time.sleep(10)
    preserved = json.loads((durable/'preserved.json').read_bytes())
    assert len(preserved['fits']) == len(preserved['tests']) == 18
    assert digest(original/'summary.json') == preserved['summary']
    assert digest(original/'results/seal.json') == preserved['seal']
    original_lock = (original/'worker.lock').open('a')
    fcntl.flock(original_lock, fcntl.LOCK_EX)
    # check_streaming is the originally published executable, run from its original relative import environment.
    source = original/'src'
    for name in ('check_streaming.py','streaming.py','study.py','run.py'):
        assert digest(source/name) == digest(durable/'src'/name), name
    stream = original/'streaming_selected.json'
    if not stream.exists():
        subprocess.run([sys.executable, 'check_streaming.py', 'selected'], cwd=source, check=True)
    info = json.loads(stream.read_bytes())
    assert info['origin'] == 'selected' and len(info['rows']) == 18
    stream_copy = durable/'streaming_selected.json'
    if stream_copy.exists():
        assert digest(stream_copy) == digest(stream)
    else:
        shutil.copyfile(stream, stream_copy)
    target = audit/'cold_evidence.zip'
    program = Path(__file__).with_name('replay_attention_free.py')
    subprocess.run([sys.executable, str(program), 'export', str(original), str(target)], check=True)
    subprocess.run([sys.executable, str(program), 'verify', str(target), str(audit/'replay.json')], check=True)
    replay = json.loads((audit/'replay.json').read_bytes())
    final = {'protected_states':replay['protected_states'], 'numerical_checks':replay['numerical_checks'],
             'worst_replay_difference':replay['maximum_absolute_difference_from_registered_report'],
             'evidence_archive_sha256':digest(target), 'evidence_archive_bytes':target.stat().st_size,
             'replay_sha256':digest(audit/'replay.json'), 'original_streaming_selected_sha256':digest(stream),
             'original_summary_sha256':preserved['summary'], 'original_terminal_lock_released':True}
    (audit/'completed.json').write_text(json.dumps(final, indent=2, sort_keys=True)+'\n')
    print(json.dumps(final, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()

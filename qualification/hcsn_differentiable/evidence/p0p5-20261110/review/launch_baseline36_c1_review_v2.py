"""One isolated read-only native review; original candidates remain untouched."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import signal
import stat
import subprocess
import time
import traceback
from zipfile import ZipFile

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
PROGRAM = Path('/home/qian-qi/hepta-hcsn-independent-baseline36-c1-program-20261110-c385-v2')
OUTPUT = Path('/home/qian-qi/hepta-hcsn-independent-baseline36-c1-20261110-c385-v2')
LAUNCH = BASE / 'baseline36-c1-review-launch-v2'
ARCHIVE = BASE / 'baseline36-c1-independent-reviewer-program-v2.zip'
EXPECTED = '6ede11014d33e219f6ebc109911ad50a8550bb585388b16b5c604a2d4cb54c51'
PYTHON = '/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    started = time.monotonic()
    LAUNCH.mkdir(exist_ok=False)
    require = lambda ok, reason: None if ok else (_ for _ in ()).throw(ValueError(reason))
    require(sha(ARCHIVE) == EXPECTED and ARCHIVE.stat().st_size == 174435, 'review capsule mismatch')
    require(not OUTPUT.exists() and not PROGRAM.exists(), 'new review directories must not exist')
    PROGRAM.mkdir()
    with ZipFile(ARCHIVE) as zipped:
        require(zipped.testzip() is None, 'program CRC mismatch')
        for member in zipped.infolist():
            path = PurePosixPath(member.filename)
            require(not path.is_absolute() and '..' not in path.parts
                    and not stat.S_ISLNK(member.external_attr >> 16), 'unsafe archive member')
        zipped.extractall(PROGRAM)
    manifest = json.loads((PROGRAM / 'MANIFEST.json').read_bytes())
    for name, item in manifest['files'].items():
        path = PROGRAM / name
        require(path.stat().st_size == item['bytes'] and sha(path) == item['sha256'], 'review program member mismatch')
    os.nice(10)
    argv = [PYTHON, '-B', str(PROGRAM/'run_c1_clock_supplement.py'), '--base', str(BASE), '--output', str(OUTPUT)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1',
               MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', CUDA_VISIBLE_DEVICES='')
    receipt = {'schema': 'native-baseline36-C1-independent-review-launch-v2',
               'idempotency_key': 'hcsn-baseline36-c1-independent-review-c385-v2',
               'launcher_sha256': sha(__file__), 'program_archive_sha256': EXPECTED,
               'program': str(PROGRAM), 'output': str(OUTPUT), 'argv': argv,
               'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'started',
               'nice_adjustment': 10, 'torch_threads': 1, 'timeout_seconds': 1800,
               'address_space_limit_bytes': 8589934592, 'host_load_before': os.getloadavg(),
               'scope': 'Seven C1 chains only; original36 results and all bytes reverified and reused from failed-v1. No HCSN directory read, training replay or optimizer step. May overlap original HCSN jobs. Failed-v1 costs remain additional.',
               'source_copy_and_hash_seconds': time.monotonic() - started,
               'energy_joules': None}
    save(LAUNCH/'launch.json', receipt)
    cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    before = time.monotonic()
    process = None
    try:
        with (LAUNCH/'review.stdout').open('xb') as stdout, (LAUNCH/'review.stderr').open('xb') as stderr:
            def limits():
                resource.setrlimit(resource.RLIMIT_AS, (8589934592, 8589934592))
            process = subprocess.Popen(argv, cwd=PROGRAM, env=env, stdout=stdout, stderr=stderr,
                                       start_new_session=True, preexec_fn=limits)
            receipt['pid'] = process.pid
            process.wait(timeout=1800)
            receipt.update(status='completed' if process.returncode == 0 else 'failed', returncode=process.returncode)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        receipt.update(status='timed_out', returncode=process.returncode)
    except Exception:
        receipt.update(status='launcher_failed', error=traceback.format_exc(), returncode=None)
    cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt.update(whole_review_process_wall_seconds=time.monotonic()-before,
                   waited_review_child_cpu_seconds=cpu1.ru_utime+cpu1.ru_stime-cpu0.ru_utime-cpu0.ru_stime,
                   child_peak_rss_bytes=cpu1.ru_maxrss*1024,
                   program_sources_unchanged=all(sha(PROGRAM/name) == item['sha256'] for name, item in manifest['files'].items()),
                   finished_utc=datetime.now(timezone.utc).isoformat(),
                   complete_launcher_wall_seconds=time.monotonic()-started,
                   host_load_after=os.getloadavg())
    for stream in ('stdout', 'stderr'):
        path = LAUNCH / ('review.' + stream)
        receipt[stream] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    if (OUTPUT / 'SUMMARY.json').exists():
        receipt['review_summary'] = json.loads((OUTPUT/'SUMMARY.json').read_bytes())
        receipt['result_sha256'] = sha(OUTPUT/'RESULT.json')
    if (OUTPUT / 'ARCHIVE.json').exists():
        receipt['review_archive'] = json.loads((OUTPUT/'ARCHIVE.json').read_bytes())
    save(LAUNCH/'receipt.json', receipt)
    print(json.dumps(receipt), flush=True)
    return receipt.get('returncode') or (0 if receipt['status'] == 'completed' else 1)


if __name__ == '__main__':
    raise SystemExit(main())

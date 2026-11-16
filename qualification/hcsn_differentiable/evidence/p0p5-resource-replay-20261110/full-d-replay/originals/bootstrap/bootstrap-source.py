"""Exclusive native deployment, synthetic validation, then one read-only replay."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time
import traceback
from zipfile import ZipFile

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
PROGRAM = Path('/home/qian-qi/hepta-hcsn-best-full-D-replay-program-20261110-c385-v1')
ARCHIVE = Path('/home/qian-qi/hepta-hcsn-best-full-D-replay-source-20261110-c385-v1.zip')
OUTPUT = Path('/home/qian-qi/hepta-hcsn-best-full-D-replay-20261110-c385-v1')
OUT = BASE / 'best-full-D-replay-bootstrap-v1'
LAUNCH = BASE / 'best-full-D-replay-launch-v1'
PYTHON = '/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python'
KEY = 'hcsn-best-full-d-replay-c385-v1'
DIGEST = 'a748888f26409ff6f5fff8db8a9266cf67d0a5f5516dc88b566cd3c296fca206'
MANIFEST = '8cd0fdcf94a5af733173d6fc513b2b379df8bdd9f28604116658fe40a7c19e12'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def verify():
    require(sha(PROGRAM / 'MANIFEST.json') == MANIFEST, 'program manifest differs')
    entries = json.loads((PROGRAM / 'MANIFEST.json').read_bytes())['files']
    for name, item in entries.items():
        p = PROGRAM / name
        require(p.stat().st_size == item['bytes'] and sha(p) == item['sha256'], 'program member differs: ' + name)
    return dict(manifest_sha256=MANIFEST, verified_members=len(entries) + 1)


started = time.monotonic()
usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
OUT.mkdir(exist_ok=False)
source = sys.orig_argv[sys.orig_argv.index('-c') + 1]
(OUT / 'bootstrap-source.py').write_text(source)
report = dict(schema='independent-six-best-D-bootstrap-v1', stable_key=KEY,
              started_utc=datetime.now(timezone.utc).isoformat(), program_sha256=DIGEST,
              bootstrap_source_sha256=hashlib.sha256(source.encode()).hexdigest(),
              actual_checkpoint_replay_started=False, scientific_admission='HOLD',
              original_training_adequacy=False, confirmation_E_access=False,
              concurrency='May overlap one independent numerical-audit worker; no idle-host or speed-comparison claim.')
save(OUT / 'launch.json', report)
env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
           CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1')
try:
    require(not PROGRAM.exists() and not OUTPUT.exists() and not LAUNCH.exists(), 'exclusive replay paths exist')
    os.nice(10)
    require(ARCHIVE.stat().st_size == 34757 and sha(ARCHIVE) == DIGEST, 'source archive identity differs')
    PROGRAM.mkdir(exist_ok=False)
    with ZipFile(ARCHIVE) as zipped:
        require(zipped.testzip() is None and len(zipped.namelist()) == len(set(zipped.namelist())) == 13,
                'invalid program ZIP')
        for name in zipped.namelist():
            p = Path(name)
            require(not p.is_absolute() and '..' not in p.parts and not name.endswith('/'), 'unsafe member')
            target = PROGRAM / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(zipped.read(name))
    report['program_before'] = verify()
    point = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    argv = [PYTHON, '-B', '-m', 'unittest', 'discover', '-s', str(PROGRAM), '-p', 'test_*.py', '-v']
    timed_out = False
    with (OUT / 'tests.stdout').open('xb') as stdout, (OUT / 'tests.stderr').open('xb') as stderr:
        process = subprocess.Popen(argv, cwd=BASE, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    text = (OUT / 'tests.stderr').read_text()
    match = re.search(r'Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s', text)
    validation = dict(argv=argv, returncode=process.returncode, timed_out=timed_out,
                      whole_child_wall_seconds=time.monotonic() - point,
                      waited_child_CPU_seconds=usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime,
                      child_peak_rss_bytes=usage.ru_maxrss * 1024, observed_tests=int(match.group(1)) if match else None,
                      unittest_seconds=float(match.group(2)) if match else None,
                      actual_trained_checkpoint_read=False, optimizer_steps=0, backward_calls=0,
                      stdout_sha256=sha(OUT / 'tests.stdout'), stderr_sha256=sha(OUT / 'tests.stderr'),
                      program_after=verify())
    validation['passed'] = process.returncode == 0 and not timed_out and bool(match and int(match.group(1)) == 16 and '\nOK\n' in text)
    save(OUT / 'NATIVE-VALIDATION.json', validation)
    report['native_validation'] = validation
    print(json.dumps(dict(stage='native_validation', **validation)), flush=True)
    require(validation['passed'], 'native synthetic validation failed; real checkpoints not read')
    argv = [PYTHON, '-B', str(PROGRAM / 'launch.py'), '--output', str(OUTPUT), '--launch-directory', str(LAUNCH)]
    report.update(actual_checkpoint_replay_started=True, replay_argv=argv,
                  replay_started_utc=datetime.now(timezone.utc).isoformat())
    save(OUT / 'replay-start.json', report)
    print(json.dumps(dict(stage='replay_start', stable_key=KEY, argv=argv, started_utc=report['replay_started_utc'])), flush=True)
    process = subprocess.run(argv, cwd=BASE, env=env, check=False)
    report.update(returncode=process.returncode, status='completed' if process.returncode == 0 else 'failed_or_capped',
                  program_after=verify())
    if Path(str(OUTPUT) + '.zip').is_file():
        p = Path(str(OUTPUT) + '.zip')
        report['replay_archive'] = dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p))
except Exception:
    report.update(status='bootstrap_failed', error=traceback.format_exc(), returncode=None)
finally:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                  bootstrap_script_wall_seconds=time.monotonic() - started,
                  own_process_CPU_seconds=time.process_time(),
                  waited_children_CPU_seconds=usage.ru_utime + usage.ru_stime - usage0.ru_utime - usage0.ru_stime,
                  own_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                  child_peak_rss_bytes=usage.ru_maxrss * 1024, energy_joules=None,
                  cost_scope='Bootstrap script interval after stdlib import, including extraction, native synthetic validation, controller/fit group, serialization and archive SHA. Nested values are not additional; source upload transport excluded.')
    save(OUT / 'receipt.json', report)
    print(json.dumps(report), flush=True)
raise SystemExit(report['returncode'] if report.get('returncode') is not None else 1)

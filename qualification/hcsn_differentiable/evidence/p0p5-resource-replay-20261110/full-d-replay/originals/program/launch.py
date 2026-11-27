"""Hard one-hour group deadline; no child can outlive this replay launch."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

from audit_io import require, save, sha, verify_program


def main(output, launch_directory):
    program, out = Path(__file__).resolve().parent, Path(launch_directory)
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    row = dict(schema='independent-six-HCSN-best-D-hard-launch-v1', process_started=False,
               started_utc=datetime.now(timezone.utc).isoformat(), hard_wall_seconds=3600,
               scientific_admission='HOLD', training_steps=0, confirmation_E_access=False)
    process = None
    try:
        row['program_manifest_sha256_before'] = verify_program(program)
        plan = json.loads((program / 'PLAN.json').read_bytes())
        require(plan['resources']['whole_controller_wall_seconds'] == 3600 and not Path(output).exists(), 'invalid cap/output')
        argv = [sys.executable, '-B', str(program / 'run_controller.py'), '--output', str(output)]
        env = dict(os.environ, HCSN_REPLAY_CONTROLLER_STARTED=str(started), OMP_NUM_THREADS='1',
                   MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1')
        save(out / 'launch.json', dict(row, argv=argv))
        with (out / 'stdout').open('xb') as stdout, (out / 'stderr').open('xb') as stderr:
            process = subprocess.Popen(argv, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            row.update(process_started=True, pid=process.pid)
            try:
                process.wait(timeout=max(.001, 3600 - (time.monotonic() - started)))
                row.update(status='completed' if process.returncode == 0 else 'failed', returncode=process.returncode)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                row.update(status='whole_budget_exhausted', returncode=process.returncode)
        row['program_manifest_sha256_after'] = verify_program(program)
    except Exception:
        row.update(status='launch_or_monitor_failed', error=traceback.format_exc())
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(whole_controller_wall_seconds=time.monotonic() - started,
                   own_CPU_seconds=time.process_time(),
                   waited_controller_and_descendant_CPU_seconds=usage.ru_utime + usage.ru_stime - usage0.ru_utime - usage0.ru_stime,
                   child_peak_rss_bytes=usage.ru_maxrss * 1024, finished_utc=datetime.now(timezone.utc).isoformat(),
                   scope='Complete controller process group including fits and final serialization/archive; nested timers not additional.',
                   energy_joules=None)
        for name in ('stdout', 'stderr'):
            p = out / name
            row[name] = dict(bytes=p.stat().st_size, sha256=sha(p)) if p.exists() else {'missing': True}
        save(out / 'receipt.json', row)
        print(json.dumps(row), flush=True)
    return 0 if row['status'] == 'completed' else 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--launch-directory', required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.output, args.launch_directory))

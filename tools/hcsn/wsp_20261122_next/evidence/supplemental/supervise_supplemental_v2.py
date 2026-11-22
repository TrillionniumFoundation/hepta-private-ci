"""One create-only, bounded supplemental retained-evidence verification."""
from pathlib import Path
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time


def pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def main():
    spec_path = Path(sys.argv[1]).resolve()
    attempt = Path(sys.argv[2]).resolve()
    spec = json.loads(spec_path.read_bytes())
    original_spec = pin(spec_path)
    for entry in (spec['verifier_pin'], spec['supervisor_pin']):
        if pin(entry['path']) != entry:
            raise ValueError('frozen supplemental source changed')
    attempt.mkdir(parents=True, exist_ok=False)
    command = [spec['python'], '-B', spec['verifier_pin']['path'], '--spec', str(spec_path),
               '--output', str(attempt / 'output')]
    environment = dict(os.environ, PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1',
                       OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    def restrict():
        os.setsid()
        os.sched_setaffinity(0, {7})
        resource.setrlimit(resource.RLIMIT_CPU, (8, 9))
        resource.setrlimit(resource.RLIMIT_AS, (2147483648,) * 2)
    started, cpu = time.monotonic(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (attempt / 'stdout.txt').open('xb') as out, (attempt / 'stderr.txt').open('xb') as err:
        process = subprocess.Popen(command, env=environment, stdout=out, stderr=err, preexec_fn=restrict)
        timed_out = False
        try:
            process.wait(timeout=29)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = attempt / 'output' / 'RESULTS.json'
    record = dict(schema='hepta-value-supplemental-process-v1',
                  status='COMPLETED' if process.returncode == 0 and result.is_file() else 'FAILED',
                  returncode=process.returncode, wall_timeout=timed_out, command=command,
                  spec_pin=original_spec, spec_unchanged=pin(spec_path) == original_spec,
                  verifier_pin=pin(spec['verifier_pin']['path']), supervisor_pin=pin(__file__),
                  result_pin=pin(result) if result.is_file() else None,
                  child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                  supervisor_CPU_seconds=time.process_time()-cpu,
                  wall_seconds=time.monotonic()-started, peak_child_RSS_KiB=after.ru_maxrss,
                  limits=spec['limits'], quality_work=spec['quality_work'])
    with (attempt / 'PROCESS.json').open('x') as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps(record), flush=True)
    sys.exit(0 if record['status'] == 'COMPLETED' else 1)


if __name__ == '__main__':
    main()

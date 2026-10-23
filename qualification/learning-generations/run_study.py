#!/usr/bin/env python3
"""Run one exact native study and retain whole-process costs, including failures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

SELECTOR = ('cognitive_ranker::tests::three_generation_learning::'
            'three_actual_fits_installations_future_instances_no_update_and_revocation')


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    binary, output = args.binary.resolve(strict=True), args.output.absolute()
    if output.exists() or output.is_symlink() or not binary.is_file():
        raise ValueError('fresh output and actual native test binary required')
    source = Path(__file__).resolve().parent / 'custodian.py'
    frozen_custodian = output.with_suffix('.custodian.py')
    source_bytes = source.read_bytes()
    if len(source_bytes) > 1024 * 1024:
        raise ValueError('bounded custodian source')
    with frozen_custodian.open('xb') as handle:
        handle.write(source_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    environment = dict(os.environ, HEPTA_LEARNING_STUDY_DIRECTORY=str(output),
        HEPTA_LEARNING_CUSTODIAN=str(frozen_custodian), HEPTA_LEARNING_STUDY_PYTHON=sys.executable)
    command = [str(binary), '--exact', SELECTOR, '--ignored', '--nocapture', '--test-threads=1']
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall, cpu = time.monotonic_ns(), time.process_time_ns()
    binary_hash = sha(binary)
    log = output.with_suffix('.native.log')
    with log.open('xb') as handle:
        child = subprocess.Popen(command, env=environment, stdout=handle, stderr=subprocess.STDOUT)
        # This host exposes a /proc PID namespace different from getpid().
        # A numeric child pid can refer to another process there. Use waited
        # kernel rusage instead of presenting an unauthenticated RSS sample.
        while child.poll() is None:
            if time.monotonic_ns() - wall > 600 * 10**9:
                child.terminate()
                try:
                    child.wait(10)
                except subprocess.TimeoutExpired:
                    child.kill()
                break
            time.sleep(0.05)
        code = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    files = sorted(path for path in output.rglob('*') if path.is_file()) if output.exists() else []
    receipt = dict(schema='hepta.local-learning-whole-process-cost.v1', command=command,
        binary_sha256=binary_hash, binary_unchanged=sha(binary) == binary_hash, native_exit_code=code,
        custodian_source=str(frozen_custodian), custodian_sha256=sha(frozen_custodian),
        wall_ns=time.monotonic_ns()-wall, observer_cpu_ns=time.process_time_ns()-cpu,
        child_user_seconds=after.ru_utime-before.ru_utime, child_system_seconds=after.ru_stime-before.ru_stime,
        waited_child_peak_rss_bytes=after.ru_maxrss*1024, sampled_native_peak_rss_bytes=None,
        rss_sampling_status="unavailable: numeric child pid is not authenticated in the mounted proc namespace",
        memory_scope="maximum waited process high-water; simultaneous whole-tree RSS not measured",
        retained_files=len(files), retained_bytes=sum(path.stat().st_size for path in files),
        log_sha256=sha(log), compilation_included=False, energy_cost=None, monetary_cost=None,
        scope='entire native process including role child CPU via waited descendants; role costs overlap and must not be added again')
    receipt_path = output.with_suffix('.execution.json')
    with receipt_path.open('x') as handle:
        json.dump(receipt, handle, indent=2)
        handle.write('\n')
    with log.open('rb') as handle:
        native_output = handle.read(512 * 1024 + 1)
    if len(native_output) > 512 * 1024:
        raise SystemExit('native output exceeds bounded qualification log; failure retained')
    # Expose the actual libtest summary to the existing hepta_ci_exec observer.
    # The full retained bytes and digest remain the native evidence, not a new
    # acceptance counter manufactured from our report fields.
    print(native_output.decode('utf-8', errors='replace'), end='', flush=True)
    print(json.dumps(receipt), flush=True)
    if code or not receipt['binary_unchanged'] or not (output/'summary.json').is_file():
        raise SystemExit('native study failed; exact failure and partial artifacts retained')
    subprocess.run([sys.executable, str(source.with_name('verify_study.py')), str(output)], check=True)


if __name__ == '__main__':
    main()

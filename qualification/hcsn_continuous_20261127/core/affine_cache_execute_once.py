"""Own one bounded controls process and retain failures without automatic retry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--protocol-sha256', required=True)
    args = parser.parse_args()
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); before = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {'schema': 'hepta.affine-cache-controlled-launch.v1',
               'status': 'STARTED', 'counts_complete': False, 'automatic_retry': False,
               'failure': None, 'protocol_sha256': args.protocol_sha256,
               'model_rollouts_authorized': 0, 'optimizer_steps_authorized': 0}
    (out/'LAUNCH_ONCE.json').write_text(json.dumps(receipt, sort_keys=True)+'\n')
    process = None; code = None
    try:
        here = Path(__file__).resolve().parent
        raw = (here/'AFFINE_CACHE_PROTOCOL.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != args.protocol_sha256:
            raise RuntimeError('PROTOCOL_IDENTITY_MISMATCH')
        protocol = json.loads(raw)
        if sys.platform != 'linux':
            raise RuntimeError('QUALIFICATION_REQUIRES_LINUX')

        def limits():
            os.umask(0o077)
            resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_FSIZE, (8*1024*1024, 8*1024*1024))

        environment = dict(os.environ)
        environment.update({'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                            'MKL_NUM_THREADS': '1', 'CUDA_VISIBLE_DEVICES': '',
                            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0'})
        with (out/'stdout.txt').open('xb') as stdout, (out/'stderr.txt').open('xb') as stderr:
            process = subprocess.Popen([sys.executable, '-B', str(here/'affine_cache_controls.py'),
                                        '--output', str(out/'controls')],
                                       env=environment, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr,
                                       start_new_session=True, preexec_fn=limits)
            receipt['owned_pid'] = process.pid
            try:
                code = process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                receipt['deadline_expired'] = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    code = process.wait()
        result_path = out/'controls/RESULT.json'
        result_raw = result_path.read_bytes(); result = json.loads(result_raw)
        receipt['result_sha256'] = hashlib.sha256(result_raw).hexdigest()
        receipt['result_status'] = result.get('status')
        receipt['returned_counts'] = result.get('counts_returned')
        valid = (code == 0 and result.get('schema') == 'hepta.affine-cache-copy-load-controls.v1'
                 and result.get('protocol_sha256') == args.protocol_sha256
                 and result.get('status') == 'COMPLETED_ALL_SIX_SYNTHETIC_CONTROLS'
                 and result.get('counts_complete') is True and result.get('failure') is None
                 and result.get('counts_started') == protocol['call_caps'] == result.get('counts_returned')
                 and result.get('price_output_values_returned') == protocol['price_output_value_cap']
                 and len(result.get('cases', [])) == 6
                 and all(row.get('status') == 'PASS' for row in result['cases']))
        if not valid:
            raise RuntimeError('CONTROLS_NOT_COMPLETED_OR_RECEIPT_INVALID')
        receipt['status'] = 'COMPLETED'; receipt['counts_complete'] = True
    except BaseException as error:
        receipt['status'] = 'FAILED_OR_UNKNOWN_PARTIAL_EXECUTION'
        receipt['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            code = process.wait()
        receipt['exit_code'] = code
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt['wall_seconds'] = time.monotonic()-started
        receipt['child_cpu_seconds'] = after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime
        receipt['child_max_rss_kib'] = after.ru_maxrss
        partial = out/'controls/PROGRESS.json'
        if not receipt['counts_complete'] and partial.exists():
            try:
                body = partial.read_bytes(); value = json.loads(body)
                receipt['partial_count_witness'] = {'sha256': hashlib.sha256(body).hexdigest(),
                    'started_lower_bound': value.get('counts_started'),
                    'returned_lower_bound': value.get('counts_returned'), 'counts_complete': False}
            except BaseException as error:
                receipt['partial_parse_error'] = type(error).__name__+': '+str(error)
        (out/'EXTERNAL_COST.json').write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False)+'\n')
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt['counts_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

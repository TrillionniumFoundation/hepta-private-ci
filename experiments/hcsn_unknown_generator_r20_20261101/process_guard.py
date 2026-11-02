"""POSIX accounting for normal and caught launch/IO failures; not arbitrary SIGKILL recovery."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def persist(path, value):
    """Emit a custody copy before an attempted exclusive disk write."""
    print(json.dumps(dict(record_path=str(path), record=value), sort_keys=True, allow_nan=False), flush=True)
    try:
        with Path(path).open("x") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        return True
    except OSError as error:
        print(json.dumps(dict(record_write_failed=str(path), error=str(error))), flush=True)
        return False


def wait_process(process):
    while True:
        try:
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            return usage
        except InterruptedError:
            continue


def workers(module, names, output):
    processes, receipts, errors = [], {}, []
    try:
        output.mkdir(exist_ok=False)
        for name in names:
            with (output / (name + "_STDOUT.txt")).open("x") as log:
                process = subprocess.Popen([sys.executable, "-m", module, "--worker", name], stdout=log, stderr=subprocess.STDOUT)
                processes.append((name, process))
                print(json.dumps(dict(worker_launched=name, pid=process.pid)), flush=True)
    except Exception as error:
        errors.append("launch: " + repr(error))
    finally:
        for name, process in processes:
            try:
                usage = wait_process(process)
                receipts[name] = dict(exit_code=process.returncode, child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                                      max_rss_kib=usage.ru_maxrss)
            except Exception as error:
                errors.append("wait " + name + ": " + repr(error))
    if not persist(output / "WORKER_RECEIPTS.json", receipts):
        errors.append("Worker receipt disk write failed")
    if errors:
        persist(output / "LAUNCH_OR_WAIT_FAILURE.json", dict(errors=errors, launched_workers=list(receipts),
            primary_data_qualified=False, scope="Known launched workers reaped on ordinary Python exceptions; no asynchronous-kill guarantee"))
    return receipts, errors


def outer(module, receipt_path, worker_path):
    start = time.perf_counter()
    try:
        process = subprocess.Popen([sys.executable, "-m", module, "--child"])
        usage = wait_process(process)
    except Exception as error:
        persist(receipt_path, dict(exit_code=1, child_cpu_seconds=None, worker_cpu_sum=None,
            coordinator_start_or_wait_error=repr(error), wall_seconds=time.perf_counter() - start,
            data_qualified=False, scope="No successful outer wait4 receipt; cost not assumed zero"))
        return 1
    total, worker_cpu, read_error = usage.ru_utime + usage.ru_stime, None, None
    try:
        records = json.loads(Path(worker_path).read_text())
        worker_cpu = sum(value["child_cpu_seconds"] for value in records.values())
    except (OSError, ValueError, KeyError, TypeError) as error:
        read_error = repr(error)
    sanity = None if worker_cpu is None else total + 1e-6 >= worker_cpu
    receipt = dict(exit_code=process.returncode, child_cpu_seconds=total, parallel_worker_cpu_sum=worker_cpu,
        worker_receipts_read_error=read_error, wall_seconds=time.perf_counter() - start,
        max_process_rss_kib=usage.ru_maxrss, concurrent_family_peak_rss_kib=None,
        accounting_sanity_total_at_least_workers=sanity,
        scope="Outerwait4 coordinator and its waited worker descendants; workers included once. Handles ordinary launch/IO exceptions; no arbitrary SIGKILL/orphan-cost closure. Development and outer launcher self cost separate.")
    stored = persist(receipt_path, receipt)
    return process.returncode if stored and sanity is not False and read_error is None else 1

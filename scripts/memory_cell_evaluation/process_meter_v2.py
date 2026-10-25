"""Linux process supervision with per-child wait4 usage and bounded raw evidence."""

import datetime
import os
from pathlib import Path
import resource
import signal
import subprocess
import time

from bounded_process import digest, save


def run(argv, cwd, output, limits, environment):
    output = Path(output)
    output.mkdir()
    record = {
        "argv": argv,
        "cwd": str(cwd),
        "environment": environment,
        "limits": limits,
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "returncode": None,
        "timeout": False,
        "error": None,
        "usage": None,
        "cpu_affinity": [min(os.sched_getaffinity(0))],
    }
    save(output / "request.json", record)
    started, child = time.monotonic(), None

    def restrict():
        os.sched_setaffinity(0, record["cpu_affinity"])
        for kind, cap in (
            (resource.RLIMIT_CPU, limits["cpu_seconds"]),
            (resource.RLIMIT_AS, limits["address_bytes"]),
            (resource.RLIMIT_FSIZE, limits["output_file_bytes"]),
            (resource.RLIMIT_CORE, 0),
        ):
            resource.setrlimit(kind, (cap, cap))

    def reap(block):
        pid, status, usage = os.wait4(child.pid, 0 if block else os.WNOHANG)
        if pid:
            child.returncode = os.waitstatus_to_exitcode(status)
            record["returncode"] = child.returncode
            record["usage"] = {
                "user_cpu_seconds": usage.ru_utime,
                "system_cpu_seconds": usage.ru_stime,
                "maxrss_kib": usage.ru_maxrss,
                "minor_faults": usage.ru_minflt,
                "major_faults": usage.ru_majflt,
                "block_inputs": usage.ru_inblock,
                "block_outputs": usage.ru_oublock,
                "basis": "wait4 direct child, including its waited descendants",
            }
        return bool(pid)

    try:
        with (
            (output / "stdout").open("xb") as out,
            (output / "stderr").open("xb") as err,
        ):
            child = subprocess.Popen(
                argv,
                cwd=cwd,
                env=environment,
                stdout=out,
                stderr=err,
                start_new_session=True,
                preexec_fn=restrict,
            )
            record["pid"] = child.pid
            while not reap(False):
                if time.monotonic() - started >= limits["wall_seconds"]:
                    record["timeout"] = True
                    break
                time.sleep(0.01)
    except Exception as error:
        record["error"] = repr(error)
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as error:
                record["cleanup_error"] = repr(error)
            if child.returncode is None:
                try:
                    reap(True)
                except Exception as error:
                    record["reap_error"] = repr(error)
        record["wall_seconds"] = time.monotonic() - started
        for name in ("stdout", "stderr"):
            try:
                record[name] = digest(output / name)
            except OSError as error:
                record[name] = {"error": repr(error)}
        save(output / "process.json", record)
    return record

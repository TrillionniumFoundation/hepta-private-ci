"""Bounded Linux jobs with independently measured wall/CPU and retained output.

The controller reserves before spawning. It kills the process group at the wall
deadline. Direct child parent-death binding survives exec; this is not a generic
adversarial process-tree sandbox or a physical-host budget controller.
"""

import hashlib
import json
import os
from pathlib import Path
import signal
import resource
import subprocess
import sys
import time

from budget_ledger import BudgetExceeded, canonical, digest, quantities


def retain(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_job(
    ledger,
    event_id,
    phase,
    *,
    argv,
    directory,
    timeout_ns,
    upper_bound,
    work_counters=None,
    output_limit=1024 * 1024,
    task_cwd=None,
):
    """Execute a source-pinned host task, charging declared work and actual clocks.

    work_counters is for deterministic no-model operations. Model jobs must be
    settled by their measured model-work owner through BudgetLedger directly;
    this helper cannot fabricate optimizer/token counts for opaque commands.
    """
    if sys.platform != "linux":
        raise ValueError("Linux process-group/parent-death measurement required")
    if (
        type(timeout_ns) is not int
        or timeout_ns <= 0
        or type(output_limit) is not int
        or not 1024 <= output_limit <= 16 * 1024 * 1024
    ):
        raise ValueError("positive bounded job limits required")
    if (
        not argv
        or not Path(argv[0]).is_absolute()
        or any(type(x) is not str for x in argv)
    ):
        raise ValueError("explicit executable and argument vector required; no shell")
    counters = quantities(work_counters or {})
    if any(
        counters[k]
        for k in (
            "decoder_updates",
            "router_updates",
            "gradient_probes",
            "train_tokens",
            "decoder_queries",
            "feature_forwards",
            "input_tokens",
            "output_tokens",
        )
    ):
        raise ValueError("opaque model work requires its own measured-work settlement")
    upper = quantities(upper_bound)
    if upper["wall_ns"] < timeout_ns + 1_000_000_000 or upper["cpu_ns"] <= 0:
        raise ValueError("reserve wall cleanup margin and positive CPU before spawn")
    request = dict(
        argv=argv,
        timeout_ns=timeout_ns,
        work_counters=counters,
        output_limit=output_limit,
        upper_bound=upper,
        task_cwd=str(Path(task_cwd).resolve()) if task_cwd else None,
    )
    reservation = ledger.reserve(event_id, phase, upper, request_sha256=digest(request))
    directory = Path(directory)
    if reservation["state"] != "reserved":
        terminal = directory / "receipt.json"
        if not terminal.exists():
            raise ValueError("settled job lost its original receipt")
        receipt = json.loads(terminal.read_text())
        if digest(receipt) != reservation.get("receipt_sha256"):
            raise ValueError("settled job receipt changed")
        return receipt
    if directory.exists():
        ledger.abandon(
            event_id,
            reason="existing job directory without an admitted terminal receipt",
        )
        raise BudgetExceeded("uncertain prior effects; refusing automatic replay")
    directory.mkdir(parents=True)
    retain(directory / "request.json", request)
    child_request = dict(
        parent_pid=os.getpid(),
        argv=argv,
        cpu_ns=upper["cpu_ns"],
        file_size_limit=output_limit,
    )
    retain(directory / "child-request.json", child_request)
    started, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
    timed_out, process = False, None
    try:
        with (
            (directory / "stdout.log").open("xb") as stdout,
            (directory / "stderr.log").open("xb") as stderr,
        ):
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("budget_child.py")),
                    str((directory / "child-request.json").resolve()),
                ],
                cwd=task_cwd or directory,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                if time.perf_counter_ns() - started >= timeout_ns:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    _, status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                time.sleep(0.01)
        elapsed = time.perf_counter_ns() - started
        child_cpu_ns = math_ns(usage.ru_utime + usage.ru_stime)
        parent_cpu_ns = time.process_time_ns() - parent_cpu
        actual = dict(counters, wall_ns=elapsed, cpu_ns=child_cpu_ns + parent_cpu_ns)
        logs = {}
        for name in ("stdout.log", "stderr.log"):
            data = (directory / name).read_bytes()
            logs[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        actual["write_bytes"] += sum(x["bytes"] for x in logs.values())
        receipt = dict(
            event_id=event_id,
            request_sha256=digest(request),
            pid=process.pid,
            returncode=process.returncode,
            timed_out=timed_out,
            actual=actual,
            child_peak_rss_bytes=usage.ru_maxrss * 1024,
            sum_of_process_rss_peaks_upper_bound=(
                usage.ru_maxrss + resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            )
            * 1024,
            child_cpu_ns=child_cpu_ns,
            parent_cpu_ns=parent_cpu_ns,
            observed_block_input_bytes=usage.ru_inblock * 512,
            observed_block_output_bytes=usage.ru_oublock * 512,
            logs=logs,
            process_reaped=True,
            no_model_work_metered=True,
            direct_child_parent_death_supported=True,
            unsupported_platforms=["Windows", "macOS"],
            generic_adversarial_process_containment=False,
        )
        retain(directory / "receipt.json", receipt)
        ledger.settle(event_id, actual, receipt_sha256=digest(receipt))
        return receipt
    except BaseException:
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                os.waitpid(process.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        state = next(
            row for row in ledger.snapshot()["events"] if row["event"] == event_id
        )
        if state["state"] == "reserved":
            ledger.abandon(
                event_id, reason="controller exception before measured settlement"
            )
        raise


def math_ns(seconds):
    return int(round(seconds * 1_000_000_000))

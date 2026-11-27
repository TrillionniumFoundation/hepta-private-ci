"""Reap every worker termination and persist an atomic partial terminal record."""

import json
import os
from pathlib import Path
import resource
import signal
import time

from .lifecycle import atomic_json, read_progress


def _sample(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().split()
    ticks = os.sysconf("SC_CLK_TCK")
    memory = Path(f"/proc/{pid}/status").read_text().splitlines()
    return ((int(fields[13]) + int(fields[14])) * 10**9 // ticks,
            max(int(line.split()[1]) * 1024 for line in memory
                if line.startswith(("VmRSS:", "VmHWM:"))))


def _kill(process, signum):
    try:
        # launch starts a new session. Direct test callers must do the same.
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def supervise(output, process, *, cpu_limit_ns=1800_000_000_000,
              rss_limit_bytes=2**31, byte_limit=2**31, poll_seconds=.01,
              grace_seconds=.05, request_stop=None, parent_clock=time.process_time_ns):
    output = Path(output)
    reason, grace_deadline, usage, status, failure = None, None, None, None, None
    reaped = False
    signals_sent = []
    received_signal = []
    previous = {}
    if request_stop is None:
        def capture(signum, frame):
            received_signal.append(signum)
        previous = {s: signal.signal(s, capture) for s in (signal.SIGTERM, signal.SIGINT)}
        request_stop = lambda: ("launcher received " + signal.Signals(received_signal[0]).name
                                if received_signal else None)
    try:
        while True:
            child, status, usage = os.wait4(process.pid, os.WNOHANG)
            if child:
                reaped = True
                break
            try:
                worker_cpu, peak = _sample(process.pid)
                resource_stop = worker_cpu + parent_clock() > cpu_limit_ns or peak > rss_limit_bytes
            except (FileNotFoundError, ProcessLookupError, ValueError):
                resource_stop = False
            if resource_stop:
                reason = reason or "supervisor actual CPU/RSS cap exceeded"
                if signal.SIGKILL not in signals_sent:
                    _kill(process, signal.SIGKILL)
                    signals_sent.append(signal.SIGKILL)
                grace_deadline = None
            elif reason is None:
                reason = request_stop()
                if reason:
                    _kill(process, signal.SIGTERM)
                    signals_sent.append(signal.SIGTERM)
                    grace_deadline = time.monotonic() + grace_seconds
            elif grace_deadline is not None and time.monotonic() >= grace_deadline:
                _kill(process, signal.SIGKILL)
                signals_sent.append(signal.SIGKILL)
                grace_deadline = None
            time.sleep(poll_seconds)
    except BaseException as error:
        failure = type(error).__name__ + ": " + str(error)
        reason = reason or "supervisor exception: " + failure
        _kill(process, signal.SIGKILL)
        signals_sent.append(signal.SIGKILL)
    finally:
        if not reaped:
            _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    code = process.returncode
    child_cpu = round((usage.ru_utime + usage.ru_stime) * 1e9)
    total = parent_clock() + child_cpu
    rss_bound = (usage.ru_maxrss + resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    if total > cpu_limit_ns or rss_bound > rss_limit_bytes:
        reason = reason or "complete supervisor+worker CPU/RSS cap exceeded"
    if code < 0:
        reason = reason or "worker terminated by " + signal.Signals(-code).name
    worker_result = None
    try:
        worker_result = json.loads((output / "result.json").read_text())
        if not isinstance(worker_result, dict):
            raise ValueError("worker result is not an object")
        atomic_json(output / "worker-result.json", worker_result)
    except (OSError, ValueError) as error:
        reason = reason or "worker terminal receipt missing: " + type(error).__name__
    if worker_result is not None and worker_result.get("exit_code") != code:
        reason = reason or "worker exit status contradicts its terminal receipt"
    progress = read_progress(output)
    incomplete = bool(set(progress["started_stages"]) - set(progress["completed_stages"]))
    if incomplete:
        reason = reason or "worker left an incomplete stage: " + str((worker_result or {}).get("reason", "no worker receipt"))
    partial = reason is not None or worker_result is None or incomplete
    terminal = dict(worker_result or {})
    terminal.update(progress)
    terminal.update(schema="hepta.fashion-D-supervised-terminal.v2",
                    status="interrupted_partial" if partial else terminal.get("status", "failed"),
                    exit_code=1 if partial else (code if code > 0 else 0),
                    partial=partial, termination_reason=reason,
                    worker_returncode=code, signals_sent=[signal.Signals(s).name for s in signals_sent],
                    accounting_complete=not partial,
                    process_plus_descendant_CPU_ns_before_receipt=total,
                    parent_CPU_ns=parent_clock(), worker_CPU_ns=child_cpu,
                    worker_peak_RSS_bytes=usage.ru_maxrss * 1024,
                    parent_plus_worker_peak_RSS_upper_bound_bytes=rss_bound,
                    grace_seconds=grace_seconds if signal.SIGTERM in signals_sent else 0,
                    boundary="Progress is last atomically committed checkpoint; interrupted work may have advanced further. All termination/receipt CPU stays in method bill. Sampling does not guarantee zero overshoot.")
    atomic_json(output / "result.json", terminal)
    atomic_json(output / "supervisor.json", terminal)
    retained = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    if parent_clock() + child_cpu > cpu_limit_ns or retained > byte_limit or rss_bound > rss_limit_bytes:
        terminal.update(exit_code=1, partial=True, accounting_complete=False,
                        status="interrupted_partial", termination_reason=reason or "complete receipt tail cap exceeded",
                        retained_bytes_after_first_receipt=retained)
        atomic_json(output / "result.json", terminal)
        atomic_json(output / "supervisor.json", terminal)
    return terminal

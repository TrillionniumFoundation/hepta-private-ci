"""Waited local subprocess receipts for the bounded rule-repair experiment."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

try:
    import resource
except ImportError:
    resource = None

ACTIONS = ("STOP", "CHECK", "REPAIR")
TARIFF = {"STOP": 0.005, "CHECK": 0.015, "REPAIR": 0.08, "ORACLE": 0.02}
HORIZON = 5


def child_usage():
    if resource is None:
        return None
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return value.ru_utime + value.ru_stime


def invoke(mode, path, scale, offset, timeout=2.0):
    start, cpu, children = time.perf_counter(), time.process_time(), child_usage()
    command = [
        sys.executable,
        "-I",
        str(Path(__file__).with_name("tool_worker.py")),
        mode,
        str(path),
        str(scale),
        str(offset),
    ]
    status = "completed"
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            status = "timeout"
    except OSError as error:
        stdout, stderr, status = "", repr(error), "failed"
    after = child_usage()
    result = None
    try:
        if status == "completed" and process.returncode == 0:
            result = json.loads(stdout)
        elif status == "completed":
            status = "failed"
    except json.JSONDecodeError:
        status = "failed"
    valid = isinstance(result, dict)
    if mode in ("CHECK", "REPAIR"):
        allowed = ("0", "1", "2") if mode == "CHECK" else ("attempted",)
        valid = valid and set(result) == {"outcome"} and result["outcome"] in allowed
    elif mode == "ORACLE":
        valid = valid and set(result) == {"quality", "failed_inputs"}
        if valid:
            failed = result["failed_inputs"]
            valid = (
                type(result["quality"]) is int
                and result["quality"] in (0, 1)
                and isinstance(failed, list)
                and all(type(x) is int and -11 <= x < 14 for x in failed)
                and failed == sorted(set(failed))
                and result["quality"] == int(not failed)
            )
    else:
        valid = False
    if status == "completed" and not valid:
        status = "failed"
    return {
        "action": mode,
        "status": status,
        "command": command,
        "returncode": None if process is None else process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "result": result,
        "output_schema_valid": valid,
        "wall_s": time.perf_counter() - start,
        "parent_cpu_s": time.process_time() - cpu,
        "child_cpu_s": None if after is None else after - children,
        "tariff": TARIFF[mode],
        "metering": "exclusive_action",
    }


def initial_source(task):
    scale, offset, bugs = task["scale"], task["offset"], task["bugs"]
    left = "(scale + 1)" if "scale" in bugs else "scale"
    right = "(offset + 1)" if "offset" in bugs else "offset"
    return f"def solve(x):\n    scale = {scale}\n    offset = {offset}\n    return x * {left} + {right}\n"


def run_episode(selector, task, cancel_after=None):
    """The selector receives only the immutable public action/outcome history.

    The evaluator's task, source bytes and oracle never enter that callback.
    Expiry, cancellation and failed actions retain costs and cannot deliver.
    """
    wall, cpu, children = time.perf_counter(), time.process_time(), child_usage()
    events, history, status, delivered = [], (), "expired", False
    source = initial_source(task)
    controller_wall, controller_cpu = 0.0, 0.0
    with tempfile.TemporaryDirectory(prefix="hepta-tool-") as directory:
        path = Path(directory) / "candidate.py"
        path.write_text(source, encoding="utf-8")
        for step in range(HORIZON):
            if cancel_after is not None and step >= cancel_after:
                status = "cancelled"
                break
            select_wall, select_cpu = time.perf_counter(), time.process_time()
            try:
                action = selector(history)
            except Exception as error:
                events.append({"action": "CONTROLLER", "status": "failed", "error": repr(error), "tariff": 0.0})
                status = "failed"
                break
            finally:
                controller_wall += time.perf_counter() - select_wall
                controller_cpu += time.process_time() - select_cpu
            if action not in ACTIONS:
                events.append({"action": "CONTROLLER", "status": "failed", "error": "illegal action", "tariff": 0.0})
                status = "failed"
                break
            if action == "STOP":
                events.append({"action": "STOP", "status": "completed", "tariff": TARIFF["STOP"]})
                delivered, status = True, "completed"
                history += ((action, "delivered"),)
                break
            event = invoke(action, path, task["scale"], task["offset"])
            events.append(event)
            if event["status"] != "completed":
                status = event["status"]
                break
            outcome = event["result"].get("outcome")
            if outcome not in (("0", "1", "2") if action == "CHECK" else ("attempted",)):
                event["status"], status = "failed", "failed"
                break
            history += ((action, outcome),)
        termination_reason = status
        oracle = invoke("ORACLE", path, task["scale"], task["offset"])
        events.append(oracle)
        if oracle["status"] != "completed" and status == "completed":
            status = oracle["status"]
        quality = int(delivered and oracle["status"] == "completed" and oracle["result"]["quality"] == 1)
        final_source = path.read_text(encoding="utf-8")
    after = child_usage()
    tariff = sum(event["tariff"] for event in events)
    return {
        "task": task,
        "status": status,
        "termination_reason": termination_reason,
        "verification_status": oracle["status"],
        "delivered": delivered,
        "quality": quality,
        "return": quality - tariff,
        "tariff": tariff,
        "events": events,
        "history": history,
        "initial_source": source,
        "final_source": final_source,
        "initial_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "final_sha256": hashlib.sha256(final_source.encode()).hexdigest(),
        "wall_s": time.perf_counter() - wall,
        "parent_cpu_s": time.process_time() - cpu,
        "child_cpu_s": None if after is None else after - children,
        "controller_wall_s": controller_wall,
        "controller_cpu_s": controller_cpu,
        "cost_unit": "declared_research_credits",
        "physical_costs_monetized": False,
        "peak_rss_bytes": None,
        "monetary_cost": None,
    }


def failure_controls():
    """Executed qualification faults, retained separately from service cells."""
    records = []
    with tempfile.TemporaryDirectory(prefix="hepta-tool-fault-") as directory:
        path = Path(directory) / "candidate.py"
        for label, source, timeout in (
            ("syntax_failure", "def solve(: pass", 2.0),
            ("malformed_success", "import sys\nprint('[]')\nsys.exit(0)\n", 2.0),
            ("deadline", "print('entered', flush=True)\nwhile True: pass\n", 0.25),
        ):
            path.write_text(source, encoding="utf-8")
            record = invoke("CHECK", path, 2, 3, timeout=timeout)
            record.update({"control": label, "input_source": source})
            records.append(record)
    cancelled = run_episode(
        lambda _: "CHECK", {"id": "qualification-cancel", "scale": 2, "offset": 3, "bugs": []}, cancel_after=1
    )
    cancelled["control"] = "cancelled_after_one_action"
    records.append(cancelled)
    return records

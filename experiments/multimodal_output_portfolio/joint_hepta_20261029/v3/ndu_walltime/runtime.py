"""Execute frozen JSON workers with explicit delivery, paid failures and one clock.

This is an execution/evaluation adapter, not a learning algorithm. Commands are
operator-supplied programs; process separation is not a security sandbox or an
independent scientific evaluator. Worker identity assertions are retained, not
treated as proof that a remote provider served immutable model weights.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
import signal
import subprocess
import time


@dataclass(frozen=True)
class Worker:
    argv: tuple[str, ...]
    attempt_fee: float = 0.0


@dataclass(frozen=True)
class Contract:
    deadline_seconds: float = 2.0
    call_timeout_seconds: float = 1.0
    time_price: float = 0.01
    max_decisions: int = 5
    max_output_bytes: int = 65536
    objective_version: str = "external-quality-minus-paid-attempts-minus-envelope-v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _positive(value, zero=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value >= 0 if zero else value > 0))


def validate(contract, controller, tools, verifier, identity):
    if os.name != "posix":
        raise ValueError("This execution contract requires POSIX process-group supervision")
    if (not isinstance(contract, Contract)
            or not all(_positive(x) for x in
                       (contract.deadline_seconds, contract.call_timeout_seconds))
            or not _positive(contract.time_price, zero=True)
            or type(contract.max_decisions) is not int or contract.max_decisions < 1
            or type(contract.max_output_bytes) is not int or contract.max_output_bytes < 1
            or contract.objective_version != Contract().objective_version):
        raise ValueError("Invalid frozen timing/objective contract")
    if (not isinstance(tools, dict) or any(not isinstance(n, str) or not n
                                         or n == "STOP" for n in tools)):
        raise ValueError("Tools must have nonempty legal names other than STOP")
    for worker in (controller, verifier, *tools.values()):
        if (not isinstance(worker, Worker) or not isinstance(worker.argv, tuple)
                or not worker.argv or any(not isinstance(a, str) or not a for a in worker.argv)
                or not _positive(worker.attempt_fee, zero=True)):
            raise ValueError("Invalid worker or attempt price")
    if (not isinstance(identity, dict)
            or identity.get("kind") not in ("validation_fixture", "frozen_llm")
            or not isinstance(identity.get("model_id"), str) or not identity["model_id"]
            or not isinstance(identity.get("revision"), str) or not identity["revision"]
            or identity["revision"].lower() in ("latest", "main", "unknown")):
        raise ValueError("An explicit frozen worker identity is required")
    canonical(identity)


def _unique_json_object(pairs):
    """Reject duplicate keys at every depth before worker output earns authority.

    The standard JSON decoder accepts duplicates and silently uses the last
    value, which can change action or quality depending on the verifier.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _invoke(worker, payload, timeout, output_limit):
    started = time.perf_counter_ns()
    record = {"argv_sha256": digest(worker.argv), "attempt_fee": worker.attempt_fee,
              "status": "not_started"}
    process = None
    try:
        request = canonical(payload)
        record["input_sha256"] = hashlib.sha256(request.encode()).hexdigest()
        process = subprocess.Popen(worker.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        stdout, stderr = process.communicate(request.encode(), timeout=timeout)
        record.update(exit_code=process.returncode,
                      stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                      stderr_sha256=hashlib.sha256(stderr).hexdigest(),
                      stdout_bytes=len(stdout), stderr_bytes=len(stderr))
        # Limits apply before interpreting output. communicate captures the output;
        # production adapters must add process/stream resource limits separately.
        if process.returncode != 0:
            record["status"] = "nonzero_exit"
        elif record["stdout_bytes"] > output_limit:
            record["status"] = "oversized_output"
        else:
            result = json.loads(stdout.decode("utf-8"),
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                                object_pairs_hook=_unique_json_object)
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            canonical(result)  # Reject nested nonfinite numbers, including 1e999.
            record.update(status="ok", result=result)
    except subprocess.TimeoutExpired:
        record["status"] = "timeout"
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        record.update(status="invalid_output_or_launch", error_type=type(error).__name__)
    finally:
        if process is not None:
            # This is our newly created worker group, never an inherited group.
            # Also clean surviving descendants after a normally exited worker.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()  # Reap direct child; never wait for escaped pipe holders.
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
    record["wall_seconds"] = (time.perf_counter_ns() - started) / 1e9
    return record


def run_episode(task, controller, tools, verifier, identity, contract=Contract(),
                cancelled=lambda: False):
    """Run one task. Only explicit STOP + timely verification delivers quality.

Every attempted invocation is charged, including launch failure, invalid JSON,
timeout and a failed verifier. On termination before STOP no verifier is started
and quality is zero; no unobserved correctness is imputed. Fees are synthetic
objective units unless an external protocol supplies real monetary prices.
One envelope includes controller work, tools, verification and dispatch overhead.
It is the only quantity multiplied by time_price; stage clocks are subtotals.
"""
    setup_start = time.perf_counter_ns()
    validate(contract, controller, tools, verifier, identity)
    frozen = {"contract": asdict(contract), "controller": asdict(controller),
              "tools": {n: asdict(w) for n, w in tools.items()},
              "verifier": asdict(verifier), "identity": identity}
    manifest_hash, task_hash = digest(frozen), digest(task)
    setup_wall = (time.perf_counter_ns() - setup_start) / 1e9
    started = setup_start
    history, events = [], []
    termination, quality, stop_requested = "decision_limit", 0.0, False
    delivery_at = None

    def elapsed():
        return (time.perf_counter_ns() - started) / 1e9

    def invoke(role, worker, payload):
        remaining = contract.deadline_seconds - elapsed()
        if remaining <= 0:
            return None
        entry = _invoke(worker, payload, min(remaining, contract.call_timeout_seconds),
                        contract.max_output_bytes)
        entry.update(role=role, completed_at_seconds=elapsed())
        events.append(entry)
        return entry

    for decision in range(contract.max_decisions):
        if cancelled():
            termination = "cancelled"
            break
        if elapsed() >= contract.deadline_seconds:
            termination = "expired"
            break
        response = invoke("controller", controller, {"task": task, "history": history,
            "elapsed_seconds": elapsed(), "remaining_seconds": contract.deadline_seconds-elapsed(),
            "legal_actions": ["STOP", *tools]})
        if response is None:
            termination = "expired"
            break
        if response["status"] != "ok":
            termination = "controller_" + response["status"]
            break
        command = response["result"]
        action = command.get("action")
        if not isinstance(action, str) or set(command) != {"action", "payload"}:
            termination = "invalid_action"
            break
        if cancelled():
            termination = "cancelled"
            break
        if elapsed() >= contract.deadline_seconds:
            termination = "expired"
            break
        if action == "STOP":
            stop_requested = True
            checked = invoke("verifier", verifier, {"task": task, "answer": command["payload"]})
            if checked is None:
                termination = "expired"
            elif checked["status"] != "ok":
                termination = "verifier_" + checked["status"]
            elif (set(checked["result"]) != {"quality"}
                  or not _positive(checked["result"]["quality"], zero=True)
                  or checked["result"]["quality"] > 1):
                termination = "invalid_verifier"
            elif cancelled():
                termination = "cancelled"
            elif (delivery_at := elapsed()) > contract.deadline_seconds:
                termination = "expired"
            else:
                quality, termination = float(checked["result"]["quality"]), "delivered"
            break
        if action not in tools:
            termination = "invalid_action"
            break
        observed = invoke("tool:"+action, tools[action],
                          {"task": task, "payload": command["payload"]})
        if observed is None:
            termination = "expired"
            break
        # Failed tool attempts remain observable evidence, with their full fee/time.
        history.append({"action": action, "status": observed["status"],
                        "observation": observed.get("result")})

    wall = elapsed()
    fee = math.fsum(e["attempt_fee"] for e in events)
    time_cost = contract.time_price * wall
    return {"schema": "ndu.measured-clock.episode.v1", "identity": identity,
            "contract": asdict(contract),
            "manifest_sha256": manifest_hash, "task_sha256": task_hash,
            "termination": termination, "stop_requested": stop_requested,
            "delivery_at_seconds": delivery_at if termination == "delivered" else None,
            "delivered_quality": quality, "attempt_fees": fee,
            "wall_seconds": wall, "time_cost": time_cost,
            "net_utility": quality-fee-time_cost, "setup_wall_seconds": setup_wall,
            "events": events, "clock": "time.perf_counter_ns",
            "process_scope": "POSIX worker group; workers must not detach or escape their group",
            "cancellation_scope": "checked at call boundaries; active calls end at their timeout",
            "setup_scope": "per-episode validation/hashing subtotal included in envelope",
            "deadline_missed": (delivery_at if termination == "delivered" else wall) > contract.deadline_seconds,
            "service_envelope_exceeded_deadline": wall > contract.deadline_seconds,
            "scientific_status": ("NOT_LLM_EVIDENCE" if identity["kind"] == "validation_fixture"
                                  else "EXECUTION_ONLY_PENDING_INDEPENDENT_TASK_COMPARISON"),
            "pricing_scope": "declared utility tariff; no full-lifecycle net-benefit claim"}

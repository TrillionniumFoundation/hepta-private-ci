"""Real file/SQLite tools and four baselines; offline smoke is not LLM confirmation."""
import argparse
import functools
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import urllib.parse
from .transport import call, canonical, digest, host_envelope, load, number, stamp
from .policy import PolicyBindingError, verify_policy


def select_action(arm, task, history, settings, remaining):
    """Exact finite deterministic-signal planning; durations/MAP accuracy are predictors."""
    names = sorted(task["tools"])
    tried = {h["action"] for h in history}
    available = [n for n in names if n not in tried]
    remaining -= settings["reserve_model_seconds"]
    slots = settings["max_tools"]-len(tried)
    if arm == "direct_stop" or remaining <= 0 or slots <= 0:
        return "STOP"
    if arm == "fixed_budget":
        eligible = names[:settings["fixed_budget"]]
        return next((n for n in available if n in eligible and
                     task["tools"][n]["predicted_seconds"] <= remaining), "STOP")
    hypotheses = task["planning_model"]["hypotheses"]
    if len(names) > 10 or len(hypotheses) > 256:
        raise ValueError("Finite planner qualification limits exceeded")
    planning_deadline = time.perf_counter()+remaining
    support = tuple(i for i, h in enumerate(hypotheses) if all(
        h["signals"].get(o["action"]) == o["result"]["signal"]
        for o in history if o["status"] == "ok"))
    if not support:
        return "STOP"  # Misspecified model: no fabricated posterior or oracle fallback.
    weights = [h["weight"] for h in hypotheses]
    if any(not number(w) for w in weights) or math.fsum(weights[i] for i in support) <= 0:
        raise ValueError("Invalid frozen prior")

    def terminal(indices):
        masses = {}
        for i in indices:
            answer = canonical(hypotheses[i]["answer"])
            masses[answer] = masses.get(answer, 0.) + weights[i]
        return max(masses.values())/math.fsum(weights[i] for i in indices)

    @functools.lru_cache(None)
    def solve(indices, actions, seconds, left):
        if time.perf_counter() > planning_deadline:
            raise TimeoutError("Planning exhausted its real-time allowance")
        best, choice = terminal(indices), "STOP"
        if left <= 0:
            return best, choice
        total = math.fsum(weights[i] for i in indices)
        for name in actions:
            spec = task["tools"][name]
            duration, money = spec["predicted_seconds"], spec["predicted_currency"]
            if not number(duration) or not number(money):
                raise ValueError("Unknown planner cost is not zero")
            if duration > seconds:
                continue
            groups = {}
            for i in indices:
                groups.setdefault(hypotheses[i]["signals"][name], []).append(i)
            next_actions = tuple(a for a in actions if a != name)
            gain = -(money*settings["currency_to_score"] + duration*settings["time_price"])
            for group in groups.values():
                value = terminal(group) if arm == "one_step_voi" else solve(
                    tuple(group), next_actions, seconds-duration, left-1)[0]
                gain += math.fsum(weights[i] for i in group)/total*value
            if gain > best+1e-12:
                best, choice = gain, name
        return best, choice
    if arm not in ("one_step_voi", "strong_planner"):
        raise ValueError("Supply the candidate policy explicitly for the full arm")
    return solve(support, tuple(available), remaining, slots)[1]


def _tool(task, action):
    spec = task["tools"][action]
    path = Path(spec["path"])
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError("Tool source changed")
    if spec["kind"] == "file":
        lines = data.decode("utf-8").splitlines()
        value = "\n".join(lines[spec.get("first_line", 1)-1:spec.get("last_line", len(lines))])
    elif spec["kind"] == "sqlite":
        uri = "file:"+urllib.parse.quote(str(path.resolve()))+"?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as db:
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
            db.set_authorizer(lambda op, *rest: sqlite3.SQLITE_OK if op in allowed else sqlite3.SQLITE_DENY)
            cursor = db.execute(spec["query"])
            value = [list(row) for row in cursor.fetchmany(1001)]
            if len(value) > 1000:
                raise ValueError("Frozen result-size cap exceeded")
    else:
        raise ValueError("Unsupported tool kind")
    return {"value": value, "signal": digest(value)}


def worker(request):
    if request["op"] == "tool":
        return _tool(request["task"], request["action"])
    if request["op"] == "verify":
        return {"quality": float(canonical(request["answer"]) == canonical(request["task"]["expected_answer"]))}
    raise ValueError("Unknown worker operation")


def public_task(task):
    return {"prompt": task["prompt"], "planning_model": task["planning_model"],
            "tools": {n: {k: s[k] for k in ("kind", "predicted_seconds", "predicted_currency")}
                      for n, s in task["tools"].items()}}


def method_digest(arm, settings, policy=None):
    verify_policy(arm, settings, policy)
    sources = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in ("tasks.py", "transport.py", "contracts.py", "ledger.py", "policy.py")}
    contract = {k: v for k, v in settings.items() if k not in ("protocol_sha256", "method_sha256")}
    return digest({"sources": sources, "arm": arm, "settings": contract})


def run_episode(task, arm, provider, settings, ledger, protocol_hash, method_hash,
                repeat=0, policy=None, cancelled=lambda: False):
    """policy(public_task, history, settings, remaining, request_model)->action. Use its request_model hook for every model call."""
    start, started_at = time.perf_counter(), stamp()
    if method_hash != method_digest(arm, settings, policy):
        raise ValueError("Method/configuration differs from the frozen source digest")
    context = {"task_id": task["id"], "arm": arm, "repeat": repeat, "protocol_sha256": protocol_hash}
    events, history = [], []
    local = {"kind": "local", "argv": [sys.executable, "-m", __package__+".tasks", "--worker"],
             "identity": {"kind": "local_tool", "model_id": "file-sqlite-verifier", "revision": "v1"}}
    quality, delivery, stopped, terminal, answer = 0., None, False, "expired", None
    task_hash = digest(task)
    verifier_hash = digest({"source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                            "rule": "canonical-json-exact-v1", "expected_answer": task["expected_answer"]})

    def remaining():
        return settings["deadline_seconds"]-(time.perf_counter()-start)

    def execute(kind, config, payload):
        if remaining() <= 0 or cancelled():
            return None, None
        event, result = call(config, payload, context, ledger,
                             min(settings["call_timeout_seconds"], remaining()), kind,
                             absolute_deadline=start+settings["deadline_seconds"])
        events.append(event)
        return event, result

    try:
        # Setup, finite-model planning, tools, final inference, verification and fsync share one clock.
        for _ in range(settings["max_tools"]+1):
            if cancelled():
                terminal = "cancelled"
                break
            if remaining() <= 0:
                break
            if policy is not None:
                verify_policy(arm, settings, policy)
                public, observed, frozen_settings = json.loads(canonical([public_task(task), history, settings]))
                action = policy(public, observed, frozen_settings, remaining(),
                                lambda payload: execute("model", provider, payload))
                verify_policy(arm, settings, policy)
            else:
                action = select_action(arm, task, history, settings, remaining())
            if action == "STOP":
                stopped = True
                event, text = execute("model", provider, {"task": public_task(task), "history": history,
                    "instruction": "Return exactly a JSON object with one key, answer, containing the answer."})
                if event is None or event["status"] != "ok":
                    terminal = "model_failure" if event else "expired"
                    break
                parsed = json.loads(text)
                if not isinstance(parsed, dict) or set(parsed) != {"answer"}:
                    raise ValueError("Invalid model answer")
                answer = parsed["answer"]
                checked, result = execute("verifier", local,
                    {"op": "verify", "task": task, "answer": parsed["answer"]})
                if checked and checked["status"] == "ok" and not cancelled() and remaining() >= 0:
                    quality, delivery, terminal = result["quality"], time.perf_counter()-start, "delivered"
                else:
                    terminal = "cancelled" if cancelled() else "verifier_failure"
                break
            if action not in task["tools"] or any(h["action"] == action for h in history):
                terminal = "invalid_policy"
                break
            event, result = execute("tool", local, {"op": "tool", "task": task, "action": action})
            if event is None:
                terminal = "expired"
                break
            history.append({"action": action, "status": event["status"], "result": result})
        else:
            terminal = "decision_limit"
    except PolicyBindingError:
        raise  # Retained ledger plus missing episode forces HOLD after an actual method change.
    except TimeoutError:
        terminal = "planner_timeout"
    except (ValueError, TypeError, KeyError, RecursionError):
        terminal = "invalid_model_or_policy_output"
    meter = host_envelope(context, ledger, started_at, start)
    events.append(meter)
    return {"schema": "ndu.confirmation.episode.v1", "task_id": task["id"], "arm": arm, "repeat": repeat, "started_at": started_at,
            "protocol_sha256": protocol_hash, "task_sha256": task_hash, "verifier_sha256": verifier_hash,
            "method_sha256": method_hash, "answer": answer, "quality": quality,
            "contract": {k: settings[k] for k in ("deadline_seconds", "currency_to_score", "time_price")}, "delivery_at_seconds": delivery,
            "stop_requested": stopped, "terminal": terminal, "wall_seconds": meter["wall_seconds"],
            "request_ids": [e["request_id"] for e in events], "history": history,
            "scientific_status": "NOT_LLM_EVIDENCE" if provider["identity"]["kind"] == "offline_fixture"
                                 else "EXECUTION_ONLY_PENDING_CONFIRMATION"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--provider")
    parser.add_argument("--settings")
    parser.add_argument("--arm", choices=("direct_stop", "fixed_budget", "one_step_voi", "strong_planner"))
    parser.add_argument("--ledger")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.worker:
        print(canonical(worker(json.load(sys.stdin))))
    else:
        settings = load(args.settings)
        result = run_episode(load(args.task), args.arm, load(args.provider), settings, args.ledger,
                             settings["protocol_sha256"], settings["method_sha256"])
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(canonical(result)+"\n")
        print(canonical({"scientific_status": result["scientific_status"], "terminal": result["terminal"]}))

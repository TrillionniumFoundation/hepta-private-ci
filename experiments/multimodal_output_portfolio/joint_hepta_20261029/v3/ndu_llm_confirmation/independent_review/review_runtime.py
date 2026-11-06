"""Independent local-only dispatch-fault and actual callback-binding checks.

The target source is read, never edited. All worker commands and policy modules
are created under TemporaryDirectory. No HTTP endpoint or external API is used.
"""
import argparse
import datetime as dt
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import uuid
from review_gate import TARGET_DEFAULT, canonical, digest, fingerprint

sys.dont_write_bytecode = True
CONTEXT = {"task_id": "independent-local-fixture", "arm": "full", "repeat": 0, "protocol_sha256": "a"*64}
IDENTITY = {"kind": "offline_fixture", "model_id": "independent-scripted-fixture", "revision": "review-v1"}


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def response():
    return {"model_id": IDENTITY["model_id"], "revision": IDENTITY["revision"], "text": '{"answer":"ten"}',
            "usage": {"input_tokens": 3, "output_tokens": 2}, "provider_request_id": "independent-synthetic-provider-id"}


def worker_config(marker, ledger=None, pause=0.):
    program = "import json,time;from pathlib import Path;"
    if ledger is None:
        program += "Path("+repr(str(marker))+").write_text('executed');"
    else:
        program += "rows=[json.loads(x) for x in Path("+repr(str(ledger))+").read_text().splitlines()];Path("+repr(str(marker))+").write_text(json.dumps(rows[-1]));"
    program += "time.sleep("+repr(pause)+");print("+repr(canonical(response()))+")"
    return {"kind": "local", "identity": dict(IDENTITY), "argv": [sys.executable, "-c", program]}


def invoice(event, amount=.037):
    return {"request_id": event["request_id"], "status": "final", "amount": amount, "currency": "USD",
            "invoice_sha256": digest({"synthetic_review_invoice": event["request_id"], "amount": amount}), "line_id": event["request_id"],
            "usage": event.get("usage"), "identity_sha256": event["expected_identity_sha256"],
            "provider_request_sha256": event.get("provider_request_sha256")}


def expect_value_error(action, label):
    try:
        action()
    except ValueError as exc:
        return type(exc).__name__
    raise AssertionError(label+": expected a rejected invalid value")


def load_policy(path, source):
    path.write_text(source)
    name = "independent_review_policy_"+uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


POLICY_SOURCE = '''MODE = "STOP"
STATE = ["STOP"]
import math

def stop_now(task, history, settings, remaining, request_model):
    return MODE

def read_then_stop(task, history, settings, remaining, request_model):
    return "read" if not history else "STOP"

def nested_call(task, history, settings, remaining, request_model):
    request_model({"independent_review": "nested-model-call"})
    return "STOP"

def mutable_global(task, history, settings, remaining, request_model):
    return STATE[0]

def imported_global(task, history, settings, remaining, request_model):
    return "STOP" if math.sqrt(4) == 2 else "read"

def hidden_default(task, history, settings, remaining, request_model=None):
    return "STOP"

def internal_import(task, history, settings, remaining, request_model):
    import math
    return "STOP"
'''


def run_suite(transport, ledger_module, tasks, policy_module, contracts):
    results = []

    def case(name, fn):
        try:
            details = fn()
            results.append({"name": name, "passed": True, "details": details})
        except Exception as exc:
            results.append({"name": name, "passed": False, "exception_type": type(exc).__name__, "reason": str(exc)})

    with tempfile.TemporaryDirectory(prefix="ndu-independent-review-") as directory:
        root = Path(directory)

        def good_request():
            log, marker = root/"valid.jsonl", root/"valid-marker.json"
            event, text = transport.call(worker_config(marker, log), {"review": "local-only"}, CONTEXT, str(log), 2.)
            raw = lines(log)
            assert event["status"] == "ok" and text == response()["text"]
            assert [e["phase"] for e in raw] == ["intent", "terminal"]
            observed_intent = json.loads(marker.read_text())
            assert observed_intent == raw[0] and observed_intent["request_id"] == event["request_id"]
            assert event["intent_sha256"] == digest(raw[0])
            assert raw[0]["prepared_monotonic"] <= event["intent_finished_monotonic"] <= event["dispatch_monotonic"] <= event["finished_monotonic"]
            for e in raw:
                contracts.validate(e, "event")
            complete = ledger_module.complete_events(raw)
            assert len(complete) == 1
            costs, problems = ledger_module.reconcile(complete, [invoice(event)], "USD")
            assert not problems and costs == {event["request_id"]: .037}
            assert ledger_module.reconcile(complete, [invoice(event), invoice(event)], "USD")[1]
            return {"intent_seen_by_worker": True, "raw_rows": len(raw), "completed_attempts": len(complete), "billed_once": costs[event["request_id"]], "raw": raw}
        case("durable_intent_visible_before_worker_and_single_charge", good_request)

        def absent_directory():
            marker = root/"absent-directory-marker"
            try:
                transport.call(worker_config(marker), {}, CONTEXT, str(root/"does-not-exist"/"ledger.jsonl"), 2.)
            except FileNotFoundError:
                assert not marker.exists()
                return {"worker_executed": False}
            raise AssertionError("Missing ledger directory did not abort dispatch")
        case("unwritable_ledger_stops_before_worker", absent_directory)

        def fsync_failure():
            log, marker = root/"fsync.jsonl", root/"fsync-marker"
            try:
                with patch.object(ledger_module.os, "fsync", side_effect=OSError("independent simulated fsync failure")):
                    transport.call(worker_config(marker), {}, CONTEXT, str(log), 2.)
            except OSError:
                assert not marker.exists()
                raw = lines(log)
                assert len(raw) == 1 and raw[0]["phase"] == "intent"
                expect_value_error(lambda: ledger_module.complete_events(raw), "unfinished intent after fsync failure")
                return {"worker_executed": False, "raw_phases": [e["phase"] for e in raw]}
            raise AssertionError("Failed fsync did not abort dispatch")
        case("failed_intent_fsync_prevents_worker_and_leaves_HOLD", fsync_failure)

        def terminal_append_failure():
            log, marker = root/"terminal-fail.jsonl", root/"terminal-fail-marker"
            original = transport.append_event
            def fail_terminal(path, event):
                if event["phase"] == "terminal":
                    raise OSError("independent terminal append fault")
                return original(path, event)
            try:
                with patch.object(transport, "append_event", side_effect=fail_terminal):
                    transport.call(worker_config(marker), {}, CONTEXT, str(log), 2.)
            except OSError:
                assert marker.exists()
                raw = lines(log)
                assert len(raw) == 1 and raw[0]["phase"] == "intent"
                expect_value_error(lambda: ledger_module.complete_events(raw), "unfinished intent after terminal failure")
                return {"worker_executed": True, "recoverable_request_id": raw[0]["request_id"], "raw_phases": [e["phase"] for e in raw]}
            raise AssertionError("Terminal append failure was suppressed")
        case("terminal_append_failure_preserves_pending_intent", terminal_append_failure)

        def slow_admission(absolute):
            log, marker = root/("absolute-slow.jsonl" if absolute else "slow.jsonl"), root/("absolute-marker" if absolute else "slow-marker")
            original = transport.append_event
            def delay_intent(path, event):
                original(path, event)
                if event["phase"] == "intent":
                    time.sleep(.09)
            end = time.perf_counter()+.04 if absolute else None
            with patch.object(transport, "append_event", side_effect=delay_intent):
                event, text = transport.call(worker_config(marker), {}, CONTEXT, str(log), 2. if absolute else .04, absolute_deadline=end)
            raw = lines(log)
            assert not marker.exists() and text is None and event["status"] == "timeout"
            assert event["dispatched"] is False and event["dispatch_monotonic"] is None and event["response_received"] is False
            assert [e["phase"] for e in raw] == ["intent", "terminal"]
            assert event["finished_monotonic"] >= event["deadline_monotonic"]
            assert len(ledger_module.complete_events(raw)) == 1
            return {"worker_executed": False, "status": event["status"], "wall_seconds": event["wall_seconds"], "absolute_deadline_used": absolute}
        case("slow_intent_consumes_request_deadline", lambda: slow_admission(False))
        case("slow_intent_consumes_absolute_deadline", lambda: slow_admission(True))

        def failed_spawn():
            log = root/"failed-spawn.jsonl"
            config = {"kind": "local", "identity": dict(IDENTITY), "argv": [str(root/"not-an-executable")]}
            event, text = transport.call(config, {}, CONTEXT, str(log), 2.)
            assert event["status"] == "failure" and event["dispatched"] is False and event["dispatch_monotonic"] is None
            assert event["response_received"] is False and text is None
            assert len(ledger_module.complete_events(lines(log))) == 1
            return {"status": event["status"], "dispatched": event["dispatched"], "actual_amount": event["actual_amount"]}
        case("failed_spawn_has_consistent_undispatched_state", failed_spawn)

        def worker_timeout():
            log, marker = root/"worker-timeout.jsonl", root/"worker-timeout-marker"
            event, text = transport.call(worker_config(marker, pause=2.), {}, CONTEXT, str(log), .12)
            raw = lines(log)
            assert event["status"] == "timeout" and event["dispatched"] is True and text is None
            assert event["usage"] is None and event["actual_amount"] is None
            completed = ledger_module.complete_events(raw)
            costs, errors = ledger_module.reconcile(completed, [], "USD")
            assert costs[event["request_id"]] is None and errors
            return {"status": event["status"], "raw_phases": [e["phase"] for e in raw], "unknown_cost_retained": True, "invoice_missing_problems": errors}
        case("worker_timeout_retains_unknown_cost", worker_timeout)

        source = root/"candidate.py"
        module = load_policy(source, POLICY_SOURCE)
        fact = root/"fact.txt"; fact.write_text("ten")
        task = {"id": "independent-local-task", "prompt": "Return the known word", "expected_answer": "ten",
                "tools": {"read": {"kind": "file", "path": str(fact), "sha256": hashlib.sha256(fact.read_bytes()).hexdigest(), "predicted_seconds": .01, "predicted_currency": .01}},
                "planning_model": {"hypotheses": [{"weight": 1., "answer": "ten", "signals": {"read": digest("ten")}}]}}
        common_settings = {"deadline_seconds": 3., "call_timeout_seconds": 1., "reserve_model_seconds": .1,
                           "max_tools": 1, "fixed_budget": 1, "currency_to_score": 1., "time_price": 0.}

        def valid_candidate():
            log, marker = root/"valid-policy.jsonl", root/"valid-policy-marker"
            settings = {**common_settings, "policy_binding": policy_module.policy_binding(module.stop_now)}
            method = tasks.method_digest("full", settings, module.stop_now)
            record = tasks.run_episode(task, "full", worker_config(marker), settings, str(log), "a"*64, method, policy=module.stop_now)
            assert record["terminal"] == "delivered" and record["quality"] == 1. and marker.exists()
            completed = ledger_module.complete_events(lines(log))
            assert [e["kind"] for e in completed] == ["model", "verifier", "host_envelope"]
            assert record["request_ids"] == [e["request_id"] for e in completed]
            assert record["scientific_status"] == "NOT_LLM_EVIDENCE"
            return {"terminal": record["terminal"], "quality": record["quality"], "completed_kinds": [e["kind"] for e in completed], "binding": settings["policy_binding"]}
        case("valid_actual_callback_binding_positive_control", valid_candidate)

        def absent_binding():
            error = expect_value_error(lambda: tasks.method_digest("full", common_settings, module.stop_now), "missing full binding")
            return {"rejected_by": error}
        case("full_binding_is_required", absent_binding)

        def different_entrypoint():
            marker, log = root/"swap-marker", root/"swap.jsonl"
            settings = {**common_settings, "policy_binding": policy_module.policy_binding(module.stop_now)}
            method = tasks.method_digest("full", settings, module.stop_now)
            error = expect_value_error(lambda: tasks.run_episode(task, "full", worker_config(marker), settings, str(log), "a"*64, method, policy=module.read_then_stop), "different function in same file")
            assert not marker.exists() and not log.exists()
            return {"same_source_file": True, "worker_executed": False, "rejected_by": error}
        case("same_file_different_callback_rejected_before_dispatch", different_entrypoint)

        def changed_global():
            settings = {**common_settings, "policy_binding": policy_module.policy_binding(module.stop_now)}
            original = module.MODE
            try:
                module.MODE = "read"
                error = expect_value_error(lambda: tasks.method_digest("full", settings, module.stop_now), "changed immutable global value")
            finally:
                module.MODE = original
            return {"rejected_by": error}
        case("changed_immutable_global_changes_binding", changed_global)

        def changed_code():
            original = module.stop_now.__code__
            try:
                module.stop_now.__code__ = module.read_then_stop.__code__
                error = expect_value_error(lambda: policy_module.policy_binding(module.stop_now), "changed runtime code")
            finally:
                module.stop_now.__code__ = original
            return {"rejected_by": error}
        case("actual_runtime_code_swap_is_rejected", changed_code)

        def changed_source():
            original = source.read_text()
            settings = {**common_settings, "policy_binding": policy_module.policy_binding(module.stop_now)}
            try:
                source.write_text(original+"\n# independent source change\n")
                error = expect_value_error(lambda: tasks.method_digest("full", settings, module.stop_now), "changed source artifact")
            finally:
                source.write_text(original)
            return {"rejected_by": error}
        case("source_changed_after_freeze_is_rejected", changed_source)

        for name in ("mutable_global", "imported_global", "hidden_default", "internal_import"):
            case("unsupported_callback_"+name, lambda name=name: {"rejected_by": expect_value_error(lambda: policy_module.policy_binding(getattr(module, name)), name)})
        case("anonymous_callback_rejected", lambda: {"rejected_by": expect_value_error(lambda: policy_module.policy_binding(lambda a,b,c,d,e: "STOP"), "anonymous callback")})
        def make_closure():
            answer = "STOP"
            def callback(a,b,c,d,e):
                return answer
            return callback
        case("closure_callback_rejected", lambda: {"rejected_by": expect_value_error(lambda: policy_module.policy_binding(make_closure()), "closure callback")})
        case("baseline_cannot_be_replaced_by_callback", lambda: {"rejected_by": expect_value_error(lambda: tasks.method_digest("direct_stop", common_settings, module.stop_now), "baseline callback substitution")})

        def nested_calls_metered():
            log, marker = root/"nested-policy.jsonl", root/"nested-policy-marker"
            settings = {**common_settings, "policy_binding": policy_module.policy_binding(module.nested_call)}
            method = tasks.method_digest("full", settings, module.nested_call)
            record = tasks.run_episode(task, "full", worker_config(marker), settings, str(log), "a"*64, method, policy=module.nested_call)
            completed = ledger_module.complete_events(lines(log))
            models = [e for e in completed if e["kind"] == "model"]
            assert record["terminal"] == "delivered" and len(models) == 2
            assert len(set(e["request_id"] for e in completed)) == 4
            assert record["request_ids"] == [e["request_id"] for e in completed]
            return {"model_attempts": len(models), "completed_attempts_and_meter": len(completed)}
        case("nested_model_hook_calls_are_all_metered", nested_calls_metered)

        def episode_slow_intent():
            log, marker = root/"episode-slow.jsonl", root/"episode-slow-marker"
            settings = {**common_settings, "deadline_seconds": .06, "call_timeout_seconds": 2., "max_tools": 0}
            original = transport.append_event
            def delay_intent(path, event):
                original(path, event)
                if event["phase"] == "intent":
                    time.sleep(.1)
            method = tasks.method_digest("direct_stop", settings)
            with patch.object(transport, "append_event", side_effect=delay_intent):
                record = tasks.run_episode(task, "direct_stop", worker_config(marker), settings, str(log), "a"*64, method)
            completed = ledger_module.complete_events(lines(log))
            model = next(e for e in completed if e["kind"] == "model")
            meter = next(e for e in completed if e["kind"] == "host_envelope")
            assert not marker.exists() and model["dispatched"] is False and model["status"] == "timeout"
            assert model["deadline_monotonic"] <= meter["started_monotonic"]+settings["deadline_seconds"]
            assert record["quality"] == 0. and record["delivery_at_seconds"] is None
            return {"worker_executed": False, "terminal": record["terminal"], "model_status": model["status"], "wall_seconds": record["wall_seconds"], "deadline_seconds": settings["deadline_seconds"]}
        case("slow_intent_cannot_restart_episode_clock", episode_slow_intent)
    return {"status": "PASS" if all(r["passed"] for r in results) else "FAIL", "check_count": len(results),
            "passed": sum(r["passed"] for r in results), "failed": sum(not r["passed"] for r in results), "checks": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=TARGET_DEFAULT)
    parser.add_argument("--execute-after-stable-notice", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.execute_after_stable_notice:
        print(json.dumps({"status": "NOT_RUN", "reason": "Await stable target notice."}))
        return 0
    if args.output is None or args.output.exists():
        raise SystemExit("Provide a new output file; old review receipts are preserved.")
    args.target = args.target.resolve()
    args.output = args.output.resolve()
    os.chdir(args.target.parent)  # Local worker modules resolve without altering provider/network configuration.
    before = fingerprint(args.target)
    sys.path.insert(0, str(args.target.parent))
    modules = [importlib.import_module(args.target.name+"."+name) for name in ("transport", "ledger", "tasks", "policy", "contracts")]
    report = run_suite(*modules)
    after = fingerprint(args.target)
    report.update(schema="ndu.independent.runtime-review.v1", reviewed_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  source_sha256_before=before, source_sha256_after=after, source_stable=before == after,
                  scope="Independent local fake-worker and callback qualification; no external API, real LLM, or bill authentication.")
    if before != after:
        report["status"] = "INVALIDATED_SOURCE_CHANGED"
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "check_count": report["check_count"], "failed": report["failed"], "output": str(args.output)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

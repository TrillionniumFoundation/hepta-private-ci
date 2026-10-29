"""Cold reconstruction of the frozen research credit ledger, without task IO.

Recovery verifies retained settlements against original requests/results and
recomputes accounting independently. It inspects the original native owner
anchor; it never sends a new execution command to a terminated task.
"""

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .credit_execution import CONTRACT, CreditAccount, HERE, ROOT, file_sha
from .credit_execution import source_identity as credit_source_identity
from .native_execution import ResearchOwner, ZERO, canonical, save_once, sha


RECOVERY_PROFILE = "hepta.fpt-adaptive.credit-recovery.v1"
RECOVERY_SOURCES = (
    "experiments/first_passage_adaptive/credit_recovery.py",
    "experiments/first_passage_adaptive/tests/test_credit_recovery.py",
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(Path(path).read_text(), object_pairs_hook=unique, parse_constant=invalid_constant)


def expectations(case_directory):
    execution = read_json(Path(case_directory) / "EXECUTION.json")
    summary, rows = execution["summary"], execution["rows"]
    return {
        "case": summary["case"], "enabled": summary["feedback_enabled"], "count": len(rows),
        "initial_task_state": rows[0]["request"]["state"], "final_task_state": rows[-1]["response"]["state"],
        "final_price": summary["final_price"], "final_credit_sha256": summary["credit_final_sha256"],
        "final_owner_anchor": summary["owner_final_anchor"], "found": summary["found"],
        "selected_model_sha256": rows[0]["snapshot"]["selected_model_sha256"],
    }


def restore_state(case_directory, expected):
    """Reconstruct accounting without calling CreditAccount.settle to restore it."""
    case_directory = Path(case_directory)
    count = expected["count"]
    require(type(count) is int and 1 <= count <= 16, "unsupported settlement count")
    names = [f"{index:04}.json" for index in range(1, count + 1)]
    require(sorted(path.name for path in (case_directory / "credit").glob("*.json")) == names,
            "missing, additional or noncontiguous settlement files")
    require(sorted(path.name for path in (case_directory / "steps").glob("*.json")) == names,
            "missing, additional or noncontiguous step files")
    owner_sidecars = case_directory / "owner/task-sidecars"
    owner_names = sorted(f"{kind}-{name}" for kind in ("request", "response") for name in names)
    require(sorted(path.name for path in owner_sidecars.glob("*.json")) == owner_names,
            "missing or additional original owner request/result")
    account = CreditAccount(expected["enabled"])
    previous_state = expected["initial_task_state"]
    previous_anchor, previous_fpt = ZERO, ZERO
    found = False
    last_request, last_response = None, None
    for index, name in enumerate(names, 1):
        row = read_json(case_directory / "steps" / name)
        receipt = read_json(case_directory / "credit" / name)
        request = read_json(owner_sidecars / ("request-" + name))
        response = read_json(owner_sidecars / ("response-" + name))
        require(request == row["request"] and response == row["response"], "step and original owner request/result differ")
        require(request["sequence"] == index, "owner request sequence is out of order")
        require(request["state"] == previous_state, "task state does not continue the preceding result")
        require(request["checkpoint_digest"] == previous_anchor == response["owner"]["checkpoint_before"],
                "owner anchor predecessor mismatch")
        require(request["fpt_predecessor_digest"] == previous_fpt, "FPT predecessor mismatch")
        require(request["fpt_checkpoint_digest"] == sha(request["fpt_checkpoint_json"].encode()) == response["fpt_checkpoint_digest"],
                "FPT checkpoint binding mismatch")
        require(response["request_digest"] == sha(request), "owner request digest mismatch")
        require(not response["replayed"], "historical charge must use the original result, not a zero-usage replay")
        snapshot, ndu = row["snapshot"], row["ndu"]
        require(snapshot["credit"] == account.snapshot(), "next NDU snapshot does not carry the preceding credit state")
        require(snapshot["task_state"] == request["state"] and snapshot["found"] == found,
                "next NDU snapshot disagrees with observed task state")
        require(snapshot["selected_model_sha256"] == expected["selected_model_sha256"] == sha(snapshot["selected_model"]),
                "selected physical model changed in retained chain")
        require(ndu["request"]["snapshot_digest"] == sha(snapshot)
                and ndu["response"]["request_digest"] == sha(ndu["request"])
                and ndu["response"]["evaluation_digest"] == request["ndu_receipt_digest"] == response["ndu_receipt_digest"],
                "NDU/request/response receipt binding mismatch")
        require(receipt == row["credit_settlement"], "step and credit settlement differ")
        require(receipt.get("already_applied") is False and receipt["sha256"] == sha(receipt["record"]),
                "settlement hash mismatch")
        key = response["request_digest"]
        require(key not in account.records, "duplicate settled owner request")
        usage = response["source_read_attempts_this_call"]
        require(type(usage) is int and usage in (0, 1)
                and response["state"]["read_units_spent"] - request["state"]["read_units_spent"] == usage,
                "actual attempt charge and original owner budget disagree")
        before = account.price
        eta = CONTRACT["price_step"] if account.enabled else 0.0
        after = max(0.0, min(CONTRACT["price_maximum"], before + eta * (usage - CONTRACT["target_usage_per_decision"])))
        recomputed = {
            "schema": "hepta.fpt-adaptive.credit-settlement.v1", "previous_sha256": account.previous,
            "owner_request_digest": key, "owner_anchor": response["owner"]["checkpoint_after"],
            "owner_response_sha256": sha(response), "actual_usage": usage,
            "successful_source_reads": response["source_reads_this_call"],
            "answer_observed": bool(response["read"] and response["read"].get("answer")),
            "terminal": response["state"]["terminal"], "price_before": before, "price_after": after,
            "eta": eta, "target": CONTRACT["target_usage_per_decision"], "maximum": CONTRACT["price_maximum"],
            "actual_base_cost": CONTRACT["base_read_cost"] * usage, "shadow_resource_charge": before * usage,
            "physical_cancel_rate_updated": False,
        }
        require(receipt["record"] == recomputed, "settlement arithmetic, predecessor or content mismatch")
        account.price, account.previous = after, receipt["sha256"]
        account.records[key] = receipt
        previous_state, previous_anchor = response["state"], response["owner"]["checkpoint_after"]
        previous_fpt = request["fpt_checkpoint_digest"]
        found = found or recomputed["answer_observed"]
        last_request, last_response = request, response
    require(account.price == expected["final_price"] and account.previous == expected["final_credit_sha256"],
            "restored credit does not match the retained terminal expectation")
    require(previous_state == expected["final_task_state"] and previous_anchor == expected["final_owner_anchor"]
            and found == expected["found"], "restored task does not match the retained terminal expectation")
    return account, {"task_state": previous_state, "found": found, "owner_anchor": previous_anchor,
                     "last_request": last_request, "last_response": last_response}


def export_account(account):
    return {"snapshot": account.snapshot(), "records": copy.deepcopy(account.records)}


class InspectionOnlyOwner(ResearchOwner):
    """Keep the original native bridge but reject execution in this workflow."""

    def __init__(self, manifest):
        super().__init__(manifest)
        self.inspection_calls = 0
        self.execute_attempts = 0

    def invoke(self, directory, request, inspect=False):
        if not inspect:
            self.execute_attempts += 1
            raise ValueError("credit recovery forbids native task execution")
        self.inspection_calls += 1
        return super().invoke(directory, request, inspect=True)


def restore_credit(case_directory, expected, owner):
    account, context = restore_state(case_directory, expected)
    inspection = owner.invoke(Path(case_directory), context["last_request"], inspect=True)
    require(inspection["checkpoint_digest"] == context["owner_anchor"] and inspection["sequence"] == expected["count"],
            "current native owner anchor differs from restored credit terminal anchor")
    require(inspection["source_reads"] == 0, "owner inspection unexpectedly accessed a task source")
    return account, context, inspection


def uninterrupted_reference(case_directory):
    """Live in-memory settlement replay of retained results, with no restoration API."""
    original = read_json(Path(case_directory) / "EXECUTION.json")
    account = CreditAccount(original["summary"]["feedback_enabled"])
    for row in original["rows"]:
        receipt = account.settle(row["response"], row["request"]["state"]["read_units_spent"])
        require(receipt == row["credit_settlement"], "uninterrupted settlement reference differs from original execution")
    return account, original["rows"][-1]["response"]


def isolated_probes(account, final_response):
    """Only accounting messages; no synthetic message is sent to the task owner."""
    original = export_account(account)
    replay = copy.deepcopy(final_response)
    replay.update(replayed=True, source_read_attempts_this_call=0, source_reads_this_call=0)
    replay_receipt = account.settle(replay, final_response["state"]["read_units_spent"])
    require(replay_receipt["already_applied"] and original == export_account(account), "restored replay updated credit twice")
    isolated = copy.deepcopy(account)
    spent = final_response["state"]["read_units_spent"]
    hypothetical = {
        "schema": "hepta.fpt-adaptive.hypothetical-credit-message.v1", "synthetic": True,
        "request_digest": sha(["isolated-next-credit-message", final_response["request_digest"]]),
        "owner": {"checkpoint_after": sha(["synthetic-anchor-never-sent-to-owner", final_response["request_digest"]])},
        "source_read_attempts_this_call": 1, "source_reads_this_call": 1,
        "state": {"read_units_spent": spent + 1, "terminal": None},
        "read": {"answer": None}, "replayed": False,
    }
    next_receipt = isolated.settle(hypothetical, spent)
    return {"replay": replay_receipt, "replay_unchanged": original == export_account(account),
            "hypothetical_message": hypothetical, "hypothetical_receipt": next_receipt,
            "hypothetical_account": export_account(isolated),
            "scope": "isolated accounting continuation only; terminal task is not resumed and no new native execution or task utility is recorded"}


def current_sources():
    return {"recovery": {name: file_sha(ROOT / name) for name in RECOVERY_SOURCES},
            "frozen_credit_dependencies": credit_source_identity()}


def input_files(input_directory):
    result = {}
    for path in sorted(Path(input_directory).rglob("*")):
        if path.is_file() and "data" not in path.relative_to(input_directory).parts:
            result[path.relative_to(input_directory).as_posix()] = file_sha(path)
    return result


def freeze(input_directory, owner_build, destination):
    input_directory = Path(input_directory).resolve()
    owner = ResearchOwner(owner_build)
    credit_freeze = read_json(input_directory.parent / "SOURCE_FREEZE.json")
    require(credit_freeze["source_identity"] == credit_source_identity(), "original credit frozen sources changed")
    value = {
        "schema": RECOVERY_PROFILE + ".freeze", "created_at": datetime.now(timezone.utc).isoformat(),
        "validation_started": False, "source_identity": current_sources(),
        "input_directory": str(input_directory), "input_sha256": input_files(input_directory),
        "credit_source_freeze_sha256": file_sha(input_directory.parent / "SOURCE_FREEZE.json"),
        "owner_build_sha256": file_sha(owner_build), "owner_binary_sha256": owner.build["binary_sha256"],
        "cases": {name: expectations(input_directory / name) for name in CONTRACT["fixtures"]},
        "scope": "serial trusted writer; hash-linked research recovery; no power-loss atomicity or concurrent-writer guarantee",
    }
    save_once(Path(destination), value)
    return value


def verify_freeze(frozen, owner_build):
    require(frozen["schema"] == RECOVERY_PROFILE + ".freeze" and not frozen["validation_started"], "unsupported recovery freeze")
    require(frozen["source_identity"] == current_sources(), "recovery source identity changed after freeze")
    require(frozen["owner_build_sha256"] == file_sha(owner_build), "owner build changed after recovery freeze")


def inspect_in_child(case_directory, expected, owner):
    account, context, inspection = restore_credit(case_directory, expected, owner)
    restored = export_account(account)
    probes = isolated_probes(account, context["last_response"])
    after = owner.invoke(Path(case_directory), context["last_request"], inspect=True)
    require(after == inspection, "read-only recovery/probes changed native owner inspection")
    return {"account": restored, "task_state": context["task_state"], "found": context["found"],
            "owner_inspection": inspection, "owner_inspection_after_probes": after, "probes": probes,
            "native_inspection_calls": owner.inspection_calls, "native_execute_requests": owner.execute_attempts}


def fault_validation(source_case, expected, owner):
    """Mutate disposable copies only; source fixtures are deliberately not copied."""
    results = []
    faults = ("missing_settlement", "tampered_price", "rehashed_wrong_price", "reordered_settlements",
              "missing_owner_result", "attempt_budget_conflict", "corrupt_native_witness")
    for kind in faults:
        with tempfile.TemporaryDirectory(prefix="hepta-credit-recovery-") as temporary:
            target = Path(temporary) / "case"
            shutil.copytree(source_case, target, ignore=shutil.ignore_patterns("data"))
            first = target / "credit/0001.json"
            step_path = target / "steps/0001.json"
            if kind == "missing_settlement":
                first.unlink()
            elif kind in ("tampered_price", "rehashed_wrong_price"):
                receipt = read_json(first)
                receipt["record"]["price_after"] += 0.01
                if kind == "rehashed_wrong_price":
                    receipt["sha256"] = sha(receipt["record"])
                first.write_bytes(canonical(receipt))
                step = read_json(step_path)
                step["credit_settlement"] = receipt
                step_path.write_bytes(canonical(step))
            elif kind == "reordered_settlements":
                second = target / "credit/0002.json"
                one, two = first.read_bytes(), second.read_bytes()
                first.write_bytes(two)
                second.write_bytes(one)
            elif kind == "missing_owner_result":
                (target / "owner/task-sidecars/response-0001.json").unlink()
            elif kind == "attempt_budget_conflict":
                result_path = target / "owner/task-sidecars/response-0001.json"
                response = read_json(result_path)
                response["source_read_attempts_this_call"] = 0
                result_path.write_bytes(canonical(response))
                step = read_json(step_path)
                step["response"] = response
                step_path.write_bytes(canonical(step))
            else:
                witness = target / "owner/witness.bin"
                damaged = bytearray(witness.read_bytes())
                damaged[-1] ^= 1
                witness.write_bytes(damaged)
            try:
                restore_credit(target, expected, owner)
            except (ValueError, KeyError, OSError) as error:
                results.append({"fault": kind, "rejected": True, "reason": str(error),
                                "source_data_directory_present": (target / "data").exists()})
            else:
                raise AssertionError("Corrupt recovery was accepted: " + kind)
    return results


def run(input_directory, owner_build, frozen_path, output):
    frozen = read_json(frozen_path)
    verify_freeze(frozen, owner_build)
    input_directory = Path(input_directory).resolve()
    require(str(input_directory) == frozen["input_directory"] and input_files(input_directory) == frozen["input_sha256"],
            "retained credit input changed after recovery freeze")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    owner = InspectionOnlyOwner(owner_build)
    cases = []
    for name, expected in frozen["cases"].items():
        case_directory = input_directory / name
        live, final_response = uninterrupted_reference(case_directory)
        expected_live = export_account(live)
        expected_probes = isolated_probes(live, final_response)
        result = subprocess.run(
            [sys.executable, "-m", "experiments.first_passage_adaptive.credit_recovery", "inspect",
             "--case-directory", str(case_directory), "--case", name,
             "--owner-build", str(Path(owner_build).resolve()), "--freeze", str(Path(frozen_path).resolve())],
            capture_output=True, check=True, timeout=20,
        )
        cold = json.loads(result.stdout)
        require(cold["account"] == expected_live, "cold credit state/price/predecessor/records differs from uninterrupted reference")
        require(cold["task_state"] == expected["final_task_state"] and cold["found"] == expected["found"], "cold task state mismatch")
        require(cold["probes"] == expected_probes, "cold credit next settlement or replay differs from uninterrupted reference")
        record = {"case": name, "expected_uninterrupted_account": expected_live,
                  "expected_isolated_probes": expected_probes, "cold_process": cold,
                  "passed": True, "original_settlements": expected["count"]}
        save_once(output / (name + ".json"), record)
        cases.append({"case": name, "settlements": expected["count"], "state_records_exact": True,
                      "replay_unchanged": True, "hypothetical_next_settlement_exact": True,
                      "owner_anchor": cold["owner_inspection"]["checkpoint_digest"], "native_inspect_source_reads": 0,
                      "native_inspection_calls": cold["native_inspection_calls"],
                      "native_execute_requests": cold["native_execute_requests"]})
    faults = fault_validation(input_directory / "feedback_enabled", frozen["cases"]["feedback_enabled"], owner)
    checks = {
        "three_fresh_processes_reconstruct_exact_state": len(cases) == 3 and all(case["state_records_exact"] for case in cases),
        "seven_original_settlements_reconstructed": sum(case["settlements"] for case in cases) == 7,
        "three_hypothetical_continuations_match_live": all(case["hypothetical_next_settlement_exact"] for case in cases),
        "three_completed_replays_do_not_charge_twice": all(case["replay_unchanged"] for case in cases),
        "seven_faults_rejected": len(faults) == 7 and all(row["rejected"] for row in faults),
        "retained_input_unchanged": input_files(input_directory) == frozen["input_sha256"],
        "source_identity_unchanged": frozen["source_identity"] == current_sources(),
        "no_native_execute_called": owner.execute_attempts == 0 and all(case["native_execute_requests"] == 0 for case in cases),
    }
    summary = {
        "schema": RECOVERY_PROFILE, "freeze_sha256": file_sha(frozen_path), "checks": checks,
        "cases": cases, "fault_injections": faults, "passed": all(checks.values()),
        "native_inspection_calls": owner.inspection_calls + sum(case["native_inspection_calls"] for case in cases),
        "reference": "Original CreditAccount settles retained original responses uninterrupted in memory; cold restoration independently recomputes fields without calling settle.",
        "continuation_scope": "Explicit synthetic accounting message on isolated copies; no terminated task resumes and no new task return is added.",
        "native_boundary": "Only original owner --inspect; final checkpoint and terminal task state must match retained expectations.",
        "durability_scope": "Serial trusted writer and readable completed records; no concurrent transaction or power-loss atomicity guarantee.",
        "production_activation": False,
    }
    save_once(output / "CREDIT_RECOVERY.json", summary)
    require(summary["passed"], "recovery verification failed")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("freeze", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("--input", type=Path, required=True)
        sub.add_argument("--owner-build", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if command == "run":
            sub.add_argument("--freeze", type=Path, required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--case-directory", type=Path, required=True)
    inspect_parser.add_argument("--case", required=True)
    inspect_parser.add_argument("--owner-build", type=Path, required=True)
    inspect_parser.add_argument("--freeze", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.input, args.owner_build, args.output)
        print(json.dumps({"freeze": str(args.output), "sha256": file_sha(args.output)}))
    elif args.command == "inspect":
        frozen = read_json(args.freeze)
        verify_freeze(frozen, args.owner_build)
        result = inspect_in_child(args.case_directory, frozen["cases"][args.case], InspectionOnlyOwner(args.owner_build))
        print(canonical(result).decode())
    else:
        result = run(args.input, args.owner_build, args.freeze, args.output)
        print(json.dumps(result, indent=2))

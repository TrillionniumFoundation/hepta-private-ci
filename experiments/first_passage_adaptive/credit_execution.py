"""Connect selected A1 physics, research resource credit and real native actions.

The dual price is a research adapter state, not an existing Organ Credit API.
It changes decision cost while preserving the selected physical cancellation
rate. Frozen native owner sources and all preceding evidence remain unchanged.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from experiments.first_passage_cell.cell import CellParameters, FirstPassageCell
from experiments.first_passage_cell.kernels import first_passage
from experiments.first_passage_cell.ndu import NativeNduPort, RECURSIVE_PROFILE, SCHEMA, canonical, q32

from .adaptive_study import load_checkpoint
from .native_execution import PROFILE as OWNER_PROFILE, ResearchOwner, ZERO, save_once, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTRACT = {
    "schema": "hepta.fpt-adaptive.resource-credit-contract.v1",
    "base_read_cost": 0.05,
    "answer_reward": 1.0,
    "frozen_relevance_prior": 0.5,
    "event_penalty": 1.0,
    "expected_read_resource": 1.0,
    "resource_unit": "physical-read-attempt",
    "price_initial": 0.0,
    "price_step": 0.8,
    "target_usage_per_decision": 0.25,
    "price_maximum": 2.0,
    "price_update": "clip(pi + eta * (actual_read_attempts - target), 0, pi_max)",
    "decision_cost": "base_read_cost + pi * expected_read_resource",
    "price_role": "resource constraint dual price, distinct from physical cancellation lambda",
    "physical_lambda_role": "independent physical task cancellation rate; never changed by credit",
    "physical_cost_ledger": "base_read_cost times actual attempts; dual charges recorded separately",
    "continuation": "one-read forecast then replan using actual result and settled credit",
    "read_duration": 0.05,
    "initial_distance": 1.0,
    "drift_offset": 0.0,
    "reset_gap": 0.9,
    "refractory": 0.06,
    "deadline": 1.0,
    "read_budget": 4,
    "fixture_seed": 2026102991,
    "fixture_answer_index": 2,
    "fixtures": ["feedback_enabled", "feedback_disabled", "failed_attempt_feedback"],
    "control": "Same model, inputs, files, seed and legal actions; disabled control holds pi at zero.",
    "scope": "mechanistic integration and price intervention; no efficacy or convergence inference",
    "production_activation": False,
}
SOURCE_PATHS = (
    "experiments/first_passage_adaptive/credit_execution.py",
    "experiments/first_passage_adaptive/tests/test_credit_execution.py",
    "experiments/first_passage_adaptive/native_execution.py",
    "experiments/first_passage_adaptive/native_build.py",
    "experiments/first_passage_adaptive/native/owner_bridge.rs",
    "experiments/first_passage_adaptive/native/owner_bridge_tests.rs",
    "experiments/first_passage_adaptive/native/execution_state.rs",
    "experiments/first_passage_adaptive/native/task_journal.rs",
    "experiments/first_passage_adaptive/native/owner-Cargo.lock",
    "experiments/first_passage_adaptive/native/SOURCE_IDENTITY.json",
    "experiments/first_passage_cell/cell.py",
    "experiments/first_passage_cell/kernels.py",
    "experiments/first_passage_cell/ndu.py",
    "experiments/first_passage_cell/native_bridge.rs",
    "experiments/first_passage_cell/NATIVE_BUILD.json",
    "experiments/first_passage_cell/NATIVE_SOURCE_MANIFEST.json",
)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_selected_model(path, expected_sha256=None):
    path = Path(path)
    actual = file_sha(path)
    if expected_sha256 is not None and actual != expected_sha256:
        raise ValueError("Selected A1 checkpoint SHA-256 changed")
    saved = load_checkpoint(path)
    if not saved["training_complete"] or saved["registration_sha256"] != file_sha(path.with_name("registration.json")):
        raise ValueError("Selected training completion or registration binding failed")
    mu, sigma, cancel_rate = map(float, saved["physical_training"]["final"])
    if not all(math.isfinite(x) for x in (mu, sigma, cancel_rate)) or sigma <= 0 or cancel_rate < 0:
        raise ValueError("Invalid selected physical parameters")
    # A1 is an upper barrier for voltage. The existing cell uses positive
    # distance to a lower barrier: d(distance) = -mu dt + sigma dW.
    parameters = CellParameters(
        drift=-(mu + CONTRACT["drift_offset"]), weights=(0.0, 0.0), sigma=sigma,
        barrier=0.0, reset_gap=CONTRACT["reset_gap"], refractory=CONTRACT["refractory"],
    )
    selected = {
        "schema": "hepta.fpt-adaptive.selected-physics.v1",
        "training_checkpoint_sha256": actual,
        "training_registration_sha256": saved["registration_sha256"],
        "training_source_identity": saved["source_identity"],
        "training_parameters": {"upper_mu_bias": mu, "sigma": sigma, "physical_cancel_rate": cancel_rate},
        "mapping": "lower-distance drift = -(trained upper mu bias + declared drift_offset)",
        "drift_offset": CONTRACT["drift_offset"],
        "cell_parameters": asdict(parameters),
        "cell_model_digest": parameters.digest(),
        "cancellation_owner": "research adapter independent clock; not a field in original cell V1",
        "credit_changes_physical_parameters": False,
    }
    return parameters, selected


class CreditAccount:
    """Serial research feedback ledger; replay cannot update the dual twice."""

    def __init__(self, enabled):
        self.enabled = bool(enabled)
        self.price = CONTRACT["price_initial"]
        self.previous = ZERO
        self.records = {}

    def snapshot(self):
        return {"enabled": self.enabled, "dual_price": self.price,
                "previous_feedback_sha256": self.previous, "settled_decisions": len(self.records)}

    def settle(self, response, spent_before):
        key = response["request_digest"]
        if key in self.records:
            old = self.records[key]
            if old["record"]["owner_anchor"] != response["owner"]["checkpoint_after"]:
                raise ValueError("Credit replay owner anchor changed")
            return {"already_applied": True, "sha256": old["sha256"], "current_price": self.price}
        if response.get("replayed"):
            raise ValueError("Cannot infer missing credit settlement from a replay")
        usage = response["source_read_attempts_this_call"]
        if type(usage) is not int or usage not in (0, 1) or response["state"]["read_units_spent"] - spent_before != usage:
            raise ValueError("Actual owner attempt charge and task budget disagree")
        before = self.price
        eta = CONTRACT["price_step"] if self.enabled else 0.0
        self.price = min(CONTRACT["price_maximum"], max(0.0, before + eta * (usage - CONTRACT["target_usage_per_decision"])))
        record = {
            "schema": "hepta.fpt-adaptive.credit-settlement.v1", "previous_sha256": self.previous,
            "owner_request_digest": key, "owner_anchor": response["owner"]["checkpoint_after"],
            "owner_response_sha256": sha(response), "actual_usage": usage,
            "successful_source_reads": response["source_reads_this_call"],
            "answer_observed": bool(response["read"] and response["read"].get("answer")),
            "terminal": response["state"]["terminal"], "price_before": before, "price_after": self.price,
            "eta": eta, "target": CONTRACT["target_usage_per_decision"], "maximum": CONTRACT["price_maximum"],
            "actual_base_cost": CONTRACT["base_read_cost"] * usage,
            "shadow_resource_charge": before * usage,
            "physical_cancel_rate_updated": False,
        }
        receipt = {"already_applied": False, "record": record, "sha256": sha(record)}
        self.records[key] = receipt
        self.previous = receipt["sha256"]
        return receipt


class CreditNdu(NativeNduPort):
    """Use the existing generic native utility interface with an explicit contract."""

    def choose(self, values, snapshot, remaining_budget, objective_digest):
        candidates = []
        for name, row in values.items():
            candidates.append({
                "id": name, "verified": row["feasible"],
                "verification_digest": sha(["credit-research-guards", snapshot, name, row["feasible"]]),
                "support_digest": sha([snapshot, name, row]),
                "resource_cost_q32": q32(row["expected_resource"]), "risk_q32": q32(row["risk"]),
                "uncertainty_q32": 0, "terminal_q32": 0,
                "events": [{"instant_q32": q32(row["utility"]), "discount_q32": q32(1.0),
                            "event_digest": sha(["credit-forecast", snapshot, name]),
                            "preference_digest": objective_digest}],
            })
        request = {
            "schema": SCHEMA, "recursive_profile": RECURSIVE_PROFILE,
            "objective_digest": objective_digest, "snapshot_digest": sha(snapshot), "generation": 1,
            "utility_unit": "task-return", "resource_unit": "task-cost", "risk_unit": "probability",
            "resource_budget_q32": q32(remaining_budget), "risk_ceiling_q32": q32(1.0), "candidates": candidates,
        }
        response = self._invoke(request)
        selected = response["advisory_candidate_id"]
        if selected not in values or not values[selected]["feasible"]:
            raise ValueError("NDU selected an unsupported research action")
        return selected, {"request": request, "response": response,
                          "resource_binding": "native task-cost is one physical read-attempt",
                          "credit_owner": "research adapter, not an existing native Organ Credit API"}


def candidate_values(cell, found, cancelled, remaining, horizon, risk, price):
    in_ref = cell.refractory_remaining > 1e-12
    read_cost = CONTRACT["base_read_cost"] + price * CONTRACT["expected_read_resource"]
    return {
        "read": {"utility": CONTRACT["frozen_relevance_prior"] * CONTRACT["answer_reward"] - read_cost - CONTRACT["event_penalty"] * risk,
                 "decision_cost": read_cost, "expected_resource": CONTRACT["expected_read_resource"], "risk": risk,
                 "feasible": not found and not cancelled and not in_ref and horizon > 0 and remaining > 0},
        "wait": {"utility": 0.1 if in_ref else -0.01, "decision_cost": 0.0, "expected_resource": 0.0, "risk": 0.0,
                 "feasible": not found and not cancelled and horizon > 0},
        "abstain": {"utility": 0.0, "decision_cost": 0.0, "expected_resource": 0.0, "risk": 0.0, "feasible": True},
    }


def source_identity():
    return {"sha256": {name: file_sha(ROOT / name) for name in SOURCE_PATHS},
            "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}}


def freeze(checkpoint, owner_build, destination):
    _, selected = load_selected_model(checkpoint)
    owner = ResearchOwner(owner_build)
    ndu = CreditNdu(HERE.parent / "first_passage_cell/NATIVE_BUILD.json")
    value = {
        "schema": "hepta.fpt-adaptive.credit-source-freeze.v1",
        "created_at": datetime.now(timezone.utc).isoformat(), "execution_started": False,
        "source_identity": source_identity(), "selected_model": selected, "selected_model_sha256": sha(selected),
        "contract": CONTRACT, "owner_build_sha256": file_sha(owner_build),
        "owner_source_digest": owner.build["source_digest"], "owner_binary_sha256": owner.build["binary_sha256"],
        "ndu_binary_sha256": ndu.binary_sha256, "ndu_source_manifest_sha256": ndu.source_manifest_sha256,
        "scope": "pre-execution freeze for a mechanical closed-loop fixture; not a scientific confirmation cohort",
    }
    save_once(Path(destination), value)
    return value


def execute_case(name, enabled, failed_read, parameters, selected, owner, ndu, output):
    directory = output / name
    (directory / "data").mkdir(parents=True, exist_ok=False)
    for index in range(CONTRACT["read_budget"]):
        payload = (f"distractor_{index}=unused\n" + ("needle=verified answer\n" if index == CONTRACT["fixture_answer_index"] else "")).encode()
        if failed_read and index == 0:
            payload = b"\xff"
        (directory / "data" / f"chunk-{index}.txt").write_bytes(payload)
    cell = FirstPassageCell(parameters, CONTRACT["initial_distance"], seed=CONTRACT["fixture_seed"])
    cancel_rate = selected["training_parameters"]["physical_cancel_rate"]
    cancel_time = (float(np.random.default_rng(np.random.SeedSequence([CONTRACT["fixture_seed"], 991])).exponential(1.0 / cancel_rate))
                   if cancel_rate > 0 else math.inf)
    credit = CreditAccount(enabled)
    state = {"clock_us": 0, "refractory_until_us": 0, "refractory_period_us": round(parameters.refractory * 1e6),
             "events": 0, "read_units_spent": 0, "read_units_budget": CONTRACT["read_budget"], "terminal": None}
    predecessor = ZERO
    fpt_predecessor = ZERO
    window = {"end_us": 0, "hit_times_us": []}
    found = False
    rows = []
    objective = sha({"contract": CONTRACT, "selected_model_sha256": sha(selected)})
    for sequence in range(1, 17):
        checkpoint = cell.checkpoint()
        save_once(directory / "fpt" / (checkpoint["sha256"] + ".json"), checkpoint)
        remaining = state["read_units_budget"] - state["read_units_spent"]
        horizon = min(CONTRACT["read_duration"], max(0.0, CONTRACT["deadline"] - cell.time))
        physical = first_passage(max(cell.level, 0.0), parameters.drift, parameters.sigma, horizon)
        risk = min(1.0, max(0.0, 1.0 - math.exp(-cancel_rate * horizon) * float(physical["S"])))
        cancelled = cell.time >= cancel_time
        values = candidate_values(cell, found, cancelled, remaining, horizon, risk, credit.price)
        snapshot = {
            "contract_sha256": sha(CONTRACT), "selected_model": selected, "selected_model_sha256": sha(selected),
            "fpt_checkpoint_sha256": checkpoint["sha256"], "task_state": state, "found": found,
            "cancelled": cancelled, "credit": credit.snapshot(), "risk": risk, "horizon": horizon,
            "physical_cancel_time": cancel_time if math.isfinite(cancel_time) else None,
        }
        chosen, evaluation = ndu.choose(values, snapshot, remaining, objective)
        command = {"kind": "Cancel" if cancelled else {"read": "Read", "wait": "Wait", "abstain": "Stop"}[chosen]}
        if command["kind"] == "Read":
            command.update(relative_path=f"chunk-{state['read_units_spent']}.txt", query="needle")
        feature_values = [min(8.0, max(-8.0, cell.level)), risk, min(8.0, float(cell.event_count)),
                          remaining / max(1, state["read_units_budget"]), horizon]
        request = {
            "schema": OWNER_PROFILE, "subject": "credit." + name, "sequence": sequence,
            "owner_monotonic_us": time.monotonic_ns() // 1000, "checkpoint_digest": predecessor,
            "objective_digest": objective, "ndu_receipt_digest": evaluation["response"]["evaluation_digest"],
            "fpt_checkpoint_digest": checkpoint["sha256"], "fpt_predecessor_digest": fpt_predecessor,
            "fpt_checkpoint_json": canonical(checkpoint["payload"]).decode(),
            "features_q24": [round(value * (1 << 24)) for value in feature_values],
            "state": state, "window": window, "deadline_us": round(CONTRACT["deadline"] * 1e6), "command": command,
        }
        response = owner.invoke(directory, request)
        settlement = credit.settle(response, state["read_units_spent"])
        save_once(directory / "credit" / f"{sequence:04}.json", settlement)
        row = {"snapshot": snapshot, "candidate_values": values, "ndu": evaluation, "request": request,
               "response": response, "credit_settlement": settlement}
        # One explicit price intervention at the same observed successor state.
        # This calls the actual native evaluator but executes no alternative IO.
        if name == "feedback_enabled" and sequence == 2:
            counter_snapshot = dict(snapshot, intervention="hold observed state, set dual price to zero",
                                    credit=dict(snapshot["credit"], dual_price=0.0))
            counter_values = candidate_values(cell, found, cancelled, remaining, horizon, risk, 0.0)
            counter_action, counter_receipt = ndu.choose(counter_values, counter_snapshot, remaining, objective)
            row["price_intervention"] = {"selected": counter_action, "snapshot": counter_snapshot,
                                          "candidate_values": counter_values, "ndu": counter_receipt, "executed": False}
        save_once(directory / "steps" / f"{sequence:04}.json", row)
        rows.append(row)
        state = response["state"]
        found = found or bool(response["read"] and response["read"].get("answer"))
        predecessor = response["owner"]["checkpoint_after"]
        fpt_predecessor = checkpoint["sha256"]
        if state["terminal"] is not None:
            break
        duration = cell.refractory_remaining if command["kind"] == "Wait" else CONTRACT["read_duration"]
        duration = min(duration, max(0.0, CONTRACT["deadline"] - cell.time), max(0.0, cancel_time - cell.time))
        transition = cell.advance(duration, (0.0, 0.0))
        window = {"end_us": round(transition["time"] * 1e6),
                  "hit_times_us": [round(event["time"] * 1e6) for event in transition["events"]]}
    else:
        raise ValueError("Bounded credit fixture did not terminate")
    replay = owner.invoke(directory, rows[-1]["request"])
    before_replay = credit.snapshot()
    replay_credit = credit.settle(replay, rows[-1]["request"]["state"]["read_units_spent"])
    if replay["source_read_attempts_this_call"] != 0 or before_replay != credit.snapshot() or not replay_credit["already_applied"]:
        raise ValueError("Replay changed task execution or credit")
    summary = {
        "case": name, "feedback_enabled": enabled, "actions": [row["request"]["command"]["kind"] for row in rows],
        "actual_attempts": state["read_units_spent"], "successful_reads": sum(row["response"]["source_reads_this_call"] for row in rows),
        "found": found, "terminal": state["terminal"], "prices_before_decision": [row["snapshot"]["credit"]["dual_price"] for row in rows],
        "final_price": credit.price, "actual_base_cost": sum(row["credit_settlement"]["record"]["actual_base_cost"] for row in rows),
        "shadow_resource_charges": sum(row["credit_settlement"]["record"]["shadow_resource_charge"] for row in rows),
        "natural_events": cell.event_count,
        "physical_task_return": float(found) - CONTRACT["base_read_cost"] * state["read_units_spent"] - CONTRACT["event_penalty"] * cell.event_count,
        "selected_physical_parameters": selected["training_parameters"], "cell_model_digest": parameters.digest(),
        "owner_final_anchor": predecessor, "credit_final_sha256": credit.previous,
        "replay_attempts": replay["source_read_attempts_this_call"], "replay_credit_unchanged": True,
    }
    save_once(directory / "EXECUTION.json", {"summary": summary, "rows": rows, "replay": replay, "credit_replay": replay_credit})
    return summary, rows


def run(checkpoint, owner_build, frozen, output):
    frozen_path = Path(frozen)
    frozen = json.loads(frozen_path.read_text())
    if frozen.get("schema") != "hepta.fpt-adaptive.credit-source-freeze.v1" or frozen["execution_started"]:
        raise ValueError("Expected a pre-execution credit source freeze")
    parameters, selected = load_selected_model(checkpoint, frozen["selected_model"]["training_checkpoint_sha256"])
    if (frozen["source_identity"] != source_identity() or frozen["selected_model"] != json.loads(canonical(selected))
            or frozen["contract"] != CONTRACT or frozen["owner_build_sha256"] != file_sha(owner_build)):
        raise ValueError("Credit source, selected physics or owner build changed after freeze")
    owner = ResearchOwner(owner_build)
    ndu = CreditNdu(HERE.parent / "first_passage_cell/NATIVE_BUILD.json")
    if ndu.binary_sha256 != frozen["ndu_binary_sha256"] or ndu.source_manifest_sha256 != frozen["ndu_source_manifest_sha256"]:
        raise ValueError("NDU identity differs from credit freeze")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    save_once(output / "RUN_REGISTRATION.json", {"freeze_sha256": file_sha(frozen_path), "selected_model": selected,
                                               "contract": CONTRACT, "started_at": datetime.now(timezone.utc).isoformat()})
    cases = [execute_case(name, name != "feedback_disabled", name == "failed_attempt_feedback",
                          parameters, selected, owner, ndu, output) for name in CONTRACT["fixtures"]]
    adaptive, control, failed = [case[0] for case in cases]
    adaptive_rows, control_rows, _ = [case[1] for case in cases]
    checks = {
        "trained_physics_loaded": all(case[0]["selected_physical_parameters"] == selected["training_parameters"] for case in cases),
        "lambda_preserved_not_relabelled_price": all(case[0]["selected_physical_parameters"]["physical_cancel_rate"] == selected["training_parameters"]["physical_cancel_rate"] for case in cases),
        "feedback_changes_next_real_action": adaptive["actions"] == ["Read", "Stop"] and control["actions"] == ["Read", "Read", "Read", "Stop"],
        "real_reads_differ": adaptive["actual_attempts"] == 1 and control["actual_attempts"] == 3,
        "same_physical_successor_at_price_intervention": adaptive_rows[1]["request"]["fpt_checkpoint_digest"] == control_rows[1]["request"]["fpt_checkpoint_digest"],
        "same_observed_task_successor_at_price_intervention": adaptive_rows[1]["snapshot"]["task_state"] == control_rows[1]["snapshot"]["task_state"] and not adaptive_rows[1]["snapshot"]["found"] and not control_rows[1]["snapshot"]["found"],
        "price_stop_is_not_a_guard_rejection": adaptive_rows[1]["candidate_values"]["read"]["feasible"] and adaptive_rows[1]["price_intervention"]["selected"] == "read",
        "actual_result_disables_read_after_answer": control["found"] and control_rows[-1]["snapshot"]["found"] and not control_rows[-1]["candidate_values"]["read"]["feasible"],
        "stop_has_zero_attempts": all(row["response"]["source_read_attempts_this_call"] == 0 for _, rows in cases for row in rows if row["request"]["command"]["kind"] == "Stop"),
        "failed_opened_read_is_charged_and_updates_price": failed["actual_attempts"] == 1 and failed["successful_reads"] == 0 and failed["final_price"] > 0 and failed["terminal"] == "ReadFailed",
        "feedback_chain_reaches_next_ndu_snapshot": all(rows[index]["snapshot"]["credit"]["previous_feedback_sha256"] == rows[index-1]["credit_settlement"]["sha256"] for _, rows in cases for index in range(1, len(rows))),
        "replay_does_not_update_credit_or_read": all(case[0]["replay_attempts"] == 0 and case[0]["replay_credit_unchanged"] for case in cases),
        "source_identity_unchanged": frozen["source_identity"] == source_identity(),
    }
    result = {
        "schema": "hepta.fpt-adaptive.credit-execution.v1", "freeze_sha256": file_sha(frozen_path),
        "selected_model": selected, "selected_model_sha256": sha(selected), "checks": checks,
        "cases": [case[0] for case in cases], "native_ndu_calls": ndu.calls,
        "native_owner_ticks": sum(len(case[1]) for case in cases),
        "owner_build_sha256": file_sha(owner_build), "native_owner_build": owner.build,
        "native_ndu_binary_sha256": ndu.binary_sha256,
        "interpretation": "Price feedback causally changes a legal successor action and real attempts in this fixture; no efficacy, optimality or dual convergence claim.",
        "authority_boundary": "Serial trusted research credit sidecar and bounded local IO; no native Organ Credit API or production TaskFlow activation.",
        "passed": all(checks.values()), "production_activation": False,
    }
    save_once(output / "CREDIT_EXECUTION.json", result)
    if not result["passed"]:
        raise AssertionError(checks)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("freeze", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("--checkpoint", type=Path, required=True)
        sub.add_argument("--owner-build", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if command == "run":
            sub.add_argument("--freeze", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        frozen = freeze(args.checkpoint, args.owner_build, args.output)
        print(json.dumps({"freeze": str(args.output), "sha256": file_sha(args.output),
                          "selected_parameters": frozen["selected_model"]["training_parameters"]}, indent=2))
    else:
        result = run(args.checkpoint, args.owner_build, args.freeze, args.output)
        print(json.dumps({"checks": result["checks"], "cases": result["cases"],
                          "native_ndu_calls": result["native_ndu_calls"], "native_owner_ticks": result["native_owner_ticks"]}, indent=2))

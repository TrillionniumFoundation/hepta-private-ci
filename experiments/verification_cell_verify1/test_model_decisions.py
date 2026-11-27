"""Exercise the gate on SQLite fixtures or a read-only retained model run."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from .model_audit import inference_bindings
from .model_decisions import decision_bindings
from .model_policy import Pilot
from .model_protocol import Journal, cases, frozen_plan
from .model_summary import summarize
from .test_model_policy import UnitOnlyScore, dependencies


INPUTS = (
    "plan.json",
    "assessments.jsonl",
    "operations.jsonl",
    "trajectory_rows.jsonl",
    "decisions.jsonl",
)


def read_inputs(directory):
    data, hashes = [], {}
    for name in INPUTS:
        raw = (directory / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        data.append(
            [json.loads(line) for line in raw.splitlines()]
            if name.endswith("jsonl")
            else json.loads(raw)
        )
    return data, hashes


class DecisionBindingsTests(unittest.TestCase):
    run_directory = None

    @classmethod
    def setUpClass(cls):
        if cls.run_directory is None:
            temporary = tempfile.TemporaryDirectory()
            cls.addClassCleanup(temporary.cleanup)
            cls.directory = Path(temporary.name) / "fixture"
            plan = frozen_plan()
            selected = [
                next(c for c in cases("confirmation") if c["fault"] == fault)
                for fault in (
                    "clean",
                    "missing_receipt",
                    "semantic_error",
                    "stale_read",
                )
            ]
            arms = ["single", "fixed_check"] + [
                "intervention/" + s["name"] for s in plan["interventions"]
            ]
            plan["planned_trajectories"] = [
                {"case_id": case["goal"]["task_id"], "arm": arm}
                for case in selected
                for arm in arms
            ]
            journal = Journal(cls.directory, plan)
            pilot = Pilot(journal, dependencies(), UnitOnlyScore(0.3), plan)
            pilot.prior = 0.3
            for case in selected:
                for arm in ("single", "fixed_check"):
                    pilot.trajectory(case, arm)
                for setting in plan["interventions"]:
                    pilot.trajectory(case, "single", setting)
        else:
            cls.directory = cls.run_directory
        cls.original, cls.input_sha256 = read_inputs(cls.directory)

    def data(self):
        return copy.deepcopy(self.original)

    def primary(self, data, step=2):
        full = {(r["case_id"], r["arm"]) for r in data[3] if r["reached_step"] == 3}
        return next(
            d
            for d in data[4]
            if d["arm"] == "single"
            and d["tick"] == step
            and d["selection"] == "check"
            and (d["case_id"], d["arm"]) in full
        )

    def test_original_and_smaller_declared_roster(self):
        self.assertTrue(decision_bindings(*self.original))
        data = self.data()
        chosen = self.primary(data)
        pair = chosen["case_id"], chosen["arm"]
        data[0]["planned_trajectories"] = [{"case_id": pair[0], "arm": pair[1]}]
        data[3] = [r for r in data[3] if (r["case_id"], r["arm"]) == pair]
        data[4] = [d for d in data[4] if (d["case_id"], d["arm"]) == pair]
        data[2] = [
            o
            for o in data[2]
            if o["context"].get("split") != "confirmation"
            or (o["context"].get("case_id"), o["context"].get("arm")) == pair
        ]
        self.assertTrue(decision_bindings(*data))

    def test_risk_cost_and_budget_tampering(self):
        changes = [
            ("policy_risk_input", 0.0),
            ("declared_check_cost", -100),
            ("budget_before", -1),
            ("declared_check_cost", 0.1),
            ("budget_before", 0.5),
            ("policy_risk_input", True),
            ("declared_check_cost", float("nan")),
            ("budget_before", float("inf")),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                data = self.data()
                self.primary(data)[field] = value
                self.assertFalse(decision_bindings(*data))

    def test_budget_is_carried_after_a_check(self):
        data = self.data()
        first = self.primary(data)
        second = next(
            d
            for d in data[4]
            if d["case_id"] == first["case_id"]
            and d["arm"] == first["arm"]
            and d["tick"] == 3
        )
        second["budget_before"] = first["budget_before"]
        self.assertFalse(decision_bindings(*data))
        for field, value in (
            ("optional_budget", 0.5),
            ("optional_cost", 0.3),
            ("error_loss", 0.0),
        ):
            with self.subTest(plan_field=field):
                data = self.data()
                data[0][field] = value
                self.assertFalse(decision_bindings(*data))

    def test_matching_removed_check_cannot_hide_wrong_selection(self):
        data = self.data()
        decision = self.primary(data)
        decision["selection"] = "defer"
        data[2] = [
            o
            for o in data[2]
            if not (
                o["kind"] == "optional_host_check"
                and all(
                    o["context"].get(k) == decision[k]
                    for k in ("case_id", "arm", "tick")
                )
            )
        ]
        self.assertFalse(decision_bindings(*data))

    def test_fixed_check_cannot_move_to_an_earlier_frontier(self):
        data = self.data()
        decision = next(
            d for d in data[4] if d["arm"] == "fixed_check" and d["tick"] == 2
        )
        decision["selection"] = "check"
        operation = copy.deepcopy(
            next(o for o in data[2] if o["kind"] == "optional_host_check")
        )
        operation.update(
            operation_id="unit/forged-early-check",
            context={k: decision[k] for k in ("split", "case_id", "arm", "tick")},
        )
        data[2].append(operation)
        self.assertFalse(decision_bindings(*data))

    def test_intervention_is_bound_to_its_frozen_setting(self):
        for change in ("setting", "input", "budget", "model_arm"):
            with self.subTest(change=change):
                data = self.data()
                d = next(d for d in data[4] if d["arm"] == "intervention/risk_high")
                if change == "setting":
                    d["intervention"]["risk"] = 0.8
                    d["policy_risk_input"] = 0.8
                elif change == "input":
                    d["policy_risk_input"] = d["raw_model_score"]
                elif change == "budget":
                    d["budget_before"] = data[0]["optional_budget"]
                else:
                    next(
                        a for a in data[1] if a["assessment_id"] == d["assessment_id"]
                    )["arm"] = "roles_two"
                self.assertFalse(decision_bindings(*data))

    def test_missing_duplicate_and_extra_decisions(self):
        for change in ("missing", "duplicate", "extra"):
            with self.subTest(change=change):
                data = self.data()
                if change == "missing":
                    data[4].pop()
                else:
                    extra = copy.deepcopy(self.primary(data))
                    if change == "extra":
                        extra["tick"] = 1
                    data[4].append(extra)
                self.assertFalse(decision_bindings(*data))

    def test_declared_frontier_cannot_hide_actual_later_effect(self):
        data = self.data()
        chosen = self.primary(data)
        row = next(
            r
            for r in data[3]
            if r["case_id"] == chosen["case_id"] and r["arm"] == chosen["arm"]
        )
        row.update(reached_step=2, interrupted=True)
        data[4] = [
            d
            for d in data[4]
            if not (
                d["case_id"] == row["case_id"]
                and d["arm"] == row["arm"]
                and d["tick"] == 3
            )
        ]
        self.assertFalse(decision_bindings(*data))

    def test_check_execution_must_match_the_selection(self):
        for change in ("missing", "duplicate", "failed", "unplanned"):
            with self.subTest(change=change):
                data = self.data()
                operation = next(
                    o for o in data[2] if o["kind"] == "optional_host_check"
                )
                if change == "missing":
                    data[2].remove(operation)
                elif change == "duplicate":
                    extra = copy.deepcopy(operation)
                    extra["operation_id"] = "unit/duplicate-check"
                    data[2].append(extra)
                elif change == "failed":
                    operation["status"] = "failed"
                else:
                    operation["context"]["case_id"] = "unplanned"
                self.assertFalse(decision_bindings(*data))

    def test_checker_report_identity_and_contract(self):
        changes = [
            ("subject_sha256", "0" * 64),
            ("checked_step", 99),
            ("state_version", 0),
            ("property", "unrelated"),
            ("assumptions", []),
            ("checker_id", "untrusted"),
            ("checker_version", "999"),
            ("evidence_sha256", "bad"),
            ("verdict", "invalid"),
            ("reason", "invented"),
            ("residual_obligations", ["invented"]),
            ("accepted", True),
            ("production_authority", "GRANTED"),
        ]
        for field, value in changes:
            with self.subTest(field=field):
                data = self.data()
                next(o for o in data[2] if o["kind"] == "optional_host_check")[
                    "result"
                ][field] = value
                self.assertFalse(decision_bindings(*data))
        for kind in ("optional_host_check", "mandatory_host_check"):
            data = self.data()
            next(o for o in data[2] if o["kind"] == kind)["result"] = {}
            self.assertFalse(decision_bindings(*data))
        data = self.data()
        first = next(o for o in data[2] if o["kind"] == "optional_host_check")
        other = next(
            o
            for o in data[2]
            if o["kind"] == "optional_host_check"
            and o["context"]["case_id"] != first["context"]["case_id"]
        )
        first["result"] = copy.deepcopy(other["result"])
        self.assertFalse(decision_bindings(*data))

    def test_deleted_suffix_cannot_fabricate_an_early_interrupt(self):
        for detected in (None, 2, 3):
            with self.subTest(detected=detected):
                data = self.data()
                row = next(
                    r
                    for r in data[3]
                    if r["arm"] == "fixed_check" and r["detected_step"] == 3
                )
                row.update(reached_step=2, interrupted=True, detected_step=detected)

                def removed(record):
                    return (
                        all(record.get(k) == row[k] for k in ("case_id", "arm"))
                        and record.get("tick") == 3
                    )

                data[4] = [d for d in data[4] if not removed(d)]
                data[2] = [
                    o
                    for o in data[2]
                    if not (
                        o["kind"] in ("host_effect", "optional_host_check")
                        and removed(o["context"])
                    )
                ]
                self.assertFalse(decision_bindings(*data))

    def test_reconciliation_and_terminal_retry_are_required(self):
        for field, value in (("effects_replayed", 1), ("resolved", False)):
            data = self.data()
            next(o for o in data[2] if o["kind"] == "host_reconcile_without_replay")[
                "result"
            ][field] = value
            self.assertFalse(decision_bindings(*data))
        data = self.data()
        recovery = next(
            o
            for o in data[2]
            if o["kind"] == "host_reconcile_without_replay"
            and o["context"]["tick"] == 4
        )
        index = data[2].index(recovery)
        del data[2][index + 1]
        self.assertFalse(decision_bindings(*data))

    def test_detected_step_and_host_event_order_are_rebuilt(self):
        data = self.data()
        next(r for r in data[3] if r["detected_step"] is not None)["detected_step"] = 99
        self.assertFalse(decision_bindings(*data))
        data = self.data()
        check_index = next(
            i for i, o in enumerate(data[2]) if o["kind"] == "optional_host_check"
        )
        check = data[2][check_index]
        effect_index = next(
            i
            for i, o in enumerate(data[2])
            if o["kind"] == "host_effect" and o["context"] == check["context"]
        )
        data[2][check_index], data[2][effect_index] = (
            data[2][effect_index],
            data[2][check_index],
        )
        self.assertFalse(decision_bindings(*data))

    def test_malformed_and_incomplete_records_fail_closed(self):
        mutations = [
            lambda d: d[0].update(version="unknown"),
            lambda d: d[0].update(intervention_scope="budget2"),
            lambda d: d[0].update(optional_budget=True),
            lambda d: d[0]["interventions"].append(d[0]["interventions"][0]),
            lambda d: d[3].pop(),
            lambda d: d[3].append(d[3][0]),
            lambda d: d[3][0].update(status="failed"),
            lambda d: d[4][0].update(tick=True),
            lambda d: d[4][0].pop("budget_before"),
            lambda d: d[4][0].update(split="calibration"),
            lambda d: d[4][0].update(assessment_id="absent"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = self.data()
                mutate(data)
                self.assertFalse(decision_bindings(*data))

    def test_summary_uses_the_gate_without_relabeling_historical_source(self):
        report = summarize(self.directory, None, 0, 0)
        self.assertTrue(report["engineering_gates"]["plan_bound_decisions_and_budgets"])
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            for path in self.directory.glob("*.json*"):
                (target / path.name).write_bytes(path.read_bytes())
            data = self.data()
            self.primary(data)["declared_check_cost"] = -100
            (target / "decisions.jsonl").write_text(
                "".join(json.dumps(d) + "\n" for d in data[4])
            )
            self.assertFalse(
                summarize(target, None, 0, 0)["engineering_gates"][
                    "plan_bound_decisions_and_budgets"
                ]
            )
        if self.run_directory is not None:
            self.assertFalse(report["engineering_gates"]["source_unchanged"])
        self.assertEqual(read_inputs(self.directory)[1], self.input_sha256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        parser.error("receipt is create-only")
    DecisionBindingsTests.run_directory = args.run_dir
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DecisionBindingsTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = DecisionBindingsTests.original
    historical = []
    if args.run_dir is not None:
        for field, value in (
            ("policy_risk_input", 0.0),
            ("declared_check_cost", -100),
            ("budget_before", -1),
        ):
            modified = copy.deepcopy(data)
            next(
                d
                for d in modified[4]
                if d["arm"] == "single" and d["selection"] == "check"
            )[field] = value
            historical.append(
                {
                    "field": field,
                    "mutated_value": value,
                    "original_inference_gate": inference_bindings(
                        modified[1], modified[2], modified[3], modified[4]
                    ),
                    "new_decision_gate": decision_bindings(*modified),
                }
            )
    after = read_inputs(args.run_dir)[1] if args.run_dir is not None else None
    receipt = {
        "schema": "hepta.verify1.decision-bindings-replay.v1",
        "mode": "retained_read_only" if args.run_dir else "unit_fixture",
        "optimization": sys.flags.optimize,
        "tests": result.testsRun,
        "successful": result.wasSuccessful(),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "source_commit": None,
        "trajectories": len(data[3]),
        "decisions": len(data[4]),
        "operations": len(data[2]),
        "input_sha256": DecisionBindingsTests.input_sha256,
        "input_sha256_after": after,
        "originals_unchanged": after == DecisionBindingsTests.input_sha256
        if after is not None
        else None,
        "original_gate_mutation_observations": historical,
        "new_model_calls": 0,
        "scope": "decision integrity only; no model, training, host-effect or scientific-benefit rerun",
        "source_sha256": {
            name: hashlib.sha256(
                (Path(__file__).parent / name).read_bytes()
            ).hexdigest()
            for name in (
                "model_decisions.py",
                "model_readbacks.py",
                "model_summary.py",
                "test_model_decisions.py",
            )
        },
    }
    with args.receipt.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    print(json.dumps(receipt, allow_nan=False))
    return (
        0
        if result.wasSuccessful() and receipt["originals_unchanged"] is not False
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

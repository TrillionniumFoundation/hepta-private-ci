"""Synthetic actual-Adam traces and known arithmetic; no planner is called."""

import copy
from itertools import product
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, "/workspace/scratch/60f94d809f44/hepta-repo/qa/stem-bakeoff")
from cell_field_controller_v7 import commit_cursor, initial_snapshot, install_plan, make_contract
from cell_field_development_artifacts_v7 import save_result
from cell_field_state import CellTrainingState
from cell_learning_models import NumpyCellHead
from v7_audit_records import digest, inspect_case, losses, pair_hash
from v7_audit_statistics import recompute


def physical_fixture(count):
    train = (np.zeros((8, 8)), np.tile(np.arange(4), 2))
    panels = [train]*4
    selection = (np.zeros((512, 8)), np.tile(np.arange(4), 128))
    inputs = {"split": {"current_train": train}, "current_panels": panels, "old_panels": panels,
        "selection": {"old": selection, "future": selection}}
    initial = CellTrainingState(NumpyCellHead(8, 4, "linear", seed=7),
        bindings={"protocol_sha256": "0"*64}, contexts={"current_train": pair_hash(train)}, active_context="current_train")
    config = {"steps": 32, "dt": .02, "effort_price": .03, "action_bound": 4., "old_weight": 0.,
        "current_dispersion": 0., "relinearizations": 0}
    anchors = np.full(4, np.log(4.))
    identity = {"controller_protocol_sha256": "a"*64, "controller_source_sha256": "b"*64}
    contract = make_contract(initial, train, panels, panels, anchors, "future_field_h8", config, **identity)
    controller = initial_snapshot(initial, contract)
    states, controllers, actions, receipts, records = [initial.clone()], [copy.deepcopy(controller)], [], [], []
    current = initial.clone()
    for origin in range(0, count, 8):
        block_states, block_receipts, block_actions = [current.clone()], [], np.zeros((8, initial.parameter_count))
        for action in block_actions:
            block_receipts.append(current.advance(*train, intervention=.02*action))
            block_states.append(current.clone())
        verified_record = {"certified": True, "verified_optimizer_steps": 8, "panel_head_evaluations": 36}
        planned_record = {"rounds": []}
        verified = {"state": current, "states": block_states, "actions": block_actions,
            "receipts": block_receipts, "record": verified_record}
        controller = install_plan(controller, block_actions, verified, {"record": planned_record})
        for k, (state, receipt) in enumerate(zip(block_states[1:], block_receipts, strict=True)):
            controller = commit_cursor(controller, state, receipt, origin+k+1)
            controllers.append(copy.deepcopy(controller))
        states.extend(block_states[1:]); receipts.extend(block_receipts); actions.extend(block_actions)
        records.append({"at_step": origin, "committed_steps": 8, "status": "committed_certified",
            "plan": planned_record, "repair": verified_record})
    status = "completed" if count == 32 else "not_executed_tangent_infeasible"
    if count != 32:
        records.append({"at_step": count, "committed_steps": 0, "status": status,
            "plan": {"status": "tangent_infeasible", "rounds": []}})
    controllers[-1]["counters"]["controller_cpu_ns"] = 10000
    controllers[-1]["run_status"] = "completed" if count == 32 else "stopped"
    if count != 32:
        controllers[-1]["failure_ledger"] = [{"origin_absolute_step": 0, "stopped_absolute_step": count,
            "status": status, "paid_cpu_ns": 10000, "paid_wall_ns": 20000,
            "execution_record_sha256": digest(records), "error": None}]
    result = {"state": current, "states": states, "controllers": controllers,
        "actions": np.asarray(actions).reshape(-1, initial.parameter_count), "receipts": receipts,
        "record": {"policy": "future_field_h8", "status": status, "error": None,
            "initial_state_sha256": initial.digest(), "terminal_state_sha256": current.digest(),
            "completed_steps": count, "newly_committed_steps": count, "origin_absolute_step": 0,
            "registered_steps": 32, "parameter_action_penalty": 0., "cpu_ns": 10000, "wall_ns": 20000,
            "steps": records}}
    return initial, inputs, anchors, config, identity, result


class PostrunAuditTests(unittest.TestCase):
    def test_all_controller_cuts_and_stored_suffixes_restore_without_planning(self):
        for count in (0, 16, 32):
            initial, inputs, anchors, config, identity, result = physical_fixture(count)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/"case"
                save_result(path, {"fit_id": "fixture"}, initial, inputs, anchors, "future_field_h8", config,
                    result, {"cpu_ns": 30000, "wall_ns": 40000}, losses(initial, inputs["selection"]["old"]),
                    controller_identity=identity)
                checked = inspect_case(path, initial, inputs, config, "future_field_h8", "a"*64, "b"*64,
                    native_directory=Path(directory)/"native", keep_vectors=True)
                self.assertTrue(checked["available"])
                self.assertEqual(checked["actual_errors"], [])
                self.assertEqual([r["step"] for r in checked["registered_checkpoint_rows"]], [k for k in (0, 16, 17, 32) if k <= count])
                self.assertEqual(checked["state_vectors"].shape[0], count+1)
                self.assertTrue(all(r["restore_checked"] for r in checked["registered_checkpoint_rows"]))

    def test_statistics_selects_plausible_subset_and_keeps_stopped_baseline(self):
        plan = {"versions": ["v5", "v6"], "tasks": ["agnews", "dbpedia"], "head_modes": ["linear", "gated"],
            "seeds": [7, 17, 29], "primary_policies": ["myopic_h1", "loss2_h8", "future_field_h8"],
            "configurations": [{"configuration": {"index": i}} for i in range(12)]}
        cases = {}
        for index, version, task, head, seed, policy in product(range(12), plan["versions"], plan["tasks"],
                plan["head_modes"], plan["seeds"], plan["primary_policies"]):
            cases[index, version, task, head, seed, policy] = {"available": True, "actual_errors": [],
                "header": {"status": "completed", "completed_steps": 32, "audit_passed": True, "error": None,
                    "selection_sources_sha256": version+task, "cpu_ns": 100},
                "future_losses": np.full(512, .49 if policy == "future_field_h8" else .5),
                "old_differences": np.full(512, -.03 if index == 5 else -.001)}
        summaries, selected, _ = recompute(plan, cases)
        self.assertEqual(selected["selected_index"], 5)
        self.assertEqual(len(summaries), 12)
        self.assertTrue(selected["confirmation_plausibility_passed"])
        cases[5, "v5", "agnews", "linear", 7, "loss2_h8"]["header"].update(status="not_executed_tangent_infeasible", completed_steps=0)
        summaries, selected, _ = recompute(plan, cases)
        self.assertFalse(summaries[5]["eligible"])
        self.assertFalse(selected["confirmation_plausibility_passed"])
        self.assertEqual(selected["selected_scope"], "diagnostic_only")


if __name__ == "__main__":
    unittest.main()

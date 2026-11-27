"""Audit the real Adam engine and complete controller snapshots, not mock states."""

import copy
import unittest

import numpy as np

from cell_field_controller_v7 import commit_cursor, digest_json, initial_snapshot, install_plan, make_contract
from cell_field_development_audit_v7 import audit_policy, replay_actions
from cell_field_development_selection_v7 import configurations
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


def example(count=2):
    x, y = np.zeros((8, 8)), np.tile(np.arange(4), 2)
    train, panels = (x, y), [(x, y)]*4
    state = CellTrainingState(NumpyCellHead(8, 4, "linear", seed=7),
        bindings={"protocol_sha256": "a"*64}, contexts={"current_train": dataset_digest(x, y)},
        active_context="current_train")
    config = configurations()[0]["configuration"]
    anchors = np.full(4, np.log(4.))
    contract = make_contract(state, train, panels, panels, anchors, "myopic_h1", config)
    controller = initial_snapshot(state, contract)
    states, controllers, receipts, actions = [state.clone()], [copy.deepcopy(controller)], [], []
    current = state.clone()
    for step in range(count):
        before, action = current.clone(), np.zeros(state.parameter_count)
        receipt = current.advance(x, y, intervention=.02*action)
        verified = {"state": current.clone(), "actions": action[None, :], "states": [before, current.clone()], "receipts": [receipt],
            "record": {"certified": True, "verified_optimizer_steps": 1, "panel_head_evaluations": 4}}
        controller = install_plan(controller, action[None, :], verified, {"record": {"rounds": []}})
        controller = commit_cursor(controller, current, receipt, step+1)
        states.append(current.clone()); controllers.append(copy.deepcopy(controller))
        actions.append(action); receipts.append(receipt)
    result = {"state": current, "states": states, "controllers": controllers, "actions": np.asarray(actions),
        "receipts": receipts, "record": {"status": "completed" if count == 32 else "not_executed_rejected", "policy": "myopic_h1",
            "completed_steps": count, "newly_committed_steps": count, "origin_absolute_step": 0, "registered_steps": 32,
            "initial_state_sha256": state.digest(), "terminal_state_sha256": current.digest(),
            "parameter_action_penalty": 0., "steps": [], "error": None, "cpu_ns": 100, "wall_ns": 100}}
    terminal = result["controllers"][-1]
    terminal["run_status"] = "completed" if count == 32 else "stopped"
    terminal["counters"]["controller_cpu_ns"] = 100
    if count != 32:
        terminal["failure_ledger"] = [{"origin_absolute_step": 0, "stopped_absolute_step": count,
            "status": "not_executed_rejected", "paid_cpu_ns": 100, "paid_wall_ns": 100,
            "execution_record_sha256": digest_json([]), "error": None}]
    return state, train, panels, anchors, config, result


class DevelopmentAuditTests(unittest.TestCase):
    def test_deliberate_stop_retains_exact_trace_and_is_integrity_valid(self):
        state, train, panels, anchors, config, result = example()
        audit = audit_policy(state, train, panels, panels, anchors, "myopic_h1", config, result)
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["exact_replayed_steps"], 2)
        restored = replay_actions(state, train, result["actions"], .02, result["receipts"], audit["state_sha256"])
        self.assertEqual([s.digest() for s in restored], [s.digest() for s in result["states"]])

    def test_nested_actual_error_is_preserved_and_fails_integrity(self):
        state, train, panels, anchors, config, result = example()
        result["record"]["steps"] = [{"repair": {"step_records": [{"error": {"type": "ArithmeticError"}}]}}]
        result["controllers"][-1]["failure_ledger"][0]["execution_record_sha256"] = digest_json(result["record"]["steps"])
        audit = audit_policy(state, train, panels, panels, anchors, "myopic_h1", config, result)
        self.assertFalse(audit["passed"])
        self.assertEqual(audit["actual_errors"], [{"type": "ArithmeticError"}])

    def test_action_receipt_controller_or_anchor_tampering_is_rejected(self):
        mutations = [lambda r: r["actions"].__setitem__((0, 0), .1),
            lambda r: r["receipts"][0].update(state_sha256="0"*64),
            lambda r: r["controllers"][1]["receipt_chain"].update(sha256="0"*64)]
        for mutate in mutations:
            state, train, panels, anchors, config, result = example()
            mutate(result)
            with self.assertRaises(ValueError):
                audit_policy(state, train, panels, panels, anchors, "myopic_h1", config, result)
        state, train, panels, anchors, config, result = example()
        with self.assertRaisesRegex(ValueError, "threshold"):
            audit_policy(state, train, panels, panels, anchors+.01, "myopic_h1", config, result)


if __name__ == "__main__":
    unittest.main()

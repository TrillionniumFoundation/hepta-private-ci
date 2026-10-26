"""Admitted controller identities and atomic complete-checkpoint boundaries."""

import copy
import hashlib
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_controller_v7 import digest_json, initial_snapshot, load_snapshot, make_contract
from cell_field_policy_v7 import execute_policy, resume_policy
from cell_field_repair_v7 import repair_sequence
from cell_learning_models import canonical
from test_cell_field_policy_v7 import fixture


class ControllerBoundaryTests(unittest.TestCase):
    def test_new_controller_identity_preserves_historical_optimizer_origin_and_empty_plan(self):
        state, train, panels, anchors, config = fixture()
        config.update(steps=8, relinearizations=0)
        contract = make_contract(state, train, panels, panels, anchors, "myopic_h1", config,
            controller_protocol_sha256="b"*64, controller_source_sha256="c"*64)
        self.assertEqual(contract["protocol_sha256"], "b"*64)
        self.assertEqual(contract["controller_source_sha256"], "c"*64)
        self.assertEqual(contract["optimizer_origin_protocol_sha256"], "a"*64)
        initial = initial_snapshot(state, contract)
        raw = canonical(initial)
        self.assertEqual(load_snapshot(raw, state, contract,
            expected_sha256=hashlib.sha256(raw).hexdigest()), initial)
        result = resume_policy(state, raw, contract, train, panels, panels,
            expected_controller_sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["record"]["status"], "completed", result["record"])
        replay = state.clone()
        for index, action in enumerate(result["actions"]):
            self.assertEqual(replay.advance(*train, intervention=.02*action), result["receipts"][index])
            snapshot = result["controllers"][index+1]
            self.assertEqual((snapshot["plan_horizon"], snapshot["action_cursor"]), (1, 1))
            self.assertEqual(snapshot["contract"], contract)
            self.assertEqual(load_snapshot(canonical(snapshot), replay, contract), snapshot)
        self.assertEqual(result["state"].digest(), replay.digest())
        final = result["controllers"][-1]
        terminal = resume_policy(replay, canonical(final), contract, train, panels, panels)
        self.assertEqual(terminal["record"]["newly_committed_steps"], 0)
        self.assertEqual(terminal["actions"].shape, (0, state.parameter_count))
        self.assertEqual(terminal["state"].digest(), replay.digest())

    def test_self_consistent_initial_replacement_cannot_change_admitted_warmup(self):
        state, train, panels, anchors, config = fixture()
        contract = make_contract(state, train, panels, panels, anchors, "future_field_h8", config)
        snapshot = initial_snapshot(state, contract)
        changed = state.clone()
        vector = changed.vector()
        vector[0] += .001
        changed.set_vector(vector)
        snapshot.update(full_state_sha256=changed.digest(), plan_origin_state_sha256=changed.digest(),
            plan_state_sha256=[changed.digest()])
        with self.assertRaises(ValueError):
            load_snapshot(canonical(snapshot), changed, contract)

    def test_admitted_bytes_and_complete_state_reject_identity_rng_and_counter_tampering(self):
        state, train, panels, anchors, config = fixture()
        config.update(steps=8, relinearizations=0)
        result = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
        self.assertEqual(result["record"]["status"], "completed", result["record"])
        snapshot, current = result["controllers"][1], result["states"][1]
        raw, contract = canonical(snapshot), snapshot["contract"]
        checksum = hashlib.sha256(raw).hexdigest()
        changed = copy.deepcopy(snapshot)
        changed["counters"]["controller_cpu_ns"] += 1
        with self.assertRaisesRegex(ValueError, "byte commitment"):
            load_snapshot(canonical(changed), current, contract, expected_sha256=checksum)
        for change in ("theta", "momentum", "variance", "rng", "clock", "external_batch"):
            with self.subTest(change=change):
                other = current.clone()
                if change in ("theta", "momentum", "variance"):
                    vector = other.vector()
                    vector[{"theta": 0, "momentum": 1, "variance": 2}[change]*other.parameter_count] += 1e-6
                    other.set_vector(vector)
                elif change == "rng":
                    other.rng.random()
                elif change == "clock":
                    other.step_count += 1
                else:
                    other.external_batch_count += 1
                with self.assertRaises(ValueError):
                    load_snapshot(raw, other, contract)
        for field, replacement in (("protocol_sha256", "d"*64), ("controller_source_sha256", "e"*64)):
            changed = copy.deepcopy(snapshot)
            changed["contract"][field] = replacement
            with self.assertRaisesRegex(ValueError, "contract changed"):
                load_snapshot(canonical(changed), current, contract)

    def test_corrupt_final_checkpoint_action_or_census_cannot_partially_commit_block(self):
        for corruption in ("final_state", "resolved_action", "census"):
            with self.subTest(corruption=corruption):
                state, train, panels, anchors, config = fixture()
                config.update(steps=8, relinearizations=0)
                before = state.digest()

                def corrupt(*args, **kwargs):
                    result = repair_sequence(*args, **kwargs)
                    self.assertTrue(result["record"]["certified"], result["record"])
                    if corruption == "final_state":
                        result["states"][-1].rng.random()
                    elif corruption == "resolved_action":
                        value = result["actions"][-1, 0]
                        result["actions"][-1, 0] = value*.5 if value else 1e-9
                    else:
                        result["states"].pop()
                        result["receipts"].pop()
                    return result

                with patch("cell_field_policy_v7.repair_sequence", side_effect=corrupt):
                    result = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
                self.assertNotEqual(result["record"]["status"], "completed")
                self.assertEqual(result["record"]["newly_committed_steps"], 0)
                self.assertEqual(result["actions"].shape, (0, state.parameter_count))
                self.assertEqual((len(result["states"]), len(result["controllers"]), result["receipts"]), (1, 1, []))
                self.assertEqual((state.digest(), result["state"].digest()), (before, before))

    def test_unavailable_plan_persists_paid_stop_receipt_and_cannot_be_retried(self):
        state, train, panels, anchors, config = fixture()
        unavailable = {"record": {"status": "unresolved", "rounds": []}, "actions": None}
        with patch("cell_field_policy_v7.make_plan", return_value=unavailable):
            result = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
        snapshot, record = result["controllers"][-1], result["record"]
        self.assertEqual(record["newly_committed_steps"], 0)
        self.assertEqual(snapshot["run_status"], "stopped")
        self.assertEqual(len(snapshot["failure_ledger"]), 1)
        failure = snapshot["failure_ledger"][0]
        self.assertEqual(failure["execution_record_sha256"], digest_json(record["steps"]))
        self.assertEqual((failure["paid_cpu_ns"], failure["paid_wall_ns"]),
            (record["cpu_ns"], record["wall_ns"]))
        self.assertGreater(failure["paid_cpu_ns"], 0)
        self.assertEqual(snapshot["counters"]["controller_cpu_ns"], record["cpu_ns"])
        self.assertEqual(snapshot["counters"]["plans"], 0)
        self.assertEqual(result["state"].digest(), state.digest())
        with self.assertRaisesRegex(ValueError, "stopped controller"):
            resume_policy(result["state"], canonical(snapshot), snapshot["contract"],
                train, panels, panels)


if __name__ == "__main__":
    unittest.main()

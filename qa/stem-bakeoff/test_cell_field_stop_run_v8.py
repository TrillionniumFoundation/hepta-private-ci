"""Real finite optimizer/query observation and fail-closed paired-slot census."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_filter_audit_v8 import audit_filter, audit_observer, old_losses
from cell_field_filter_observer_v8 import CallObserver
from cell_field_repair_v7 import repair_sequence
from cell_field_state import CellTrainingState, dataset_digest
from cell_field_stop_run_v8 import FILTERS, run_origin
from cell_learning_models import NumpyCellHead, normalize_features


def fixture():
    rng = np.random.default_rng(1987)
    train = rng.normal(size=(32, 4)), np.arange(32) % 4
    panels = [(rng.normal(size=(8, 4)), np.arange(8) % 4) for _ in range(4)]
    state = CellTrainingState(NumpyCellHead(4, 4, "gated", seed=7),
        bindings={"fixture": "transparent-queries", "protocol_sha256": "a"*64},
        contexts={"current_train": dataset_digest(*train)}, active_context="current_train")
    state.advance(*train)
    return state, train, panels


class StopRunnerTests(unittest.TestCase):
    def test_transparent_return_values_and_global_methods_restore_after_exception(self):
        state, train, panels = fixture()
        original_loss, original_advance = NumpyCellHead.loss_gradients, CellTrainingState.advance
        x, y = normalize_features(panels[0][0]), panels[0][1]
        expected = state.head.loss_gradients(x, y, 0.)
        expected_state = state.clone(); expected_receipt = expected_state.advance(*train)
        observer = CallObserver(state, train, panels)
        with self.assertRaisesRegex(RuntimeError, "injected outer"):
            with observer:
                actual = state.head.loss_gradients(x, y, 0.)
                self.assertEqual(actual[0], expected[0])
                for name in expected[1]:
                    np.testing.assert_array_equal(actual[1][name], expected[1][name])
                self.assertEqual(state.clone().advance(*train), expected_receipt)
                raise RuntimeError("injected outer")
        self.assertIs(NumpyCellHead.loss_gradients, original_loss)
        self.assertIs(CellTrainingState.advance, original_advance)
        audit = audit_observer(observer)
        self.assertEqual((audit["old_value_gradient_queries_replayed"], audit["actual_optimizer_transitions_replayed"]), (1, 1))
        observer.queries[0]["gradient_sha256"] = "f"*64
        with self.assertRaisesRegex(ValueError, "gradient independently"):
            audit_observer(observer)

    def test_accepted_real_sequence_and_moment_tampering_are_independently_checked(self):
        state, train, panels = fixture()
        anchors = old_losses(state, panels)+1.
        intended = np.zeros((8, state.parameter_count))
        observer = CallObserver(state, train, panels)
        with observer:
            result = repair_sequence(state, train, panels, intended, anchors, horizon=8)
        audit, vectors = audit_filter(state, train, panels, intended, anchors, result, observer,
            horizon=8, dt=.02, action_bound=4., effort_price=.03)
        self.assertEqual(audit["accepted_steps"], 8)
        self.assertEqual(vectors.shape, (9, 3*state.parameter_count))
        self.assertEqual(audit["query_and_transition_replay"]["old_value_gradient_queries_replayed"], 36)
        changed = copy.deepcopy(result)
        changed["states"][-1].m[state.names[0]].flat[0] += .001
        with self.assertRaisesRegex(ValueError, "accepted state"):
            audit_filter(state, train, panels, intended, anchors, changed, observer,
                horizon=8, dt=.02, action_bound=4., effort_price=.03)
        failed = copy.deepcopy(result)
        failed["record"].update(status="rejected", certified=False, certified_optimizer_steps=0)
        with self.assertRaisesRegex(ValueError, "atomic complete"):
            audit_filter(state, train, panels, intended, anchors, failed, observer,
                horizon=8, dt=.02, action_bound=4., effort_price=.03)

    def test_failed_proposal_preserves_both_registered_filters_and_measured_cost(self):
        state, train, panels = fixture()
        row = {"slot": "config00/v5-task-seed7-gated/myopic_h1", "fit_id": "v5-task-seed7-gated",
            "version": "v5", "task": "task", "head": "gated", "seed": 7, "policy": "myopic_h1",
            "configuration_index": 0, "configuration": {"dt": .02, "effort_price": .03, "action_bound": 4.,
                "old_weight": 0., "current_dispersion": 0., "relinearizations": 2},
            "committed_steps": 16, "original_method": "full", "attempted_horizon": 1,
            "status": "not_executed_unresolved", "origin_state_sha256": state.digest(),
            "original_old_anchors": old_losses(state, panels).tolist(), "training_sha256": dataset_digest(*train),
            "current_panel_sha256": [dataset_digest(*p) for p in panels], "old_panel_sha256": [dataset_digest(*p) for p in panels]}
        data = {"train": train, "current": panels, "old": panels}
        def failed(*args, **kwargs):
            raise RuntimeError("injected proposal failure")
        with tempfile.TemporaryDirectory() as tmp, patch("cell_field_stop_run_v8.load_origin", return_value=state):
            result = run_origin(row, Path(tmp), Path(tmp), {("v5", "task"): data}, Path(tmp), 1,
                failed, {name: self.fail for name in FILTERS})
            self.assertEqual(result["attempted_horizon"], 1)
            self.assertEqual(result["effective_relinearizations"], 0)
            self.assertEqual(result["original_relinearizations"], 2)
            self.assertEqual(set(result["filters"]), set(FILTERS))
            self.assertTrue(all(r["status"] == "unavailable_input_or_proposal" and not r["qualified_safe_witness"]
                for r in result["filters"].values()))
            self.assertGreater(result["proposal"]["call"]["cpu_ns"], 0)
            self.assertEqual(result["proposal"]["call"]["error"]["message"], "injected proposal failure")


if __name__ == "__main__":
    unittest.main()

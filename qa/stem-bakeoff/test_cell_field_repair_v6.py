"""Real Adam sequence repair, exact replay, stationary hold and atomic rejection."""

import unittest

import numpy as np

from cell_field_repair_v6 import repair_sequence
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


def fixture(conflict=False, stochastic=False, mode="linear"):
    x = np.array([[1.,0.],[-1.,0.],[0.,1.],[0.,-1.]])
    y = np.array([0,1,0,1])
    current = 1-y if conflict else y
    state = CellTrainingState(NumpyCellHead(2,2,mode,seed=7),seed=17,
        bindings={"fixture":"repair-full-optimizer","mode":mode},
        protocol={"sampler":"iid_with_replacement" if stochastic else "full_batch","batch_size":4},
        contexts={"old_train":dataset_digest(x,y),"current_train":dataset_digest(x,current)},active_context="old_train")
    for _ in range(32):
        state.advance(x,y)
    state.select_context("current_train")
    old = float(state.head.loss_gradients(normalize_features(x),y,0.)[0])
    return state,{"current_train":(x,current),"old_probe":(x,y)},old


class SequenceRepairTests(unittest.TestCase):
    def assert_replay(self,state,data,result,anchor,dt=.02):
        replay = state.clone()
        self.assertTrue(result["record"]["certified"],result["record"])
        for k,u in enumerate(result["arrays"]["actions"]):
            self.assertEqual(replay.advance(*data["current_train"],intervention=dt*u),result["receipts"][k])
            np.testing.assert_array_equal(replay.vector(),result["arrays"]["states"][k+1])
            loss = replay.head.loss_gradients(normalize_features(data["old_probe"][0]),data["old_probe"][1],0.)[0]
            self.assertEqual(loss,result["arrays"]["old_losses"][k+1])
            self.assertLessEqual(loss,anchor)
        self.assertEqual(replay.digest(),result["state"].digest())
        self.assertEqual(result["record"]["committed_optimizer_steps"],0)
        self.assertTrue(all(len(s["trials"]) <= 16 for s in result["record"]["step_records"]))

    def test_safe_both_head_sequences_preserve_full_state_rng_and_commit_checkpoint(self):
        for mode in ("linear","gated"):
            state,data,anchor = fixture(stochastic=True,mode=mode)
            origin = state.digest()
            actions = np.zeros((8,state.parameter_count))
            result = repair_sequence(state,data,actions,anchor,commit_steps=4)
            self.assert_replay(state,data,result,anchor)
            self.assertEqual(result["record"]["repaired_steps"],0)
            self.assertEqual(result["record"]["verified_optimizer_steps"],8)
            self.assertEqual(result["record"]["probe_head_evaluations"],9)
            prefix = state.clone()
            for _ in range(4):
                prefix.advance(*data["current_train"])
            self.assertEqual(prefix.digest(),result["commit_state"].digest())
            self.assertEqual(state.digest(),origin)

    def test_unsafe_intended_step_is_repaired_by_exact_old_gradient_search(self):
        state,data,anchor = fixture(stochastic=True)
        origin = state.digest()
        _,g = state.head.loss_gradients(normalize_features(data["old_probe"][0]),data["old_probe"][1],0.)
        direction = np.concatenate([g[n].ravel() for n in state.names])
        action = 10*direction/np.linalg.norm(direction)
        result = repair_sequence(state,data,action,anchor,action_bound=40.)
        self.assert_replay(state,data,result,anchor)
        self.assertGreater(result["record"]["repaired_steps"],0)
        self.assertEqual(result["record"]["step_records"][0]["accepted_kind"],"gradient_line")
        self.assertFalse(result["record"]["step_records"][0]["trials"][0]["within_threshold"])
        self.assertTrue(np.all(np.abs(result["arrays"]["actions"]) <= 40/np.sqrt(state.parameter_count)))
        self.assertGreater(result["record"]["verified_optimizer_steps"],8)
        self.assertEqual(state.digest(),origin)

    def test_true_gated_stationary_point_uses_bounded_parameter_hold(self):
        # Each class has zero feature mean: at all-zero theta the actual gated
        # probe gradient is exactly zero, although a nonzero gated head is better.
        x = np.array([[1.,0.],[-1.,0.],[0.,1.],[0.,-1.]])
        y = np.array([0,0,1,1])
        head = NumpyCellHead(2,2,"gated",seed=7)
        head.params["W"] = np.array([[1.,-1.],[-1.,1.]])
        head.params["a"][:] = 1.
        state = CellTrainingState(head,bindings={"fixture":"nonlinear-stationary-hold"},
            contexts={"current_train":dataset_digest(x,y)},active_context="current_train")
        state.advance(x,y)
        anchor = float(state.head.loss_gradients(normalize_features(x),y,0.)[0])
        base = state.clone()
        base.advance(x,y)
        action = -base.parameter_vector()  # dt=1 makes exact zero parameters.
        data = {"current_train":(x,y),"old_probe":(x,y)}
        result = repair_sequence(state,data,action,anchor,horizon=1,dt=1.,action_bound=50.,commit_steps=1)
        self.assert_replay(state,data,result,anchor,dt=1.)
        step = result["record"]["step_records"][0]
        self.assertEqual(step["accepted_kind"],"parameter_hold")
        self.assertTrue(step["parameter_hold_within_box"])
        self.assertEqual([r["kind"] for r in step["trials"]],["intended","parameter_hold","selected_replay"])
        np.testing.assert_array_equal(result["state"].parameter_vector(),state.parameter_vector())
        self.assertNotEqual(result["state"].digest(),state.digest())

    def test_failure_after_safe_prefix_rejects_whole_block_without_zero_drift(self):
        state,data,anchor = fixture(conflict=True)
        origin = state.digest()
        result = repair_sequence(state,data,np.zeros(state.parameter_count),anchor,action_bound=1e-12)
        record = result["record"]
        self.assertEqual(record["status"],"rejected")
        self.assertFalse(record["certified"])
        self.assertGreater(record["prospective_safe_steps"],0)
        self.assertLess(record["prospective_safe_steps"],8)
        self.assertIn("global feasibility unknown",record["step_records"][-1]["reason"])
        self.assertFalse(record["step_records"][-1]["parameter_hold_within_box"])
        self.assertEqual(result["arrays"]["actions"].shape,(0,state.parameter_count))
        self.assertEqual(result["receipts"],[])
        self.assertEqual(result["arrays"]["states"].shape,(1,3*state.parameter_count))
        self.assertEqual((state.digest(),result["state"].digest(),result["commit_state"].digest()),(origin,origin,origin))

    def test_no_tolerance_or_reanchoring_and_unavailable_plans_remain_unavailable(self):
        state,data,_ = fixture()
        next_state = state.clone()
        next_state.advance(*data["current_train"])
        anchor = float(next_state.head.loss_gradients(normalize_features(data["old_probe"][0]),data["old_probe"][1],0.)[0])
        zero = np.zeros(state.parameter_count)
        equal = repair_sequence(state,data,zero,anchor,horizon=1,commit_steps=1,action_bound=1e-300)
        below = repair_sequence(state,data,zero,float(np.nextafter(anchor,-np.inf)),horizon=1,commit_steps=1,action_bound=1e-300)
        self.assertTrue(equal["record"]["certified"])
        self.assertFalse(below["record"]["certified"])
        self.assertEqual(below["record"]["old_anchor"],float(np.nextafter(anchor,-np.inf)))
        for status in ("unresolved","tangent_infeasible"):
            result = repair_sequence(state,data,None,anchor,candidate_status=status)
            self.assertEqual(result["record"]["status"],"not_executed_"+status)
            self.assertEqual(result["record"]["step_records"],[])
            self.assertEqual(result["state"].digest(),state.digest())

    def test_context_withheld_roles_and_original_action_box_are_enforced(self):
        state,data,anchor = fixture()
        for changed in ({**data,"old_test":data["old_probe"]},
                        {**data,"current_train":(data["current_train"][0],1-data["current_train"][1])}):
            with self.assertRaises(ValueError):
                repair_sequence(state,changed,np.zeros(state.parameter_count),anchor)
        with self.assertRaises(ValueError):
            repair_sequence(state,data,np.ones(state.parameter_count),anchor,action_bound=.1)


if __name__ == "__main__":
    unittest.main()

"""Actual controlled Adam rollouts, nonlinear finite differences and Mealy parity."""

import unittest

import numpy as np

from cell_field_response_v7 import build_response,loss2_terminal_maps,loss2_impulse_maps
from cell_learning_models import normalize_features
from test_cell_field_response_v5 import example


def controlled_example(mode,clip=5.):
    state,train,_=example(mode,clip)
    rng=np.random.default_rng(4301)
    panels=tuple((rng.normal(size=(24,8)),np.arange(24)%4) for _ in range(8))
    nominal=rng.uniform(-.25,.25,size=(8,state.parameter_count))
    return state,train,panels,nominal


def observed(head,panels):
    return np.asarray([head.loss_gradients(normalize_features(x),y,0.)[0] for x,y in panels])


class ControlledResponseTests(unittest.TestCase):
    def test_reference_includes_every_nominal_action_and_preserves_complete_origin(self):
        for mode in ("linear","gated"):
            state,train,panels,nominal=controlled_example(mode)
            before=state.digest()
            response=build_response(state,train,panels,nominal_actions=nominal)
            actual=state.clone()
            for k in range(9):
                np.testing.assert_array_equal(response.states[k],actual.vector())
                np.testing.assert_array_equal(response.observations[k],observed(actual.head,panels))
                if k<8:
                    actual.advance(*train,intervention=.02*nominal[k])
            self.assertEqual(state.digest(),before)
            self.assertGreater(np.max(np.abs(response.states-build_response(state,train,panels).states)),.001)
            original=nominal.copy();nominal[:]=0
            np.testing.assert_array_equal(response.nominal_actions,original)

    def test_controlled_h8_maps_match_actual_nonlinear_central_and_half_step_differences(self):
        for mode in ("linear","gated"):
            for clip in (5.,.001):
                state,train,panels,nominal=controlled_example(mode,clip)
                response=build_response(state,train,panels,nominal_actions=nominal)
                directions=np.random.default_rng(87).normal(size=nominal.shape)
                for impulse in (False,True):
                    delta=directions.copy()
                    if impulse:
                        delta[1:]=0
                    expected=np.einsum("kqp,kp->q",response.terminal_sequence_maps(),delta)
                    for epsilon in (1e-4,5e-5):
                        outcomes=[]
                        for sign in (1,-1):
                            actual,rows=state.clone(),[]
                            for k in range(8):
                                actual.advance(*train,intervention=.02*(nominal[k]+sign*epsilon*delta[k]))
                                rows.append(observed(actual.head,panels))
                            outcomes.append(np.asarray(rows))
                        finite=(outcomes[0]-outcomes[1])/(2*epsilon)
                        np.testing.assert_allclose(expected,finite[-1],rtol=3e-5,atol=3e-9)
                        if impulse:
                            np.testing.assert_allclose(response.impulse_maps()[1:]@delta[0],finite,rtol=3e-5,atol=3e-9)

    def test_loss2_mealy_matches_explicit_two_state_rollout_and_keeps_direct_outputs(self):
        for mode in ("linear","gated"):
            state,train,panels,nominal=controlled_example(mode)
            response=build_response(state,train,panels,nominal_actions=nominal)
            p=state.parameter_count
            delta=np.random.default_rng(151).normal(size=nominal.shape)
            retained=np.zeros(2)
            for k in range(8):
                average=response.gradients[k].reshape(2,4,p).mean(axis=1)
                observation=np.hstack((average,np.zeros((2,2*p))))
                restored=np.linalg.lstsq(observation,retained,rcond=1e-10)[0]
                advanced=response.transitions[k].jvp(restored)
                advanced[:p]+=.02*delta[k]
                outputs=response.gradients[k+1]@advanced[:p]
                retained=outputs.reshape(2,4).mean(axis=1)
            reduced=loss2_terminal_maps(response)
            np.testing.assert_allclose(np.einsum("kqp,kp->q",reduced,delta),outputs,rtol=2e-11,atol=2e-13)
            np.testing.assert_array_equal(reduced[-1],response.terminal_sequence_maps()[-1])
            np.testing.assert_array_equal(loss2_impulse_maps(response)[1],response.impulse_maps()[1])
            self.assertGreater(np.linalg.norm(reduced[:-1]-response.terminal_sequence_maps()[:-1]),1e-8)
            one=build_response(state,train,panels,horizon=1,nominal_actions=nominal[:1])
            np.testing.assert_array_equal(loss2_terminal_maps(one),one.terminal_sequence_maps())

    def test_changed_context_nonfinite_nominal_or_wrong_panel_census_fails(self):
        state,train,panels,nominal=controlled_example("linear")
        with self.assertRaisesRegex(ValueError,"context"):
            build_response(state,(train[0]+.01,train[1]),panels)
        with self.assertRaisesRegex(ValueError,"eight ordered"):
            build_response(state,train,panels[:-1])
        nominal[1,2]=np.nan
        with self.assertRaisesRegex(ValueError,"nominal"):
            build_response(state,train,panels,nominal_actions=nominal)


if __name__=="__main__":
    unittest.main()

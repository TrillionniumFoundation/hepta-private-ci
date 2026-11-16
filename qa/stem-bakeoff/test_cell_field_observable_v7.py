"""Future-panel quotient versus complete-state and actual nonlinear dynamics."""

import unittest

import numpy as np

from cell_field_observable_v7 import from_response
from cell_field_response_v7 import build_response
from test_cell_field_response_v7 import controlled_example,observed


class PanelFieldTests(unittest.TestCase):
    def test_arbitrary_hidden_state_and_time_varying_inputs_match_full_tangent(self):
        for mode in ("linear","gated"):
            state,train,panels,nominal=controlled_example(mode)
            response=build_response(state,train,panels,nominal_actions=nominal)
            field=from_response(response)
            p=state.parameter_count
            rng=np.random.default_rng(19)
            for _ in range(6):
                initial=rng.normal(size=3*p)*np.repeat([.01,.001,1e-8],p)
                actions=rng.normal(size=(8,p))
                full=initial.copy();outputs=[response.gradients[0]@full[:p]]
                retained=[field.observations[0]@full]
                for k,action in enumerate(actions):
                    full=response.transitions[k].jvp(full)
                    full[:p]+=.02*action
                    outputs.append(response.gradients[k+1]@full[:p])
                    retained.append(field.observations[k+1]@full)
                forecast=field.forecast(actions,initial)
                np.testing.assert_allclose(forecast["losses"],outputs,rtol=2e-11,atol=2e-13)
                for predicted,expected in zip(forecast["fields"],retained):
                    np.testing.assert_allclose(predicted,expected,rtol=2e-11,atol=2e-13)
            np.testing.assert_allclose(field.terminal_maps(),response.terminal_sequence_maps(),rtol=2e-12,atol=2e-14)
            np.testing.assert_array_equal(field.arrays()["field_dimensions"],np.arange(72,7,-8))

    def test_field_derivative_matches_nonlinear_full_origin_and_action_perturbation(self):
        for mode in ("linear","gated"):
            state,train,panels,nominal=controlled_example(mode)
            response=build_response(state,train,panels,nominal_actions=nominal)
            field=from_response(response);p=state.parameter_count
            rng=np.random.default_rng(219)
            scales=np.r_[np.full(p,.01),np.maximum(np.abs(state.vector()[p:2*p]),1e-8),state.vector()[2*p:]]
            initial=rng.normal(size=3*p)*scales*.1
            actions=rng.normal(size=(8,p))*.2
            epsilon=1e-4;outcomes=[]
            for sign in (1,-1):
                actual=state.clone();actual.set_vector(state.vector()+sign*epsilon*initial)
                values=[observed(actual.head,panels)]
                for k in range(8):
                    actual.advance(*train,intervention=.02*(nominal[k]+sign*epsilon*actions[k]))
                    values.append(observed(actual.head,panels))
                outcomes.append(np.asarray(values))
            finite=(outcomes[0]-outcomes[1])/(2*epsilon)
            np.testing.assert_allclose(field.forecast(actions,initial)["losses"],finite,rtol=3e-5,atol=3e-9)

    def test_zero_action_deviation_does_not_repeat_the_nonzero_nominal_plan(self):
        state,train,panels,nominal=controlled_example("gated")
        response=build_response(state,train,panels,nominal_actions=nominal)
        field=from_response(response)
        np.testing.assert_array_equal(field.forecast(np.zeros_like(nominal))["losses"],np.zeros((9,8)))
        self.assertGreater(np.linalg.norm(field.forecast(nominal)["losses"]),1e-5)
        with self.assertRaisesRegex(ValueError,"deviations"):
            field.forecast(nominal[0])


if __name__=="__main__":
    unittest.main()

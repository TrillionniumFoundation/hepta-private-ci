"""Test the quotient identity against full-state dynamics, not its own formula."""

import unittest

import numpy as np

from cell_field_observable_v6 import from_response
from cell_field_response_v5 import build_response
from test_cell_field_response_v5 import example


class ObservableTests(unittest.TestCase):
    def test_arbitrary_initial_state_and_all_actions_match_full_state(self):
        for mode in ("linear","gated"):
            state,train,probes = example(mode)
            response = build_response(state,train,probes)
            field = from_response(response)
            p=state.parameter_count
            rng=np.random.default_rng(409)
            for _ in range(12):
                initial=rng.normal(size=3*p)*np.repeat([.01,.001,1e-6],p)
                actions=rng.normal(size=(8,p))
                full=initial.copy()
                expected=[response.gradients[0]@full[:p]]
                for k,action in enumerate(actions):
                    full=response.transitions[k].jvp(full)
                    full[:p]+=.02*action
                    expected.append(response.gradients[k+1]@full[:p])
                actual=field.forecast(actions,initial)
                np.testing.assert_allclose(actual["losses"],expected,rtol=2e-11,atol=2e-13)
                self.assertEqual([len(x) for x in actual["fields"]],list(range(18,1,-2)))

    def test_terminal_action_rows_equal_separate_full_adjoint(self):
        for mode in ("linear","gated"):
            state,train,probes=example(mode)
            response=build_response(state,train,probes)
            field=from_response(response)
            np.testing.assert_allclose(field.terminal_maps(),response.terminal_sequence_maps(),rtol=1e-12,atol=1e-14)
            arrays=field.arrays()
            self.assertEqual(arrays["field_observations"].shape,(9,18,3*state.parameter_count))
            np.testing.assert_array_equal(arrays["field_dimensions"],np.arange(18,1,-2))

    def test_new_quotient_has_no_loss_projection_pseudoinverse(self):
        state,train,probes=example("gated")
        response=build_response(state,train,probes)
        field=from_response(response)
        for k in range(8):
            p=state.parameter_count
            rng=np.random.default_rng(k)
            directions=rng.normal(size=(3*p,3))
            transported=field.observations[k+1]@response.transitions[k].jvp(directions)
            np.testing.assert_allclose(transported,field.observations[k][2:]@directions,rtol=1e-11,atol=1e-12)


if __name__=="__main__":
    unittest.main()

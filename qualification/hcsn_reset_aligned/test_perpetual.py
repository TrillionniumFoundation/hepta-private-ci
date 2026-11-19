"""Physical perpetual-value derivatives and differentiated dynamic identities."""

from fractions import Fraction
import json
import math
import unittest

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_reset_aligned.perpetual import perpetual_partials
from qualification.hcsn_reset_aligned.mesh import aligned_model
from qualification.hcsn_reset_aligned.sensitivities import PARAMETERS, solve_aligned_partials


GEOMETRY = dict(left_intervals=4, right_intervals=4, endpoint=2., grading=1., delay=.2)
OPTIONS = dict(rtol=2e-11, atol=2e-13, max_step=.02)


class SharedPerpetual(unittest.TestCase):
    records = []

    @classmethod
    def tearDownClass(cls):
        print("PERPETUAL_PARTIALS_EVIDENCE", json.dumps(cls.records, sort_keys=True))

    def test_same_generator_implicit_partials_match_forward_closure(self):
        theta = np.array([.01, -.12, .5, math.exp(.51), .15])
        values, jacobian = perpetual_partials(theta, GEOMETRY)
        model = aligned_model(theta, **GEOMETRY)[0]
        nodes, reset = model.perpetual()
        np.testing.assert_allclose(values, np.r_[nodes[1:], reset], rtol=0, atol=2e-13)
        rows = []
        for j, name in enumerate(PARAMETERS):
            errors = []
            for step in (2e-5, 1e-5):
                delta = np.zeros(5)
                delta[j] = step
                high_model = aligned_model(theta+delta, **GEOMETRY)[0]
                low_model = aligned_model(theta-delta, **GEOMETRY)[0]
                high, hr = high_model.perpetual()
                low, lr = low_model.perpetual()
                fd = (np.r_[high[1:], hr]-np.r_[low[1:], lr])/(2*step)
                np.testing.assert_allclose(jacobian[:, j], fd, rtol=5e-6, atol=5e-7)
                errors.append(float(max(abs(jacobian[:, j]-fd))))
            rows.append(dict(parameter=name, errors=errors))
        self.records.append(dict(case="implicit_closure", rows=rows))

    def test_differentiated_dynamic_identity_includes_age_and_history(self):
        theta = np.array([.01, -.12, .5, math.exp(.51), .15])
        values, jacobian = perpetual_partials(theta, GEOMETRY)
        model, generator_derivatives = aligned_model(theta, **GEOMETRY)
        active = np.zeros(9)
        active[1] = .4
        content = np.column_stack((2*active, -3*active))
        phase = (Packet("phase", Fraction(1,20), Fraction(3,20), Fraction(3,5), (Fraction(6,5), Fraction(-9,5))),)
        rows = solve_aligned_partials(model, generator_derivatives, [0., .1, .4, .6],
                                     active, content, phase, **OPTIONS)["rows"]
        closures, gradients = [], []
        for row in rows:
            time, primal = row["time"], row["primal"]
            state = np.vstack((primal["active"], primal["upper"], primal["discounted_remaining_phase"]))
            future = values@state
            discount = math.exp(-model.discount*time)
            closure = model.active_reward*primal["discounted_active_time"]+model.hit_reward*primal["discounted_events"]+discount*future
            current = []
            for j, name in enumerate(PARAMETERS):
                partial = row["partials"][name]
                ds = np.vstack((partial["active"], partial["upper"], partial["discounted_remaining_phase"]))
                dc = jacobian[:, j]@state+values@ds
                current.append(model.active_reward*partial["discounted_active_time"]+
                    model.hit_reward*partial["discounted_events"]+discount*(dc-(time*future if j==4 else 0)))
            closures.append(closure)
            gradients.append(np.stack(current))
        primal_error = float(np.max(abs(np.asarray(closures)-closures[0])))
        gradient_error = float(np.max(abs(np.asarray(gradients)-gradients[0])))
        self.assertLess(primal_error, 4e-8)
        self.assertLess(gradient_error, 8e-8)
        self.records.append(dict(case="differentiated_dynamic_identity", query_times=[0., .1, .4, .6],
                                 primal_error=primal_error, gradient_error=gradient_error))


if __name__ == "__main__":
    unittest.main()

"""Pure hand acceptance/negative controls for one prospective attribute head."""

import unittest

import numpy as np

from content_theory.attributes import attribute_gradient, attribute_law, joint_logits, project_main_effects
from content_theory.categorical import ALPHA, logit_geometry, softmax


class AttributeChecks(unittest.TestCase):
    def setUp(self):
        self.z = np.array([.2, -.3, .7, -.4, .1, .6, -.2])

    def test_class_CE_is_sum_not_average_of_attribute_CEs(self):
        s = attribute_law(self.z)
        np.testing.assert_allclose(s, softmax(joint_logits(self.z)), atol=1e-15)
        for color in range(3):
            for shape in range(2):
                for position in range(2):
                    code = (color * 2 + shape) * 2 + position
                    terms = (-np.log(softmax(self.z[:3])[color])
                             - np.log(softmax(self.z[3:5])[shape])
                             - np.log(softmax(self.z[5:7])[position]))
                    self.assertAlmostEqual(-ALPHA * np.log(s[code]), ALPHA * terms, places=14)

    def test_fixed_projection_preserves_additive_logits(self):
        projected = project_main_effects(joint_logits(self.z))
        np.testing.assert_allclose(attribute_law(projected), attribute_law(self.z), atol=1e-15)
        # The projection is linear, so it can be applied to every weight row.
        values = np.stack((joint_logits(self.z), joint_logits(self.z[::-1])))
        np.testing.assert_allclose(project_main_effects(values.sum(0)),
                                   project_main_effects(values).sum(0), atol=1e-15)

    def test_original_A_N_class_utility_chain_gradients(self):
        r = np.full((12, 12), .1)
        np.fill_diagonal(r, 1.)
        eta = np.eye(12)[9]
        for arm in ("A", "N"):
            _, joint_gradient, _ = logit_geometry(joint_logits(self.z), eta, r, arm)
            analytic = attribute_gradient(joint_gradient)
            for index in range(7):
                d = np.eye(7)[index] * 1e-5
                plus = logit_geometry(joint_logits(self.z + d), eta, r, arm)[0]
                minus = logit_geometry(joint_logits(self.z - d), eta, r, arm)[0]
                self.assertAlmostEqual((plus - minus) / 2e-5, analytic[index], places=9)

    def test_correlated_attribute_uncertainty_is_a_negative_control(self):
        # Hand true labels0 or11 only, each half. Product of their attribute
        # marginals puts mass on six unsupported cross-combinations as well.
        color, shape, position = np.array([.5, 0., .5]), np.array([.5, .5]), np.array([.5, .5])
        product = (color[:, None, None] * shape[None, :, None] * position[None, None, :]).reshape(12)
        self.assertAlmostEqual(float(product[[0, 11]].sum()), .25)
        self.assertAlmostEqual(float(.5 * product[0] + .5 * product[11]), .125)
        self.assertLess(.125, .5)  # unrestricted two-label law has joint success.5


if __name__ == "__main__":
    unittest.main(verbosity=2)

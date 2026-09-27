"""A driver cannot rewrite the input it is supposed to have scored."""
import unittest

from scripts.hepta_laya_retrieval import Rejected, score
from scripts.tests.test_hepta_laya_retrieval import Port, request


class InputBindingTests(unittest.TestCase):
    def test_model_side_input_mutation_is_not_a_valid_receipt(self):
        class MutatingPort(Port):
            def predict(self, state, questions):
                result = super().predict(state, questions)
                questions["source"]["criteria"]["c1"] = "unbound replacement evidence"
                return result
        port = MutatingPort()
        with self.assertRaisesRegex(Rejected, "mutated"):
            score(request(), port, now_ms=lambda: 1000, current=lambda _: True)
        self.assertEqual(len(port.calls), 1)


if __name__ == "__main__":
    unittest.main()

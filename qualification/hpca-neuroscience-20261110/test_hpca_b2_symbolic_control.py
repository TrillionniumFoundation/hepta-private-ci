"""Independent tiny arithmetic-rule control; adverse and archive tests."""
import copy
import unittest
from pathlib import Path
from hpca_b2_symbolic_control import decide, evaluate, read_exact, run, MANIFEST_SHA, RESULT_SHA

HERE = Path(__file__).resolve().parent

class RuleControlTests(unittest.TestCase):
    def test_five_families_positive_and_negative(self):
        pairs = [
            ("Is 46 an even integer?", "yes"), ("Is 47 an even integer?", "no"),
            ("Is 6 strictly greater than 5?", "yes"), ("Is 5 strictly greater than 5?", "no"),
            ("Is the integer 42 divisible by 7 with no remainder?", "yes"),
            ("Is the integer 42 divisible by 8 with no remainder?", "no"),
            ("Does the number 9 occur in the set {4, 9, 13}?", "yes"),
            ("Does the number 9 occur in the set {4, 10, 13}?", "no"),
            ("Is 43 a prime integer?", "yes"), ("Is 49 a prime integer?", "no"),
        ]
        for tail, expected in pairs:
            self.assertEqual(decide("Answer yes or no. " + tail)[1], expected)

    def test_adversarial_inputs_rejected(self):
        for prompt in [
            "Answer yes or no. Is 3 an even integer? yes",
            "Answer yes or no. Is 5 greater than 4?",
            "Is 5 a prime integer?",
            "Answer yes or no. Is the integer 12 divisible by 0 with no remainder?",
            "Answer yes or no. Does the number 2 occur in the set {1,2}?",
        ]:
            with self.assertRaises(ValueError):
                decide(prompt)

    def test_full_original_observed_control(self):
        result = run(HERE)
        self.assertEqual((result["rule_correct"], result["rule_decisions"]), (540, 540))
        self.assertEqual((result["original_model_correct"], result["original_model_decisions"]), (270, 540))
        self.assertTrue(all(v == 1 for v in result["rule_family_accuracy"].values()))

    def test_corruption_rejected(self):
        orig = read_exact(HERE / "POSTTRAIN_B2_MANIFEST.json", MANIFEST_SHA)
        res = read_exact(HERE / "POSTTRAIN_B2_RESULT.json", RESULT_SHA)
        bad = copy.deepcopy(orig)
        bad["tasks"][0]["truth"] = "no"
        with self.assertRaisesRegex(ValueError, "arithmetical truth"):
            evaluate(bad, res, repeats=1)
        bad = copy.deepcopy(res)
        bad["runs"][0]["scores"]["rows"][0]["prediction"] = "yes"
        with self.assertRaisesRegex(ValueError, "model output"):
            evaluate(orig, bad, repeats=1)
        bad = copy.deepcopy(orig)
        bad["tasks"][0]["prompt"] = "Answer yes or no. Is 3 a banana?"
        with self.assertRaises(ValueError):
            evaluate(bad, res, repeats=1)
        with self.assertRaises(ValueError):
            evaluate(orig, res, repeats=0)

if __name__ == "__main__":
    unittest.main()

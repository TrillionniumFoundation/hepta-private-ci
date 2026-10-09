import unittest

from factorial_receipt import ABSTAIN, conditional, decode


class FactorialReceiptTests(unittest.TestCase):
    def test_answerability_and_failures_keep_their_own_denominators(self):
        rows = [
            dict(
                status="succeeded",
                f1=0.5,
                target_unanswerable=False,
                answer="Kyoto [E1]",
            ),
            dict(status="succeeded", f1=1.0, target_unanswerable=True, answer=ABSTAIN),
            dict(status="failed", f1=None),
        ]
        result = conditional(rows)
        self.assertEqual(result["attempted"], 3)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["answerable_f1"], 0.5)
        self.assertEqual(result["unanswerable_f1"], 1.0)
        self.assertEqual(result["diagnostic_f1"], 0.75)
        self.assertEqual(result["emitted_citations"], 1)
        self.assertEqual(result["exact_protocol_abstentions"], 1)
        self.assertIsNone(conditional([])["diagnostic_f1"])

    def test_bad_or_duplicate_numeric_records_reject(self):
        for raw in ('{"x":NaN}', '{"x":1,"x":2}'):
            with self.assertRaises(ValueError):
                decode(raw)
        with self.assertRaises(ValueError):
            conditional([dict(status="succeeded", f1=True, answer="x")])


if __name__ == "__main__":
    unittest.main()

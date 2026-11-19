"""Original question options are inputs; the correct option is held-out annotation."""

import copy
import unittest

from composition_evidence import make_case
from test_composition_evidence import row


class CompositionOptionsTests(unittest.TestCase):
    def test_preserve_every_original_option_without_selecting_correct_one(self):
        source = row()
        case, _ = make_case(source, [], "2026-01-01T00:00:00Z", "capability")
        text = case["question"]["content"]
        self.assertTrue(text.startswith(source["question"]["stem"]))
        for option in source["question"]["choices"]:
            self.assertEqual(text.count(f"({option['label']}) {option['text']}"), 1)
        for answer in "ABCDEFGH":
            changed = copy.deepcopy(source)
            changed["answerKey"] = answer
            other, _ = make_case(changed, [], "2026-01-01T00:00:00Z", "capability")
            self.assertEqual(case, other)
        self.assertNotIn("answerKey", text)
        self.assertNotIn(source["combinedfact"], text)


if __name__ == "__main__":
    unittest.main()

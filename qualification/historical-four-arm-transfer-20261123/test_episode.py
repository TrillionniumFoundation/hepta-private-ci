import unittest
from episode import outputs, panel, passes


class EpisodeTests(unittest.TestCase):
    def test_equivalent_grammar(self):
        self.assertEqual(outputs("for x in range(3, 10, 3):\n print(x)"), [3, 6, 9])
        self.assertEqual(
            outputs("for x in range(1, 10):\n if x%3==0:\n  print(x)"), [3, 6, 9]
        )

    def test_incorrect_valid_script_cannot_win(self):
        case = dict(divisor=2, bound=10)
        self.assertFalse(passes(1, "for x in range(3, 10, 3):\n print(x)", case))

    def test_outside_language_rejected(self):
        for s in (
            "print(0)",
            "for x in range(400):\n print(x)",
            "for x in range(1,4):\n print(1)",
        ):
            self.assertIsNone(outputs(s))

    def test_panel_separates_wording_and_changed_answer(self):
        cases = panel(735, "historical")
        self.assertEqual(len({c["query"] for c in cases}), 19)
        self.assertEqual(sum(c["divisor"] == 7 for c in cases), 7)
        changed = [c for c in cases if c["group"] == "changed"]
        self.assertEqual(len({(c["divisor"], c["bound"]) for c in changed}), 12)

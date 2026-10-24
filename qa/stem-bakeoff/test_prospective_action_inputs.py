import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from operational_cohort_plan import canonical, digest
from operational_source_regions import ACTION_PREFIX
from prospective_action_inputs import frozen_actions, freeze_inputs, predictor, sha_file


def example():
    view = {"text": "TEST SOURCE tests/test_value.py\ndef test_value():\n    assert value(2) == 3\n",
            "source_files": {"tests/test_value.py": {"sha256": "a" * 64, "bytes": 73}}}
    command = {"id": "primary-0", "runner": "pytest", "args": ["-q", "tests/test_value.py::test_value"],
               "view": view, "comparators": []}
    return {"bug": {"project": "scrapy", "group_id": "bugsinpy/scrapy/1", "bug_id": 1,
                    "revisions": {"base": "b" * 40, "candidate": "c" * 40}},
            "implementation": {"production_paths": ["value.py"],
                               "diff": "--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-return x\n+return x + 1\n"},
            "commands": [command]}


class ProspectiveActionInputTests(unittest.TestCase):
    def test_exact_spans_preserve_marker_like_source_and_unicode(self):
        case = example()
        case["commands"][0]["view"]["text"] += "MESSAGE = 'ACTION\\nCOMMAND café'\n"
        action = frozen_actions(case)[0]
        row, unavailable = predictor(case, action, "d" * 64)
        self.assertIsNone(unavailable)
        c, a = row["input_regions"]["change"], row["input_regions"]["action"]
        self.assertEqual(row["text"][slice(*c)], case["implementation"]["diff"])
        self.assertEqual(row["text"][slice(*a)], action["view"]["text"])
        self.assertEqual(row["text"][:c[0]], ACTION_PREFIX)
        self.assertEqual(row["text_utf8_sha256"], digest(row["text"].encode()))

    def test_dedup_and_role_metadata_cannot_change_predictor(self):
        case = example()
        duplicate = copy.deepcopy(case["commands"][0])
        duplicate["id"] = "control-pretend"
        case["commands"][0]["comparators"].append(duplicate)
        self.assertEqual(len(frozen_actions(case)), 1)
        original, _ = predictor(case, frozen_actions(case)[0], "d" * 64)
        case["commands"][0]["id"] = "selected_after_outcome"
        case["observed_result"] = {"secret_label": 1}
        amended, _ = predictor(case, frozen_actions(case)[0], "d" * 64)
        self.assertEqual(original, amended)

    def test_conflicting_duplicate_source_rejected(self):
        case = example()
        duplicate = copy.deepcopy(case["commands"][0])
        duplicate["view"]["text"] = "different supplied program"
        case["commands"][0]["comparators"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            frozen_actions(case)

    def test_unavailable_input_stays_in_proposal_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = example()
            missing = copy.deepcopy(case["commands"][0])
            missing.update(id="other", args=["-q", "tests/test_value.py::missing"], view=None)
            case["commands"].append(missing)
            path = root / "case.json"
            path.write_bytes(canonical(case))
            protocol = root / "protocol.md"
            protocol.write_text("frozen example")
            result = freeze_inputs([path], root / "out", protocol)
            self.assertEqual((result["proposed_groups"], result["proposed_unique_actions"],
                              result["source_available_rows"]), (1, 2, 1))
            self.assertEqual(result["case_source_sha256"], {case["bug"]["group_id"]: sha_file(path)})

    def test_source_change_during_build_cannot_receive_a_seal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, protocol = root / "case.json", root / "protocol.md"
            path.write_bytes(canonical(example()))
            protocol.write_text("frozen example")
            def mutating_predictor(*args, **kwargs):
                result = predictor(*args, **kwargs)
                path.write_bytes(path.read_bytes() + b"\n")
                return result
            with patch("prospective_action_inputs.predictor", side_effect=mutating_predictor):
                with self.assertRaisesRegex(ValueError, "changed while"):
                    freeze_inputs([path], root / "out", protocol)
            self.assertFalse((root / "out" / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()

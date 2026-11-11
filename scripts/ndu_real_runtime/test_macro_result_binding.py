"""Manufactured original-host score/result drift regressions; not policy evidence."""

import json
from pathlib import Path
import tempfile
import unittest

from .metacontrol_macro_contract import observe_branch
from .test_macro_wire_delivery_admission import case


class HostResultBindingTests(unittest.TestCase):
    def test_persisted_result_drift_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            actions = ["WRITE_TEXT", "STOP"]
            config, directory, result = case(Path(tmp), actions)
            stored = json.loads((directory / "result.json").read_text())
            stored["gross_score"] = 0.25
            (directory / "result.json").write_text(json.dumps(stored))
            with self.assertRaises(ValueError):
                observe_branch(directory, result, actions, 0.2, 0.01, config)

    def test_reported_score_components_must_match_scored_snapshot(self):
        for field, forged in (
            ("delivery_sha256", "0" * 64),
            ("rubric_sha256", "0" * 64),
            ("quality", 0.25),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                actions = ["WRITE_TEXT", "STOP"]
                config, directory, result = case(Path(tmp), actions)
                result["score_components"][field] = forged
                (directory / "result.json").write_text(json.dumps(result))
                with self.assertRaises(ValueError):
                    observe_branch(directory, result, actions, 0.2, 0.01, config)

    def test_reported_output_and_rubric_must_match_delivery(self):
        for field in ("output_text_sha256", "rubric_sha256"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                actions = ["WRITE_TEXT", "STOP"]
                config, directory, result = case(Path(tmp), actions)
                result[field] = "0" * 64
                (directory / "result.json").write_text(json.dumps(result))
                with self.assertRaises(ValueError):
                    observe_branch(directory, result, actions, 0.2, 0.01, config)

    def test_missing_original_host_result_fields_fail_closed(self):
        for missing in ("score_components", "rubric_sha256", "output_text_sha256"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                actions = ["WRITE_TEXT", "STOP"]
                config, directory, result = case(Path(tmp), actions)
                del result[missing]
                (directory / "result.json").write_text(json.dumps(result))
                with self.assertRaises(ValueError):
                    observe_branch(directory, result, actions, 0.2, 0.01, config)


if __name__ == "__main__":
    unittest.main()


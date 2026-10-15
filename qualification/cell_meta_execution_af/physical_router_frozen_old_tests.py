"""Old-only frozen-parent research; physical Torch and Torch-free adversarial replay."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qualification.cell_meta_execution_af import physical_router_audit as original_audit
from qualification.cell_meta_execution_af import physical_router_frozen_old as producer
from qualification.cell_meta_execution_af import physical_router_frozen_old_audit as auditor
from qualification.cell_meta_execution_af import physical_router_trial as trial


class FrozenOldParentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel = trial.synthetic_panel(seed=41, rule="conditional", rows=32)
        cls.frozen = producer.run(cls.panel, steps=4)

    def test_real_old_only_frozen_tensor_replays_independently(self) -> None:
        output = auditor.validate(self.panel, self.frozen)
        self.assertEqual(output["outcome"], "FROZEN_OLD_PARENT_REPLAY_ONLY")
        self.assertFalse(output["ndu_selection_authorized"])
        self.assertFalse(output["existing_v1_no_change_is_frozen"])
        self.assertEqual(self.frozen["meters"]["optimizer_steps"], 4)
        self.assertEqual(self.frozen["meters"]["sample_exposures"], 4 * 32)
        self.assertEqual(self.frozen["trained_new_rows"], 0)
        self.assertFalse(self.frozen["total_compute_matched"])

    def test_training_requests_labels_from_old_train_only(self) -> None:
        original = trial.vectors
        calls: list[tuple[str, bool]] = []

        def observed(panel: dict, name: str, *, include_labels: bool = True):
            calls.append((name, include_labels))
            if name != "old_train" and include_labels:
                raise AssertionError("future labels used before frozen prediction seal")
            return original(panel, name, include_labels=include_labels)

        with patch.object(trial, "vectors", side_effect=observed):
            got = producer.run(self.panel, steps=2)
        self.assertEqual(got["trained_new_rows"], 0)
        self.assertEqual([x for x in calls if x[1]], [("old_train", True)])

    def test_old_frozen_is_not_the_unfrozen_v1_no_change_control(self) -> None:
        existing = trial.run(self.panel, steps=4)
        check = auditor.validate(self.panel, self.frozen, continued=existing)
        self.assertIn("descriptive_accuracy_delta_continued_minus_frozen", check)
        self.assertGreater(existing["results"][0]["meters"]["optimizer_steps"],
                           self.frozen["meters"]["optimizer_steps"])
        self.assertNotEqual(existing["results"][0]["weights_sha256"],
                            self.frozen["weights_sha256"])
        self.assertEqual(original_audit.validate(self.panel, existing)["outcome"],
                         "NUMERIC_REPLAY_ONLY")

    def test_claimed_real_evidence_and_selection_are_rejected(self) -> None:
        for field, fake in (
            ("ndu_selection_authorized", True),
            ("real_pretrained_encoder_executed", True),
            ("independent_outcome_verified", True),
            ("future_window_prospective", True),
            ("total_compute_matched", True),
            ("production_admission", "ACCEPTED"),
            ("trained_new_rows", 1),
            ("split_proposed", True),
            ("freeze_point", "after_new_train"),
        ):
            with self.subTest(field=field):
                modified = copy.deepcopy(self.frozen)
                modified[field] = fake
                with self.assertRaises(original_audit.AuditError):
                    auditor.validate(self.panel, modified)

    def test_tampered_weights_predictions_metrics_and_counts_reject(self) -> None:
        for modifier in (
            lambda x: x["weights_fp32"]["heads"].update({"data_le_hex": "00" * 40}),
            lambda x: x["predictions"]["future_1"][0].update({"probability": 0.99}),
            lambda x: x["evaluation"]["future_2"].update({"accuracy": 1.0}),
            lambda x: x["meters"].update({"head_forward_rows": 0}),
            lambda x: x.update({"optimizer_steps_old_only": 48}),
        ):
            with self.subTest(modifier=str(modifier)):
                changed = copy.deepcopy(self.frozen)
                modifier(changed)
                with self.assertRaises((original_audit.AuditError, ValueError)):
                    auditor.validate(self.panel, changed)

    def test_mismatched_source_and_unknown_fields_reject(self) -> None:
        different = trial.synthetic_panel(seed=47, rule="conditional", rows=32)
        with self.assertRaises(original_audit.AuditError):
            auditor.validate(different, self.frozen)
        changed = copy.deepcopy(self.frozen)
        changed["grant"] = True
        with self.assertRaises(original_audit.AuditError):
            auditor.validate(self.panel, changed)

    def test_cli_is_create_only_and_output_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "frozen.json"
            path = Path(temp) / "panel.json"
            path.write_bytes(trial.canonical(self.panel))
            self.assertEqual(producer.main(["--panel", str(path), "--steps", "2",
                                            "--report", str(out)]), 0)
            original_bytes = out.read_bytes()
            self.assertEqual(producer.main(["--panel", str(path), "--steps", "2",
                                            "--report", str(out)]), 2)
            self.assertEqual(out.read_bytes(), original_bytes)
            audit = auditor.validate(self.panel, json.loads(original_bytes))
            self.assertEqual(audit["production_admission"], "BLOCKED")

    def test_duplicate_keys_and_false_positive_external_artifact_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_bytes(b'{"schema":"a","schema":"b"}')
            with self.assertRaises(original_audit.AuditError):
                original_audit.load(path)
            fake = copy.deepcopy(self.frozen)
            fake["authority_posture"] = "ALLOW"
            with self.assertRaises(original_audit.AuditError):
                auditor.validate(self.panel, fake)


if __name__ == "__main__":
    unittest.main()

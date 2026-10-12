"""Dependency-light policy regressions; public-shaped fixtures are artificial."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from development_study_data import phase
from public_structural_data import (GROUPED_PARTITIONS, INTENTS, PARTITIONS,
                                    protect_content_groups, publisher_rows)
from public_structural_stage import stage


def fixture():
    return {p: [[f"fixture {p} {label} {i}", label] for label in INTENTS for i in range(n)]
            for p, n in PARTITIONS.items()}


class PublicCorpusChecks(unittest.TestCase):
    def test_strict_default_still_refuses_overlap(self):
        data = fixture()
        data["train"][0][0] = data["val"][20][0]
        with self.assertRaises(ValueError):
            publisher_rows(data)

    def test_explicit_grouping_preserves_every_id_text_and_original_label(self):
        data = fixture()
        data["train"][0][0] = data["val"][20][0]
        original = deepcopy(data)
        rows, _, provenance = publisher_rows(data, partition_policy=GROUPED_PARTITIONS)
        self.assertEqual(data, original)
        self.assertEqual(len(rows), 1200)
        for row in rows:
            _, split, index = row["sample_id"].split(":")
            text, label = original[split][int(index)]
            self.assertEqual((row["state"], INTENTS[row["label"]]), (text, label))
        conflict = [r for r in rows if r["state"] == data["train"][0][0]]
        self.assertEqual(len(conflict), 2)
        self.assertEqual({phase(r) for r in conflict}, {"calibration"})
        self.assertEqual(len({r["label"] for r in conflict}), 2)
        report = provenance["partition_policy"]
        self.assertEqual((report["retained_rows"], report["dropped_rows"]), (1200, 0))
        self.assertEqual(len(report["moved_rows"]), 1)
        self.assertEqual(len(report["conflicting_label_groups"]), 1)
        self.assertFalse(report["official_publisher_partitions_unchanged"])

    def test_test_members_never_move_to_training_or_calibration(self):
        data = fixture()
        text = data["test"][0][0]
        data["train"][0][0] = text
        data["val"][20][0] = text
        rows, _, provenance = publisher_rows(data, partition_policy=GROUPED_PARTITIONS)
        group = [r for r in rows if r["state"] == text]
        self.assertEqual(len(group), 3)
        self.assertEqual({phase(r) for r in group}, {"held_out"})
        self.assertEqual(len(provenance["partition_policy"]["moved_rows"]), 2)

    def test_assignment_does_not_depend_on_labels(self):
        data = fixture()
        data["train"][0][0] = data["val"][20][0]
        rows, _, _ = publisher_rows(data, partition_policy=GROUPED_PARTITIONS)
        altered = deepcopy(rows)
        for row in altered:
            row["label"] = (row["label"] + 3) % 8
        a, _ = protect_content_groups(rows)
        b, _ = protect_content_groups(altered)
        self.assertEqual([(r["sample_id"], phase(r)) for r in a], [(r["sample_id"], phase(r)) for r in b])

    def test_input_order_does_not_change_group_destination(self):
        rows = [{"sample_id": "a", "state": " same text ", "label": 0, "split": "train", "training_phase": "base"},
                {"sample_id": "b", "state": "same  text", "label": 1, "split": "train", "training_phase": "extra"}]
        a, ma = protect_content_groups(rows)
        b, mb = protect_content_groups(list(reversed(rows)))
        self.assertEqual({r["sample_id"]: phase(r) for r in a}, {r["sample_id"]: phase(r) for r in b})
        self.assertEqual(ma, mb)
        self.assertEqual({phase(r) for r in a}, {"extra"})

    def test_unknown_policy_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            publisher_rows(fixture(), partition_policy="skip_bad_rows")

    def test_bad_data_stops_before_any_model_metadata_or_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stage"
            with patch("public_structural_stage.download_checked") as download, \
                    patch("public_structural_stage.prepare_dataset", side_effect=ValueError("fixture overlap")), \
                    patch("public_structural_stage.model_pins") as model:
                with self.assertRaisesRegex(ValueError, "fixture overlap"):
                    stage(output, partition_policy=GROUPED_PARTITIONS)
            self.assertEqual(download.call_count, 2)
            self.assertTrue(all("clinc/oos-eval" in call.args[0] for call in download.call_args_list))
            model.assert_not_called()
            self.assertEqual(json.loads((output / "FAILED.json").read_bytes())["message"], "fixture overlap")
            self.assertEqual(json.loads((output / "PLAN.json").read_bytes())["partition_policy"], GROUPED_PARTITIONS)

    def test_existing_stage_never_reexecutes_network(self):
        with tempfile.TemporaryDirectory() as directory, patch("public_structural_stage.download_checked") as download:
            with self.assertRaises(FileExistsError):
                stage(Path(directory))
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()

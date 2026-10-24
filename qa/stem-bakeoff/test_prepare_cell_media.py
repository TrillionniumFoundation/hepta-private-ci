"""Check source isolation and label-free predictor planning without model scores."""

import json
from pathlib import Path
import tempfile
import unittest

from prepare_cell_media import (freeze_dataset, image_records, input_identity,
                                remove_crossing_groups, unique_representatives)


class MediaPlanningTests(unittest.TestCase):
    def test_cross_partition_excludes_whole_original_recording(self):
        rows = [{"source_id": str(i), "group_id": group, "fold": fold}
                for i, (group, fold) in enumerate((("a", 1), ("a", 4), ("b", 2), ("b", 2), ("c", 5)))]
        kept, removed = remove_crossing_groups(rows, lambda row: row["fold"])
        self.assertEqual(removed, ["a"])
        self.assertEqual([row["source_id"] for row in kept], ["2", "3", "4"])
        first = unique_representatives(kept)
        second = unique_representatives(list(reversed(kept)))
        self.assertEqual({r["source_id"] for r in first}, {r["source_id"] for r in second})
        self.assertEqual(len(first), 2)

    def row(self, number, label, split="train"):
        prompt, media = "A photograph.", "sha256:" + f"{number:064x}"
        return {"source_id": str(number), "group_id": str(number), "fine_label": label,
                "split": split, "text": prompt, "modality": "image",
                "record": {"text": prompt, "image": "media/" + str(number) + ".png"},
                "input_content_sha256": input_identity("image", prompt, media)}

    def test_class_support_exposes_unavailable_budget_without_replication(self):
        rows = [self.row(i, 1 if i < 4 else 3) for i in range(8)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "frozen"
            result = freeze_dataset(rows, "image", {"neutral_prompt": "A photograph."}, {}, root)
            status = next(x for x in result["task_status"] if x["task_id"] == "image_road_transport")
            self.assertEqual(status["available_balanced_budgets"], [8])
            self.assertEqual(status["negative_positive_support"]["train"], [4, 4])
            self.assertEqual(len(json.loads((root / "dataset.json").read_bytes())["rows"]), 8)
            with self.assertRaises(FileExistsError):
                freeze_dataset(rows, "image", {"neutral_prompt": "A photograph."}, {}, root)

    def test_neutral_text_is_allowed_but_duplicate_media_and_leaked_prompt_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self.row(1, 1), self.row(2, 3)]
            rows[1]["input_content_sha256"] = rows[0]["input_content_sha256"]
            with self.assertRaisesRegex(ValueError, "duplicate full predictor"):
                freeze_dataset(rows, "image", {"neutral_prompt": "A photograph."}, {}, Path(tmp) / "a")
            rows = [self.row(1, 1), self.row(2, 3)]
            rows[1]["record"]["text"] = "A cat."
            with self.assertRaisesRegex(ValueError, "neutral record"):
                freeze_dataset(rows, "image", {"neutral_prompt": "A photograph."}, {}, Path(tmp) / "b")

    def test_identity_changes_with_content_and_modality_but_excludes_labels(self):
        first, second = self.row(1, 1), self.row(1, 3)
        self.assertEqual(first["input_content_sha256"], second["input_content_sha256"])
        self.assertNotEqual(first["input_content_sha256"], self.row(2, 1)["input_content_sha256"])
        self.assertNotEqual(input_identity("audio", "same", "digest"), input_identity("image", "same", "digest"))

    def test_corrupt_archive_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.tar.gz"
            path.write_bytes(b"not the author dataset")
            with self.assertRaisesRegex(ValueError, "checksum"):
                image_records(path)


if __name__ == "__main__":
    unittest.main()

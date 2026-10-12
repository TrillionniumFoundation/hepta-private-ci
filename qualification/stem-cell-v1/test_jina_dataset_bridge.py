"""Pure-Python adversarial schema bridge tests. No Jina weights executed."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jina_dataset_bridge import convert, main


def six_window_rows():
    rows = []
    for day, split in enumerate(("train", "calibration", "held_out",
                                 "future_1", "future_2", "ood"), 1):
        for i in range(4):
            ident = f"{split}-{i}"
            rows.append({
                "sample_id": ident,
                "source_group": ident,
                "episode_id": ident,
                "cell_id": "cell-A" if i % 2 else "cell-B",
                "task_id": "decision", "principal_id": "approved-principal",
                "split": split, "language": "en", "scope": "scope-1",
                "state": "unique case state " + ident,
                "question": "choose one", "options": ["one", "two"],
                "label": i % 2,
                "event_time": f"2026-01-0{day}T12:00:{i:02d}Z",
            })
    return rows


class DatasetBridgeTests(unittest.TestCase):
    def test_lossless_ids_options_windows_and_task_scope(self):
        rows = six_window_rows()
        converted, manifest = convert(rows)
        self.assertEqual(24, len(converted))
        self.assertEqual({r["case_id"] for r in converted},
                         {r["sample_id"] for r in rows})
        self.assertEqual({r["source_episode_id"] for r in converted},
                         {r["episode_id"] for r in rows})
        self.assertEqual(len([r for r in converted if r["split"] == "future"]), 8)
        self.assertEqual({r["future_window"] for r in converted
                          if r["split"] == "future"}, {"future_1", "future_2"})
        self.assertEqual([r["options"] for r in converted],
                         [r["options"] for r in rows])
        self.assertFalse(manifest["production_promotion_permitted"])
        self.assertFalse(manifest["independent_data_authorization_verified"])

    def test_missing_principal_and_reused_fold_contents_rejected(self):
        rows = six_window_rows()
        rows[0]["principal_id"] = ""
        with self.assertRaisesRegex(ValueError, "Cell/task/principal"):
            convert(rows)
        rows = six_window_rows()
        rows[-1]["state"] = rows[0]["state"]
        with self.assertRaisesRegex(ValueError, "identical candidate"):
            convert(rows)

    def test_unordered_or_overlapping_windows_rejected(self):
        rows = six_window_rows()
        next(r for r in rows if r["split"] == "future_2")["event_time"] = (
            "2026-01-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "chronological"):
            convert(rows)
        rows = six_window_rows()
        next(r for r in rows if r["split"] == "future_2")["source_group"] = "future_1-0"
        with self.assertRaisesRegex(ValueError, "source-group leakage"):
            convert(rows)

    def test_cli_requires_exact_pinned_source_and_append_only_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "approved.jsonl"
            out = root / "jina.jsonl"
            src.write_text("".join(json.dumps(row) + "\n" for row in six_window_rows()))
            sha = hashlib.sha256(src.read_bytes()).hexdigest()
            args = ["jina_dataset_bridge.py", "--source", str(src),
                    "--approved-source-sha256", "a" * 64,
                    "--output", str(out)]
            with patch.object(sys, "argv", args):
                with self.assertRaisesRegex(ValueError, "externally approved"):
                    main()
            args[args.index("a" * 64)] = sha
            with patch.object(sys, "argv", args):
                main()
            self.assertEqual(len(out.read_text().splitlines()), 24)
            manifest = json.loads(Path(str(out) + ".bridge.json").read_text())
            self.assertEqual(manifest["approved_source_file_sha256_unverified_owner_claim"], sha)
            self.assertEqual(manifest["jina_converted_jsonl_sha256"],
                             hashlib.sha256(out.read_bytes()).hexdigest())
            self.assertFalse(manifest["ndu_utility_verified"])
            with patch.object(sys, "argv", args):
                with self.assertRaises(FileExistsError):
                    main()


if __name__ == "__main__":
    unittest.main()

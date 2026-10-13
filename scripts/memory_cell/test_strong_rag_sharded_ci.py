"""No inference: test locked stage identities and artifact tamper rejection."""

from copy import deepcopy
import hashlib
import io
from contextlib import redirect_stderr, redirect_stdout
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import strong_rag_sharded_ci as sharded


def write(path, data):
    path.write_text(json.dumps(data, sort_keys=True) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ShardedCiTransportTests(unittest.TestCase):
    def test_only_measurement_seconds_may_vary_in_staged_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, canon = root / "model", root / "canonical"
            model.mkdir()
            canon.mkdir()
            inv = {"inventory_digest": "exact-qwen"}
            pub = {"revision": "exact-fixed-revision"}
            stage = {
                "inventory_sha256": "i",
                "publisher_sha256": "p",
                "tier": "qwen-3b",
                "seconds": 25.0,
            }
            pins = {
                "inventory.json": write(canon / "inventory.json", inv),
                "publisher.json": write(canon / "publisher.json", pub),
                "stage.json": write(canon / "stage.json", stage),
            }
            write(model / "inventory.json", inv)
            write(model / "publisher.json", pub)
            write(model / "stage.json", stage | {"seconds": 47.25})
            with patch.dict(sharded.CANONICAL_SHA, pins):
                receipt = sharded.align_model_stage(
                    model, canon, root / "staging-observation.json"
                )
            self.assertEqual(receipt["actual_shard_model_staging_seconds"], 47.25)
            self.assertTrue(receipt["canonical_stage_seconds_are_historical"])
            self.assertEqual(
                (model / "stage.json").read_bytes(),
                (canon / "stage.json").read_bytes(),
            )
            self.assertFalse(receipt["production_accepted"])

    def test_new_weight_or_inventory_revision_may_not_be_silently_aligned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, canon = root / "m", root / "c"
            model.mkdir()
            canon.mkdir()
            inv, pub = {"digest": "old"}, {"revision": "old"}
            stage = {"tier": "qwen-3b", "seconds": 1.0, "version": "old"}
            pins = {
                "inventory.json": write(canon / "inventory.json", inv),
                "publisher.json": write(canon / "publisher.json", pub),
                "stage.json": write(canon / "stage.json", stage),
            }
            write(model / "inventory.json", inv)
            write(model / "publisher.json", pub)
            write(model / "stage.json", stage | {"seconds": 2.0, "version": "new"})
            with patch.dict(sharded.CANONICAL_SHA, pins):
                with self.assertRaises(ValueError):
                    sharded.align_model_stage(model, canon, root / "bad.json")

    def test_sealed_directory_fails_on_changed_or_extra_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.jsonl").write_text("{}\n")
            digest = hashlib.sha256((root / "raw.jsonl").read_bytes()).hexdigest()
            (root / "SHA256SUMS").write_text(f"{digest}  ./raw.jsonl\n")
            self.assertEqual(sharded.check_tree(root), 1)
            (root / "other.txt").write_text("injected")
            with self.assertRaises(ValueError):
                sharded.check_tree(root)
            (root / "other.txt").unlink()
            (root / "raw.jsonl").write_text('{"rewritten":true}\n')
            with self.assertRaises(ValueError):
                sharded.check_tree(root)

    def test_unpinned_zip_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            zipfile = Path(tmp) / "garbage.zip"
            zipfile.write_bytes(b"not even a ZIP")
            with self.assertRaises(ValueError):
                sharded.extract_original(zipfile, Path(tmp) / "original")
            with self.assertRaises(ValueError):
                sharded.extract_model_identity(zipfile, Path(tmp) / "model")


    def test_cli_dispatches_all_four_actions_with_exact_paths(self):
        # Exercise argparse rather than the model or immutable artifact.
        cases = (
            ("original", "extract_original", ("archived.zip", "original")),
            ("identity", "extract_model_identity", ("locked.zip", "identity")),
            ("align", "align_model_stage", ("live", "canonical", "receipt.json")),
            ("verify", "check_tree", ("recorded",)),
        )
        for action, target, raw_paths in cases:
            result = {"tested_action": action, "model_calls": 0}
            with self.subTest(action=action):
                with patch("sys.argv", ["strong_rag_sharded_ci.py", action, *raw_paths]):
                    with patch.object(sharded, target, return_value=result) as invoked:
                        with redirect_stdout(io.StringIO()) as output:
                            sharded.main()
                invoked.assert_called_once_with(*(Path(p) for p in raw_paths))
                self.assertEqual(json.loads(output.getvalue()), result)

    def test_cli_rejects_missing_archive_without_any_extraction(self):
        with patch("sys.argv", ["strong_rag_sharded_ci.py", "original"]):
            with patch.object(sharded, "extract_original") as execute:
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        sharded.main()
        self.assertEqual(error.exception.code, 2)
        execute.assert_not_called()

    def test_cli_rejects_unknown_operation_before_any_io(self):
        with patch("sys.argv", ["strong_rag_sharded_ci.py", "unsupported"]):
            with patch.object(sharded, "check_tree") as checker:
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        sharded.main()
        self.assertEqual(error.exception.code, 2)
        checker.assert_not_called()


if __name__ == "__main__":
    unittest.main()

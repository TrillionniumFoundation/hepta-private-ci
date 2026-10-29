"""Synthetic source metadata and access barriers; no scientific assets or outcomes."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import sources


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        roles, cursors = {}, {"train": 0, "test": 0}
        for name, (origin, count) in sources.ROLE_PLAN.items():
            ids = [f"mnist:{origin}:{i}:{sources.sha(f'synthetic:{origin}:{i}'.encode())}"
                   for i in range(cursors[origin], cursors[origin] + count)]
            cursors[origin] += count
            roles[name] = {"official_partition": origin, "identities": ids}
        files = [{"name": n, "sha256": h, "bytes": sources.DATASET_SIZES[n]} for n, h in sources.v3.FILES.items()]
        manifest, packed = sources._records(roles, files)
        self.manifest = self.root / "SOURCE_ALLOCATION.json"
        write_json(self.manifest, manifest)
        (self.root / "SOURCE_IDENTITIES.json.gz").write_bytes(packed)
        checkpoint = self.root / "model.bin"
        checkpoint.write_bytes(b"synthetic checkpoint")
        self.checkpoints = self.root / "checkpoints.json"
        self.checkpoint_record = {"schema": sources.CHECKPOINT_SCHEMA, "phase": "qualification", "training_complete": True,
                                  "checkpoints": [{"id": "model-0", "path": "model.bin", "bytes": checkpoint.stat().st_size,
                                                   "sha256": sources.file_hash(checkpoint)}]}
        self.freeze = self.root / "freeze.json"
        self.freeze_record = {"schema": sources.FREEZE_SCHEMA, "phase": "qualification",
                              "source_manifest_sha256": sources.file_hash(self.manifest),
                              "allowed_roles": list(sources.PHASE_ROLES["qualification"]), "required_checkpoint_ids": ["model-0"]}
        self.reseal()

    def reseal(self):
        write_json(self.checkpoints, self.checkpoint_record)
        self.freeze_record["checkpoint_manifest_sha256"] = sources.file_hash(self.checkpoints)
        write_json(self.freeze, self.freeze_record)
        self.kwargs = {"phase": "qualification", "freeze_path": self.freeze,
                       "expected_freeze_sha256": sources.file_hash(self.freeze), "checkpoint_manifest_path": self.checkpoints,
                       "expected_checkpoint_manifest_sha256": sources.file_hash(self.checkpoints)}

    def load(self, roles=("qualification_task",), **changes):
        return sources.load_new_roles(self.root / "nonexistent-assets", self.manifest, list(roles), **{**self.kwargs, **changes})

    def test_authorized_subset_reaches_only_requested_materialization(self):
        with patch.object(sources, "_materialize_roles", return_value="synthetic result") as materialize:
            self.assertEqual(self.load(), "synthetic result")
        self.assertEqual(materialize.call_args.args[1], ["qualification_task"])
        self.assertEqual(materialize.call_args.args[4], "qualification")

    def test_no_implicit_phase_or_default_access(self):
        with patch.object(sources, "_materialize_roles") as materialize:
            with self.assertRaises(TypeError):
                sources.load_new_roles(self.root, self.manifest, ["qualification_task"])
            for roles in ([], ["primary"], ["final_task"], ["qualification_task", "qualification_task"]):
                with self.subTest(roles=roles), self.assertRaises(ValueError):
                    self.load(roles)
            materialize.assert_not_called()

    def test_freeze_and_checkpoint_bytes_bound_before_assets(self):
        with patch.object(sources, "_materialize_roles") as materialize:
            with self.assertRaisesRegex(ValueError, "freeze identity"):
                self.load(expected_freeze_sha256="0" * 64)
            (self.root / "model.bin").write_bytes(b"different checkpoint")
            with self.assertRaisesRegex(ValueError, "Checkpoint bytes"):
                self.load()
            materialize.assert_not_called()

    def test_missing_training_checkpoint_and_wrong_phase_fail(self):
        with patch.object(sources, "_materialize_roles") as materialize:
            self.checkpoint_record["training_complete"] = False
            self.reseal()
            with self.assertRaisesRegex(ValueError, "incomplete"):
                self.load()
            self.checkpoint_record["training_complete"] = True
            self.freeze_record["required_checkpoint_ids"].append("missing-model")
            self.reseal()
            with self.assertRaisesRegex(ValueError, "inventory"):
                self.load()
            with self.assertRaises(ValueError):
                self.load(("final_task",), phase="final")
            materialize.assert_not_called()

    def test_checkpoint_escape_and_registry_tamper_fail(self):
        with patch.object(sources, "_materialize_roles") as materialize:
            self.checkpoint_record["checkpoints"][0]["path"] = "../model.bin"
            self.reseal()
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                self.load()
            self.checkpoint_record["checkpoints"][0]["path"] = "model.bin"
            self.reseal()
            packed = self.root / "SOURCE_IDENTITIES.json.gz"
            packed.write_bytes(packed.read_bytes() + b"tamper")
            with self.assertRaises((ValueError, OSError)):
                self.load()
            materialize.assert_not_called()

    def test_training_roles_exclude_historical_reserved_pools(self):
        with patch.object(sources.v3, "load_corpus_roles", return_value="old metadata") as loader:
            self.assertEqual(sources.load_training_roles(self.root, "C", ["fit_gradient"]), "old metadata")
            loader.assert_called_once_with(self.root / "ndu-data", ["fit_gradient"])
            for stage, role in (("A", "primary"), ("B", "retention"), ("C", "development_task"), ("C", "audit_task")):
                with self.subTest(stage=stage, role=role), self.assertRaises(ValueError):
                    sources.load_training_roles(self.root, stage, [role])
            self.assertEqual(loader.call_count, 1)

    def test_metadata_excludes_duplicates_conflicts_and_old_pixels(self):
        h = [sources.sha(str(i).encode()) for i in range(6)]
        parts = {"train": {"hashes": [h[0], h[1], h[1], h[2], h[3], h[4]], "labels": [0, 1, 1, 2, 3, 4]},
                 "test": {"hashes": [h[2], h[5], h[3]], "labels": [2, 5, 9]}}
        remaining = sources._eligible(parts, {h[0]})
        self.assertEqual({k: len(v) for k, v in remaining.items()}, {"train": 2, "test": 2})
        self.assertEqual({sources._identity(i)[2] for i in remaining["train"]}, {h[1], h[4]})
        plan = {"a": ("train", 2), "b": ("test", 2)}
        expected = sources._assign_roles(remaining, plan)
        self.assertEqual(expected, sources._assign_roles({k: list(reversed(v)) for k, v in remaining.items()}, plan))
        for part in parts.values():
            part["labels"] = [(x + 1) % 10 for x in part["labels"]]
        self.assertEqual(sources._eligible(parts, {h[0]}), remaining)


if __name__ == "__main__":
    unittest.main()

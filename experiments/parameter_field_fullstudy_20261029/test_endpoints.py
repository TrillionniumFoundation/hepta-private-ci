"""Synthetic endpoint barrier/serialization tests; opens no scientific assets."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import endpoints


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


class EndpointBarrierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_manifest = self.root / "synthetic-source-manifest.json"
        write_json(self.source_manifest, {"fixture": "metadata only; not a real corpus"})

    def population(self, phase):
        expected = endpoints.expected_ids(phase)
        _, _, microsteps = endpoints.phase_spec(phase)
        for seed in endpoints.SEEDS:
            directory = self.root / ("stage_" + phase) / f"seed-{seed}"
            paths = directory / "paths"
            paths.mkdir(parents=True)
            rows = []
            for identity, (row_seed, schedule, method) in expected.items():
                if row_seed != seed:
                    continue
                record = {"schema": endpoints.SCHEMA,
                          "cursor": {"seed": seed, "schedule_id": schedule, "path_kind": method, "clock": 288,
                                     "remaining_steps": 0, "total_steps": 288, "guard_grain": 48,
                                     "baseline_action": endpoints.BASELINES[seed]},
                          "binding": {"source_freeze_sha256": "1" * 64, "runtime_sha256": "2" * 64}}
                target = paths / (identity + ".state")
                target.write_bytes(endpoints.codec.dumps(record))
                rows.append({"id": identity, "seed": seed, "schedule_id": schedule, "method": method,
                             "path": target.name, "bytes": target.stat().st_size, "sha256": endpoints.file_hash(target),
                             "costs": {"scheduled_gradient_microsteps": 288}})
            write_json(paths / "PATHS.json", {"complete": True, "training_complete": True, "phase": phase,
                       "seed": seed, "paths": rows, "new_endpoint_roles_opened": []})
            write_json(directory / "COMPLETE.json", {"complete": True, "phase": phase, "seed": seed,
                       "registered_commit": "a" * 40, "source_freeze_sha256": "1" * 64,
                       "path_count": len(rows), "costs": {"scheduled_gradient_microsteps": microsteps}})
        return endpoints.collect_checkpoints(self.root, phase, "2" * 64)

    def test_all_a_seeds_and_complete_physical_work_are_required(self):
        inventory = self.population("A")
        self.assertEqual(len(inventory["entries"]), 48)
        complete = self.root / "stage_A" / "seed-43" / "COMPLETE.json"
        original = json.loads(complete.read_text())
        broken = {**original, "costs": {"scheduled_gradient_microsteps": 39167}}
        write_json(complete, broken)
        with patch.object(endpoints.sources, "load_training_roles") as loader:
            with self.assertRaisesRegex(ValueError, "work inventory"):
                endpoints.collect_checkpoints(self.root, "A", "2" * 64)
            loader.assert_not_called()
        write_json(complete, original)
        complete.unlink()
        with self.assertRaisesRegex(ValueError, "All three"):
            endpoints.collect_checkpoints(self.root, "A", "2" * 64)

    def test_b_barrier_contains_every_checkpoint_and_opens_only_qualification(self):
        inventory = self.population("B")
        with patch.object(endpoints.sources, "load_new_roles", return_value="synthetic corpus") as loader:
            corpus, access = endpoints.load_endpoint_corpus(self.root, "B", inventory, self.source_manifest,
                                                           {"registered_commit": "b" * 40}, "3" * 64)
        self.assertEqual(corpus, "synthetic corpus")
        self.assertEqual(loader.call_args.args[2], ["qualification_task", "qualification_clean"])
        manifest = json.loads(Path(access["checkpoint_manifest_path"]).read_text())
        self.assertEqual(len(manifest["checkpoints"]), 240)
        self.assertEqual({row["id"] for row in manifest["checkpoints"]}, set(endpoints.expected_ids("B")))
        freeze = json.loads(Path(access["freeze_path"]).read_text())
        self.assertEqual(freeze["required_checkpoint_ids"], sorted(endpoints.expected_ids("B")))
        first = Path(inventory["stage"]) / inventory["entries"][0]["path"]
        first.write_bytes(b"tampered after freeze")
        with self.assertRaisesRegex(ValueError, "Checkpoint bytes"):
            endpoints.sources._barrier(self.source_manifest, ["qualification_task"], **access)

    def test_checkpoint_subset_duplicate_and_tamper_cannot_pass(self):
        inventory = self.population("B")
        with patch.object(endpoints.sources, "load_new_roles") as loader:
            subset = {**inventory, "entries": inventory["entries"][:-1]}
            with self.assertRaisesRegex(ValueError, "subset"):
                endpoints.load_endpoint_corpus(self.root, "B", subset, self.source_manifest,
                                               {"registered_commit": "b" * 40}, "3" * 64)
            loader.assert_not_called()
        paths = self.root / "stage_B" / "seed-17" / "paths" / "PATHS.json"
        original = json.loads(paths.read_text())
        altered = json.loads(paths.read_text())
        altered["paths"][-1] = altered["paths"][0]
        write_json(paths, altered)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            endpoints.collect_checkpoints(self.root, "B")
        write_json(paths, original)
        target = paths.parent / original["paths"][0]["path"]
        target.write_bytes(target.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            endpoints.collect_checkpoints(self.root, "B")

    def test_runtime_terminal_state_and_failed_phase_are_checked_before_access(self):
        inventory = self.population("A")
        with self.assertRaisesRegex(ValueError, "runtime differs"):
            endpoints.collect_checkpoints(self.root, "A", "9" * 64)
        paths = self.root / "stage_A" / "seed-17" / "paths" / "PATHS.json"
        manifest = json.loads(paths.read_text())
        row = manifest["paths"][0]
        target = paths.parent / row["path"]
        record = endpoints.codec.loads(target.read_bytes(), row["sha256"], row["bytes"])
        record["cursor"]["clock"] = 240
        target.write_bytes(endpoints.codec.dumps(record))
        row.update(bytes=target.stat().st_size, sha256=endpoints.file_hash(target))
        write_json(paths, manifest)
        with self.assertRaisesRegex(ValueError, "terminal learning state"):
            endpoints.collect_checkpoints(self.root, "A")
        write_json(self.root / "stage_A" / "seed-29" / "FAILED.json", {"complete": False})
        # A marker at an earlier seed makes failure take priority over file parsing.
        write_json(self.root / "stage_A" / "seed-17" / "FAILED.json", {"complete": False})
        with self.assertRaisesRegex(ValueError, "failed training phase"):
            endpoints.collect_checkpoints(self.root, "A")

    def test_a_role_access_keeps_training_context_separate(self):
        inventory = self.population("A")
        with patch.object(endpoints.sources, "load_training_roles", return_value="endpoint corpus") as loader:
            result, access = endpoints.load_endpoint_corpus(self.root, "A", inventory, None,
                                                          {"registered_commit": "b" * 40}, "3" * 64)
        self.assertEqual(result, "endpoint corpus")
        self.assertEqual(access, {})
        loader.assert_called_once_with(self.root, "A", ["development_task", "development_clean"])
        self.assertEqual(endpoints.TRAINING_ROLES,
                         ["development_gradient", "development_rehearsal", "development_probe", "development_guard"])


class EndpointReadbackTests(unittest.TestCase):
    def test_hard_outputs_roundtrip_and_analysis_requires_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            score = {"values": {"reward": np.asarray([.2, .4]), "audit": np.asarray([.1, .3])},
                     "means": {"reward": .3, "audit": .2}, "output_sha256": ["a" * 64, "b" * 64],
                     "conditions": ["clean", "clean"], "source_ids": [("toy:a", "toy:b"), ("toy:c", "toy:d")],
                     "pixels_u8": np.arange(8, dtype=np.uint8).reshape(2, 1, 2, 2),
                     "captions_utf8": np.asarray(["toy one", "toy two"])}
            metadata = endpoints.save_score(root / "toy.npz", score)
            self.assertTrue(metadata["readback_equal"])
            self.assertEqual(metadata["file_sha256"], endpoints.file_hash(root / "toy.npz"))
            manifest = root / "ENDPOINTS.json"
            write_json(manifest, {"schema": "hepta.fullstudy.AB.endpoints.1", "complete": False})
            with self.assertRaisesRegex(ValueError, "completed"):
                endpoints.load_records(manifest)
            write_json(manifest, {"schema": "hepta.fullstudy.AB.endpoints.1", "complete": True,
                                 "phase": "A", "training_path_count": 48, "observers": ["reward", "audit"], "records": []})
            with self.assertRaisesRegex(ValueError, "analysis grid"):
                endpoints.load_records(manifest)
            coordinates = endpoints.expected_ids("A")
            coordinates.update({f"seed-{seed}-frozen": (seed, None, "frozen") for seed in endpoints.SEEDS})
            packed, records = (root / "toy.npz").read_bytes(), []
            for identity, (seed, schedule, method) in coordinates.items():
                for role in ("task", "clean"):
                    target = root / (identity + "-" + role + ".npz")
                    target.write_bytes(packed)
                    records.append({"id": identity + "-" + role, "seed": seed, "schedule_id": schedule,
                                    "method": method, "role": role, "source_role": "development_" + role,
                                    "path": target.name, "bytes": len(packed), "sha256": metadata["file_sha256"],
                                    "rows": 2, "costs": {}})
            write_json(manifest, {"schema": "hepta.fullstudy.AB.endpoints.1", "complete": True,
                                 "phase": "A", "training_path_count": 48, "observers": ["reward", "audit"],
                                 "records": records})
            decoded = endpoints.load_records(manifest, endpoints.file_hash(manifest))
            self.assertEqual(len(decoded), 102)
            np.testing.assert_array_equal(decoded[0]["values"]["audit"], score["values"]["audit"])
            (root / records[0]["path"]).write_bytes(packed + b"tamper")
            with self.assertRaisesRegex(ValueError, "literal bytes"):
                endpoints.load_records(manifest)
            write_json(root / "FAILED.json", {"complete": False})
            with self.assertRaisesRegex(ValueError, "failed endpoint phase"):
                endpoints.load_records(manifest)


if __name__ == "__main__":
    unittest.main()

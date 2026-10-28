"""Development-only real-native integration fixtures; no confirmation data."""

from dataclasses import asdict
import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .common import canonical, save_json, sha, write_records
from .execution import run_context
from .integration import restore_task_checkpoint, run_owner_study
from .math_model import TaskSpec, build_model, solve_dp
from .models import ActorAdapter
from .native.adapter import NativeBridge, save_profile
from .training import profile_for


BINARY = os.environ.get("CONTINUOUS_NATIVE_BINARY")


@unittest.skipUnless(
    BINARY and Path(BINARY).is_file(),
    "Set CONTINUOUS_NATIVE_BINARY for original-owner integration",
)
class DurableTaskConsumer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="continuous-owner-fixture-", dir="/dev/shm"
        )
        self.base = Path(self.temp.name)
        self.root = self.base / "study"
        self.root.mkdir()
        self.binary = Path(BINARY)
        self.seed = 9007
        self.candidate = {
            "decay": 0.7,
            "gain_c": 0.5,
            "gain_p": 0.8,
            "fixed_boundary": 0.65,
        }
        self.spec = TaskSpec(horizon=6, initial=0.22)
        model = build_model(self.spec, n_grid=64)
        self.context = {
            "model": model,
            "dp": solve_dp(model),
            "index": 0,
            "spec": asdict(self.spec),
            "id": "non-confirmation-fixture",
        }

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, arms=("fixed_margin", "value_dual", "event_reset")):
        manifest = {
            "schema": "hepta.continuous-boundary.study.v1",
            "arms": list(arms),
            "seeds": [self.seed],
            "splits": {"test_id": 4, "test_ood": 4},
            "grid_states": 64,
            "grid_upper_domain": 4.8,
            "checkpoints": [],
            "records": [],
            "diagnostic_fixture": True,
        }
        with NativeBridge(self.binary, self.root / "fast-host") as bridge:
            for arm in arms:
                # Three actual native decisions exercise keep, repair and STOP.
                bias = np.array([0.4, 0.1, 0.0])
                if arm == "event_reset":
                    bias = np.array([0.1, 0.4, 0.0])
                elif arm == "value_dual":
                    bias = np.array([-0.4, -0.1, 0.0])
                profile = profile_for(
                    self.seed, arm, self.candidate, None, np.zeros((3, 20)), bias
                )
                path, identity = save_profile(self.root / "profiles", profile)
                bridge.load_profile(path, identity)
                checkpoint = {
                    "schema": "hepta.continuous-boundary.actor-checkpoint.v1",
                    "seed": self.seed,
                    "arm": arm,
                    "candidate": self.candidate,
                    "profile_path": str(path.relative_to(self.root)),
                    "profile_sha256": identity,
                    "boundary_weights": None,
                }
                cp_path = self.root / "checkpoints" / f"{arm}.json"
                cp_sha = save_json(cp_path, checkpoint)
                manifest["checkpoints"].append(
                    {
                        "arm": arm,
                        "train_seed": self.seed,
                        "path": str(cp_path.relative_to(self.root)),
                        "sha256": cp_sha,
                    }
                )
                for split in ("test_id", "test_ood"):
                    execution = run_context(
                        self.context,
                        seed=self.seed,
                        phase=split,
                        paths=4,
                        arm=arm,
                        checkpoint_sha256=cp_sha,
                        bridge=bridge,
                        profile_sha=identity,
                        candidate=self.candidate,
                    )
                    target = self.root / "records" / f"{arm}.{split}.jsonl.gz"
                    entry = write_records(target, execution["records"])
                    entry["path"] = str(target.relative_to(self.root))
                    manifest["records"].append(entry)
        bridge.process.stdout.close()
        save_json(self.root / "manifest.json", manifest)
        return manifest

    def test_complete_owner_task_cold_resume_and_terminal_guard(self):
        self.fixture()
        before = (self.root / "manifest.json").read_bytes()
        output = self.base / "engineering"
        result = run_owner_study(self.root, self.binary, output)
        self.assertTrue(result["passed"], result["results"])
        self.assertEqual(result["engineering_episode_count"], 6)
        self.assertEqual(result["scientific_incremental_sample_count"], 0)
        self.assertEqual(result["cold_resumes"], 6)
        self.assertEqual(result["continued_after_resume_episodes"], 4)
        self.assertEqual(result["terminal_only_resume_episodes"], 2)
        self.assertEqual(result["stop_rejection_checks"], 2)
        self.assertGreater(
            result["native_total_counters"]["original_journal_replay_steps"], 0
        )
        self.assertGreater(result["native_total_counters"]["owner_ticks"], 0)
        self.assertEqual((self.root / "manifest.json").read_bytes(), before)
        for path in (output / "cases").glob("*/COLD_RESUME.json"):
            cold = json.loads(path.read_text())[0]
            self.assertNotEqual(cold["closed_pid"], cold["new_pid"])
            self.assertNotEqual(cold["native_clock_micros"] / 1e6, cold["task_clock"])

    def test_actual_native_action_is_not_copied_from_record(self):
        manifest = self.fixture(arms=("fixed_margin",))
        entry = manifest["records"][0]
        path = self.root / entry["path"]
        records = [
            json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()
        ]
        records[0]["steps"][0]["action"] = "repair"
        expanded = b"".join(canonical(row) + b"\n" for row in records)
        path.write_bytes(gzip.compress(expanded, mtime=0))
        entry["sha256"], entry["uncompressed_sha256"] = (
            sha(path.read_bytes()),
            sha(expanded),
        )
        (self.root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        result = run_owner_study(self.root, self.binary, self.base / "engineering")
        self.assertFalse(result["passed"])
        failures = [r for r in result["results"] if not r["passed"]]
        self.assertEqual(len(failures), 1)
        self.assertIn("effective task action mismatch", failures[0]["error"])

    def test_typed_feature_mismatch_is_rejected(self):
        manifest = self.fixture(arms=("fixed_margin",))
        entry = manifest["records"][0]
        path = self.root / entry["path"]
        records = [
            json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()
        ]
        records[0]["steps"][0]["raw_features"]["raw_q24"][0] += 1
        expanded = b"".join(canonical(row) + b"\n" for row in records)
        path.write_bytes(gzip.compress(expanded, mtime=0))
        entry["sha256"], entry["uncompressed_sha256"] = (
            sha(path.read_bytes()),
            sha(expanded),
        )
        (self.root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        result = run_owner_study(self.root, self.binary, self.base / "engineering")
        self.assertFalse(result["passed"])
        self.assertTrue(
            any(
                "typed features mismatch" in r.get("error", "")
                for r in result["results"]
            )
        )

    def test_full_task_checkpoint_rejects_bindings_clocks_and_missing_adapter(self):
        self.fixture(arms=("fixed_margin",))
        output = self.base / "engineering"
        result = run_owner_study(self.root, self.binary, output)
        self.assertTrue(result["passed"], result["results"])
        packet_path = next((output / "cases").glob("*/TASK_CHECKPOINT.json"))
        original = json.loads(packet_path.read_text())
        binding_names = (
            "episode_id",
            "arm",
            "train_seed",
            "manifest_sha256",
            "source_record_sha256",
            "actor_checkpoint_sha256",
            "profile_sha256",
            "binary_sha256",
            "spec_sha256",
            "grid_sha256",
        )
        bindings = {key: original["payload"][key] for key in binding_names}
        for number, (field, replacement) in enumerate(
            [
                ("spec_sha256", "0" * 64),
                ("profile_sha256", "1" * 64),
                ("native_logical_micros", 1),
                ("task_physical_time", 999),
                ("adapter_state", [[0] * 5]),
            ]
        ):
            packet = json.loads(json.dumps(original))
            packet["payload"][field] = replacement
            packet["payload_sha256"] = sha(canonical(packet["payload"]))
            changed = self.base / f"changed-{number}.json"
            changed.write_bytes(canonical(packet) + b"\n")
            adapter = ActorAdapter(
                self.spec, self.context["dp"], "fixed_margin", self.candidate, self.seed
            )
            with self.assertRaises(ValueError):
                restore_task_checkpoint(
                    changed,
                    sha(changed.read_bytes()),
                    bindings,
                    adapter,
                    self.context["model"],
                    10000,
                )
            self.assertIsNone(adapter.state)
        actor = ActorAdapter(
            self.spec, self.context["dp"], "fixed_margin", self.candidate, self.seed
        )
        with self.assertRaises(ValueError):
            restore_task_checkpoint(
                packet_path, "0" * 64, bindings, actor, self.context["model"], 10000
            )


if __name__ == "__main__":
    unittest.main()

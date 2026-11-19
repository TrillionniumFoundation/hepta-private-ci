"""Adversarial audit of a tiny run through the real production runner.

The fixture explicitly uses one profile/seed, one scenario per split, one
training epoch and one sampled episode. It is not the research campaign.
Fixtures are generated only after this test source is complete and stay in
temporary directories; their original source manifest is never rewritten.
"""

from contextlib import redirect_stdout
from dataclasses import asdict
from fractions import Fraction
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ndu_ctrl1 import run as runner
from ndu_ctrl1 import verify as auditor
from ndu_ctrl1.learning import _sha
from ndu_ctrl1.model import Profile, Scenario


def unit_scenarios(split):
    prior = {
        "train": Fraction(1, 4),
        "development": Fraction(3, 8),
        "confirmation": Fraction(2, 3),
    }[split]
    scenario = Scenario(prior=prior, horizon=1, budget=6, deadline=5)
    return [(f"{split}-{runner.digest(asdict(scenario))[:16]}", scenario)]


def put_json(path, value):
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def reseal(directory):
    """Update file hashes after an attack, so semantic checks must detect it."""
    manifest = json.loads((directory / "ARTIFACTS.json").read_bytes())
    manifest["files"] = {
        str(path.relative_to(directory)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in directory.rglob("*")
        if path.is_file() and path.name != "ARTIFACTS.json"
    }
    put_json(directory / "ARTIFACTS.json", manifest)


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.TemporaryDirectory(prefix="ctrl1-evidence-unit-")
        cls.original = Path(cls.storage.name) / "original"
        with (
            patch.multiple(
                runner,
                SEEDS=(7,),
                EPOCHS=1,
                EXAMPLES_PER_SCENARIO=2,
                EPISODES=1,
                ROSTER=(
                    "fixed",
                    "fast_actor_critic",
                    "distilled_candidate",
                    "selected_fast",
                    "learned_router",
                ),
            ),
            patch.object(runner, "profiles", return_value=[Profile()]),
            patch.object(runner, "scenarios", side_effect=unit_scenarios),
            redirect_stdout(io.StringIO()),
        ):
            runner.run(cls.original)
        cls.baseline = auditor.verify(cls.original)

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()

    def setUp(self):
        self.copy = Path(tempfile.mkdtemp(dir=self.storage.name)) / "run"
        shutil.copytree(self.original, self.copy)

    def replace_plan(self, plan):
        put_json(self.copy / "PLAN.json", plan)
        for name in ("REPORT.json", "ARTIFACTS.json"):
            data = json.loads((self.copy / name).read_bytes())
            data["plan_sha256"] = runner.digest(plan)
            put_json(self.copy / name, data)
        reseal(self.copy)

    def rollouts(self):
        path = next(self.copy.glob("rollouts-*.jsonl.gz"))
        return path, [
            json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()
        ]

    def put_rollouts(self, path, rows):
        path.write_bytes(
            gzip.compress(b"".join(runner.encode(row) + b"\n" for row in rows), mtime=0)
        )
        reseal(self.copy)

    def result_rows(self):
        path = next(self.copy.glob("results-*.jsonl"))
        return path, [json.loads(line) for line in path.read_bytes().splitlines()]

    def put_results(self, path, rows):
        path.write_bytes(
            b"".join(
                json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows
            )
        )
        reseal(self.copy)

    def test_real_small_runner_has_complete_bound_originals(self):
        self.assertTrue(self.baseline["verified"])
        self.assertEqual(
            (
                self.baseline["comparisons"],
                self.baseline["sampled_originals"],
                self.baseline["training_runs"],
                self.baseline["development_originals"],
                self.baseline["router_training_runs"],
            ),
            (5, 5, 2, 2, 1),
        )
        self.assertEqual(self.baseline["scientific_promotion"], "HOLD")

    def test_file_hash_tamper_is_rejected(self):
        path = self.copy / "REPORT.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "identity"):
            auditor.verify(self.copy)

    def test_manifest_traversal_and_manifest_symlink_are_rejected(self):
        manifest_path = self.copy / "ARTIFACTS.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"]["../outside.json"] = manifest["files"].pop("REPORT.json")
        put_json(manifest_path, manifest)
        with self.assertRaises(ValueError):
            auditor.verify(self.copy)
        manifest_path.unlink()
        external = self.copy.parent / "outside-manifest.json"
        external.write_bytes((self.original / "ARTIFACTS.json").read_bytes())
        try:
            manifest_path.symlink_to(external)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "symlink"):
            auditor.verify(self.copy)

    def test_missing_and_duplicate_sampled_originals_are_rejected(self):
        path, originals = self.rollouts()
        self.put_rollouts(path, originals[1:])
        with self.assertRaises(ValueError):
            auditor.verify(self.copy)
        originals[-1] = originals[0]
        self.put_rollouts(path, originals)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            auditor.verify(self.copy)

    def test_duplicate_comparison_does_not_preserve_denominator(self):
        path, rows = self.result_rows()
        rows[-1] = rows[0]
        self.put_results(path, rows)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            auditor.verify(self.copy)

    def test_missing_attempt_completion_is_rejected(self):
        path = self.copy / "attempts.jsonl"
        lines = path.read_bytes().splitlines()
        path.write_bytes(b"\n".join(lines[:-1]) + b"\n")
        reseal(self.copy)
        with self.assertRaisesRegex(ValueError, "attempt"):
            auditor.verify(self.copy)

    def test_current_source_drift_is_rejected_and_historical_mode_is_explicit(self):
        changed = copy.deepcopy(runner.source_manifest())
        changed[next(iter(changed))]["sha256"] = "0" * 64
        with patch.object(auditor, "source_manifest", return_value=changed):
            with self.assertRaisesRegex(ValueError, "source"):
                auditor.verify(self.copy)
            self.assertFalse(
                auditor.verify(self.copy, check_source=False)["source_checked"]
            )

    def test_selection_is_recomputed_from_original_development(self):
        path = self.copy / "REPORT.json"
        report = json.loads(path.read_bytes())
        choice = report["selections"][0]
        choice["decision"] = (
            "NoUpdate" if choice["decision"] == "Candidate" else "Candidate"
        )
        put_json(path, report)
        reseal(self.copy)
        with self.assertRaisesRegex(ValueError, "recomputed development"):
            auditor.verify(self.copy)

    def test_held_out_scenarios_cannot_enter_development_evidence(self):
        plan = json.loads((self.copy / "PLAN.json").read_bytes())
        path = next(self.copy.glob("development-*.json"))
        rows = json.loads(path.read_bytes())
        rows[0]["scenario_id"] = plan["scenarios"]["confirmation"][0]["id"]
        put_json(path, rows)
        reseal(self.copy)
        with self.assertRaisesRegex(ValueError, "held-out"):
            auditor.verify(self.copy)

    def test_duplicate_profile_and_cross_split_identity_are_rejected(self):
        plan = json.loads((self.copy / "PLAN.json").read_bytes())
        original = copy.deepcopy(plan)
        plan["profiles"].append(copy.deepcopy(plan["profiles"][0]))
        self.replace_plan(plan)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            auditor.verify(self.copy)
        leaked = copy.deepcopy(original["scenarios"]["train"][0])
        leaked["id"] = leaked["id"].replace("train-", "confirmation-", 1)
        original["scenarios"]["confirmation"] = [leaked]
        self.replace_plan(original)
        with self.assertRaisesRegex(ValueError, "cross-split"):
            auditor.verify(self.copy)

    def test_self_consistent_checkpoint_cannot_replace_the_other_training_run(self):
        target = next((self.copy / "checkpoints").glob("*-actor_critic.json"))
        source = next((self.copy / "checkpoints").glob("*-distillation.json"))
        target.write_bytes(source.read_bytes())
        reseal(self.copy)
        with self.assertRaisesRegex(ValueError, "training identity"):
            auditor.verify(self.copy)

    def test_jsonl_nonfinite_and_duplicate_fields_are_rejected(self):
        path, rows = self.result_rows()
        rows[0]["value"] = float("nan")
        self.put_results(path, rows)
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            auditor.verify(self.copy)
        path.write_bytes(next(self.original.glob("results-*.jsonl")).read_bytes())
        lines = path.read_bytes().splitlines()
        lines[0] = lines[0][:-1] + b',"id":"duplicate"}'
        path.write_bytes(b"\n".join(lines) + b"\n")
        reseal(self.copy)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            auditor.verify(self.copy)

    def test_reconciled_but_wrong_compute_charge_is_rejected(self):
        path, rows = self.rollouts()
        rows[0]["path"][0]["controller_cost"] += 1
        rows[0]["controller_cost"] += 1
        self.put_rollouts(path, rows)
        with self.assertRaisesRegex(ValueError, "computation charge"):
            auditor.verify(self.copy)

    def test_forged_kernel_probability_is_rejected(self):
        path, rows = self.rollouts()
        rows[0]["path"][0]["probability"] = "0"
        self.put_rollouts(path, rows)
        with self.assertRaisesRegex(ValueError, "joint kernel"):
            auditor.verify(self.copy)

    def test_router_cannot_switch_to_another_self_consistent_fast_reference(self):
        path = next((self.copy / "routers").glob("*.json"))
        record = json.loads(path.read_bytes())
        other = json.loads(
            next((self.copy / "checkpoints").glob("*-distillation.json")).read_bytes()
        )
        for field in ("parameters_sha256", "checkpoint_sha256"):
            record["fast_" + field] = other[field]
            record["training"]["fast_" + field] = other[field]
        record.pop("checkpoint_sha256")
        record["checkpoint_sha256"] = _sha(record)
        put_json(path, record)
        reseal(self.copy)
        with self.assertRaisesRegex(ValueError, "Router is not bound"):
            auditor.verify(self.copy)

    def test_summary_cannot_cherry_pick_original_metrics(self):
        path = self.copy / "REPORT.json"
        report = json.loads(path.read_bytes())
        report["summary"][0]["value"] += 0.1
        put_json(path, report)
        reseal(self.copy)
        with self.assertRaisesRegex(ValueError, "summary"):
            auditor.verify(self.copy)


if __name__ == "__main__":
    unittest.main()

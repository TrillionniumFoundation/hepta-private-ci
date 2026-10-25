"""Adversarial provenance checks use nonmodel bytes; they assert no scientific gain."""

from concurrent.futures import ThreadPoolExecutor
import copy
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from . import io
from .evaluate import LEDGER_NAME, claim_final, evaluate, read_final_once
from .gates import verify_model_seal, verify_training
from .harness import exact_owner, launch
from .infer import compare_replay
from .models import verify_bootstrap
from .test_support import plan, reseal, rewrite, source_ids, synthetic_data, synthetic_generation
from .data_prepare import planned_cases


class ProvenanceTests(unittest.TestCase):
    def test_altered_base_schedule_and_source_fail_even_after_resealing(self):
        for field in ("batch_action_schedule_sha256", "source_manifest_sha256", "initial_parameter_sha256", "fresh_generation_id"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                owner, p = Path(tmp), plan(Path(tmp))
                synthetic_generation(owner, p)
                root = owner / "bootstrap"
                path = root / "seed-17-supervised-training.json"
                report = io.read_json(path)
                report[field] = "synthetic-wrong"
                rewrite(path, report)
                reseal(root, "bootstrap-seal.json")
                with self.assertRaises(ValueError):
                    verify_bootstrap(root, p)

    def test_missing_base_gate_and_observer_cannot_hide_by_resealing(self):
        for stage, name in (("bootstrap", "seed-43-supervised.pt"), ("bootstrap", "audit-observer.pt"),
                            ("training", "seed43-b1g1.pt")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                owner, p = Path(tmp), plan(Path(tmp))
                synthetic_generation(owner, p)
                (owner / stage / name).unlink()
                reseal(owner / stage, "bootstrap-seal.json" if stage == "bootstrap" else "training-seal.json")
                with self.assertRaises(ValueError):
                    verify_model_seal(p)

    def test_fresh_generation_must_not_claim_historical_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner, p = Path(tmp), plan(Path(tmp))
            synthetic_generation(owner, p)
            path = owner / "bootstrap" / "bootstrap.json"
            report = io.read_json(path)
            report["historical_weights_loaded"] = True
            rewrite(path, report)
            reseal(path.parent, "bootstrap-seal.json")
            with self.assertRaises(ValueError):
                verify_bootstrap(path.parent, p)

    def test_observer_selection_source_overlap_and_alias_fail(self):
        for mutation in ("selection", "source", "alias"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                owner, p = Path(tmp), plan(Path(tmp))
                synthetic_generation(owner, p)
                root = owner / "bootstrap"
                path = root / ("bootstrap.json" if mutation == "alias" else "audit-observer.json")
                report = io.read_json(path)
                if mutation == "selection":
                    report["selected_by_calibration"] = True
                elif mutation == "source":
                    report["source_ids_sha256"] = io.read_json(root / "reward-observer.json")["source_ids_sha256"]
                else:
                    report["observers"]["audit"]["path"] = "reward-observer.pt"
                rewrite(path, report)
                reseal(root, "bootstrap-seal.json")
                with self.assertRaises(ValueError):
                    verify_bootstrap(root, p)

    def test_gate_schedule_utility_and_parent_generation_are_required(self):
        for field in ("gate_update_schedule_sha256", "utility_table", "fresh_generation_id", "base_sha256"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                owner, p = Path(tmp), plan(Path(tmp))
                synthetic_generation(owner, p)
                path = owner / "training" / "seed17-b0g1-training.json"
                report = io.read_json(path)
                report[field] = [[99]] if field == "utility_table" else "synthetic-wrong"
                rewrite(path, report)
                reseal(path.parent, "training-seal.json")
                with self.assertRaises(ValueError):
                    verify_training(path.parent, p)

    def test_append_only_generation_seal_cannot_omit_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner, p = Path(tmp), plan(Path(tmp))
            synthetic_generation(owner, p)
            before = verify_model_seal(p)
            with self.assertRaises(FileExistsError):
                io.write(owner / "model-seal.json", before)
            changed = copy.deepcopy(before)
            changed["model_files"].pop("training/seed43-b1g1.pt")
            rewrite(owner / "model-seal.json", changed)
            with self.assertRaises(ValueError):
                verify_model_seal(p)

    def test_every_gate_recipe_field_is_checked_after_resealing(self):
        for field, value in (("seed", 999), ("fit_split", "validation"), ("batch_seed", 7),
                             ("content_plan_metric_sha256", "wrong-metric"),
                             ("content_plan_scenario_count", 99), ("content_plan_risk_aversion", 99)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                owner, p = Path(tmp), plan(Path(tmp))
                synthetic_generation(owner, p)
                path = owner / "training" / "seed17-b0g1-training.json"
                report = io.read_json(path)
                report[field] = value
                rewrite(path, report)
                reseal(path.parent, "training-seal.json")
                with self.assertRaises(ValueError):
                    verify_training(path.parent, p)

    def test_output_owner_relative_symlink_and_copy_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner = Path(tmp) / "owner"
            owner.mkdir()
            p = plan(owner)
            synthetic_data(owner, p)
            self.assertEqual(exact_owner(p, str(owner)), owner)
            alternate = Path(tmp) / "alternate"
            alternate.mkdir()
            alias = Path(tmp) / "alias"
            alias.symlink_to(owner, target_is_directory=True)
            for path in (alternate, alias, Path("relative-owner")):
                with self.assertRaises(ValueError):
                    exact_owner(p, str(path))
                with self.assertRaises(ValueError):
                    io.validate_data(path / "data", p)

    def test_exposed_or_reserved_source_blocks_without_resampling(self):
        p, ids = plan(), source_ids()
        cases, reserve = planned_cases(p, ids)
        self.assertNotIn(ids["future"][1800], reserve["future"])
        self.assertIn(ids["future"][700], reserve["future"])
        p["exposed_source_pixels"].append(cases[0]["source_ids"][0].split(":")[-1])
        with self.assertRaises(ValueError):
            planned_cases(p, ids)
        p = plan()
        p["case_ranges"]["retention"]["offset"] = 450
        with self.assertRaises(ValueError):
            planned_cases(p, ids)

    def test_independent_replay_rejects_state_action_and_output_changes(self):
        rows = [{"seed": 17, "fixed_suffix": ["refine_image"], "output_sha256": {"image": "a"}, "cost": 1}]
        states = np.zeros((1, 4, 384), np.float32)
        replay = copy.deepcopy(rows)
        replay[0]["cost"] = 2
        compare_replay(rows, states, replay, states.copy())
        for field, value in (("fixed_suffix", ["couple"]), ("output_sha256", {"image": "b"})):
            changed = copy.deepcopy(replay)
            changed[0][field] = value
            with self.assertRaises(ValueError):
                compare_replay(rows, states, changed, states)
        changed = states.copy()
        changed[0, 0, 0] = 1
        with self.assertRaises(ValueError):
            compare_replay(rows, states, rows, changed)

    def test_final_ledger_concurrency_and_failure_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            binding = {"source_owner_directory": tmp, "synthetic": True}
            def attempt(_):
                try:
                    claim_final(data, binding)
                    return True
                except FileExistsError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(attempt, range(2))), [False, True])
            with self.assertRaises(FileExistsError):
                claim_final(data, binding)
            self.assertTrue(io.read_json(data / LEDGER_NAME)["failure_consumes_sources"])
            payload = data / "final-targets.npz"
            record = io.arrays(payload, pixels=np.zeros((90, 1, 28, 56), np.float32), labels=np.zeros((90, 2), np.int64))
            self.assertEqual(read_final_once(payload, record)[1].shape, (90, 2))
            with self.assertRaises(ValueError):
                read_final_once(payload, {**record, "sha256": "0" * 64})

    def test_failed_environment_gate_never_claims_final(self):
        module = importlib.import_module(evaluate.__module__)
        with tempfile.TemporaryDirectory() as tmp:
            owner, p = Path(tmp), plan(Path(tmp))
            protocol = owner / "protocol.json"
            io.write(protocol, p)
            with patch.object(module, "published_source", return_value={}), \
                 patch.object(module, "cpu_environment", side_effect=ValueError("synthetic environment rejection")), \
                 patch.object(module, "claim_final") as claim:
                with self.assertRaises(ValueError):
                    evaluate(owner / "data", owner / "training", owner / "inference", owner / "replay", protocol,
                             "synthetic-only", owner / "evaluation")
                claim.assert_not_called()
            self.assertFalse((owner / "data" / LEDGER_NAME).exists())

    def test_forbidden_final_payload_access_is_rejected_in_child_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final-targets.npz"
            path.write_bytes(b"synthetic")
            import subprocess
            code = f"import sys; from {__package__}.io import deny_final; sys.addaudithook(deny_final); open(sys.argv[1], 'rb')"
            result = subprocess.run([sys.executable, "-c", code, str(path)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PermissionError", result.stderr)


class ResourceHarnessTests(unittest.TestCase):
    def test_failure_cost_and_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = launch("synthetic-failure", [sys.executable, "-c", "print('synthetic'); raise SystemExit(3)"],
                            root, root, os.environ.copy(), time.monotonic() + 10, plan()["resource_budget"])
            self.assertEqual(result["returncode"], 3)
            self.assertIsNotNone(result["failure"])
            self.assertGreater(result["cpu_ns_including_import_and_exit"], 0)
            self.assertEqual(result["automatic_retries"], 0)
            self.assertIn("synthetic", (root / "synthetic-failure.log").read_text())

    def test_expired_total_budget_prevents_stage_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = launch("synthetic-expired", [sys.executable, "-c", "raise AssertionError('must not launch')"],
                            root, root, os.environ.copy(), time.monotonic() - 1, plan()["resource_budget"])
            self.assertEqual(result["failure"]["type"], "TimeoutError")
            self.assertIsNone(result["returncode"])
            self.assertFalse((root / "synthetic-expired.log").exists())

    def test_evidence_budget_failure_preserves_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            budget = {**plan()["resource_budget"], "maximum_new_evidence_bytes": 1}
            result = launch("synthetic-size", [sys.executable, "-c", "print('over budget')"],
                            root, root, os.environ.copy(), time.monotonic() + 10, budget)
            self.assertEqual(result["failure"]["type"], "OSError")
            self.assertTrue((root / "synthetic-size.log").is_file())


if __name__ == "__main__":
    unittest.main()

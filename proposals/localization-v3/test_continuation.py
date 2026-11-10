"""Synthetic epoch-boundary recovery fixtures; no scientific training credit.

Run with HCSN_S4_REPO pointing to the exact official checkout. These tests
inject an explicitly synthetic, hash-checked reader instead of inventing an
official UCI manifest. The training and continuation implementations are real.
"""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import torch


HERE = Path(__file__).resolve().parent


def local_module(name, filename):
    # Official S4 also has a top-level train.py; never resolve it by sys.path.
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRAIN = local_module("hcsn_original_train_for_continuation_test", "train.py")
CONTINUATION = local_module("hcsn_continuation_for_test", "continuation.py")
GRID = {
    "active_cells": 8,
    "endpoint": 2.4,
    "phase_cells": 4,
    "refractory": 0.2,
    "tail_rate": 1.0,
    "quadrature_order": 8,
    "initial_log_std": 0.08,
}
PLIF = {
    "init_tau": 3.0,
    "threshold": 0.7,
    "input_weight_gain": 1.5,
    "readout": "spike_trace",
    "trace_decay": 0.75,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return digest(path)


class ContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hcsn-continuation-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.prepared = self.root / "explicit-synthetic-fixture"
        self.prepared.mkdir()
        entries = []
        for index, length in enumerate((3, 4, 5, 3, 4, 4, 3)):
            partition = "train" if index < 5 else "dev"
            subject = "ABC"[index % 3] if partition == "train" else "D"
            row = {"id": f"{subject}-synthetic-{index}", "x": [], "dt": [], "y": []}
            for step in range(length):
                dt = 0.0 if step == 0 else (0.01, 0.02, 0.04)[step % 3]
                tag = (index + step) % 4
                values, mask = [0.0] * 12, [0.0] * 12
                for axis in range(3):
                    values[3 * tag + axis] = math.sin(index + step + axis / 3)
                    mask[3 * tag + axis] = 1.0
                row["x"].append(values + mask + [math.log1p(dt)])
                row["dt"].append(dt)
                row["y"].append((3 * index + step) % 11)
            filename = f"episode-{index}.json"
            entries.append(
                {
                    "path": filename,
                    "partition": partition,
                    "sha256": write_json(self.prepared / filename, row),
                }
            )
        frontend_sha = write_json(self.prepared / "frontend.json", {"synthetic": True})
        self.manifest_sha = write_json(
            self.prepared / "data-manifest.json",
            {
                "schema": "explicit-synthetic-continuation-fixture-v1",
                "mode": "all-development",
                "scientific_training_credit": False,
                "frontend_sha256": frontend_sha,
                "episodes": entries,
            },
        )

    def read_fixture(self, prepared, expected_sha):
        root = Path(prepared)
        if root != self.prepared or digest(root / "data-manifest.json") != expected_sha:
            raise ValueError("synthetic fixture manifest identity mismatch")
        manifest = json.loads((root / "data-manifest.json").read_bytes())
        if digest(root / "frontend.json") != manifest["frontend_sha256"]:
            raise ValueError("synthetic frontend changed")
        data = {"train": [], "dev": []}
        for entry in manifest["episodes"]:
            path = root / entry["path"]
            if digest(path) != entry["sha256"]:
                raise ValueError("synthetic episode changed")
            data[entry["partition"]].append(json.loads(path.read_bytes()))
        return data, json.loads((root / "frontend.json").read_bytes()), manifest

    def arguments(self, output, arm="gru", max_epochs=2, **changes):
        values = dict(
            prepared=str(self.prepared),
            manifest_sha256=self.manifest_sha,
            output=str(output),
            arm=arm,
            seed=101,
            width=4,
            batch_size=2,
            micro_batch_size=1,
            learning_rate=0.003,
            min_epochs=1,
            max_epochs=max_epochs,
            patience=1000,
            plateau_delta=0.002,
            memorization_updates=0,
            memorization_check_every=64,
            wall_seconds=14370.0,
            rss_bytes=8 * 1024**3,
            threads=1,
            quality_threshold=0.3,
            s4_repo=os.environ.get("HCSN_S4_REPO"),
            plif_config_json=PLIF if arm == "snn_plif" else None,
            hcsn_grid_json=GRID if arm == "hcsn" else None,
            trace_records=4096,
            trace_bytes=32 * 1024**2,
            cache_frozen_tables=arm == "hcsn",
            train_shared=False,
            learn_core_adapter=True,
        )
        return argparse.Namespace(**(values | changes))

    def run_original(self, args, metrics=None):
        torch.manual_seed(99173)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(TRAIN, "read_episodes", self.read_fixture)
            )
            stack.enter_context(mock.patch.object(torch, "set_num_interop_threads"))
            stack.enter_context(
                mock.patch.object(TRAIN, "PROCESS_STARTED", time.monotonic())
            )
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if metrics is not None:
                stack.enter_context(mock.patch.object(TRAIN, "metrics", metrics))
            started = time.monotonic()
            code = TRAIN.fit(args)
        directory = Path(args.output)
        report = json.loads((directory / "result.json").read_bytes())
        self.assertEqual(code, 0, report.get("error"))
        self.assertEqual(report["status"], "completed_development")
        self.assertTrue(report["source_unchanged"])
        self.assertTrue(report["common_weights_unchanged"])
        outer = directory.with_suffix(".outer.json")
        write_json(
            outer,
            {
                "name": directory.name,
                "status": "completed",
                "returncode": 0,
                "fit_status": "completed_development",
                "result_sha256": digest(directory / "result.json"),
                "whole_process_wall_seconds": time.monotonic() - started,
                "hard_wall_seconds": 14400.0,
                "source_unchanged": True,
                "common_weights_unchanged": True,
            },
        )
        return directory, outer, report

    def continuation_args(self, parent, outer, output, max_epochs=4, **changes):
        return argparse.Namespace(
            **(
                dict(
                    parent_dir=str(parent),
                    parent_outer_record=str(outer),
                    output=str(output),
                    max_epochs=max_epochs,
                    total_wall_seconds=14400.0,
                )
                | changes
            )
        )

    def run_continuation(self, args, metrics=None):
        # Restoration must not accidentally depend on the caller's random state.
        torch.manual_seed(41827)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(CONTINUATION, "read_episodes", self.read_fixture)
            )
            stack.enter_context(mock.patch.object(torch, "set_num_interop_threads"))
            stack.enter_context(
                mock.patch.object(CONTINUATION, "PROCESS_STARTED", time.monotonic())
            )
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if metrics is not None:
                stack.enter_context(mock.patch.object(CONTINUATION, "metrics", metrics))
            return CONTINUATION.continue_fit(args)

    def assert_nested_equal(self, left, right, path="checkpoint"):
        if torch.is_tensor(left):
            self.assertTrue(torch.is_tensor(right), path)
            self.assertEqual(left.dtype, right.dtype, path)
            self.assertTrue(torch.equal(left, right), path)
        elif isinstance(left, dict):
            self.assertEqual(left.keys(), right.keys(), path)
            for name in left:
                self.assert_nested_equal(left[name], right[name], f"{path}.{name}")
        elif isinstance(left, (tuple, list)):
            self.assertEqual(type(left), type(right), path)
            self.assertEqual(len(left), len(right), path)
            for index, (a, b) in enumerate(zip(left, right)):
                self.assert_nested_equal(a, b, f"{path}[{index}]")
        else:
            self.assertEqual(left, right, path)

    def assert_checkpoint_equal(self, left, right):
        first, second = [torch.load(path, weights_only=False) for path in (left, right)]
        for name in (
            "model",
            "model_configuration",
            "optimizer",
            "torch_rng",
            "order_rng",
            "epochs_completed",
            "main_updates",
            "data_manifest_sha256",
        ):
            self.assert_nested_equal(first[name], second[name], name)

    def exact_continuation(self, arm):
        parent, outer, _ = self.run_original(
            self.arguments(self.root / f"{arm}-two", arm)
        )
        original_files = {p.name: digest(p) for p in parent.iterdir() if p.is_file()}
        full, _, full_report = self.run_original(
            self.arguments(self.root / f"{arm}-four", arm, 4)
        )
        resumed = self.root / f"{arm}-continued"
        result = self.run_continuation(self.continuation_args(parent, outer, resumed))
        self.assertEqual(result["status"], "completed_development", result.get("error"))
        self.assertEqual(result["cumulative_epochs_completed"], 4)
        self.assert_checkpoint_equal(full / "last.pt", resumed / "last.pt")
        self.assert_checkpoint_equal(full / "best.pt", resumed / "best.pt")
        self.assertEqual(
            original_files, {p.name: digest(p) for p in parent.iterdir() if p.is_file()}
        )
        last = torch.load(resumed / "last.pt", weights_only=False)
        self.assertEqual(last["main_updates"], 12)
        self.assertEqual(full_report["main_updates"], 12)
        self.assertTrue(result["source_unchanged"])
        self.assertTrue(result["common_weights_unchanged"])
        if arm == "ssm_s4d":
            groups = last["optimizer"]["param_groups"]
            # This pinned adapter leaves S4's optional kernel LR unset. Its
            # zero-decay hints merge with the study's global zero decay.
            self.assertEqual({group["lr"] for group in groups}, {0.003})
            names = [
                name
                for group in full_report["optimizer_groups"]
                for name in group["parameter_names"]
            ]
            self.assertTrue(
                {
                    "core.kernel.log_dt",
                    "core.kernel.log_A_real",
                    "core.kernel.A_imag",
                }.issubset(names)
            )
        if arm == "snn_plif":
            self.assertEqual(last["model_configuration"]["plif_configuration"], PLIF)
        if arm == "hcsn":
            self.assertEqual(last["model_configuration"]["hcsn_grid"], GRID)

    def test_gru_epoch_boundary_is_bitwise_identical(self):
        self.exact_continuation("gru")

    def test_attention_epoch_boundary_is_bitwise_identical(self):
        self.exact_continuation("attention")

    def test_plif_trace_configuration_and_optimizer_are_restored(self):
        self.exact_continuation("snn_plif")

    def test_hcsn_cold_cache_rebuild_preserves_exact_updates(self):
        self.exact_continuation("hcsn")

    @unittest.skipUnless(
        os.environ.get("HCSN_S4_REPO"), "requires pinned official S4 checkout"
    )
    def test_official_s4_optimizer_groups_are_restored(self):
        self.exact_continuation("ssm_s4d")

    def test_plateau_anchor_counts_significant_improvement_not_running_best(self):
        rows = [
            {"epoch": i, "development": {"macro_f1_11_classes": score}}
            for i, score in enumerate((0.3, 0.301, 0.3025, 0.303, 0.3035), 1)
        ]
        self.assertEqual(
            CONTINUATION.plateau_state(rows, 0.002), (0.3035, 5, 0.3025, 2)
        )

    def test_inherited_stale_epochs_stop_on_time_and_keep_old_best(self):
        original_metrics = TRAIN.metrics

        def constant_score(logits, labels):
            return original_metrics(logits, labels) | {"macro_f1_11_classes": 0.4}

        parent, outer, report = self.run_original(
            self.arguments(self.root / "plateau-two", patience=3), constant_score
        )
        self.assertEqual(report["best_epoch"], 1)
        inherited_best = digest(parent / "best.pt")
        full, _, full_report = self.run_original(
            self.arguments(self.root / "plateau-full", max_epochs=6, patience=3),
            constant_score,
        )
        resumed = self.root / "plateau-continued"
        result = self.run_continuation(
            self.continuation_args(parent, outer, resumed, max_epochs=6), constant_score
        )
        self.assertEqual(result["status"], "completed_development", result.get("error"))
        self.assertEqual(result["stop_reason"], "development_plateau")
        self.assertEqual(
            result["cumulative_epochs_completed"], len(full_report["epochs"])
        )
        self.assertEqual(result["cumulative_epochs_completed"], 4)
        self.assertEqual([row["epoch"] for row in result["epochs"]], [3, 4])
        self.assertEqual(digest(resumed / "best.pt"), inherited_best)
        self.assertEqual(digest(parent / "best.pt"), inherited_best)
        self.assert_checkpoint_equal(full / "last.pt", resumed / "last.pt")

    def test_tampered_or_missing_parent_artifacts_fail_before_output_creation(self):
        parent, outer, _ = self.run_original(
            self.arguments(self.root / "tamper-parent")
        )
        for filename in ("last.pt", "plan.json", "result.json", "best.pt"):
            with self.subTest(filename=filename):
                path, output = parent / filename, self.root / f"reject-{filename}"
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"tampered")
                    with self.assertRaises(ValueError):
                        self.run_continuation(
                            self.continuation_args(parent, outer, output)
                        )
                    self.assertFalse(output.exists())
                finally:
                    path.write_bytes(original)
        last = parent / "last.pt"
        original = last.read_bytes()
        last.unlink()
        try:
            output = self.root / "reject-no-last"
            with self.assertRaises(ValueError):
                self.run_continuation(self.continuation_args(parent, outer, output))
            self.assertFalse(output.exists())
        finally:
            last.write_bytes(original)

    def test_bound_partial_parent_cannot_resume_from_an_old_complete_epoch(self):
        parent, outer, report = self.run_original(
            self.arguments(self.root / "partial-parent")
        )
        report["status"] = "budget_exhausted"
        report["main_updates"] += 1
        write_json(parent / "result.json", report)
        row = json.loads(outer.read_bytes())
        row["result_sha256"] = digest(parent / "result.json")
        write_json(outer, row)
        output = self.root / "reject-partial"
        with self.assertRaises(ValueError):
            self.run_continuation(self.continuation_args(parent, outer, output))
        self.assertFalse(output.exists())

    def test_rehashed_checkpoint_cannot_replace_non_tensor_dynamics_configuration(self):
        parent, outer, report = self.run_original(
            self.arguments(self.root / "configuration-parent", "snn_plif")
        )
        payload = torch.load(parent / "last.pt", weights_only=False)
        payload["model_configuration"]["plif_configuration"]["threshold"] = 1.4
        torch.save(payload, parent / "last.pt")
        # Rebinding the file identities must not bypass consistency with the
        # original plan: threshold is not present in the model tensor state.
        report["last_checkpoint_sha256"] = digest(parent / "last.pt")
        report["model_configuration"] = payload["model_configuration"]
        write_json(parent / "result.json", report)
        row = json.loads(outer.read_bytes())
        row["result_sha256"] = digest(parent / "result.json")
        write_json(outer, row)
        output = self.root / "reject-configuration"
        with self.assertRaises(ValueError):
            self.run_continuation(self.continuation_args(parent, outer, output))
        self.assertFalse(output.exists())

    def test_changed_data_and_consumed_outer_budget_are_not_new_fit_opportunities(self):
        parent, outer, _ = self.run_original(
            self.arguments(self.root / "budget-parent")
        )
        episode = self.prepared / "episode-0.json"
        original = episode.read_bytes()
        episode.write_bytes(original + b" ")
        try:
            output = self.root / "reject-data"
            with self.assertRaises(ValueError):
                self.run_continuation(self.continuation_args(parent, outer, output))
            self.assertFalse(output.exists())
        finally:
            episode.write_bytes(original)
        row = json.loads(outer.read_bytes())
        row["whole_process_wall_seconds"] = 14400.0
        write_json(outer, row)
        output = self.root / "reject-budget"
        with self.assertRaises(ValueError):
            self.run_continuation(self.continuation_args(parent, outer, output))
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

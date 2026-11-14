"""Diagnostic binding/retention integration on hand metadata and arrays only."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from independent import run
from independent import training_diagnostic as diagnostic
from independent.evaluation import measure
from independent.training_diagnostic import digest, encoded, runtime_context
from model import JointModel


class CodecEngineTests(unittest.TestCase):
    def slot_fixture(self, directory):
        root = Path(directory)
        stage = root / "training_diagnostics/codec-d1"
        stage.mkdir(parents=True)
        output = root / "runs/codec-diagnostic"
        output.mkdir(parents=True)
        order = ["rowwise-png-v1", "local-png-codebook-v1", "local-png-codebook-v1", "rowwise-png-v1"]
        plan = {"training_diagnostic": {"output_root": "runs/codec-diagnostic", "build_order": order}}
        frozen = {"source_commit": "source", "plan_sha256": "plan"}
        start = {"schema": "hepta.codec-train-once.v1", "experiment_id": "codec-train-d1",
                 **frozen, "freeze_sha256": "freeze", "build_order": order, "cwd": str(root),
                 "output": str(output), "qualification_eligible": False}
        return root, stage, output, order, plan, frozen, start

    def test_slot_requires_master_fixed_identity_and_exclusive_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, stage, output, order, plan, frozen, start = self.slot_fixture(temporary)
            own = output / ("slot-0-" + order[0])
            with patch.object(diagnostic, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "START"):
                    diagnostic.begin_slot(plan, frozen, "freeze", own, order[0], 0)
                self.assertFalse((stage / "SLOT-0.json").exists())
                (stage / "START.json").write_bytes(encoded({**start, "source_commit": "different"}))
                with self.assertRaisesRegex(ValueError, "identity"):
                    diagnostic.begin_slot(plan, frozen, "freeze", own, order[0], 0)
                (stage / "START.json").write_bytes(encoded(start))
                with self.assertRaisesRegex(ValueError, "path"):
                    diagnostic.begin_slot(plan, frozen, "freeze", output / "different", order[0], 0)
                receipt = diagnostic.begin_slot(plan, frozen, "freeze", own, order[0], 0)
                self.assertEqual(receipt, json.loads((stage / "SLOT-0.json").read_text()))
                self.assertFalse(own.exists())
                with self.assertRaises(FileExistsError):
                    diagnostic.begin_slot(plan, frozen, "freeze", own, order[0], 0)
                self.assertEqual(receipt["master_start_sha256"], digest(stage / "START.json"))

    def test_later_slot_requires_previous_valid_completion_and_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, stage, output, order, plan, frozen, start = self.slot_fixture(temporary)
            (stage / "START.json").write_bytes(encoded(start))
            own = output / ("slot-1-" + order[1])
            execution = output / "slot-0-execution.json"
            audit = output / "audit-through-slot-0.json"
            result = {"slot_index": 0, "codec_variant": order[0], "exit_code": 2}
            checked = {"schema": "hepta.codec-train-artifact-audit.v1", "qualification_eligible": False,
                       "formal_data_accessed": False}
            with patch.object(diagnostic, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "previous"):
                    diagnostic.begin_slot(plan, frozen, "freeze", own, order[1], 1)
                execution.write_bytes(encoded(result))
                audit.write_bytes(encoded(checked))
                for code in (1, -9, True):
                    execution.write_bytes(encoded({**result, "exit_code": code}))
                    with self.subTest(code=code), self.assertRaisesRegex(ValueError, "previous"):
                        diagnostic.begin_slot(plan, frozen, "freeze", own, order[1], 1)
                execution.write_bytes(encoded(result))
                receipt = diagnostic.begin_slot(plan, frozen, "freeze", own, order[1], 1)
                self.assertEqual(receipt["previous"], {"execution_sha256": digest(execution),
                                                      "audit_sha256": digest(audit)})
                self.assertFalse(own.exists())

    def fixture(self, root):
        plan = {"model_seeds": [11, 23, 47], "training_diagnostic": {"build_order": [
            "rowwise-png-v1", "local-png-codebook-v1", "local-png-codebook-v1", "rowwise-png-v1"]}}
        frozen = {"plan_sha256": "plan", "source_commit": "source", "sources": {"a.py": "a"}}
        raw = [{"per_row_cost": {"cpu_ns": [1., 2., 3.]}} for _ in range(3)]
        first = {**frozen, "experiment_id": "codec-train-d1", "freeze_sha256": "freeze",
                 "training_diagnostic": {"build_index": 0, "codec_variant": "rowwise-png-v1"},
                 "common": {"calibrations": {"11": {"raw_repeats": {"full": raw}}},
                            "reference_full_cpu_ns": 2., "observed_reference_full_cpu_ns": 2.}}
        selected = root / "first-selection.json"
        selected.write_bytes(encoded(first))
        reference = {"schema": "hepta.codec-train-reference.v1", "experiment_id": "codec-train-d1",
            "plan_sha256": "plan", "source_commit": "source", "freeze_sha256": "freeze",
            "first_selection_path": str(selected), "first_selection_sha256": digest(selected),
            "reference_full_cpu_ns": 2.}
        path = root / "reference.json"
        path.write_bytes(encoded(reference))
        return plan, frozen, first, selected, reference, path

    def test_reference_binds_exact_first_slot_raw_median_and_effective_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, frozen, first, selection, receipt, path = self.fixture(Path(directory))
            original = copy.deepcopy(plan)
            effective, context = runtime_context(plan, frozen, "freeze", "local-png-codebook-v1", 1, path)
            self.assertEqual(plan, original)
            self.assertEqual(context["reference_binding"]["receipt"], receipt)
            self.assertEqual(effective["diagnostic_reference"]["receipt"]["reference_full_cpu_ns"], 2.)
            self.assertEqual(context["effective_plan_sha256"], hashlib.sha256(encoded(effective)).hexdigest())
            for variant, index, source in (("local-png-codebook-v1", 0, None),
                                           ("rowwise-png-v1", True, None),
                                           ("local-png-codebook-v1", 1, None),
                                           ("rowwise-png-v1", 0, path)):
                with self.subTest(index=index, source=source), self.assertRaises(ValueError):
                    runtime_context(plan, frozen, "freeze", variant, index, source)
            for key, value in (("source_commit", "different"), ("reference_full_cpu_ns", 1.)):
                changed = {**receipt, key: value}
                path.write_bytes(encoded(changed))
                with self.assertRaises(ValueError):
                    runtime_context(plan, frozen, "freeze", "local-png-codebook-v1", 1, path)
            path.write_bytes(encoded(receipt))
            first["training_diagnostic"]["build_index"] = 3
            selection.write_bytes(encoded(first))
            receipt["first_selection_sha256"] = digest(selection)
            path.write_bytes(encoded(receipt))
            with self.assertRaisesRegex(ValueError, "first frozen"):
                runtime_context(plan, frozen, "freeze", "local-png-codebook-v1", 1, path)

    def test_live_measure_trace_is_same_actual_output_and_rng_for_both_codecs(self):
        model = JointModel(202, 12, 192, hidden=4, seed=514)
        manual = {"full": np.random.default_rng(170).uniform(0, 1, (3, 202)), "labels": [0, 1, 2]}
        plan = {"experiment_id": "codec-train-d1", "compute_price": .02, "runtime_batch_size": 2}
        reports = [measure(model, None, "full", manual, {**plan, "output_codec_profile": profile},
                           1000, seed=11, observe=False, capture_outputs=True)
                   for profile in ("rowwise-png-v1", "local-png-codebook-v1")]
        traces = [report["_diagnostic_output_trace"] for report in reports]
        self.assertEqual(traces[0], traces[1])
        self.assertEqual(len(traces[0]["outputs"]), 3)
        self.assertEqual([batch["rows"] for batch in traces[0]["batches"]], [2, 1])
        self.assertNotEqual(traces[0]["sample_rng_before"], traces[0]["sample_rng_after"])
        self.assertEqual(traces[0]["route_rng_before"], traces[0]["route_rng_after"])
        for report, trace in zip(reports, traces):
            self.assertEqual(report["sampled_output"]["png_sha256"], trace["outputs"][0]["png_sha256"])
            self.assertEqual(report["means"], {})
        with self.assertRaisesRegex(ValueError, "TRAIN-only"):
            measure(model, None, "full", manual, {"compute_price": .02}, 1, capture_outputs=True)

    def test_cli_threads_fixed_variant_arguments_without_execution(self):
        args = ["engine", "train", "--experiment", "codec-train-d1", "--freeze", "f.json",
                "--out", "slot1", "--variant", "local-png-codebook-v1", "--build-index", "1",
                "--reference-receipt", "reference.json"]
        with patch.object(sys, "argv", args), patch.object(run, "train", return_value=2) as train:
            self.assertEqual(run.main(), 2)
        train.assert_called_once_with("f.json", "slot1", experiment="codec-train-d1",
            variant="local-png-codebook-v1", build_index=1, reference_receipt="reference.json")

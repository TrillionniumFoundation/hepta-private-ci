"""Handmade source/model fixtures and service doubles; no experiment dataset."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from model import JointModel
from independent.accounting import WorkLedger
from independent.core_claims import METRICS, SYSTEMS
from independent import evaluation


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CoreEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        (self.root / "independent").mkdir()
        core = self.root / "core_confirmation"
        core.mkdir()
        self.marker = core / "core-c1-test-opened.json"
        protocol = core / "PROTOCOL.md"
        protocol.write_text("# Handmade protocol fixture\n")
        self.plan = {"experiment_id": "core-c1", "systems": list(SYSTEMS),
            "static_modes": ["full"], "control_reserve_units": 0,
            "control_reserve_cpu_seconds": 0, "runtime_backend": "python", "hidden": 4,
            "model_seeds": [11, 23, 47], "cpu_seconds_per_system": 1,
            "operator_units_per_system": 10000, "compute_price": .02,
            "service_horizon": 100000, "runtime_batch_size": 2,
            "calibration_rows": 4, "calibration_repeats": 3,
            "bootstrap_replicates": 20, "bootstrap_seed": 77431,
            "maximum_greedy_drop": .02, "data_profile": {"manual_fixture": True},
            "protocol_path": "core_confirmation/PROTOCOL.md", "protocol_sha256": digest(protocol)}
        self.plan_path = core / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan))
        source_names = ("model.py", "utility.py", "data.py", "control.py",
            "independent/inference.py", "independent/accounting.py", "independent/evaluation.py",
            "independent/data_v2.py", "independent/run.py", "independent/learning.py",
            "independent/experiments.py", "independent/core_claims.py")
        for name in source_names:
            (self.root / name).write_text("# Handmade frozen source fixture\n")
        self.sources = {name: digest(self.root / name) for name in source_names}
        self.models, selected, measures = {}, [], {system: {} for system in SYSTEMS}
        for index, system in enumerate(SYSTEMS):
            for seed in self.plan["model_seeds"]:
                model = JointModel(202, 12, 192, hidden=4, seed=seed + 100 * index)
                name = system + "-" + str(seed) + ".npz"
                model.save(self.run / name)
                self.models[model.digest()] = index
                means = {metric: .1 * (index + 1) for metric in METRICS}
                selected.append({"system": system, "seed": seed, "mode": "full",
                    "model_file": name, "model_sha256": digest(self.run / name),
                    "model_digest": model.digest(), "build_cpu_ns": .1e9 / 3,
                    "reference_full_cpu_ns": 100000, "controller_file": None,
                    "validation": {"full": means}})
                measures[system][str(seed)] = {"mode": "full", "means": means,
                    "decoder_corruption_score_drop": .1, "budget_violations": 0}
        budget = {"total_cap": 10000, "consumed_units": 10,
            "prices": dict(WorkLedger("fixture").prices),
            "stages": {"search_train": {"consumed_units": 10, "model_forward_rows": 1}}}
        self.selection = {"experiment_id": "core-c1", "selection_ready": True,
            "cpu_budget_violations": [], "validation_service_budget_violations": 0,
            "plan": self.plan, "plan_sha256": digest(self.plan_path), "sources": self.sources,
            "source_commit": "handmade-fixture", "selected": selected,
            "validation_measures": measures, "efficient_reference": "ndu",
            "common": {"reference_full_cpu_ns": 100000, "calibrations": {
                str(seed): {"cpu_ns": {"full": 100000}, "raw_repeats": {"full": [
                    {"repeat": repeat, "sampling_seed": seed, "rows": 4, "mode": "full",
                     "observe": False, "budget_violations": 0,
                     "per_row_cost": {"cpu_ns": [100000] * 4}, "cost": {"cpu_ns": 400000}}
                    for repeat in range(3)]}} for seed in self.plan["model_seeds"]}},
            "budgets": {system: json.loads(json.dumps(budget)) for system in SYSTEMS},
            "system_cost": {system: {"cpu_seconds": .1} for system in SYSTEMS},
            "datasets": {split: {"manual_manifest": split} for split in ("train", "validation")}}
        self.write_selection()
        self.enterContext(patch.object(evaluation, "ROOT", self.root))
        self.enterContext(patch.object(evaluation.subprocess, "check_output", self.git_show))

    def write_selection(self):
        (self.run / "selection.json").write_text(json.dumps(self.selection))

    def git_show(self, command, **kwargs):
        relative = command[-1].split(":qualification/joint-generation/", 1)[1]
        return (self.root / relative).read_bytes()

    def handmade_data(self, split, profile, **kwargs):
        self.assertEqual(profile, {"manual_fixture": True})
        if split == "test":
            self.assertTrue(kwargs["allow_test"])
            self.assertTrue(self.marker.exists())
            self.assertTrue((self.run / "test-opened.json").exists())
        return {"split": split, "full": np.zeros((4, 202)), "labels": np.arange(4),
            "source_ids": [split + "-a", split + "-a", split + "-b", split + "-b"],
            "input_hashes": [hashlib.sha256((split + str(i)).encode()).hexdigest() for i in range(4)]}

    def fake_measure(self, model, controller, mode, data, runtime, reference, **kwargs):
        self.assertIsNone(controller)
        self.assertEqual(mode, "full")
        self.assertEqual(data["split"], "test")
        self.assertEqual(reference, 100000)
        self.assertEqual(runtime["build_work_units"], 10 / 3)
        level = .1 * (self.models[model.digest()] + 1)
        return {"mode": "full", "per_row": {metric: [level] * 4 for metric in METRICS},
            "means": {metric: level for metric in METRICS}, "budget_violations": 0,
            "decoder_corruption_score_drop": .1, "cost": {"cpu_ns": 40}}

    def doubles(self, measure=None):
        data = self.enterContext(patch.object(evaluation, "dataset", side_effect=self.handmade_data))
        self.enterContext(patch.object(evaluation, "manifest", side_effect=lambda data: {"manual_manifest": data["split"]}))
        measured = self.enterContext(patch.object(evaluation, "measure", side_effect=measure or self.fake_measure))
        return data, measured

    def assert_preflight_rejected(self, regex=None):
        self.write_selection()
        with patch.object(evaluation, "dataset", side_effect=AssertionError("sealed")) as data:
            with self.assertRaisesRegex(ValueError, regex or ".*"):
                evaluation.run_evaluation(self.run, "core-c1")
            data.assert_not_called()
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.run / "test-opened.json").exists())

    def test_fixed_identity_rejects_paths_objects_and_cross_profile_before_data(self):
        from independent.experiments import resolve_experiment
        with patch.object(evaluation, "dataset", side_effect=AssertionError("sealed")) as data:
            for identity in ("other", str(self.plan_path), resolve_experiment("core-c1", root=self.root)):
                with self.subTest(identity=str(identity)), self.assertRaises(ValueError):
                    evaluation.run_evaluation(self.run, identity)
            data.assert_not_called()
        self.selection["experiment_id"] = "efficient-r2"
        self.assert_preflight_rejected("identity")

    def test_core_fixed_marker_and_four_full_measurements_once_per_seed(self):
        r2_marker = self.root / "independent" / "efficient-r2-test-opened.json"
        r2_marker.write_text("preserved-r2-opening\n")
        data, measured = self.doubles()
        with patch.object(evaluation, "GLOBAL_MARKER", r2_marker):
            result = evaluation.run_evaluation(self.run, "core-c1")
        self.assertEqual([call.args[0] for call in data.call_args_list], ["train", "validation", "test"])
        self.assertEqual(measured.call_count, 12)
        self.assertEqual(result["schema"], "hepta.independent-core-confirmation-evaluation.v1")
        self.assertEqual(result["experiment_id"], "core-c1")
        self.assertTrue(result["benefit_verified"])
        self.assertEqual(len(result["gates"]["primary_intervals"]), 6)
        self.assertTrue(all("selected" not in row for row in result["all_system_results"]))
        self.assertEqual(r2_marker.read_text(), "preserved-r2-opening\n")
        self.assertEqual(json.loads(self.marker.read_text())["experiment_id"], "core-c1")
        artifact = result["test_artifact"]
        self.assertEqual(artifact["sha256"], digest(self.run / artifact["file"]))
        with np.load(self.run / artifact["file"], allow_pickle=False) as saved:
            np.testing.assert_array_equal(saved["full"], np.zeros((4, 202)))
            self.assertEqual(saved["source_ids"].tolist(), ["test-a", "test-a", "test-b", "test-b"])
            self.assertEqual(saved["input_hashes"].shape, (4,))
        self.assertEqual(json.loads((self.run / "test-result.json").read_text()), result)

    def test_source_plan_and_committed_protocol_bound_before_data(self):
        for defect in ("source", "plan", "protocol", "committed_protocol"):
            with self.subTest(defect=defect):
                if defect == "source":
                    path = self.root / "model.py"
                elif defect == "plan":
                    path = self.plan_path
                else:
                    path = self.root / "core_confirmation" / "PROTOCOL.md"
                original = path.read_bytes()
                if defect == "committed_protocol":
                    def changed(command, **kwargs):
                        value = self.git_show(command, **kwargs)
                        return value + b"changed" if command[-1].endswith("PROTOCOL.md") else value
                    with patch.object(evaluation.subprocess, "check_output", changed):
                        self.assert_preflight_rejected("protocol")
                else:
                    path.write_bytes(original + b"changed")
                    self.assert_preflight_rejected()
                    path.write_bytes(original)

    def test_model_cap_and_service_readiness_fail_before_opening(self):
        original = json.dumps(self.selection)
        for defect in ("model", "critic", "units", "cpu", "service", "row_service", "missing_seed", "readiness"):
            with self.subTest(defect=defect):
                self.selection = json.loads(original)
                if defect == "model": self.selection["selected"][-1]["model_sha256"] = "0" * 64
                elif defect == "critic": self.selection["selected"][-1]["controller_type"] = "unused"
                elif defect == "units": self.selection["budgets"]["ndu"]["consumed_units"] = 10001
                elif defect == "cpu": self.selection["system_cost"]["ndu"]["cpu_seconds"] = 1.01
                elif defect == "service": self.selection["validation_service_budget_violations"] = 1
                elif defect == "row_service": self.selection["validation_measures"]["ndu"]["47"]["budget_violations"] = 1
                elif defect == "missing_seed": self.selection["selected"].pop()
                else: self.selection["validation_measures"]["ndu"]["11"]["means"]["cpu_net_utility"] = -99
                self.assert_preflight_rejected()

    def test_reference_uses_flattened_raw_row_median_and_rejects_detached_values(self):
        full = self.selection["common"]["calibrations"]["11"]["raw_repeats"]["full"]
        for repeat, cpu in zip(full, ([100000, 100000, 100000, 200000],
                                     [100000, 100000, 100000, 200000],
                                     [50000, 50000, 100000, 100000])):
            repeat["per_row_cost"]["cpu_ns"] = cpu
            repeat["cost"]["cpu_ns"] = sum(cpu)
        evaluation._core_cost_binding(self.selection)
        # Median of three repeat means would be 125000, changing the frozen law.
        self.assertEqual(float(np.median([row["cost"]["cpu_ns"] / 4 for row in full])), 125000)
        original = json.dumps(self.selection)
        for defect in ("common", "selected", "median", "rows", "total", "repeat", "observed"):
            with self.subTest(defect=defect):
                self.selection = json.loads(original)
                common = self.selection["common"]
                calibration = common["calibrations"]["11"]
                raw = calibration["raw_repeats"]["full"][0]
                if defect == "common": common["reference_full_cpu_ns"] += 1
                elif defect == "selected": self.selection["selected"][-1]["reference_full_cpu_ns"] += 1
                elif defect == "median": calibration["cpu_ns"]["full"] += 1
                elif defect == "rows": raw["per_row_cost"]["cpu_ns"].pop()
                elif defect == "total": raw["cost"]["cpu_ns"] += 1
                elif defect == "repeat": raw["repeat"] = 2
                else: raw["observe"] = True
                self.assert_preflight_rejected("calibration|reference")

    def native_fixture(self):
        self.plan["runtime_backend"] = "native"
        self.plan_path.write_text(json.dumps(self.plan))
        self.selection["plan_sha256"] = digest(self.plan_path)
        for name in ("independent/native.py", "independent/native.c"):
            (self.root / name).write_text("// Handmade native receipt fixture\n")
            self.sources[name] = digest(self.root / name)
        (self.run / "build").mkdir()
        library = self.run / "build" / "libjoint.so"
        library.write_bytes(b"handmade receipt-only fixture, never loaded")
        self.selection.update(native_library="build/libjoint.so", native_library_sha256=digest(library))
        source = "/original/cloud/qualification/joint-generation/independent/native.c"
        output = "/original/cloud/run/build/libjoint.so"
        self.selection["common"]["native_compile"] = {
            "schema": "hepta.native-build.v1", "exit_code": 0, "cached_compilation_used": False,
            "source_sha256": self.sources["independent/native.c"], "library_sha256": digest(library),
            "source_path": source, "library_path": output, "cpu_seconds": .01, "wall_seconds": .02,
            "argv": ["/usr/bin/cc", "-O3", "-ffp-contract=off", "-std=c11", "-shared", "-fPIC",
                     source, "-o", output, "-lm"]}

    def test_native_receipt_binds_source_library_flags_and_uncached_success_without_location_lock(self):
        self.native_fixture()
        self.write_selection()
        profile = evaluation._experiment("core-c1")
        _, bundles = evaluation._frozen(self.run, profile)
        self.assertEqual(len(bundles), 12)
        original = json.dumps(self.selection)
        for defect in ("source", "library", "flags", "path", "output", "cached", "exit"):
            with self.subTest(defect=defect):
                self.selection = json.loads(original)
                receipt = self.selection["common"]["native_compile"]
                if defect == "source": receipt["source_sha256"] = "0" * 64
                elif defect == "library": receipt["library_sha256"] = "0" * 64
                elif defect == "flags": receipt["argv"][2] = "-ffast-math"
                elif defect == "path": receipt["source_path"] += ".other"
                elif defect == "output": receipt["argv"][8] += ".other"
                elif defect == "cached": receipt["cached_compilation_used"] = True
                else: receipt["exit_code"] = 1
                self.assert_preflight_rejected("native compiler")

    def test_after_opening_failure_retains_completed_receipts_and_blocks_retry(self):
        calls = []
        def fail_fifth(*args, **kwargs):
            calls.append(1)
            if len(calls) == 5:
                raise RuntimeError("handmade fifth-service failure")
            return self.fake_measure(*args, **kwargs)
        data, measured = self.doubles(fail_fifth)
        with self.assertRaisesRegex(RuntimeError, "fifth-service"):
            evaluation.run_evaluation(self.run, "core-c1")
        partial = json.loads((self.run / "core-evaluation-partial.json").read_text())
        self.assertEqual(partial["schema"], "hepta.independent-core-confirmation-partial.v1")
        self.assertEqual(partial["experiment_id"], "core-c1")
        self.assertEqual(len(partial["completed_system_results"]), 4)
        self.assertEqual(partial["phase"], "full_measurement")
        self.assertTrue(partial["global_marker_exists"] and partial["local_marker_exists"])
        self.assertIsNotNone(partial["interrupted_measurement"])
        self.assertFalse((self.run / "test-result.json").exists())
        data.reset_mock(); measured.reset_mock()
        with self.assertRaisesRegex(ValueError, "already opened"):
            evaluation.run_evaluation(self.run, "core-c1")
        data.assert_not_called(); measured.assert_not_called()

    def test_test_construction_failure_keeps_irreversible_marker(self):
        def fail_test(split, *args, **kwargs):
            if split == "test": raise RuntimeError("handmade construction failure")
            return self.handmade_data(split, *args, **kwargs)
        self.doubles()
        with patch.object(evaluation, "dataset", side_effect=fail_test):
            with self.assertRaisesRegex(RuntimeError, "construction failure"):
                evaluation.run_evaluation(self.run, "core-c1")
        partial = json.loads((self.run / "core-evaluation-partial.json").read_text())
        self.assertEqual(partial["phase"], "test_construction")
        self.assertEqual(partial["completed_system_results"], [])
        self.assertTrue(partial["global_marker_exists"])
        self.assertIsNone(partial["test"])

    def test_exclusive_global_opening_race_prevents_test_construction(self):
        def racing_data(split, *args, **kwargs):
            if split == "validation":
                self.marker.write_text("another opener\n")
            return self.handmade_data(split, *args, **kwargs)
        data, measured = self.doubles()
        with patch.object(evaluation, "dataset", side_effect=racing_data) as data:
            with self.assertRaises(FileExistsError):
                evaluation.run_evaluation(self.run, "core-c1")
            self.assertEqual([call.args[0] for call in data.call_args_list], ["train", "validation"])
        measured.assert_not_called()
        self.assertEqual(self.marker.read_text(), "another opener\n")
        self.assertFalse((self.run / "test-opened.json").exists())

    def test_partial_persistence_error_keeps_original_service_error(self):
        original = RuntimeError("original handmade service failure")
        self.doubles(lambda *args, **kwargs: (_ for _ in ()).throw(original))
        exclusive = evaluation._exclusive
        def failing_partial(path, value):
            if path.name == "core-evaluation-partial.json":
                raise OSError("handmade storage failure")
            return exclusive(path, value)
        with patch.object(evaluation, "_exclusive", side_effect=failing_partial):
            with self.assertRaises(RuntimeError) as raised:
                evaluation.run_evaluation(self.run, "core-c1")
        self.assertIs(raised.exception, original)
        self.assertIn("storage failure", original.__notes__[0])
        self.assertTrue(self.marker.exists())
        self.assertTrue((self.run / "test-opened.json").exists())


if __name__ == "__main__":
    unittest.main()

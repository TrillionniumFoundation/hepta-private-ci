"""Pure-array and synthetic-frame checks; never import Torch or prepare real inputs."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixed_inputs_common as common
import fixed_inputs_snapshot as snapshot
import fixed_inputs_score as score
import run


class MemoryCosts:
    def __init__(self):
        self.values = {}

    def add(self, name, amount=1):
        self.values[name] = self.values.get(name, 0) + amount

    def forward(self, name, examples, action):
        self.add(name + "_calls")
        self.add(name + "_examples", examples)

    def snapshot(self):
        return dict(self.values)


class FixedInputTests(unittest.TestCase):
    def arrays(self, count=2):
        return {name: np.arange(count * int(np.prod(tail)), dtype=dtype).reshape(count, *tail)
                for name, (dtype, tail) in snapshot.ARRAY_SPEC.items()}

    def fixture(self, directory):
        sources = {"commit": "a" * 40, "files": {"synthetic": {"sha256": "b" * 64}}}
        protocol = {"snapshot_schema": "test.1", "source_roles": ["development_task", "development_clean"],
                    "panel_rows": {"task": 2, "clean": 2}, "storage_bounds": {"snapshot_bytes": 64 * 1024 ** 2}}
        panels, rows = {}, []
        for panel in ("task", "clean"):
            arrays = self.arrays()
            batch = {"condition": "clean", "noise_seed": 1234, "batch_size": 2,
                     "source_ids": [["a", "b"], ["c", "d"]], **snapshot.public_target_identity(arrays)}
            panels[panel] = {"batches": [batch], "sha256": hashlib.sha256(common.canonical([batch])).hexdigest(),
                             "independent_of_schedule_id": True}
            path = directory / (panel + "-000.npz")
            np.savez(path, **arrays)
            rows.append({"panel": panel, "batch_index": 0, **batch,
                         "file": {"path": path.name, **common.identity(path)},
                         "arrays": snapshot.validate_arrays(arrays, 2)})
        manifest = {"schema": "test.1", "source_registration": sources, "source_roles": protocol["source_roles"],
                    "seed": 17, "preparation_capability": "AVX512", "model_calls": 0,
                    "panel_identities": panels, "batches": rows, "numeric_tensor_bytes": snapshot.numeric_bytes(4),
                    "all_input_sha256": hashlib.sha256(common.canonical(rows)).hexdigest()}
        common.write(directory / "MANIFEST.json", manifest)
        return common.identity(directory / "MANIFEST.json"), panels, protocol, sources

    def test_no_torch_import_or_real_preparation(self):
        self.assertNotIn("torch", sys.modules)

    def test_exact_static_input_size_and_shape_inventory(self):
        self.assertEqual(snapshot.numeric_bytes(2560), 49_520_640)
        self.assertEqual(len(snapshot.ARRAY_SPEC), 7)
        metadata = snapshot.validate_arrays(self.arrays(), 2)
        self.assertEqual(metadata["latent_noise"]["shape"], [2, 96])

    def test_snapshot_roundtrip_covers_every_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args = self.fixture(directory)
            manifest, loaded = snapshot.verify_snapshot(directory, *args)
            self.assertEqual(len(manifest["batches"]), 2)
            snapshot.verify_loaded_unchanged(loaded)
            self.assertEqual(set(loaded["task"][0][1]), set(snapshot.ARRAY_SPEC))

    def test_snapshot_rejects_changed_latent_noise_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args = self.fixture(directory)
            path = directory / "task-000.npz"
            with np.load(path, allow_pickle=False) as saved:
                arrays = {name: saved[name].copy() for name in saved.files}
            arrays["latent_noise"][0, 0] = np.nextafter(np.float32(0), np.float32(1))
            np.savez(path, **arrays)
            with self.assertRaisesRegex(ValueError, "Snapshot NPZ changed"):
                snapshot.verify_snapshot(directory, *args)

    def test_snapshot_rejects_mutated_loaded_public_or_target_or_noise(self):
        for key in snapshot.ARRAY_SPEC:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                args = self.fixture(directory)
                unused, loaded = snapshot.verify_snapshot(directory, *args)
                loaded["task"][0][1][key].flat[0] += 1
                with self.assertRaisesRegex(ValueError, "Loaded input tensor mutated"):
                    snapshot.verify_loaded_unchanged(loaded)

    def test_snapshot_rejects_changed_manifest_or_unknown_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args = self.fixture(directory)
            (directory / "unknown.npz").write_bytes(b"unknown")
            with self.assertRaisesRegex(ValueError, "unknown or missing"):
                snapshot.verify_snapshot(directory, *args)
            (directory / "unknown.npz").unlink()
            with (directory / "MANIFEST.json").open("a") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "manifest identity"):
                snapshot.verify_snapshot(directory, *args)

    def test_snapshot_rejects_reordered_batches_even_with_rehashed_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            unused, panels, protocol, sources = self.fixture(directory)
            path = directory / "MANIFEST.json"
            value = common.read(path)
            value["batches"].reverse()
            value["all_input_sha256"] = hashlib.sha256(common.canonical(value["batches"])).hexdigest()
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "ordering/inventory"):
                snapshot.verify_snapshot(directory, common.identity(path), panels, protocol, sources)

    def test_array_schema_rejects_missing_wrong_dtype_shape_and_nan(self):
        for mode in ("missing", "dtype", "shape", "nan"):
            arrays = self.arrays()
            if mode == "missing":
                arrays.pop("latent_noise")
            elif mode == "dtype":
                arrays["latent_noise"] = arrays["latent_noise"].astype(np.float64)
            elif mode == "shape":
                arrays["latent_noise"] = arrays["latent_noise"].reshape(1, 192)
            else:
                arrays["latent_noise"][0, 0] = np.nan
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                snapshot.validate_arrays(arrays, 2)

    def test_bitwise_parity_detects_signed_zero_and_each_output_field(self):
        arrays = {name: np.asarray([0., 1.]) for name in score.OUTPUT_FIELDS}
        for name in score.OUTPUT_FIELDS:
            changed = {key: value.copy() for key, value in arrays.items()}
            changed[name][0] = -0.
            self.assertTrue(np.array_equal(arrays[name], changed[name]))
            result = score.parity_record(arrays, changed)
            self.assertEqual([key for key, value in result.items() if not value["bitwise_exact"]], [name])

    def test_parity_rejects_missing_output_field(self):
        arrays = {name: np.asarray([1.]) for name in score.OUTPUT_FIELDS}
        other = dict(arrays)
        other.pop("digit_logits")
        with self.assertRaisesRegex(ValueError, "field inventory"):
            score.parity_record(arrays, other)

    def test_exact_comparison_retains_single_ulp(self):
        left = np.asarray([[.5, .25], [-.5, .125]])
        right = left.copy()
        right[1, 0] = np.nextafter(right[1, 0], np.inf)
        result = common.compare(left, right)
        self.assertFalse(result["exact"])
        self.assertFalse(result["bitwise_exact"])
        self.assertEqual(result["indices"], [[1, 0]])
        self.assertIsNone(result["tolerance"])

    def test_missing_child_receipt_is_unknown_usage_not_zero(self):
        cases = [{"phase": "unset_before", "resource_accounting_complete": True,
                  "result": {"resources": {"task_generator_calls": 16}}},
                 {"phase": "default", "resource_accounting_complete": False, "result": None}]
        unused, complete, observed, actual = run.resource_summary(cases, None)
        self.assertFalse(complete)
        self.assertEqual(observed["generator_panel_calls"], 16)
        self.assertIsNone(actual)
        cases.pop()
        unused, complete, observed, actual = run.resource_summary(cases, None)
        self.assertTrue(complete)
        self.assertEqual(actual, observed)

    def test_json_valid_but_invalid_result_schema_is_unknown(self):
        valid = {"status": "FAIL", "resources": {"task_generator_calls": 1}, "independent_call_profile": {}}
        self.assertEqual(run.validated_result(valid), (valid, None))
        invalid = [[], None, {}, {**valid, "resources": []}, {**valid, "status": "UNKNOWN"},
                   {**valid, "panels": []}, {**valid, "panels": {"task": {"vs_historical_raw": []}}},
                   {**valid, "status": "COMPLETE"},
                   {**valid, "resources": {"task_generator_calls": -1}},
                   {**valid, "independent_call_profile": {"generator_pipeline_started": True}}]
        for item in invalid:
            normalized, error = run.validated_result(item)
            self.assertIsNone(normalized)
            self.assertEqual(error["type"], "InvalidResultSchema")
            cases = [{"resource_accounting_complete": False, "result": normalized}]
            unused, complete, observed, actual = run.resource_summary(cases, None)
            self.assertFalse(complete)
            self.assertIsNone(actual)
            self.assertEqual(observed["generator_panel_calls"], 0)

    def test_oversized_summary_preserves_child_files_and_fails_compactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            child = directory / "unset_before"
            child.mkdir()
            raw = child / "RESULT.json"
            raw.write_bytes(b"preserved detailed child evidence")
            before = common.identity(raw)
            payload = {"execution_complete": True, "preparation": None,
                "cases": [{"phase": "unset_before", "exit_code": 0, "result_file": before}],
                "large_in_memory_comparison": "x" * 50_000, "scientific_status": "FAIL", "admission": False,
                "actual_totals": {"generator_panel_calls": 40}, "resource_accounting_complete": True}
            result = common.write_bounded_summary(directory, payload, 20_000)
            saved = common.read(directory / "SUMMARY.json")
            self.assertFalse(result["full_summary_written"])
            self.assertTrue(result["metadata_bound_satisfied"])
            self.assertFalse(saved["execution_complete"])
            self.assertFalse(saved["diagnostic_interpretable"])
            self.assertEqual(saved["actual_totals"], {"generator_panel_calls": 40})
            self.assertEqual(saved["metadata_storage"]["summary_bytes"], (directory / "SUMMARY.json").stat().st_size)
            self.assertEqual(before, common.identity(raw))

    def test_small_summary_counts_existing_parent_and_preparation_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "prepare").mkdir()
            (directory / "prepare" / "RESULT.json").write_bytes(b"a" * 123)
            (directory / "REGISTRATION.json").write_bytes(b"b" * 45)
            result = common.write_bounded_summary(directory, {"execution_complete": False}, 20_000)
            saved = common.read(directory / "SUMMARY.json")
            self.assertTrue(result["full_summary_written"])
            self.assertEqual(saved["metadata_storage"]["existing_metadata_bytes"], 168)
            self.assertEqual(saved["metadata_storage"]["total_metadata_bytes"], 168 + result["summary"]["bytes"])

    def test_mse_uses_python_float_and_retains_observer_order(self):
        weights = dict(zip(common.FIELDS, (.3, .15, .35, .1, .1), strict=True))
        rows = [{"refinement_charge": .002, "observers": {name: dict(zip(common.FIELDS,
            (.5, 1., float(index) / 2, .5, .1), strict=True)) for index, name in enumerate(("reward", "audit"))}}]
        mse = np.asarray([.101234567890123])
        result = score.mse_only_values(rows, mse, weights)
        expected = np.asarray([[1 - 2 * sum(weights[key] * (float(mse[0]) if key == "pixel_mse"
            else rows[0]["observers"][name][key]) for key in common.FIELDS) - .002] for name in ("reward", "audit")])
        self.assertTrue(common.bitwise(result, expected))
        self.assertFalse(np.array_equal(result, result[::-1]))
        with self.assertRaisesRegex(ValueError, "cardinality"):
            score.mse_only_values(rows, [], weights)

    def test_disk_gate_does_not_treat_zero_bavail_as_positive(self):
        stat = SimpleNamespace(f_bfree=416, f_bavail=0, f_frsize=1024 ** 2)
        root = common.disk_record("synthetic", 160 * 1024 ** 2, 256 * 1024 ** 2, stat=stat, effective_uid=0)
        user = common.disk_record("synthetic", 160 * 1024 ** 2, 256 * 1024 ** 2, stat=stat, effective_uid=1000)
        self.assertTrue(root["passed"])
        self.assertEqual(root["f_bavail_bytes"], 0)
        self.assertFalse(user["passed"])
        stat.f_bfree -= 1
        self.assertFalse(common.disk_record("synthetic", 160 * 1024 ** 2, 256 * 1024 ** 2,
                                           stat=stat, effective_uid=0)["passed"])

    def test_ledger_stops_before_extra_generator_or_observer_call(self):
        inner = MemoryCosts()
        limited = common.LimitedCosts(inner, {"generator_panel_calls": 1, "generator_examples": 2,
            "observer_calls": 2, "observer_digit_examples": 4})
        limited.forward("task_generator", 2, 0)
        with self.assertRaisesRegex(ValueError, "Pre-call"):
            limited.forward("task_generator", 2, 0)
        limited.add("task_reward_observer_calls", 2)
        limited.add("task_reward_observer_digit_examples", 4)
        with self.assertRaisesRegex(ValueError, "Pre-call"):
            limited.add("task_reward_observer_calls", 2)
        self.assertEqual(inner.snapshot()["task_generator_calls"], 1)
        self.assertEqual(inner.snapshot()["task_reward_observer_calls"], 2)

    def test_independent_profile_limits_at_encode_before_decode(self):
        model, observer, violations, counts = object(), object(), [], {}
        watch = {"model": model, "observers": [observer], "call_limits": {
            "generator_pipeline_started": 1, "generator_decode_calls": 1, "observer_forward_calls": 1}}
        guard = common.execution_guard("avx2", violations, counts, watch)
        frame = lambda name, instance: SimpleNamespace(f_globals={"__name__": "experiments.synthetic"},
            f_code=SimpleNamespace(co_name=name), f_locals={"self": instance})
        guard(frame("encode", model), "call", None)
        with self.assertRaisesRegex(RuntimeError, "pre-call"):
            guard(frame("encode", model), "call", None)
        self.assertEqual(counts, {"generator_pipeline_started": 1})
        self.assertEqual(violations[0]["reason"], "pre-call budget")
        guard(frame("decode", model), "call", None)
        guard(frame("forward", observer), "call", None)
        with self.assertRaisesRegex(RuntimeError, "pre-call"):
            guard(frame("forward", observer), "call", None)

    def test_profile_forbids_preparation_model_and_child_input_reconstruction(self):
        for phase, module, function in (("prepare", "torch.nn.modules.module", "__init__"),
                ("default", "experiments.synthetic", "make_batch"),
                ("avx2", "torch.optim.sgd", "step")):
            violations = []
            guard = common.execution_guard(phase, violations, {}, {})
            frame = SimpleNamespace(f_globals={"__name__": module}, f_code=SimpleNamespace(co_name=function), f_locals={})
            with self.subTest(phase=phase), self.assertRaisesRegex(RuntimeError, "prohibited"):
                guard(frame, "call", None)
            self.assertEqual(len(violations), 1)

    def test_protocol_budget_separates_previous_attempt_and_reserve(self):
        protocol = common.read(Path(__file__).with_name("PROTOCOL.json"))
        self.assertEqual(protocol["cases"], list(common.CASES))
        self.assertEqual(protocol["complete_budget"]["generator_panel_calls"], 140)
        self.assertEqual(protocol["complete_budget"]["observer_calls"], 400)
        self.assertEqual(protocol["first_attempt"]["actual_totals"]["generator_panel_calls"], 80)
        self.assertEqual(protocol["first_attempt"]["actual_totals"]["observer_calls"], 320)
        self.assertEqual(run.remaining_bound(protocol, "prepare"), 160 * 1024 ** 2)
        self.assertEqual(run.remaining_bound(protocol, "unset_after"), 32 * 1024 ** 2)
        self.assertFalse(protocol["admission"])


if __name__ == "__main__":
    unittest.main()

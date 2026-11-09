"""Synthetic wire/filesystem behavior tests; these are not owner admissions."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import joint_text_training_contract as contract  # noqa: E402
from scripts import joint_text_training_io as worker_io  # noqa: E402


def synthetic_request():
    """Explicit fixture values, with intentionally different row/record counts."""

    def digest(name):
        return hashlib.sha256(("synthetic:" + name).encode()).hexdigest()

    result = {
        "schema": contract.REQUEST_SCHEMA,
        "profile": contract.PROFILE,
        "principal_id": "fixture-principal_id",
        "agent_id": "fixture-agent_id",
        "cell_id": "fixture-cell_id",
        "operation_id": "fixture-operation_id",
        "source_run_id": "fixture-source_run_id",
        "completed_task_receipt": digest("completed_task_receipt"),
        "iteration_head": digest("iteration_head"),
        "selected_bundle_digest": digest("selected_bundle_digest"),
        "selected_generation": 2,
        "candidate_artifact_id": "fixture-candidate_artifact_id",
        "evaluation_profile": digest("evaluation_profile"),
        "dataset_digest": digest("dataset_digest"),
        "dataset_observed_rows": 7,
        "dataset_observed_bytes": 1000,
        "source_record_count": 3,
        "materialization_digest": digest("materialization_digest"),
        "materialization_profile_digest": digest("materialization_profile_digest"),
        "source_support_digest": digest("source_support_digest"),
        "source_content_sha256": hashlib.sha256("Ab世界🙂".encode()).hexdigest(),
        "source_revision": 1,
        "source_policy_revision": 5,
        "predecessor_sha256": digest("predecessor_sha256"),
        "predecessor_bytes": 1024,
        "execution_source_digest": "9452aafecc4665fc54fdb1d0d928c845733c85450edbd0d0c8fbbdb6eff3567e",
        "prefix": "Ab世界",
        "continuation": "🙂",
        "steps": 2,
        "learning_rate_f64_be": "3f847ae147ae147b",
        "maximum_dataset_rows": 10,
        "maximum_dataset_bytes": 4608,
        "maximum_training_steps": 4,
        "maximum_training_milliseconds": 5000,
        "maximum_artifact_bytes": 8388608,
    }
    return result


class WireBehavior(unittest.TestCase):
    def test_unicode_conservation_and_independent_owner_counts(self):
        request = synthetic_request()
        actual = contract.validate_request(contract.json_bytes(request))
        self.assertEqual(actual["prefix"] + actual["continuation"], "Ab世界🙂")
        self.assertEqual(
            (
                actual["source_record_count"],
                actual["dataset_observed_rows"],
                actual["dataset_observed_bytes"],
            ),
            (3, 7, 1000),
        )

    def test_duplicate_unknown_and_nonfinite_json_rejected(self):
        raw = contract.json_bytes(synthetic_request())
        bad = [
            raw.replace(b'{"schema":', b'{"schema":"duplicate","schema":', 1),
            raw[:-2] + b',"extra":0}\n',
            raw.replace(b'"steps":2', b'"steps":NaN'),
        ]
        for value in bad:
            with (
                self.subTest(raw=value[:30]),
                self.assertRaises(contract.ContractError),
            ):
                contract.validate_request(value)

    def test_integer_types_overflow_and_original_budgets(self):
        for key, value in (
            ("steps", True),
            ("source_revision", 2**64),
            ("maximum_training_steps", 1),
            ("dataset_observed_rows", 11),
            ("dataset_observed_bytes", 4609),
            ("source_record_count", 0),
        ):
            request = synthetic_request()
            request[key] = value
            with self.subTest(key=key), self.assertRaises(contract.ContractError):
                contract.validate_request(contract.json_bytes(request))
        request = synthetic_request()
        request["source_revision"] = 2**63 + 123
        request["source_policy_revision"] = 0
        decoded = contract.validate_request(contract.json_bytes(request))
        self.assertIs(type(decoded["source_revision"]), int)
        self.assertEqual(decoded["source_revision"], 2**63 + 123)
        self.assertEqual(decoded["source_policy_revision"], 0)

    def test_learning_rate_and_complete_text_binding(self):
        for key, value in (
            ("learning_rate_f64_be", "7ff0000000000000"),
            ("learning_rate_f64_be", "8000000000000000"),
            ("learning_rate_f64_be", "3ff0000000000001"),
            ("source_content_sha256", "1" * 64),
            ("continuation", ""),
        ):
            request = synthetic_request()
            request[key] = value
            with self.subTest(key=key), self.assertRaises(contract.ContractError):
                contract.validate_request(contract.json_bytes(request))
        request = synthetic_request()
        request["continuation"] = "\ud800"
        with self.assertRaises(contract.ContractError):
            contract.validate_request(json.dumps(request).encode())

    def test_semantic_digest_preserves_counts_and_ignores_json_order(self):
        request = synthetic_request()
        original = contract.json_bytes(request)
        reordered = json.dumps(
            dict(reversed(list(request.items()))), ensure_ascii=True
        ).encode()
        self.assertNotEqual(contract.sha(original), contract.sha(reordered))
        self.assertEqual(
            contract.request_binding_digest(contract.validate_request(original)),
            contract.request_binding_digest(contract.validate_request(reordered)),
        )
        for key in (
            "source_record_count",
            "dataset_observed_rows",
            "dataset_observed_bytes",
            "source_revision",
            "source_policy_revision",
        ):
            changed = copy.deepcopy(request)
            changed[key] += 1
            self.assertNotEqual(
                contract.request_binding_digest(request),
                contract.request_binding_digest(changed),
            )

    def test_source_absence_is_part_of_digest(self):
        present = [{"path": "scripts/a.py", "bytes": 17, "sha256": "1" * 64}]
        self.assertEqual(
            contract.source_digest(present, ["scripts/__init__.py"]),
            "9452aafecc4665fc54fdb1d0d928c845733c85450edbd0d0c8fbbdb6eff3567e",
        )
        self.assertNotEqual(
            contract.source_digest(present, []),
            contract.source_digest(present, ["scripts/__init__.py"]),
        )
        with self.assertRaises(contract.ContractError):
            contract.source_digest(present + present, [])

    def test_unsigned_observation_rejects_boolean_and_count_laundering(self):
        # Deliberately synthetic wire object: parsing never proves execution.
        request = synthetic_request()
        source = worker_io.SourceClosure(ROOT)
        request["execution_source_digest"] = source.digest
        groups = [
            {
                "group": group,
                "parameters": 10,
                "gradient_present_parameters": 1,
                "gradient_nonzero_parameters": 1,
                "changed_parameters": 1,
                "max_abs_gradient_f64_be": contract.encode_float(1.0),
                "max_abs_delta_f64_be": contract.encode_float(0.1),
            }
            for group in contract.PARAMETER_GROUPS
        ]
        value = {
            "schema": contract.OBSERVATION_SCHEMA,
            "profile": contract.PROFILE,
            "status": "candidate",
            "authority": "DENY_ALL",
            "request_sha256": contract.sha(contract.json_bytes(request)),
            "request_binding_digest": contract.request_binding_digest(request),
            "training_profile_digest": contract.PROFILE_DIGEST,
            "update_rule_digest": contract.update_rule_digest(request),
            "execution_source_digest": source.digest,
            "execution_sources": source.rows,
            "absent_source_paths": source.absent,
            "predecessor": {
                "sha256": request["predecessor_sha256"],
                "bytes": request["predecessor_bytes"],
                "after_sha256": request["predecessor_sha256"],
                "roundtrip": True,
            },
            "candidate": {
                "sha256": "2" * 64,
                "bytes": 1024,
                "roundtrip": True,
                "changed": True,
            },
            "training": {
                "requested_steps": 2,
                "completed_steps": 2,
                "source_samples": 1,
                "source_record_count": 3,
                "dataset_observed_rows": 7,
                "dataset_observed_bytes": 1000,
                "prefix_bytes": 8,
                "continuation_bytes": 4,
                "continuation_scalars": 1,
                "losses_f64_be": [contract.encode_float(2.0)] * 3,
                "parameter_groups": groups,
                "core_gradient_nonzero": True,
                "core_changed_parameters": 1,
                "effective_wall_limit_milliseconds": 5000,
            },
            "runtime": {
                "python_version": "synthetic",
                "torch_version": "synthetic",
                "platform": "synthetic",
                "device": "cpu",
                "dtype": "float64",
                "threads": 1,
            },
            "cost": {
                "wall_nanoseconds": 1,
                "cpu_nanoseconds": 0,
                "scope": contract.COST_SCOPE,
                "physical_energy_joules": None,
                "full_history_cost": None,
            },
            "claims": {
                "content_loss_training": True,
                "ndu_training": False,
                "evaluation": False,
                "product_loading": False,
                "selection": False,
                "stage_advanced": False,
            },
            "input_files_unchanged": True,
            "source_files_unchanged": True,
        }
        contract.validate_observation(contract.json_bytes(value), request)
        bad = copy.deepcopy(value)
        bad["claims"]["content_loss_training"] = 1
        with self.assertRaises(contract.ContractError):
            contract.validate_observation(contract.json_bytes(bad), request)
        bad = copy.deepcopy(value)
        bad["training"]["source_samples"] = 7
        with self.assertRaises(contract.ContractError):
            contract.validate_observation(contract.json_bytes(bad), request)
        bad = copy.deepcopy(value)
        bad["training"]["parameter_groups"][0]["changed_parameters"] = 2
        with self.assertRaises(contract.ContractError):
            contract.validate_observation(contract.json_bytes(bad), request)


class TemporaryFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="joint-worker-synthetic-")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()


class FileBehavior(TemporaryFiles):
    def test_input_mutation_and_symlink_rejected(self):
        path = self.root / "input"
        path.write_bytes(b"original")
        snapshot = worker_io.read_snapshot(path, 8)
        snapshot.check()
        path.write_bytes(b"modified")
        with self.assertRaises(contract.ContractError):
            snapshot.check()
        link = self.root / "link"
        link.symlink_to(path)
        with self.assertRaises(contract.ContractError):
            worker_io.read_snapshot(link, 8)

    def test_source_drift_and_new_initializer_rejected(self):
        source = self.root / "source"
        for name in worker_io.SOURCE_FILES:
            destination = source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        closure = worker_io.SourceClosure(source)
        closure.check()
        initializer = source / "scripts/__init__.py"
        initializer.write_bytes(b"raise RuntimeError('must never execute')\n")
        with self.assertRaises(contract.ContractError):
            closure.check()
        initializer.unlink()
        target = source / worker_io.SOURCE_FILES[0]
        target.write_bytes(target.read_bytes() + b"\n")
        with self.assertRaises(contract.ContractError):
            closure.check()

    def test_existing_output_and_overwrite_refused(self):
        path = self.root / "output"
        store = worker_io.OutputStore(path)
        try:
            store.write("started.json", b"original")
            with self.assertRaises(FileExistsError):
                store.write("started.json", b"replacement")
            self.assertEqual(store.read("started.json"), b"original")
            with self.assertRaises(FileExistsError):
                worker_io.OutputStore(path)
            self.assertEqual(store.read("started.json"), b"original")
        finally:
            store.close()

    def test_partial_write_retained_and_never_promoted(self):
        store = worker_io.OutputStore(self.root / "partial")
        original_write, calls = os.write, []

        def short_then_fail(fd, raw):
            calls.append(fd)
            if len(calls) == 1:
                return original_write(fd, raw[:3])
            raise OSError(5, "synthetic failure")

        try:
            with (
                mock.patch.object(worker_io.os, "write", short_then_fail),
                self.assertRaises(OSError),
            ):
                store.write("candidate.heptapk", b"candidate-bytes")
            self.assertEqual((store.path / "candidate.heptapk").read_bytes(), b"can")
            self.assertNotIn("candidate.heptapk", store.written)
            with self.assertRaises(FileExistsError):
                store.write("candidate.heptapk", b"retry-is-forbidden")
            self.assertFalse((store.path / "completed.json").exists())
        finally:
            store.close()

    def test_closed_output_set_rejects_extra_file(self):
        store = worker_io.OutputStore(self.root / "extra")
        try:
            store.write("started.json", b"fixture")
            (store.path / "unexpected").write_bytes(b"extra")
            with self.assertRaises(contract.ContractError):
                store.verify_names(("started.json",))
        finally:
            store.close()

    def test_output_parent_rebinding_is_rejected(self):
        parent = self.root / "parent"
        parent.mkdir()
        store = worker_io.OutputStore(parent / "output")
        try:
            store.write("started.json", b"original")
            parent.rename(self.root / "old-parent")
            parent.mkdir()
            (parent / "output").mkdir(mode=0o700)
            with self.assertRaises(contract.ContractError):
                store.write("candidate.heptapk", b"must-not-be-written")
            self.assertEqual(
                (self.root / "old-parent/output/started.json").read_bytes(), b"original"
            )
            self.assertFalse((parent / "output/candidate.heptapk").exists())
        finally:
            store.close()


class WorkerFailureBehavior(TemporaryFiles):
    def invoke(self, raw, predecessor=b"synthetic-nonmodel"):
        request_path = self.root / "request.json"
        predecessor_path = self.root / "predecessor.heptapk"
        request_path.write_bytes(raw)
        predecessor_path.write_bytes(predecessor)
        output = self.root / "run"
        # -S intentionally removes site packages for a deterministic missing-
        # runtime fault. It is not a substitute Torch/model implementation.
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-S",
                str(ROOT / "scripts/joint_generation_v4_text_worker.py"),
                "--request",
                str(request_path),
                "--predecessor",
                str(predecessor_path),
                "--output",
                str(output),
            ],
            capture_output=True,
            check=False,
        )
        self.assertEqual(request_path.read_bytes(), raw)
        self.assertEqual(predecessor_path.read_bytes(), predecessor)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse((output / "completed.json").exists())
        self.assertFalse((output / "observation.json").exists())
        return json.loads((output / "failed.json").read_bytes())

    def test_invalid_request_failure_is_durable(self):
        raw = b'{"schema":"one","schema":"two"}'
        failure = self.invoke(raw)
        self.assertEqual(failure["stage"], "request")
        self.assertEqual(failure["error_code"], "duplicate_json_key")
        self.assertEqual(failure["request_sha256"], contract.sha(raw))

    def test_source_binding_failure_precedes_model_or_runtime(self):
        failure = self.invoke(contract.json_bytes(synthetic_request()))
        self.assertEqual(failure["stage"], "source")
        self.assertEqual(failure["error_code"], "execution_source_binding")

    def test_missing_runtime_retains_source_and_input_scope(self):
        request, predecessor = synthetic_request(), b"synthetic-nonmodel"
        request["execution_source_digest"] = worker_io.SourceClosure(ROOT).digest
        request["predecessor_sha256"] = contract.sha(predecessor)
        request["predecessor_bytes"] = len(predecessor)
        failure = self.invoke(contract.json_bytes(request), predecessor)
        self.assertEqual(failure["stage"], "load_runtime")
        self.assertEqual(failure["error_code"], "runtime_dependency_unavailable")
        self.assertIs(failure["input_files_unchanged"], True)
        self.assertIs(failure["source_files_unchanged"], True)


if __name__ == "__main__":
    unittest.main()

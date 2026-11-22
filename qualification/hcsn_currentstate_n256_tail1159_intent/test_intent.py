"""Source-only controls; no authentic checkpoint is decoded."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qualification.hcsn_currentstate_n256_authentic_tailcheck537_hexfix.test_tail537 import (
    _index256_fixture,
)
from qualification.hcsn_currentstate_n256_authentic_tailcheck537_hexfix.tail537 import (
    advance_to_index537,
)
from qualification.hcsn_currentstate_n256_authentic_compact_checkpoint.compact import (
    encode_compact_checkpoint,
)

from .admission import (
    DEPENDENCY_MANIFEST_FORMAT,
    MAX_JSON_BYTES,
    REQUEST,
    SOURCE_FREEZE,
    _runtime_digests,
    admit_runtime,
)
from .continuation import (
    SOURCE_INDEX,
    TARGET_INDEX,
    TARGET_SCHEMA,
    advance_to_index1159,
    encode_raw_index1159,
    final_tail_check,
)
from .lane import IDENTITY
from .output_validation import validate_lane_result
from .run import _cost_ledger, _drain_bounded


def _environment(request, request_path):
    return {
        "HCSN_REQUEST_SHA256": __import__("hashlib").sha256(
            request_path.read_bytes()
        ).hexdigest(),
        "UNIQUE_EXECUTION_KEY": request["execution_key"],
        "HCSN_ATTEMPT_ID": "001",
    }


def _authorized_fixture(root):
    request = json.loads(REQUEST.read_text())
    request["actual_execution_authorized"] = True
    common = {
        "identity": request["identity"],
        "execution_key": request["execution_key"],
        "intent_source_head": request["intent_source_head"],
        "source_manifest_sha256": __import__("hashlib").sha256(
            SOURCE_FREEZE.read_bytes()
        ).hexdigest(),
        "input_sha256": request["input"]["index537_collector_sha256"],
        "host": "desktop",
    }
    runtime_digests = _runtime_digests()
    originals = {
        "host_observation": {
            **common,
            "schema": "hcsn-tail1159-host-observation-v1",
            "observed_at_utc": "2020-01-01T00:00:00Z",
            "expires_at_utc": "2100-01-01T00:00:00Z",
            "ancestor_cgroup_headroom_bytes": 268435456,
        },
        "allocation": {
            **common,
            "schema": "hcsn-tail1159-allocation-v1",
            "allocation_id": "synthetic-test-allocation",
            "authority": "synthetic-test-only",
            "concurrency": 1,
            "memory_bytes": 268435456,
        },
        "calendar": {
            **common,
            "schema": "hcsn-tail1159-calendar-v1",
            "calendar_id": "synthetic-test-calendar",
            "allocation_id": "synthetic-test-allocation",
            "valid_from_utc": "2020-01-01T00:00:00Z",
            "valid_until_utc": "2100-01-01T00:00:00Z",
        },
        "runtime": {
            **common,
            "schema": "hcsn-tail1159-runtime-v1",
            "runtime_id": "synthetic-test-runtime",
            "dependency_manifest_format": DEPENDENCY_MANIFEST_FORMAT,
            **runtime_digests,
        },
    }
    originals_dir = root / "runtime_originals"
    originals_dir.mkdir()
    admission = {"concurrency": 1}
    paths = {}
    for kind, original in originals.items():
        relative = f"runtime_originals/{kind}.json"
        raw = (json.dumps(original, sort_keys=True) + "\n").encode()
        paths[kind] = root / relative
        paths[kind].write_bytes(raw)
        admission[f"{kind}_path"] = relative
        admission[f"{kind}_sha256"] = __import__("hashlib").sha256(raw).hexdigest()
    request["runtime_admission"] = admission
    request_path = root / "REQUEST.json"
    request_path.write_text(json.dumps(request, sort_keys=True))
    return request, request_path, paths


def _replace_original(request, request_path, paths, kind, raw):
    paths[kind].write_bytes(raw)
    request["runtime_admission"][f"{kind}_sha256"] = __import__("hashlib").sha256(
        raw
    ).hexdigest()
    request_path.write_text(json.dumps(request, sort_keys=True))


def _synthetic_lane_output(root, ordinal=0):
    request = json.loads(REQUEST.read_text())
    output = root / f"lane-{ordinal:02d}"
    output.mkdir()
    stem = f"synthetic-lane-{ordinal:02d}"
    body = {
        "coefficient": ["0", "1"],
        "exponential_sum": ["0", "1"],
        "growth_coefficient": ["0", "1"],
        "included_index": TARGET_INDEX,
        "iterate": [["0", "1"]],
        "lane": stem,
        "parent_payload_sha256": "1" * 64,
        "partial": [["0", "1"]],
        "schema": TARGET_SCHEMA,
        "source_payload_sha256": "2" * 64,
    }
    body_raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    raw = json.dumps(
        {
            "body": body,
            "body_sha256": __import__("hashlib").sha256(body_raw).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    compact = encode_compact_checkpoint(raw, TARGET_SCHEMA, TARGET_INDEX)
    checkpoint_name = f"{stem}.index1159.checkpoint.hcsncp"
    (output / checkpoint_name).write_bytes(compact)
    rounding = [
        {
            "ordinal": 0,
            "lower_hex": "0x0.0p+0",
            "upper_hex": "0x0.0p+0",
            "unique": True,
        }
    ]
    rounding_raw = json.dumps(rounding, sort_keys=True, separators=(",", ":")).encode()
    tail = {
        "included_index": TARGET_INDEX,
        "ratio_denominator": 2,
        "argument": ["0", "1"],
        "tail_argument": ["0", "1"],
        "growth_tail": ["0", "1"],
        "remainder_bound": ["0", "1"],
        "maximum_interval_width": ["0", "1"],
        "coordinate_count": 1,
        "unique_coordinate_count": 1,
        "all_coordinates_unique": True,
        "rounding": rounding,
        "rounding_sha256": __import__("hashlib").sha256(rounding_raw).hexdigest(),
        "tail_vector_fp64_conversions": 1,
        "rounding_calls": 2,
    }
    tail_raw = (json.dumps(tail, indent=2, sort_keys=True) + "\n").encode()
    (output / "TAIL.json").write_bytes(tail_raw)
    result = {
        "identity": IDENTITY,
        "execution_key": request["execution_key"],
        "lane_ordinal": ordinal,
        "stem": stem,
        "checkpoint_file": checkpoint_name,
        "checkpoint_raw_bytes": len(raw),
        "checkpoint_raw_sha256": __import__("hashlib").sha256(raw).hexdigest(),
        "checkpoint_compact_bytes": len(compact),
        "checkpoint_compact_sha256": __import__("hashlib").sha256(compact).hexdigest(),
        "tail_file": "TAIL.json",
        "tail_sha256": __import__("hashlib").sha256(tail_raw).hexdigest(),
        "tail": {
            field: tail[field]
            for field in (
                "coordinate_count",
                "unique_coordinate_count",
                "all_coordinates_unique",
                "rounding_sha256",
            )
        },
        "work": {
            "index537_compact_decodes": 1,
            "recurrence_row_actions": 622,
            "tail_checks": 1,
            "rounding_calls": 2,
            "index1159_compact_encodes": 1,
            "index1159_compact_decodes": 1,
        },
        "cost": {"wall_seconds": 1.0, "cpu_seconds": 0.5, "max_rss_kib": 1024},
    }
    result_path = output / "RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return request, result, result_path


class Tail1159IntentTests(unittest.TestCase):
    def test_frozen_work_denominator(self):
        request = json.loads(REQUEST.read_text())
        self.assertEqual(TARGET_INDEX - SOURCE_INDEX, 622)
        self.assertEqual(request["budget"]["checkpoint_decodes"], 30)
        self.assertEqual(request["budget"]["recurrence_row_actions"], 6220)
        self.assertEqual(request["budget"]["tail_checks"], 10)
        self.assertEqual(request["budget"]["rounding_calls_cap"], 5180)
        self.assertEqual(request["budget"]["provider_calls"], 0)
        self.assertEqual(request["checkpoint_caps"]["aggregate_compact_bytes"], 134217728)
        self.assertEqual(request["lane_log_caps"]["stdout_bytes"], 1048576)
        self.assertEqual(request["lane_log_caps"]["stderr_bytes"], 1048576)
        self.assertFalse(request["actual_execution_authorized"])

    def test_log_drain_retains_exact_bytes_within_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stdout.log"
            overflow = __import__("threading").Event()
            total = _drain_bounded(io.BytesIO(b"exact-log"), path, 9, overflow)
            self.assertEqual(total, 9)
            self.assertEqual(path.read_bytes(), b"exact-log")
            self.assertFalse(overflow.is_set())

    def test_log_drain_caps_retained_bytes_and_marks_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stderr.log"
            overflow = __import__("threading").Event()
            total = _drain_bounded(io.BytesIO(b"0123456789"), path, 4, overflow)
            self.assertEqual(total, 10)
            self.assertEqual(path.read_bytes(), b"0123")
            self.assertTrue(overflow.is_set())

    def test_cost_ledger_keeps_concurrent_process_costs_separate(self):
        results = [
            {
                "lane_ordinal": 1,
                "cost": {
                    "wall_seconds": 2.0,
                    "cpu_seconds": 1.25,
                    "max_rss_kib": 2048,
                },
            },
            {
                "lane_ordinal": 0,
                "cost": {
                    "wall_seconds": 3.0,
                    "cpu_seconds": 1.5,
                    "max_rss_kib": 4096,
                },
            },
        ]
        statuses = [(1, -15, True, 20, 2), (0, 0, False, 3, 5)]
        ledger = _cost_ledger(
            results,
            statuses,
            {"stdout_bytes": 4, "stderr_bytes": 4},
            {"wall_seconds": 4.0, "cpu_seconds": 0.25, "max_rss_kib": 1024},
        )
        self.assertEqual(
            [item["lane_ordinal"] for item in ledger["validated_lane_costs"]],
            [0, 1],
        )
        self.assertEqual(ledger["validated_lane_wall_seconds_sum"], 5.0)
        self.assertEqual(ledger["validated_lane_cpu_seconds_sum"], 2.75)
        self.assertEqual(ledger["validated_lane_max_rss_kib_max"], 4096)
        self.assertEqual(
            ledger["process_statuses"][1],
            {
                "lane_ordinal": 1,
                "returncode": -15,
                "log_overflow": True,
                "stdout_produced_bytes": 20,
                "stdout_retained_bytes": 4,
                "stderr_produced_bytes": 2,
                "stderr_retained_bytes": 2,
            },
        )

    def test_cost_ledger_rejects_nonfinite_claim(self):
        results = [
            {
                "lane_ordinal": 0,
                "cost": {
                    "wall_seconds": float("nan"),
                    "cpu_seconds": 1.0,
                    "max_rss_kib": 1024,
                },
            }
        ]
        with self.assertRaisesRegex(SystemExit, "lane wall seconds"):
            _cost_ledger(
                results,
                [(0, 0, False, 0, 0)],
                {"stdout_bytes": 4, "stderr_bytes": 4},
                {"wall_seconds": 1.0, "cpu_seconds": 1.0, "max_rss_kib": 1024},
            )

    def test_missing_allocation_refuses_before_input_read(self):
        digest = __import__("hashlib").sha256(REQUEST.read_bytes()).hexdigest()
        environment = {
            "HCSN_REQUEST_SHA256": digest,
            "UNIQUE_EXECUTION_KEY": json.loads(REQUEST.read_text())["execution_key"],
            "HCSN_ATTEMPT_ID": "001",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(SystemExit, "not authorized"):
                admit_runtime()

    def test_false_authorization_refuses_even_with_filled_runtime_fields(self):
        request = json.loads(REQUEST.read_text())
        request["runtime_admission"] = {
            "allocation_path": None,
            "allocation_sha256": "a" * 64,
            "calendar_path": None,
            "calendar_sha256": "b" * 64,
            "concurrency": 1,
            "host_observation_path": None,
            "host_observation_sha256": "c" * 64,
            "runtime_path": None,
            "runtime_sha256": "d" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "REQUEST.json"
            request_path.write_text(json.dumps(request, sort_keys=True))
            digest = __import__("hashlib").sha256(request_path.read_bytes()).hexdigest()
            environment = {
                "HCSN_REQUEST_SHA256": digest,
                "UNIQUE_EXECUTION_KEY": request["execution_key"],
                "HCSN_ATTEMPT_ID": "001",
            }
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(SystemExit, "not authorized"):
                        admit_runtime()

    def test_true_authorization_refuses_digest_only_runtime_claims(self):
        request = json.loads(REQUEST.read_text())
        request["actual_execution_authorized"] = True
        request["runtime_admission"] = {
            "allocation_path": None,
            "allocation_sha256": "a" * 64,
            "calendar_path": None,
            "calendar_sha256": "b" * 64,
            "concurrency": 1,
            "host_observation_path": None,
            "host_observation_sha256": "c" * 64,
            "runtime_path": None,
            "runtime_sha256": "d" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "REQUEST.json"
            request_path.write_text(json.dumps(request, sort_keys=True))
            environment = {
                "HCSN_REQUEST_SHA256": __import__("hashlib").sha256(
                    request_path.read_bytes()
                ).hexdigest(),
                "UNIQUE_EXECUTION_KEY": request["execution_key"],
                "HCSN_ATTEMPT_ID": "001",
            }
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(SystemExit, "path is not frozen"):
                        admit_runtime()

    def test_synthetic_originals_exercise_complete_admission_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, request_path, _ = _authorized_fixture(root)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, _environment(request, request_path), clear=True):
                    self.assertEqual(admit_runtime(), request)

    def test_modified_frozen_source_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, request_path, paths = _authorized_fixture(root)
            manifest = json.loads(SOURCE_FREEZE.read_text())
            manifest["files"] = {"drifted.py": "0" * 64}
            manifest_path = root / "SOURCE_FREEZE.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True))
            (root / "drifted.py").write_text("print('changed')\n")
            manifest_digest = __import__("hashlib").sha256(
                manifest_path.read_bytes()
            ).hexdigest()
            for kind, path in paths.items():
                original = json.loads(path.read_text())
                original["source_manifest_sha256"] = manifest_digest
                raw = (json.dumps(original, sort_keys=True) + "\n").encode()
                _replace_original(request, request_path, paths, kind, raw)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch(
                    "qualification.hcsn_currentstate_n256_tail1159_intent."
                    "admission.SOURCE_FREEZE",
                    manifest_path,
                ):
                    with patch(
                        "qualification.hcsn_currentstate_n256_tail1159_intent."
                        "admission.REPO",
                        root,
                    ):
                        with patch.dict(
                            os.environ, _environment(request, request_path), clear=True
                        ):
                            with self.assertRaisesRegex(
                                SystemExit, "frozen source differs"
                            ):
                                admit_runtime()

    def test_python_executable_digest_mismatch_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            request, request_path, paths = _authorized_fixture(Path(directory))
            runtime = json.loads(paths["runtime"].read_text())
            runtime["python_executable_sha256"] = "0" * 64
            raw = (json.dumps(runtime, sort_keys=True) + "\n").encode()
            _replace_original(request, request_path, paths, "runtime", raw)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(
                    os.environ, _environment(request, request_path), clear=True
                ):
                    with self.assertRaisesRegex(SystemExit, "executing environment"):
                        admit_runtime()

    def test_dependency_manifest_digest_mismatch_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            request, request_path, paths = _authorized_fixture(Path(directory))
            runtime = json.loads(paths["runtime"].read_text())
            runtime["dependency_manifest_sha256"] = "0" * 64
            raw = (json.dumps(runtime, sort_keys=True) + "\n").encode()
            _replace_original(request, request_path, paths, "runtime", raw)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(
                    os.environ, _environment(request, request_path), clear=True
                ):
                    with self.assertRaisesRegex(SystemExit, "executing environment"):
                        admit_runtime()

    def test_duplicate_original_key_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            request, request_path, paths = _authorized_fixture(Path(directory))
            raw = paths["allocation"].read_bytes().replace(
                b'"authority": "synthetic-test-only",',
                b'"authority": "synthetic-test-only", "authority": "forged",',
                1,
            )
            _replace_original(request, request_path, paths, "allocation", raw)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, _environment(request, request_path), clear=True):
                    with self.assertRaisesRegex(SystemExit, "unambiguous JSON"):
                        admit_runtime()

    def test_nonfinite_original_number_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            request, request_path, paths = _authorized_fixture(Path(directory))
            raw = paths["runtime"].read_bytes().rstrip()
            raw = raw[:-1] + b', "unreviewed": 1e999}\n'
            _replace_original(request, request_path, paths, "runtime", raw)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, _environment(request, request_path), clear=True):
                    with self.assertRaisesRegex(SystemExit, "unambiguous JSON"):
                        admit_runtime()

    def test_oversized_original_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            request, request_path, paths = _authorized_fixture(Path(directory))
            raw = b"{" + b" " * MAX_JSON_BYTES
            _replace_original(request, request_path, paths, "calendar", raw)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, _environment(request, request_path), clear=True):
                    with self.assertRaisesRegex(SystemExit, "byte cap"):
                        admit_runtime()

    def test_oversized_request_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            request, request_path, _ = _authorized_fixture(Path(directory))
            request_path.write_bytes(b"{" + b" " * MAX_JSON_BYTES)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, _environment(request, request_path), clear=True):
                    with self.assertRaisesRegex(SystemExit, "byte cap"):
                        admit_runtime()

    def test_request_symlink_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, request_path, _ = _authorized_fixture(root)
            link = root / "REQUEST.link.json"
            link.symlink_to(request_path.name)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                link,
            ):
                with patch.dict(os.environ, _environment(request, link), clear=True):
                    with self.assertRaisesRegex(SystemExit, "single-link regular file"):
                        admit_runtime()

    def test_request_hardlink_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, request_path, _ = _authorized_fixture(root)
            link = root / "REQUEST.hardlink.json"
            os.link(request_path, link)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                link,
            ):
                with patch.dict(os.environ, _environment(request, link), clear=True):
                    with self.assertRaisesRegex(SystemExit, "single-link regular file"):
                        admit_runtime()

    def test_request_path_swap_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, request_path, _ = _authorized_fixture(root)
            replacement = root / "replacement.json"
            replacement.write_bytes(request_path.read_bytes())
            real_open = os.open

            def swap_before_open(path, flags):
                request_path.unlink()
                replacement.rename(request_path)
                return real_open(path, flags)

            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch(
                    "qualification.hcsn_currentstate_n256_tail1159_intent.admission.os.open",
                    side_effect=swap_before_open,
                ):
                    with patch.dict(
                        os.environ, _environment(request, request_path), clear=True
                    ):
                        with self.assertRaisesRegex(
                            SystemExit, "changed while being opened"
                        ):
                            admit_runtime()

    def test_duplicate_request_key_refuses_before_input_read(self):
        with tempfile.TemporaryDirectory() as directory:
            request, request_path, _ = _authorized_fixture(Path(directory))
            raw = request_path.read_bytes().replace(
                b'"actual_execution_authorized": true',
                b'"actual_execution_authorized": true, "actual_execution_authorized": false',
                1,
            )
            request_path.write_bytes(raw)
            with patch(
                "qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST",
                request_path,
            ):
                with patch.dict(os.environ, _environment(request, request_path), clear=True):
                    with self.assertRaisesRegex(SystemExit, "unambiguous JSON"):
                        admit_runtime()

    def test_package_contains_no_runtime_outputs(self):
        names = {path.name for path in Path(__file__).resolve().parent.iterdir()}
        self.assertFalse({"RUN_OUTPUT", "FINAL_OUTPUT", "COLLECTED_LANES"} & names)

    def test_synthetic_lane_outputs_are_recomputed_from_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            request, result, result_path = _synthetic_lane_output(Path(directory))
            self.assertEqual(
                validate_lane_result(result_path, 0, request, IDENTITY), result
            )

    def test_result_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            request, _, result_path = _synthetic_lane_output(Path(directory))
            link = result_path.with_name("RESULT.link.json")
            link.symlink_to(result_path.name)
            with self.assertRaisesRegex(SystemExit, "single-link regular file"):
                validate_lane_result(link, 0, request, IDENTITY)

    def test_duplicate_result_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            request, _, result_path = _synthetic_lane_output(Path(directory))
            raw = result_path.read_bytes().replace(
                b'"lane_ordinal": 0,', b'"lane_ordinal": 0, "lane_ordinal": 1,', 1
            )
            result_path.write_bytes(raw)
            with self.assertRaisesRegex(SystemExit, "strict unambiguous JSON"):
                validate_lane_result(result_path, 0, request, IDENTITY)

    def test_checkpoint_digest_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            request, result, result_path = _synthetic_lane_output(Path(directory))
            result["checkpoint_compact_sha256"] = "0" * 64
            result_path.write_text(json.dumps(result, sort_keys=True))
            with self.assertRaisesRegex(SystemExit, "compact checkpoint bytes differ"):
                validate_lane_result(result_path, 0, request, IDENTITY)

    def test_tail_summary_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            request, result, result_path = _synthetic_lane_output(Path(directory))
            result["tail"]["unique_coordinate_count"] = 0
            result_path.write_text(json.dumps(result, sort_keys=True))
            with self.assertRaisesRegex(SystemExit, "tail summary differs"):
                validate_lane_result(result_path, 0, request, IDENTITY)

    def test_work_ledger_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            request, result, result_path = _synthetic_lane_output(Path(directory))
            result["work"]["recurrence_row_actions"] = 621
            result_path.write_text(json.dumps(result, sort_keys=True))
            with self.assertRaisesRegex(SystemExit, "work ledger differs"):
                validate_lane_result(result_path, 0, request, IDENTITY)

    def test_small_exact_continuation_and_tail(self):
        state256, parent = _index256_fixture()
        state537 = advance_to_index537(state256, parent)
        state1159 = advance_to_index1159(state537, parent)
        tail = final_tail_check(state1159, parent)
        self.assertEqual(state1159.included_index, TARGET_INDEX)
        self.assertEqual(tail["coordinate_count"], 2)
        self.assertTrue(tail["all_coordinates_unique"])
        self.assertEqual(encode_raw_index1159(state1159), encode_raw_index1159(state1159))

    def test_wrong_boundary_refuses(self):
        state256, parent = _index256_fixture()
        with self.assertRaisesRegex(ValueError, "not index537"):
            advance_to_index1159(state256, parent)
        with self.assertRaisesRegex(ValueError, "not index1159"):
            final_tail_check(state256, parent)


if __name__ == "__main__":
    unittest.main()

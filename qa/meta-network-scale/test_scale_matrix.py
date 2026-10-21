import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr

MODULE_PATH = pathlib.Path(__file__).with_name("scale_matrix.py")
spec = importlib.util.spec_from_file_location("scale_matrix", MODULE_PATH)
assert spec and spec.loader
scale_matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scale_matrix)


class ScaleMatrixTests(unittest.TestCase):
    def test_plan_contains_requested_sizes_arms_and_lifecycle(self):
        plan = scale_matrix.build_plan()
        self.assertEqual(plan["sizes"], [1, 8, 64, 256, 1024, 4096])
        self.assertEqual(plan["arms"], list(scale_matrix.ARMS))
        self.assertEqual(plan["required_provenance"], list(scale_matrix.PROVENANCE_FIELDS))
        self.assertEqual(plan["topology_lifecycle"], list(scale_matrix.LIFECYCLE))

    def test_incomplete_result_is_rejected(self):
        errors = scale_matrix.validate_result(
            {
                "schema": "hepta.cell-execution-scale-result.v1",
                "size": 8,
                "arm": "shared_encoder",
                "authority": "qualification_only",
            }
        )
        self.assertIn("evidence must be an object", errors)
        self.assertIn("provenance must be an object", errors)
        self.assertIn("evidence_receipts must be an object", errors)
        self.assertIn("metrics must be an object", errors)
        self.assertIn("metrics_receipt must be a lowercase SHA-256 digest", errors)

    def test_complete_result_is_accepted(self):
        result = {
            "schema": "hepta.cell-execution-scale-result.v1",
            "size": 4096,
            "arm": "shared_encoder",
            "authority": "qualification_only",
            "provenance": {
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "target_host_digest": "c" * 64,
                "runtime_digest": "d" * 64,
                "measurement_digest": "e" * 64,
            },
            "evidence": {key: True for key in scale_matrix.REQUIRED_EVIDENCE},
            "evidence_receipts": {
                key: "f" * 64 for key in scale_matrix.REQUIRED_EVIDENCE
            },
            "metrics": {key: 0 for key in scale_matrix.REQUIRED_METRICS},
            "metrics_receipt": "1" * 64,
            "topology_lifecycle": list(scale_matrix.LIFECYCLE),
        }
        self.assertEqual(scale_matrix.validate_result(result), [])

    def test_invalid_generation_evidence_cannot_be_hidden_in_metadata(self):
        result = {
            "schema": "hepta.cell-execution-scale-result.v1",
            "size": 1,
            "arm": "no_change",
            "authority": "qualification_only",
            "provenance": {
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "target_host_digest": "c" * 64,
                "runtime_digest": "d" * 64,
                "measurement_digest": "e" * 64,
            },
            "evidence": {key: True for key in scale_matrix.REQUIRED_EVIDENCE},
            "evidence_receipts": {
                key: "f" * 64 for key in scale_matrix.REQUIRED_EVIDENCE
            },
            "metrics": {key: 0 for key in scale_matrix.REQUIRED_METRICS},
            "metrics_receipt": "1" * 64,
            "topology_lifecycle": list(scale_matrix.LIFECYCLE),
            "metadata": {"stale_generation_rejection": True},
        }
        result["evidence"]["stale_generation_rejection"] = False
        self.assertIn(
            "evidence.stale_generation_rejection must be true",
            scale_matrix.validate_result(result),
        )

    def test_provenance_and_receipts_are_not_optional(self):
        result = {
            "schema": "hepta.cell-execution-scale-result.v1",
            "size": 64,
            "arm": "shared_encoder",
            "authority": "qualification_only",
            "evidence": {key: True for key in scale_matrix.REQUIRED_EVIDENCE},
            "metrics": {key: 0 for key in scale_matrix.REQUIRED_METRICS},
            "topology_lifecycle": list(scale_matrix.LIFECYCLE),
        }
        errors = scale_matrix.validate_result(result)
        self.assertIn("provenance must be an object", errors)
        self.assertIn("evidence_receipts must be an object", errors)
        self.assertIn("metrics_receipt must be a lowercase SHA-256 digest", errors)

    def test_non_finite_boolean_and_negative_metrics_are_rejected(self):
        result = {
            "schema": "hepta.cell-execution-scale-result.v1",
            "size": 64,
            "arm": "shared_encoder",
            "authority": "qualification_only",
            "provenance": {
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "target_host_digest": "c" * 64,
                "runtime_digest": "d" * 64,
                "measurement_digest": "e" * 64,
            },
            "evidence": {key: True for key in scale_matrix.REQUIRED_EVIDENCE},
            "evidence_receipts": {
                key: "f" * 64 for key in scale_matrix.REQUIRED_EVIDENCE
            },
            "metrics": {key: 0 for key in scale_matrix.REQUIRED_METRICS},
            "metrics_receipt": "1" * 64,
            "topology_lifecycle": list(scale_matrix.LIFECYCLE),
        }
        result["metrics"]["p99_ms"] = float("nan")
        result["metrics"]["rss_bytes"] = -1
        result["metrics"]["queue_age_ms"] = True
        errors = scale_matrix.validate_result(result)
        self.assertIn("metrics.p99_ms must be a finite number", errors)
        self.assertIn("metrics.rss_bytes must be non-negative", errors)
        self.assertIn("metrics.queue_age_ms must be a finite number", errors)
        result["metrics"]["p99_ms"] = 10**1000
        errors = scale_matrix.validate_result(result)
        self.assertIn("metrics.p99_ms must be a finite number", errors)


    def make_record(self, size, arm):
        return {
            "schema": "hepta.cell-execution-scale-result.v1",
            "size": size,
            "arm": arm,
            "authority": "qualification_only",
            "provenance": {
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "target_host_digest": "c" * 64,
                "runtime_digest": "d" * 64,
                "measurement_digest": "e" * 64,
            },
            "evidence": {key: True for key in scale_matrix.REQUIRED_EVIDENCE},
            "evidence_receipts": {
                key: "f" * 64 for key in scale_matrix.REQUIRED_EVIDENCE
            },
            "metrics": {key: 0 for key in scale_matrix.REQUIRED_METRICS},
            "metrics_receipt": "1" * 64,
            "topology_lifecycle": list(scale_matrix.LIFECYCLE),
        }

    def matrix(self):
        return {
            "schema": "hepta.cell-execution-scale-matrix-result.v1",
            "authority": "qualification_only",
            "results": [
                self.make_record(size, arm)
                for size in scale_matrix.SIZES
                for arm in scale_matrix.ARMS
            ],
        }

    def test_full_matrix_shape_is_qualification_only(self):
        matrix = self.matrix()
        self.assertEqual(len(matrix["results"]), 36)
        self.assertEqual(scale_matrix.validate_matrix(matrix), [])
        matrix["authority"] = "production"
        self.assertIn(
            "matrix authority must remain qualification_only",
            scale_matrix.validate_matrix(matrix),
        )

    def test_matrix_rejects_omissions_and_duplicate_pairs(self):
        matrix = self.matrix()
        matrix["results"].pop()
        errors = scale_matrix.validate_matrix(matrix)
        self.assertIn("matrix must contain exactly 36 results", errors)
        self.assertIn("missing matrix pair: 4096/duplicated_encoder", errors)
        matrix["results"].append(self.make_record(1, "no_change"))
        errors = scale_matrix.validate_matrix(matrix)
        self.assertIn("duplicate matrix pair: 1/no_change", errors)
        self.assertIn("missing matrix pair: 4096/duplicated_encoder", errors)

    def test_matrix_rejects_cross_host_or_cross_commit_comparisons(self):
        for key, changed in [
            ("source_commit", "9" * 40),
            ("source_tree", "8" * 40),
            ("target_host_digest", "7" * 64),
        ]:
            with self.subTest(key=key):
                matrix = self.matrix()
                matrix["results"][1]["provenance"][key] = changed
                errors = scale_matrix.validate_matrix(matrix)
                self.assertIn(
                    "results[1].provenance differs from matrix source/host cohort",
                    errors,
                )

    def test_boolean_scale_and_invalid_rows_are_rejected(self):
        result = self.make_record(True, "no_change")
        self.assertIn(
            "size must be one of 1, 8, 64, 256, 1024, 4096",
            scale_matrix.validate_result(result),
        )
        matrix = self.matrix()
        matrix["results"][-1] = result
        self.assertTrue(scale_matrix.validate_matrix(matrix))
        matrix["results"][-1] = None
        self.assertIn(
            "results[35] must be an object",
            scale_matrix.validate_matrix(matrix),
        )

    def test_duplicate_authority_and_nested_provenance_keys_fail_closed(self):
        # A last-wins JSON decoder could hide a production authority claim
        # or a conflicting provenance digest from another verifier.
        for payload in (
            '{"authority":"production","authority":"qualification_only"}',
            '{"provenance":{"source_commit":"a","source_commit":"b"}}',
        ):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                ValueError, "duplicate JSON key"
            ):
                scale_matrix.load_strict_json(io.StringIO(payload))

    def test_json_nonfinite_literals_and_nonobject_result_are_rejected(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal), self.assertRaisesRegex(
                ValueError, "non-finite JSON token"
            ):
                scale_matrix.load_strict_json(io.StringIO('{"value":' + literal + '}'))
        self.assertEqual(
            scale_matrix.validate_result(["not", "a", "result"]),
            ["result must be an object"],
        )

    def test_bounded_json_parser_rejects_oversized_and_non_utf8_input(self):
        oversized = io.StringIO(" " * (scale_matrix.MAX_QUALIFICATION_JSON_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "exceeds 4 MiB input limit"):
            scale_matrix.load_strict_json(oversized)
        with self.assertRaisesRegex(ValueError, "must be valid UTF-8"):
            scale_matrix.load_strict_json(io.BytesIO(bytes([0xFF])))

    def test_cli_rejects_duplicate_keys_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "ambiguous.json"
            path.write_text(
                '{"schema":"hepta.cell-execution-scale-result.v1",'
                '"authority":"production","authority":"qualification_only"}',
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = scale_matrix.main(["validate", str(path)])
            self.assertEqual(exit_code, 1)
            self.assertIn("duplicate JSON key: authority", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

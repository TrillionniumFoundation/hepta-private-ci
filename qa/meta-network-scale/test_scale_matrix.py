import importlib.util
import json
import pathlib
import unittest

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


if __name__ == "__main__":
    unittest.main()

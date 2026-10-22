import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
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
        self.assertEqual(
            plan["required_provenance"], list(scale_matrix.PROVENANCE_FIELDS)
        )
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

    def test_result_rejects_unregistered_authority_claims_at_every_depth(self):
        for scope in (
            "result",
            "provenance",
            "evidence",
            "evidence_receipts",
            "metrics",
        ):
            with self.subTest(scope=scope):
                result = self.make_record(64, "shared_encoder")
                target = result if scope == "result" else result[scope]
                target["final_use_authorized"] = True
                self.assertIn(
                    f"{scope}.final_use_authorized is not a registered field",
                    scale_matrix.validate_result(result),
                )

    def test_matrix_rejects_undeclared_release_and_row_claims(self):
        matrix = self.matrix()
        matrix["production_admission"] = True
        self.assertIn(
            "matrix.production_admission is not a registered field",
            scale_matrix.validate_matrix(matrix),
        )

        matrix = self.matrix()
        matrix["results"][3]["release_approved"] = True
        self.assertIn(
            "results[3].result.release_approved is not a registered field",
            scale_matrix.validate_matrix(matrix),
        )

    def test_cli_rejects_duplicate_nonfinite_and_oversized_json(self):
        # No parser should silently pick the last of two authority values.
        inputs = (
            b'{"authority":"production","authority":"qualification_only"}',
            b'{"authority":NaN}',
            b" " * (scale_matrix.MAX_INPUT_BYTES + 1),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "untrusted.json"
            for payload in inputs:
                with self.subTest(payload_size=len(payload)):
                    path.write_bytes(payload)
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(scale_matrix.main(["validate", str(path)]), 1)

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
                key: f"{2000 + index:064x}"
                for index, key in enumerate(scale_matrix.REQUIRED_EVIDENCE)
            },
            "metrics": {key: 0 for key in scale_matrix.REQUIRED_METRICS},
            "metrics_receipt": "1" * 64,
            "topology_lifecycle": list(scale_matrix.LIFECYCLE),
        }
        self.assertEqual(scale_matrix.validate_result(result), [])

    def test_metric_requirements_match_benchmark_spec(self):
        spec_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "docs"
            / "learning"
            / "CELL_EXECUTION_BENCHMARK_MATRIX.json"
        )
        with spec_path.open(encoding="utf-8") as handle:
            benchmark = json.load(handle)
        self.assertEqual(
            list(scale_matrix.REQUIRED_METRICS),
            benchmark["metrics"],
            "P4 qualification must reject missing metrics from the benchmark contract",
        )

    def test_p5_exact_source_workflow_covers_input_metric_and_ndu_contracts(self):
        # A change to an imported benchmark spec or the P3 selector must not
        # leave the P5 evidence contract silently untested at the new source SHA.
        workflow = (
            pathlib.Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
            / "hepta-p5-scale-evidence-exact.yml"
        ).read_text(encoding="utf-8")
        pull_request_paths = workflow.partition("  workflow_dispatch:")[0]
        expected = (
            "qa/meta-network-scale/**",
            "docs/learning/CELL_EXECUTION_BENCHMARK_MATRIX.json",
            "codex-rs/hepta-ndu/src/output_portfolio.rs",
            "codex-rs/hepta-ndu/src/output_portfolio_tests.rs",
            "codex-rs/hepta-ndu/src/output_portfolio_types.rs",
            ".github/workflows/hepta-p5-scale-evidence-exact.yml",
        )
        for path in expected:
            with self.subTest(path=path):
                self.assertIn(f'      - "{path}"', pull_request_paths)

    def test_p4_metrics_are_required_and_rate_units_are_bounded(self):
        for key in scale_matrix.REQUIRED_METRICS:
            with self.subTest(missing=key):
                record = self.make_record(64, "shared_encoder")
                del record["metrics"][key]
                self.assertIn(
                    f"metrics.{key} is required",
                    scale_matrix.validate_result(record),
                )
        for key in ("negative_transfer_rate", "immutable_buffer_reuse_rate"):
            for invalid in (1.01, -0.01):
                with self.subTest(rate=key, invalid=invalid):
                    record = self.make_record(64, "shared_encoder")
                    record["metrics"][key] = invalid
                    self.assertTrue(
                        any(
                            message.startswith(f"metrics.{key} must be ")
                            for message in scale_matrix.validate_result(record)
                        )
                    )
        record = self.make_record(64, "shared_encoder")
        record["metrics"]["future_window_utility"] = -1.25
        self.assertEqual(scale_matrix.validate_result(record), [])

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
                key: f"{2000 + index:064x}"
                for index, key in enumerate(scale_matrix.REQUIRED_EVIDENCE)
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

    def test_zero_hash_placeholders_cannot_masquerade_as_scale_evidence(self):
        # A zero identity is an absent/uninitialized pointer, not an actual
        # Git object, signed observer receipt, runtime or measurement digest.
        for key in scale_matrix.PROVENANCE_FIELDS:
            with self.subTest(provenance=key):
                record = self.make_record(64, "shared_encoder")
                length = 40 if key in ("source_commit", "source_tree") else 64
                record["provenance"][key] = "0" * length
                self.assertIn(
                    f"provenance.{key} cannot be a zero digest",
                    scale_matrix.validate_result(record),
                )
        for key in scale_matrix.REQUIRED_EVIDENCE:
            with self.subTest(evidence_receipt=key):
                record = self.make_record(64, "shared_encoder")
                record["evidence_receipts"][key] = "0" * 64
                self.assertIn(
                    f"evidence_receipts.{key} cannot be a zero digest",
                    scale_matrix.validate_result(record),
                )
        record = self.make_record(64, "shared_encoder")
        record["metrics_receipt"] = "0" * 64
        self.assertIn(
            "metrics_receipt cannot be a zero digest",
            scale_matrix.validate_result(record),
        )
        matrix = self.matrix()
        matrix["results"][0]["provenance"]["measurement_digest"] = "0" * 64
        self.assertIn(
            "results[0].provenance.measurement_digest cannot be a zero digest",
            scale_matrix.validate_matrix(matrix),
        )

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
                key: f"{2000 + index:064x}"
                for index, key in enumerate(scale_matrix.REQUIRED_EVIDENCE)
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
        # Deterministic fixture digests remain distinct across experiment arms.
        index = (
            scale_matrix.SIZES.index(size) * len(scale_matrix.ARMS)
            + scale_matrix.ARMS.index(arm)
        )
        evidence_id_base = 2000 + index * len(scale_matrix.REQUIRED_EVIDENCE)
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
                "measurement_digest": f"{100 + index:064x}",
            },
            "evidence": {key: True for key in scale_matrix.REQUIRED_EVIDENCE},
            "evidence_receipts": {
                claim: f"{evidence_id_base + offset:064x}"
                for offset, claim in enumerate(scale_matrix.REQUIRED_EVIDENCE)
            },
            "metrics": {key: 0 for key in scale_matrix.REQUIRED_METRICS},
            "metrics_receipt": f"{1000 + index:064x}",
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

    def test_latency_percentiles_and_physical_counts_are_consistent(self):
        record = self.make_record(1024, "shared_encoder")
        record["metrics"]["p50_ms"] = 5
        record["metrics"]["p95_ms"] = 4
        record["metrics"]["p99_ms"] = 3
        self.assertIn(
            "metrics latency percentiles must satisfy p50 <= p95 <= p99",
            scale_matrix.validate_result(record),
        )
        for count in (
            "rss_bytes",
            "gpu_peak_bytes",
            "starvation_count",
            "cache_invalidation_count",
        ):
            with self.subTest(count=count):
                record = self.make_record(1024, "shared_encoder")
                record["metrics"][count] = 1.5
                self.assertIn(
                    f"metrics.{count} must be an integer count",
                    scale_matrix.validate_result(record),
                )

    def test_matrix_rejects_recycled_metrics_and_measurement_receipts(self):
        matrix = self.matrix()
        self.assertEqual(scale_matrix.validate_matrix(matrix), [])
        matrix["results"][1]["metrics_receipt"] = matrix["results"][0][
            "metrics_receipt"
        ]
        errors = scale_matrix.validate_matrix(matrix)
        self.assertIn(
            "results[1].metrics_receipt reused across matrix pairs", errors
        )
        matrix = self.matrix()
        matrix["results"][1]["provenance"]["measurement_digest"] = (
            matrix["results"][0]["provenance"]["measurement_digest"]
        )
        errors = scale_matrix.validate_matrix(matrix)
        self.assertIn(
            "results[1].provenance.measurement_digest reused across matrix pairs",
            errors,
        )

    def test_matrix_rejects_recycled_claim_receipts_across_arms(self):
        matrix = self.matrix()
        self.assertEqual(scale_matrix.validate_matrix(matrix), [])
        # The same future-window or rollback witness cannot certify both
        # no-change and a different routed/encoder experiment pair.
        for claim in ("future_window", "rollback"):
            with self.subTest(claim=claim):
                matrix = self.matrix()
                matrix["results"][1]["evidence_receipts"][claim] = matrix["results"][0][
                    "evidence_receipts"
                ][claim]
                self.assertIn(
                    f"results[1].evidence_receipts.{claim} reused across matrix pairs",
                    scale_matrix.validate_matrix(matrix),
                )

    def test_one_result_rejects_reused_receipt_for_different_claims(self):
        record = self.make_record(64, "shared_encoder")
        record["evidence_receipts"]["rollback"] = record["evidence_receipts"][
            "future_window"
        ]
        self.assertIn(
            "evidence_receipts.rollback reuses the future_window claim receipt",
            scale_matrix.validate_result(record),
        )

    def test_matrix_rejects_cross_row_cross_claim_receipt_replay(self):
        matrix = self.matrix()
        self.assertEqual(scale_matrix.validate_matrix(matrix), [])
        matrix["results"][1]["evidence_receipts"]["rollback"] = matrix["results"][0][
            "evidence_receipts"
        ]["future_window"]
        self.assertIn(
            "results[1].evidence_receipts.rollback reused for a different evidence claim",
            scale_matrix.validate_matrix(matrix),
        )

    def test_metrics_receipt_must_not_reuse_an_evidence_claim(self):
        record = self.make_record(64, "shared_encoder")
        record["metrics_receipt"] = record["evidence_receipts"]["future_window"]
        self.assertIn(
            "metrics_receipt cannot reuse an evidence claim receipt",
            scale_matrix.validate_result(record),
        )

    def test_matrix_rejects_cross_category_receipt_replay_in_both_orders(self):
        matrix = self.matrix()
        matrix["results"][1]["metrics_receipt"] = matrix["results"][0][
            "evidence_receipts"
        ]["future_window"]
        self.assertIn(
            "results[1].metrics_receipt reused as an evidence claim receipt",
            scale_matrix.validate_matrix(matrix),
        )
        matrix = self.matrix()
        matrix["results"][1]["evidence_receipts"]["rollback"] = matrix[
            "results"
        ][0]["metrics_receipt"]
        self.assertIn(
            "results[1].evidence_receipts.rollback reused as a metrics receipt",
            scale_matrix.validate_matrix(matrix),
        )

    def test_measurement_digest_cannot_double_as_metrics_or_evidence_receipt(self):
        for role in ("metrics", "future_window", "rollback"):
            with self.subTest(role=role):
                record = self.make_record(64, "shared_encoder")
                if role == "metrics":
                    record["provenance"]["measurement_digest"] = record["metrics_receipt"]
                    expected = "metrics_receipt cannot reuse provenance measurement digest"
                else:
                    record["provenance"]["measurement_digest"] = record["evidence_receipts"][role]
                    expected = (
                        f"evidence_receipts.{role} cannot reuse provenance measurement digest"
                    )
                self.assertIn(expected, scale_matrix.validate_result(record))

    def test_matrix_rejects_measurement_digest_replay_across_proof_roles(self):
        # Both orderings must be rejected: measurement followed by a receipt,
        # or receipt followed by a later relabelled measurement digest.
        for proof_role in ("metrics", "evidence"):
            for direction in ("measurement_first", "receipt_first"):
                with self.subTest(role=proof_role, direction=direction):
                    matrix = self.matrix()
                    first, second = matrix["results"][:2]
                    if proof_role == "metrics":
                        if direction == "measurement_first":
                            second["metrics_receipt"] = first["provenance"]["measurement_digest"]
                            expected = (
                                "results[1].metrics_receipt "
                                "reused as a provenance measurement digest"
                            )
                        else:
                            second["provenance"]["measurement_digest"] = first["metrics_receipt"]
                            expected = (
                                "results[1].provenance.measurement_digest "
                                "reused as a metrics receipt"
                            )
                    else:
                        if direction == "measurement_first":
                            second["evidence_receipts"]["rollback"] = first["provenance"][
                                "measurement_digest"
                            ]
                            expected = (
                                "results[1].evidence_receipts.rollback "
                                "reused as a provenance measurement digest"
                            )
                        else:
                            second["provenance"]["measurement_digest"] = first[
                                "evidence_receipts"
                            ]["future_window"]
                            expected = (
                                "results[1].provenance.measurement_digest "
                                "reused as an evidence claim receipt"
                            )
                    self.assertIn(expected, scale_matrix.validate_matrix(matrix))

    def test_identity_roles_cannot_be_relabelled_as_single_row_evidence(self):
        for identity in ("target_host_digest", "runtime_digest"):
            for proof in ("measurement", "metrics", "rollback"):
                with self.subTest(identity=identity, proof=proof):
                    row = self.make_record(64, "shared_encoder")
                    digest = row["provenance"][identity]
                    if proof == "measurement":
                        row["provenance"]["measurement_digest"] = digest
                        expected = (
                            f"provenance.{identity} cannot reuse measurement digest"
                        )
                    elif proof == "metrics":
                        row["metrics_receipt"] = digest
                        expected = f"metrics_receipt cannot reuse provenance {identity}"
                    else:
                        row["evidence_receipts"]["rollback"] = digest
                        expected = (
                            "evidence_receipts.rollback cannot reuse provenance "
                            f"{identity}"
                        )
                    self.assertIn(expected, scale_matrix.validate_result(row))
        row = self.make_record(64, "shared_encoder")
        row["provenance"]["runtime_digest"] = row["provenance"]["target_host_digest"]
        self.assertIn(
            "provenance.runtime_digest cannot reuse target_host_digest",
            scale_matrix.validate_result(row),
        )

    def test_matrix_denies_cross_row_identity_evidence_aliases_in_both_orders(self):
        for proof in ("measurement", "metrics", "rollback"):
            for direction in ("identity_first", "evidence_first"):
                with self.subTest(proof=proof, direction=direction):
                    matrix = self.matrix()
                    first, second = matrix["results"][:2]
                    if proof == "measurement":
                        parent, key, label = (
                            "provenance",
                            "measurement_digest",
                            "provenance.measurement_digest",
                        )
                    elif proof == "metrics":
                        parent, key, label = None, "metrics_receipt", "metrics_receipt"
                    else:
                        parent, key, label = (
                            "evidence_receipts",
                            "rollback",
                            "evidence_receipts.rollback",
                        )
                    first_value = first[parent][key] if parent else first[key]
                    if direction == "identity_first":
                        value = first["provenance"]["runtime_digest"]
                        if parent:
                            second[parent][key] = value
                        else:
                            second[key] = value
                        affected = f"results[1].{label}"
                    else:
                        second["provenance"]["runtime_digest"] = first_value
                        affected = f"results[0].{label}"
                    self.assertIn(
                        f"{affected} reused as a runtime_digest identity digest",
                        scale_matrix.validate_matrix(matrix),
                    )

    def test_matrix_denies_cross_row_host_runtime_identity_alias(self):
        matrix = self.matrix()
        matrix["results"][1]["provenance"]["runtime_digest"] = matrix["results"][0][
            "provenance"
        ]["target_host_digest"]
        self.assertIn(
            "results[1].provenance.runtime_digest "
            "reused as a target_host_digest identity digest",
            scale_matrix.validate_matrix(matrix),
        )

    def test_invalid_result_root_is_a_denial_not_an_exception(self):
        for malformed in ([], None, 42, ""):
            with self.subTest(value=malformed):
                self.assertEqual(
                    scale_matrix.validate_result(malformed),
                    ["result must be an object"],
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


if __name__ == "__main__":
    unittest.main()

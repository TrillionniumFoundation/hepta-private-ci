#!/usr/bin/env python3
"""Adversarial tests for the qualification boundary (no Rust execution claims)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import verify_memory_retrieval_slo as slo


def profile() -> dict:
    return {"schema": "hepta.memory-retrieval.slo-thresholds.v1", "profile": "test-only",
            "phases": {"hnmf": {"p95_us": 20, "p99_us": 30}}}


def row() -> dict:
    return {"schema": slo.SCHEMA, "phase": "hnmf", "iterations": 100,
            "p50_us": 10, "p95_us": 20, "p99_us": 30}


def e2e() -> dict:
    value = {key: 1 for key in slo.E2E_METRICS}
    value.update(schema=slo.E2E_SCHEMA, phase="agentd-e2e", attempts=100,
                 p50_us=10, p95_us=20, p99_us=30, max_us=40,
                 abstention_count=2, stale_rejection_count=3, failure_count=0,
                 delivered_count=95, cache_state="warm", resource_scope="request_pipeline",
                 stage_observations={stage: 100 for stage in slo.STAGES},
                 stage_executions={stage: 95 for stage in slo.STAGES},
                 pending_learning_assignments=0, abstention_rate_ppm=20_000,
                 stale_rejection_rate_ppm=30_000)
    return value


class SloBoundaryTests(unittest.TestCase):
    def test_exact_limits_pass(self):
        self.assertEqual(slo.verify_measurements([row()], profile()), [])

    def test_regression_fails(self):
        value = row(); value["p95_us"] = 21
        self.assertEqual(slo.verify_measurements([value], profile()), ["hnmf: p95_us=21 exceeds 20"])

    def test_boolean_is_not_measurement(self):
        for field in ("p95_us", "p99_us"):
            value = row(); value[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                slo.verify_measurements([value], profile())

    def test_negative_and_noninteger_metrics_rejected(self):
        for invalid in (-1, 1.5, "12", None):
            value = row(); value["p95_us"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                slo.verify_measurements([value], profile())

    def test_invalid_thresholds_rejected(self):
        for invalid in (-1, True, float("inf"), "100"):
            limits = profile(); limits["phases"]["hnmf"]["p95_us"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                slo.verify_measurements([row()], limits)

    def test_duplicate_phases_never_overwrite(self):
        with self.assertRaises(ValueError):
            slo.verify_measurements([row(), row()], profile())

    def test_missing_phase_fails_closed(self):
        with self.assertRaises(ValueError):
            slo.verify_measurements([], profile())

    def test_extra_phase_rejected(self):
        extra = row(); extra["phase"] = "not-in-profile"
        with self.assertRaises(ValueError):
            slo.verify_measurements([row(), extra], profile())

    def test_empty_profile_does_not_vacuously_pass(self):
        for phases in ({}, {"hnmf": {}}):
            limits = profile(); limits["phases"] = phases
            with self.subTest(phases=phases), self.assertRaises(ValueError):
                slo.verify_measurements([row()], limits)

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):
            slo.loads('{"p95_us":99999,"p95_us":1}')

    def test_nonfinite_json_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                slo.loads('{"p95_us":' + value + '}')

    def test_nonmonotone_percentiles_rejected(self):
        for prefix in ("", "retrieval_", "revalidation_"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                slo.validate_percentiles({prefix + "p50_us": 100, prefix + "p95_us": 50})

    def test_load_binds_exact_raw_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            raw = (json.dumps(row()) + "\nMaximum resident set size (kbytes): 123\n").encode()
            path.write_bytes(raw)
            value = slo.load_measurement(path)
            self.assertEqual(value["log_sha256"], slo.sha256(raw))
            self.assertEqual(value["maximum_rss_kb"], 123)
            self.assertEqual(value["rss_scope"], "whole_command_including_build_if_any")

    def test_duplicate_measurement_rows_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            path.write_text((json.dumps(row()) + "\n") * 2)
            with self.assertRaises(ValueError):
                slo.load_measurement(path)

    def test_missing_and_ambiguous_rss_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            for count in (0, 2):
                path.write_text(json.dumps(row()) + "\n" + "Maximum resident set size (kbytes): 123\n" * count)
                with self.subTest(count=count), self.assertRaises(ValueError):
                    slo.load_measurement(path)

    def test_log_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            with path.open("wb") as stream:
                stream.truncate(slo.MAX_LOG_BYTES + 1)
            with self.assertRaises(ValueError):
                slo.load_measurement(path)

    def test_zero_iterations_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            value = row(); value["iterations"] = 0
            path.write_text(json.dumps(value) + "\nMaximum resident set size (kbytes): 123\n")
            with self.assertRaises(ValueError):
                slo.load_measurement(path)

    def test_microbenchmark_cannot_qualify_e2e(self):
        with self.assertRaises(ValueError):
            slo.verify_measurements([row()], profile(), require_e2e=True)

    def test_e2e_observes_the_full_pipeline(self):
        self.assertIsNone(slo.validate_e2e(e2e()))

    def test_e2e_missing_stage_rejected(self):
        value = e2e(); del value["stage_observations"]["learning_assignment_append"]
        with self.assertRaises(ValueError):
            slo.validate_e2e(value)

    def test_observations_are_not_execution_evidence(self):
        value = e2e(); value["stage_executions"]["downstream_ranker"] = 0
        with self.assertRaises(ValueError):
            slo.validate_e2e(value)

    def test_e2e_unsettled_learning_is_not_complete(self):
        value = e2e(); value["pending_learning_assignments"] = 1
        with self.assertRaises(ValueError):
            slo.validate_e2e(value)

    def test_e2e_rates_and_outcomes_are_recomputed(self):
        for key in ("abstention_rate_ppm", "stale_rejection_rate_ppm", "delivered_count"):
            value = e2e(); value[key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                slo.validate_e2e(value)

    def test_cargo_rss_is_not_request_pipeline_rss(self):
        value = e2e(); value["resource_scope"] = "cargo_test"
        with self.assertRaises(ValueError):
            slo.validate_e2e(value)

    def test_immutable_output_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            slo.write_immutable(path, {"passed": False})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                slo.write_immutable(path, {"passed": True})
            self.assertEqual(path.read_bytes(), before)

    def test_canonical_hash_ignores_dictionary_order_only(self):
        self.assertEqual(slo.canonical({"b": 2, "a": 1}), slo.canonical({"a": 1, "b": 2}))
        self.assertNotEqual(slo.canonical({"a": 1}), slo.canonical({"a": True}))

    def test_exact_source_rejects_dirty_and_substituted_heads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            git("init", "-q")
            git("config", "user.name", "Qualification test")
            git("config", "user.email", "qualification-test@example.invalid")
            (root / "source.rs").write_text("source\n")
            git("add", "source.rs"); git("commit", "-qm", "fixture")
            head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
            self.assertEqual(slo.source_identity(root, head, tree)["commit"], head)
            with self.assertRaises(ValueError):
                slo.source_identity(root, "0" * 40, tree)
            (root / "source.rs").write_text("changed\n")
            with self.assertRaises(ValueError):
                slo.source_identity(root, head, tree)


if __name__ == "__main__":
    unittest.main()

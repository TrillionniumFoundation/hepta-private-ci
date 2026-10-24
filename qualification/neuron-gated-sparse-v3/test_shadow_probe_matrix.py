"""Negative protocol tests. Synthetic fake receipts NEVER imply real execution."""
from __future__ import annotations

import copy
import hashlib
import unittest

import run_shadow_probe_matrix as matrix


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fake_probe() -> dict:
    return {
        "schema": matrix.REPORT_SCHEMA,
        "evidence_kind": matrix.EVIDENCE_KIND,
        "production_qualification": False,
        "ndu_eligible": False,
        "trained_model": False,
        "state_persistence_measured": False,
        "microbatch_and_gpu_measured": False,
        "artifact_provenance_verified": False,
        "arm": "v3",
        "cells": 64,
        "trace_sha256": sha(b"trace"),
        "logical_tick_count": 512,
        "process_wall_micros": 4_000,
        "p50_tick_nanos": 500,
        "p95_tick_nanos": 1_000,
        "p99_tick_nanos": 1_500,
        "process_peak_rss_bytes": 16_000_000,
        "frontier_digest": sha(b"checkpoint"),
        "warning": "fake data for protocol negative tests only",
    }


class ProbeMatrixProtocolTests(unittest.TestCase):
    def verify(self, payload: dict) -> dict:
        return matrix.validate_probe(
            payload, arm="v3", cells=64, digest=sha(b"trace"), events=8,
        )

    def test_valid_shape_never_grants_ndu(self) -> None:
        payload = self.verify(fake_probe())
        self.assertFalse(payload["production_qualification"])
        self.assertFalse(payload["ndu_eligible"])
        self.assertFalse(payload["trained_model"])

    def test_claim_of_production_qualification_fails(self) -> None:
        for forbidden in (
            "production_qualification", "ndu_eligible", "trained_model",
            "state_persistence_measured", "microbatch_and_gpu_measured",
            "artifact_provenance_verified",
        ):
            changed = fake_probe()
            changed[forbidden] = True
            with self.subTest(field=forbidden):
                with self.assertRaisesRegex(ValueError, forbidden):
                    self.verify(changed)

    def test_wrong_trace_digest_or_arm_or_case_count_rejected(self) -> None:
        for field, value in (
            ("arm", "v1"), ("trace_sha256", sha(b"different trace")),
            ("cells", 1024), ("logical_tick_count", 511),
            ("evidence_kind", "TARGET_HOST_EVIDENCE"),
        ):
            with self.subTest(field=field):
                changed = fake_probe()
                changed[field] = value
                with self.assertRaises(ValueError):
                    self.verify(changed)

    def test_missing_rss_or_latency_inversion_rejected(self) -> None:
        changed = fake_probe()
        changed["process_peak_rss_bytes"] = None
        with self.assertRaisesRegex(ValueError, "VmHWM"):
            self.verify(changed)
        changed = fake_probe()
        changed["p95_tick_nanos"] = 2_000
        with self.assertRaisesRegex(ValueError, "latency ordering"):
            self.verify(changed)

    def test_python_bool_cannot_impersonate_metric_integer(self) -> None:
        changed = fake_probe()
        changed["logical_tick_count"] = True
        with self.assertRaises(ValueError):
            self.verify(changed)
        changed = fake_probe()
        changed["process_wall_micros"] = False
        with self.assertRaisesRegex(ValueError, "wall-clock"):
            self.verify(changed)

    def test_missing_frontier_checkpoint_rejected(self) -> None:
        changed = fake_probe()
        changed["frontier_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "frontier"):
            self.verify(changed)


if __name__ == "__main__":
    unittest.main()

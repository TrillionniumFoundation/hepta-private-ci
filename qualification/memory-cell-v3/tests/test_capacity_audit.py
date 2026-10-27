import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from audit_capacity import audit_capacity
from v3.capacity_audit_core import sha256
from v3.capacity_study import run_capacity


class IndependentCapacityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.original = cls.root / "original"
        protocol = {
            "capacity": {
                "numeric_domains": [],
                "include_digits": False,
                "synthetic_rows": 24,
                "synthetic_columns": 6,
                "cells": 4,
                "random_mix": [0.0, 1.0],
                "budget_fractions_int32": [0.5, 1.0],
                "max_vq_cells": 8,
                "hidden_query_limit": 32,
                "kmeans_iterations": 4,
            }
        }
        run_capacity(protocol, cls.original, "test-unfrozen", [8011], development=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def clone(self, name):
        destination = self.root / name
        shutil.copytree(self.original, destination)
        return destination

    def test_independent_recompute_and_external_output(self):
        original_bytes = (self.original / "capacity-summary.json").read_bytes()
        report = audit_capacity(
            self.original, self.root / "audit.json", allow_legacy_development=True
        )
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["audited_selected_models"], 20)
        self.assertEqual(report["audited_pure_parameter_files"], 22)
        self.assertEqual(len(report["compact"]["random_source_negative_controls"]), 1)
        self.assertIn("cannot be retrospectively assigned", report["source_binding"])
        self.assertEqual(
            original_bytes, (self.original / "capacity-summary.json").read_bytes()
        )
        with self.assertRaises(ValueError):
            audit_capacity(self.original)
        with self.assertRaises(ValueError):
            audit_capacity(
                self.original,
                self.original / "forbidden.json",
                allow_legacy_development=True,
            )

    def test_reported_metric_tamper_is_detected(self):
        case = self.clone("metric-tamper")
        path = case / "capacity-summary.json"
        summary = json.loads(path.read_bytes())
        summary["records"][0]["hidden"]["mse_scaled_integer"] += 0.125
        path.write_text(json.dumps(summary))
        report = audit_capacity(case, allow_legacy_development=True)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any(
                "hidden mse_scaled_integer" in item["check"]
                for item in report["failures"]
            )
        )

    def test_artifact_and_work_receipt_tamper_are_detected(self):
        case = self.clone("artifact-tamper")
        summary = json.loads((case / "capacity-summary.json").read_bytes())
        record = summary["records"][0]
        path = (
            case
            / record["dataset"]
            / ("seed-" + str(record["seed"]))
            / (str(record["budget_bytes"]) + "-" + record["family"] + ".bin")
        )
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        report = audit_capacity(case, allow_legacy_development=True)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("digest mismatch" in str(item["detail"]) for item in report["failures"])
        )
        case = self.clone("work-tamper")
        summary_path = case / "capacity-summary.json"
        summary = json.loads(summary_path.read_bytes())
        record = next(
            r for r in summary["records"] if r["family"] == "predeclared_cells"
        )
        path = (
            case
            / record["dataset"]
            / ("seed-" + str(record["seed"]))
            / (str(record["budget_bytes"]) + "-" + record["family"] + ".control.json")
        )
        control = json.loads(path.read_bytes())
        control["actual_total_svd_work_proxy"] += 1
        record["same_work_global_control"]["actual_total_svd_work_proxy"] += 1
        path.write_text(json.dumps(control))
        summary_path.write_text(json.dumps(summary))
        report = audit_capacity(case, allow_legacy_development=True)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any(
                "total control SVD work" in item["check"] for item in report["failures"]
            )
        )

    def test_snapshot_protocol_binding_is_checked(self):
        run = self.root / "snapshot-fixture"
        run.mkdir()
        shutil.copytree(self.original, run / "capacity")
        summary_path = run / "capacity" / "capacity-summary.json"
        summary = json.loads(summary_path.read_bytes())
        summary["source_commit"] = "0" * 40
        summary_path.write_text(json.dumps(summary))
        protocol = {"capacity": summary["settings"], "development_seeds": [8011]}
        raw = json.dumps(protocol).encode()
        name = "qualification/memory-cell-v3/PROTOCOL.json"
        identity = {
            "commit": "0" * 40,
            "files": {name: {"bytes": len(raw), "sha256": sha256(raw)}},
        }
        (run / "source_identity.json").write_text(json.dumps(identity))
        (run / "protocol.json").write_bytes(raw)
        (run / "environment.json").write_text(json.dumps({"mode": "development_only"}))
        with zipfile.ZipFile(run / "source_snapshot.zip", "w") as archive:
            archive.writestr(name, raw)
        report = audit_capacity(run)
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["source_binding"], "snapshot-bound-development")
        (run / "protocol.json").write_bytes(raw + b"\n")
        report = audit_capacity(run)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any(
                item["check"] == "protocol snapshot bytes"
                for item in report["failures"]
            )
        )


if __name__ == "__main__":
    unittest.main()

"""Public source/Cell Q24 lineage tests; synthetic fixtures grant no authority."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

import real_public_q24_evidence_bridge as bridge


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def synthetic_q24():
    source = {
        "source_kind": "SYNTHETIC_ONLY", "real_encoder_executed": False,
        "train_sha256": h("frozen-train"), "trace_sha256": h("frozen-trace"),
    }
    plan = {"predeclared_byte_caps": [8192, 32768],
            "genuine_learned_weights_measured": False}
    blobs = {
        "hepta-near-matched-fixture.json": json.dumps(source).encode(),
        "hepta-physical-byte-plan.json": json.dumps(plan).encode(),
    }
    for idx, (train_path, native_path, caps) in enumerate((
        ("hepta-near-matched-trained/training-receipt.json",
         "hepta-near-matched-audit.json", (2048, 8192)),
        ("hepta-byte-matched-trained/training-receipt.json",
         "hepta-byte-matched-native-audit.json", (8192, 32768)),
    )):
        cells = [
            {"cap": cap, "arm": arm,
             "weight_sha256": h(f"distinct-{idx}-{cap}-{arm}")}
            for cap in caps for arm in ("v2", "v3", "ssm", "min_gru")
        ]
        original = {"physical_model_file_count": 8, "cells": cells,
                    "actual_train_input_sha256": source["train_sha256"],
                    "production_qualification": False}
        train_raw = json.dumps(original, sort_keys=True).encode()
        native = {
            "training_receipt_sha256": bridge.sha(train_raw),
            "frozen_input_trace_sha256": source["trace_sha256"],
            "physically_loaded_models": 8, "actual_native_os_processes": 16,
            "independent_integer_adapter_head_parity": True,
            "independent_temporal_model_parity": False,
            "production_qualification": False,
            "rows": [
                {"cap": row["cap"], "arm": row["arm"],
                 "physical_weight_sha256": row["weight_sha256"],
                 "verified_native_adapter_head_event_count": 8}
                for row in cells
            ],
        }
        blobs[train_path] = train_raw
        blobs[native_path] = json.dumps(native).encode()
    return blobs


class BridgeSecurityTests(unittest.TestCase):
    def test_synthetic_q24_receipts_not_real_dataset_efficacy(self):
        report = bridge.q24_census(synthetic_q24())
        self.assertEqual(report["unique_model_sha256_count"], 16)
        self.assertEqual(sum(a["native_process_count"] for a in report["studies"]), 32)
        self.assertFalse(report["actual_future_task_quality_verified"])

    def test_forbidden_real_encoder_claim_rejected(self):
        blobs = synthetic_q24()
        source = bridge.document(blobs["hepta-near-matched-fixture.json"])
        source["real_encoder_executed"] = True
        blobs["hepta-near-matched-fixture.json"] = json.dumps(source).encode()
        with self.assertRaisesRegex(bridge.Rejected, "pretrained Encoder"):
            bridge.q24_census(blobs)

    def test_cross_trial_model_sha_substitution_rejected(self):
        blobs = synthetic_q24()
        bad = bridge.document(blobs["hepta-byte-matched-native-audit.json"])
        bad["rows"][0]["physical_weight_sha256"] = h("spoofed-result")
        blobs["hepta-byte-matched-native-audit.json"] = json.dumps(bad).encode()
        with self.assertRaisesRegex(bridge.Rejected, "trained weights"):
            bridge.q24_census(blobs)

    def test_training_receipt_bytes_changed_rejected(self):
        blobs = synthetic_q24()
        original = bridge.document(blobs["hepta-near-matched-trained/training-receipt.json"])
        original["purpose"] = "forged"
        blobs["hepta-near-matched-trained/training-receipt.json"] = json.dumps(original).encode()
        with self.assertRaisesRegex(bridge.Rejected, "SHA drift"):
            bridge.q24_census(blobs)

    def test_duplicate_or_reused_weight_sha_rejected(self):
        blobs = synthetic_q24()
        original = bridge.document(blobs["hepta-near-matched-trained/training-receipt.json"])
        original["cells"][1]["weight_sha256"] = original["cells"][0]["weight_sha256"]
        blobs["hepta-near-matched-trained/training-receipt.json"] = json.dumps(original).encode()
        with self.assertRaises(bridge.Rejected):
            bridge.q24_census(blobs)

    def test_missing_native_process_receipt_rejected(self):
        blobs = synthetic_q24()
        native = bridge.document(blobs["hepta-byte-matched-native-audit.json"])
        native["actual_native_os_processes"] = 8
        blobs["hepta-byte-matched-native-audit.json"] = json.dumps(native).encode()
        with self.assertRaises(bridge.Rejected):
            bridge.q24_census(blobs)

    def test_duplicate_json_keys_nan_and_overflow_refused(self):
        with self.assertRaisesRegex(bridge.Rejected, "duplicate"):
            bridge.document(b'{"true":1,"true":2}')
        with self.assertRaisesRegex(bridge.Rejected, "nonfinite"):
            bridge.document(b'{"x":NaN}')
        with self.assertRaisesRegex(bridge.Rejected, "nonfinite"):
            bridge.document(b'{"x":1e999}')

    def test_untrusted_zip_has_no_original_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "fabricated.zip"
            with zipfile.ZipFile(source, "w") as out:
                out.writestr("public-cell-learning/scores.json", "{}")
            with self.assertRaisesRegex(bridge.Rejected, "SHA256"):
                bridge.immutable_zip(source, bridge.PUBLIC_ZIP_SHA,
                                     bridge.PUBLIC_NAMES, 6_000_000)
            alias = root / "alias.zip"
            alias.symlink_to(source)
            with self.assertRaisesRegex(bridge.Rejected, "symlink"):
                bridge.immutable_zip(alias, bridge.PUBLIC_ZIP_SHA,
                                     bridge.PUBLIC_NAMES, 6_000_000)

    def test_exact_immutable_real_artifact_opt_in(self):
        public, q24 = (os.environ.get("HEPTA_PUBLIC_BANK_ARCHIVE"),
                       os.environ.get("HEPTA_BYTE_Q24_ARCHIVE"))
        if not public and not q24:
            return
        self.assertTrue(public and q24, "both independent pinned ZIPs required")
        result = bridge.audit(Path(public), Path(q24))
        self.assertEqual(result["decision"], "NO_CROSS_STUDY_MODEL_SELECTION")
        self.assertEqual(result["public_encoder_learning"]["heldout_count"], 32)
        self.assertEqual(result["synthetic_q24_mechanism"]["unique_model_sha256_count"], 16)
        self.assertFalse(result["real_public_encoder_features_q24_32d_archived"])
        self.assertFalse(result["production_qualification"])


if __name__ == "__main__":
    unittest.main()

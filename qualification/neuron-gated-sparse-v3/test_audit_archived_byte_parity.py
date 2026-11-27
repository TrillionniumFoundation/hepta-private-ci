"""Offline negative controls for six-member training/native evidence archival linkage.

These synthetic ZIPs are deliberately not valid hosted evidence or trained weights.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import audit_archived_byte_parity as audit


def digest(msg: str) -> str:
    return hashlib.sha256(msg.encode()).hexdigest()


def make_zip(path: Path, *, mutation=None):
    trace, train_input = digest("synthetic Q24 trace"), digest("synthetic train")
    fixture = {"source_kind": "SYNTHETIC_ONLY", "authority": "DENY_ALL",
               "real_encoder_executed": False, "trace_sha256": trace,
               "train_sha256": train_input}
    plan = {"schema": "hepta.neuron.byte-budget-physical-shape-preflight.v1",
            "authority": "DENY_ALL", "predeclared_byte_caps": [8192,32768],
            "genuine_learned_weights_measured": False}
    blobs = {"hepta-near-matched-fixture.json": fixture,
             "hepta-physical-byte-plan.json": plan}
    for index, (trained_path, native_path, caps, kind, train_schema,
                native_schema) in enumerate(audit.STUDIES):
        trained_rows = []
        native_rows = []
        for cap in caps:
            for arm in audit.ARMS:
                sha = digest(f"candidate:{index}:{cap}:{arm}")
                row = {
                    "cap": cap, "arm": arm, "weight_sha256": sha,
                    "optimizer_steps": 8, "physical_bytes": cap - 64
                }
                if kind == "SERIALIZED_SAFETENSORS_BYTES":
                    row["budget_kind"] = kind
                    row["physical_byte_ceiling"] = cap
                trained_rows.append(row)
                native_rows.append({
                    "arm":arm, "cap":cap, "physical_weight_sha256":sha,
                    "verified_native_adapter_head_event_count":8,
                    "independent_integer_adapter_head_parity":True,
                    "independent_temporal_kernel_parity":False,
                    "ndu_eligible":False, "production_qualification":False,
                })
        trained = {
            "schema":train_schema,"source_class":"SYNTHETIC_FIXTURE_ONLY",
            "authority":"DENY_ALL","decision":"NO_MODEL_PROMOTION",
            "physical_model_file_count":8,"cells":trained_rows,
            "candidate_training_step_count":8,
            "actual_train_input_sha256":train_input,
            "production_qualification":False,"ndu_eligible":False,
            "future_utility_verified":False,
        }
        raw = json.dumps(trained,sort_keys=True).encode()
        native = {
            "schema":native_schema,"study_kind":kind,
            "authority":"DENY_ALL","decision":"NO_MODEL_PROMOTION",
            "training_receipt_sha256":hashlib.sha256(raw).hexdigest(),
            "frozen_input_trace_sha256":trace,
            "physically_loaded_models":8, "actual_native_os_processes":16,
            "independent_integer_adapter_head_parity":True,
            "original_selected_v1_a0_verified":False,
            "independent_temporal_model_parity":False,
            "production_qualification":False,"ndu_eligible":False,
            "future_utility_verified":False,
            "rows":native_rows,
        }
        blobs[trained_path] = trained
        blobs[native_path] = native
    if mutation:
        mutation(blobs)
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        for key, value in blobs.items():
            raw = json.dumps(value,sort_keys=True).encode()
            z.writestr(key,raw)


class ArchivedQ24BindingTests(unittest.TestCase):
    def verify(self, change=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"fixture.zip"
            make_zip(path,mutation=change)
            return audit.audit_zip(path)

    def test_complete_synthetic_contract_never_grants_production(self):
        output = self.verify()
        self.assertEqual(output["independent_weight_sha_count"],16)
        self.assertEqual(output["total_native_process_count"],32)
        self.assertEqual(output["decision"],"NO_MODEL_PROMOTION")
        self.assertFalse(output["production_qualification"])
        self.assertFalse(output["raw_weight_bytes_reopened"])

    def test_cross_study_wrong_trace_rejected(self):
        def change(blobs):
            blobs["hepta-byte-matched-native-audit.json"]["frozen_input_trace_sha256"]=digest("other")
        with self.assertRaisesRegex(audit.Refused,"SHA binding"):
            self.verify(change)

    def test_native_weight_sha_replacement_rejected(self):
        def change(blobs):
            blobs["hepta-near-matched-audit.json"]["rows"][0]["physical_weight_sha256"]=digest("other")
        with self.assertRaisesRegex(audit.Refused,"native hash"):
            self.verify(change)

    def test_duplicate_model_slot_rejected(self):
        def change(blobs):
            cells=blobs["hepta-byte-matched-trained/training-receipt.json"]["cells"]
            cells[1]["arm"]=cells[0]["arm"]
        with self.assertRaises(audit.Refused):
            self.verify(change)

    def test_forged_future_or_ndu_rejected(self):
        def change(blobs):
            blobs["hepta-near-matched-audit.json"]["future_utility_verified"]=True
        with self.assertRaisesRegex(audit.Refused,"forged"):
            self.verify(change)

    def test_wrong_physical_byte_ceiling_rejected(self):
        def change(blobs):
            blobs["hepta-byte-matched-trained/training-receipt.json"]["cells"][0]["physical_bytes"]=8193
        with self.assertRaises(audit.Refused):
            self.verify(change)

    def test_missing_original_zip_member_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"truncated.zip"
            with zipfile.ZipFile(path,"w") as z:z.writestr("hepta-near-matched-fixture.json","{}")
            with self.assertRaises(audit.Refused):
                audit.audit_zip(path)

    def test_missing_or_duplicate_object_key_rejected(self):
        with self.assertRaisesRegex(audit.Refused,"duplicate JSON field"):
            audit.read_json(b'{"claim":1,"claim":2}')
        with self.assertRaisesRegex(audit.Refused,"nonfinite"):
            audit.read_json(b'{"bad":NaN}')


if __name__ == "__main__":
    unittest.main()

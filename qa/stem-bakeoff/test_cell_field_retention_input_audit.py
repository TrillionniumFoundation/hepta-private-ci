"""Independent auditor rejects unauthenticated prior-source recovery."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cell_field_retention_input_audit as audit


class InputRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        previous, current = root / "previous", root / "data"
        previous.mkdir()
        current.mkdir()
        prior = [{"index": i, "raw_source_id": str(i), "component_id": f"prior-{i}"} for i in range(512)]
        payload = audit.canonical({"rows": prior}) + b"\n"
        source = {"sha256": audit.sha(payload), "bytes": len(payload)}
        (previous / "sources.json").write_bytes(payload)
        receipt = {"sha256": "a" * 64, "bytes": 4055}
        sealed = audit.canonical({"files": {"inputs/sources.json": source,
            "inputs/data_receipt.json": receipt}, "final_labels_opened": False}) + b"\n"
        (previous / "pre_evaluation_seal.json").write_bytes(sealed)
        provenance = {"mode": "published_pre_evaluation_seal", "seal_sha256": audit.sha(sealed),
            "original_receipt_present": False, "sources": source, "original_receipt": receipt}
        protocol = {"previous_sources_sha256": source["sha256"],
            "previous_data_receipt_sha256": receipt["sha256"], "source_split_salt": "fixed-test-salt",
            "source_counts": {"old_train": 4}, "source_archive_sha256": "b" * 64}
        plan_bytes = audit.canonical(protocol)
        plan = root / "protocol.json"
        plan.write_bytes(plan_bytes)
        objects = {
            "sources.json": {"rows": [{"index": i, "raw_source_id": str(i + 1000),
                                       "component_id": f"new-{i}"} for i in range(4)]},
            "predictors.json": {"rows": [{"source_id": f"source-{i}", "source_version": "v1",
                                          "text": f"headline {i}"} for i in range(4)]},
            "train_labels.json": {"roles": {r: {} for r in
                                            ("old_train", "old_probe", "current_train", "current_probe")}},
        }
        files = {}
        for name, obj in objects.items():
            raw = audit.canonical(obj)
            (current / name).write_bytes(raw)
            files[name] = {"sha256": audit.sha(raw), "bytes": len(raw)}
        prepared = {"protocol_sha256": audit.sha(plan_bytes),
            "previous_sources_sha256": source["sha256"], "previous_data_receipt_sha256": receipt["sha256"],
            "previous_source_provenance": provenance, "salt": "fixed-test-salt", "files": files}
        (current / "data_receipt.json").write_bytes(audit.canonical(prepared))
        pins = {"PINNED_PREVIOUS_SOURCES": source, "PINNED_PREVIOUS_RECEIPT": receipt,
                "PINNED_PREVIOUS_SEAL": audit.sha(sealed)}
        return previous, current, plan, pins

    def test_exact_recovery_passes_identity_phase_without_opening_final_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            previous, current, plan, pins = self.fixture(Path(directory))
            with patch.multiple(audit, **pins), patch.object(
                    audit, "_read_archive", side_effect=RuntimeError("source phase reached")):
                with self.assertRaisesRegex(RuntimeError, "source phase reached"):
                    audit.audit_inputs(current, "unused.zip", previous, plan)
            self.assertFalse((previous / "data_receipt.json").exists())
            self.assertFalse((current / "final_labels.json").exists())

    def test_modified_seal_and_present_bad_receipt_fail_before_source_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            previous, current, plan, pins = self.fixture(Path(directory))
            seal_path = previous / "pre_evaluation_seal.json"
            sealed = seal_path.read_bytes()
            with patch.multiple(audit, **pins), patch.object(audit, "_read_archive") as source:
                seal_path.write_bytes(sealed + b"\n")
                with self.assertRaisesRegex(ValueError, "source seal differs"):
                    audit.audit_inputs(current, "unused.zip", previous, plan)
                seal_path.write_bytes(sealed)
                (previous / "data_receipt.json").write_bytes(b"{}")
                with self.assertRaisesRegex(ValueError, "receipt differs"):
                    audit.audit_inputs(current, "unused.zip", previous, plan)
                source.assert_not_called()

    def test_audit_rejects_provenance_claim_not_matching_the_authenticated_route(self):
        with tempfile.TemporaryDirectory() as directory:
            previous, current, plan, pins = self.fixture(Path(directory))
            receipt_path = current / "data_receipt.json"
            prepared = json.loads(receipt_path.read_bytes())
            prepared["previous_source_provenance"]["mode"] = "original_receipt"
            receipt_path.write_bytes(audit.canonical(prepared))
            with patch.multiple(audit, **pins), patch.object(audit, "_read_archive") as source:
                with self.assertRaisesRegex(ValueError, "prior-exposure identity differs"):
                    audit.audit_inputs(current, "unused.zip", previous, plan)
                source.assert_not_called()


if __name__ == "__main__":
    unittest.main()

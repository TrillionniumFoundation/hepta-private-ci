"""Independent input-audit rejection and withheld-label access tests."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cell_field_action_data as preparation
import cell_field_action_input_audit as audit


class ActionInputAuditTests(unittest.TestCase):
    def fixture(self, root):
        from test_cell_field_action_data import ActionDataTests

        helper = ActionDataTests()
        helper.setUp()
        previous, provenance, pins = {}, {}, {}
        for name, raw in zip(("v1", "v2"), helper.rows[:2]):
            directory = root / name
            directory.mkdir()
            source = {**helper.prior(raw["source_id"], [raw["source_id"]]),
                      "index": 0, "source_id": "uci-news:" + raw["source_id"]}
            previous[name] = [source]
            payload = preparation.canonical({"rows": [source]}) + b"\n"
            source_identity = {"bytes": len(payload), "sha256": preparation.sha(payload)}
            receipt = preparation.canonical({"files": {"sources.json": source_identity},
                                              "source_archive_sha256": preparation.ARCHIVE_SHA256}) + b"\n"
            receipt_identity = {"bytes": len(receipt), "sha256": preparation.sha(receipt)}
            (directory / "sources.json").write_bytes(payload)
            (directory / "data_receipt.json").write_bytes(receipt)
            pins[name] = {"count": 1, "sources": source_identity, "receipt": receipt_identity}
            provenance[name] = {"mode": "original_receipt", "original_receipt_present": True,
                                "sources": source_identity, "original_receipt": receipt_identity}
            if name == "v1":
                provenance[name]["seal_sha256"] = None
        prior_ids = {name: {"sources_sha256": value["sources"]["sha256"],
                            "data_receipt_sha256": value["receipt"]["sha256"]} for name, value in pins.items()}
        plan = helper.protocol()
        plan["prior_experiments"] = prior_ids
        protocol, archive = root / "protocol.json", root / "source.zip"
        protocol.write_bytes(preparation.canonical(plan))
        archive.write_bytes(b"source fixture")
        legacy = {"known": [helper.rows[-1]]}
        with patch.object(preparation, "PRIOR_PINS", prior_ids), \
                patch.object(preparation, "previous_sources", return_value=(previous, provenance)), \
                patch.object(preparation, "_read_archive", return_value=helper.rows), \
                patch.object(preparation, "select_rows", return_value=legacy):
            preparation.prepare(archive, root / "v1", root / "v2", root / "data", protocol)
        return helper.rows, legacy, pins

    def run_audit(self, root, fixture):
        rows, legacy, pins = fixture
        original = Path.read_bytes

        def guarded(path):
            if path.name in ("validation_labels.json", "final_labels.json"):
                raise AssertionError("auditor opened withheld label payload")
            return original(path)

        with patch.object(audit, "PINNED_PRIORS", pins), \
                patch.object(audit, "_read_archive", return_value=rows), \
                patch.object(audit, "select_rows", return_value=legacy), \
                patch.object(Path, "read_bytes", guarded), \
                patch.object(preparation, "build_cohorts", side_effect=AssertionError("preparer imported")):
            return audit.audit_inputs(root / "data", root / "source.zip", root / "v1", root / "v2", root / "protocol.json")

    def test_independent_graph_selection_and_all_label_hashes_without_withheld_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_audit(root, self.fixture(root))
            self.assertEqual(result["verified_selected_components"], 36)
            self.assertEqual(result["verified_previous_components"], {"v1": 1, "v2": 1})
            self.assertFalse(result["validation_labels_file_opened"])
            self.assertFalse(result["final_labels_file_opened"])
            self.assertTrue(result["withheld_payload_hashes_reconstructed_from_raw_source_labels"])
            self.assertTrue(result["withheld_payload_bytes_verification_deferred"])

    def test_rejects_changed_withheld_label_identity_without_opening_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root)
            path = root / "data/data_receipt.json"
            saved = json.loads(path.read_bytes())
            saved["files"]["validation_labels.json"]["sha256"] = "0" * 64
            path.write_bytes(preparation.canonical(saved) + b"\n")
            with self.assertRaisesRegex(ValueError, "validation label payload identity differs"):
                self.run_audit(root, fixture)

    def test_rejects_predictor_label_leak_even_with_updated_receipt_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root)
            path = root / "data/predictors.json"
            saved = json.loads(path.read_bytes())
            saved["rows"][0]["label"] = 0
            payload = preparation.canonical(saved) + b"\n"
            path.write_bytes(payload)
            receipt_path = root / "data/data_receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["files"]["predictors.json"] = {"bytes": len(payload), "sha256": preparation.sha(payload)}
            receipt_path.write_bytes(preparation.canonical(receipt) + b"\n")
            with self.assertRaisesRegex(ValueError, "predictor identity differs"):
                self.run_audit(root, fixture)

    def test_seal_recovery_is_authenticated_but_invalid_present_receipt_cannot_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows, legacy, pins = self.fixture(root)
            seal = {"files": {"inputs/sources.json": pins["v1"]["sources"],
                              "inputs/data_receipt.json": pins["v1"]["receipt"]}, "final_labels_opened": False}
            payload = preparation.canonical(seal) + b"\n"
            pins["v1"]["seal_sha256"] = preparation.sha(payload)
            (root / "v1/pre_evaluation_seal.json").write_bytes(payload)
            (root / "v1/data_receipt.json").unlink()
            receipt_path = root / "data/data_receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["previous_source_provenance"]["v1"].update(mode="published_pre_evaluation_seal",
                seal_sha256=pins["v1"]["seal_sha256"], original_receipt_present=False)
            receipt_path.write_bytes(preparation.canonical(receipt) + b"\n")
            result = self.run_audit(root, (rows, legacy, pins))
            self.assertEqual(result["previous_source_provenance"]["v1"]["mode"], "published_pre_evaluation_seal")
            (root / "v1/data_receipt.json").write_bytes(b"{}")
            with self.assertRaisesRegex(ValueError, "original receipt identity differs"):
                self.run_audit(root, (rows, legacy, pins))


if __name__ == "__main__":
    unittest.main()

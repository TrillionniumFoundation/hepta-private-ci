"""Compatibility verifier regressions use synthetic metadata only."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from verify_platform_types_compatibility import CompatibilityError, verify


def fixture(root: Path):
    evidence = root / "evidence.txt"
    evidence.write_text("golden\n", encoding="utf-8")
    catalog = {
        "schema": "hepta.platform-types.protocol-catalog.v2",
        "schemaVersion": 2,
        "normativeSource": "codex-rs/hepta-types/src/protocol_catalog_v2.rs",
        "protocolCount": 1,
        "protocols": [
            {
                "id": "ExampleV1",
                "version": 1,
                "semanticTypeId": "platform.types:example-v1",
                "codecOwner": "platform.wire",
                "compatibility": "v1_frozen_semantics",
            }
        ],
    }
    consumer = {
        "schema": "hepta.platform-types.consumer-qualification.v2",
        "module": "platform.types",
        "consumers": [{"id": "example.consumer"}],
    }
    evidenced = {"status": "evidenced", "consumers": ["example.consumer"]}
    matrix = {
        "schema": "hepta.platform-types.compatibility-matrix.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "normativeCatalog": "codex-rs/hepta-types/src/protocol_catalog_v2.rs",
        "consumerMatrix": "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json",
        "mandatoryConsumers": ["example.consumer"],
        "optionalConsumers": [],
        "requiredAssurances": [
            "decoder",
            "validatedBoundary",
            "ownerRevalidation",
            "staleStateRejection",
            "mixedVersionRollback",
        ],
        "protocols": [
            {
                "id": "ExampleV1",
                "wireVersion": 1,
                "semanticVersion": 1,
                "semanticTypeId": "platform.types:example-v1",
                "codecOwner": "platform.wire",
                "compatibility": "v1_frozen_semantics",
                "migration": "A successor uses a new version and never rewrites V1 bytes.",
                "rollbackStrategy": "Retain the exact V1 bytes and reject incompatible replacements.",
                "consumers": ["example.consumer"],
                "goldenVectors": ["evidence.txt"],
                "assurances": {
                    "decoder": copy.deepcopy(evidenced),
                    "validatedBoundary": copy.deepcopy(evidenced),
                    "ownerRevalidation": copy.deepcopy(evidenced),
                    "staleStateRejection": copy.deepcopy(evidenced),
                    "mixedVersionRollback": copy.deepcopy(evidenced),
                },
            }
        ],
    }
    return catalog, matrix, consumer


class CompatibilityMatrixTests(unittest.TestCase):
    def test_valid_closed_matrix_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, matrix, consumer = fixture(root)
            report = verify(catalog, matrix, consumer, root)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["protocolCount"], 1)
            self.assertEqual(report["mandatoryConsumerCount"], 1)

    def test_catalog_identity_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, matrix, consumer = fixture(root)
            matrix["protocols"][0]["semanticTypeId"] = "wrong"
            with self.assertRaisesRegex(CompatibilityError, "semanticTypeId drift"):
                verify(catalog, matrix, consumer, root)

    def test_mandatory_consumer_drift_and_uncovered_consumer_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, matrix, consumer = fixture(root)
            consumer["consumers"].append({"id": "second.consumer"})
            with self.assertRaisesRegex(CompatibilityError, "mandatory consumer set"):
                verify(catalog, matrix, consumer, root)
            matrix["mandatoryConsumers"].append("second.consumer")
            with self.assertRaisesRegex(CompatibilityError, "not assigned"):
                verify(catalog, matrix, consumer, root)

    def test_missing_assurance_or_shallow_exception_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, matrix, consumer = fixture(root)
            del matrix["protocols"][0]["assurances"]["decoder"]
            with self.assertRaisesRegex(CompatibilityError, "dimensions"):
                verify(catalog, matrix, consumer, root)
            catalog, matrix, consumer = fixture(root)
            matrix["protocols"][0]["assurances"]["decoder"] = {
                "status": "not_applicable",
                "reason": "no",
            }
            with self.assertRaisesRegex(CompatibilityError, "reason is incomplete"):
                verify(catalog, matrix, consumer, root)

    def test_missing_or_escaping_golden_evidence_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, matrix, consumer = fixture(root)
            matrix["protocols"][0]["goldenVectors"] = ["missing.txt"]
            with self.assertRaisesRegex(CompatibilityError, "evidence missing"):
                verify(catalog, matrix, consumer, root)
            matrix["protocols"][0]["goldenVectors"] = ["../escape.txt"]
            with self.assertRaisesRegex(CompatibilityError, "escapes repository"):
                verify(catalog, matrix, consumer, root)


if __name__ == "__main__":
    unittest.main()

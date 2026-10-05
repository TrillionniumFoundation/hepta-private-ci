#!/usr/bin/env python3
"""Unit tests for platform.types generated-artifact convergence gates."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPAT = load_module(
    "platform_types_compatibility_gate",
    ROOT / "scripts" / "check_platform_types_compatibility_matrix.py",
)
TRUTH = load_module(
    "platform_types_truth_gate",
    ROOT / "scripts" / "platform_types_truth_matrix.py",
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class CompatibilityMatrixTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        source = root / "codex-rs/hepta-types/src/protocol_catalog_v2.rs"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "pub struct DemoProtocolV1;\n",
            encoding="utf-8",
        )
        evidence = root / "fixtures/consumer.txt"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("required-marker\n", encoding="utf-8")
        vector = root / "fixtures/vector.json"
        vector.write_text("{}\n", encoding="utf-8")

        consumer = {
            "schema": "hepta.platform-types.consumer-qualification.v2",
            "schemaVersion": 2,
            "module": "platform.types",
            "consumers": [
                {
                    "id": "consumer.one",
                    "kind": "test",
                    "path": "fixtures/consumer.txt",
                    "mustContain": ["required-marker"],
                }
            ],
        }
        write_json(
            root / "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json",
            consumer,
        )
        assurances = {
            name: {
                "status": "not_applicable",
                "reason": f"{name} is outside this fixture",
            }
            for name in COMPAT.EXPECTED_ASSURANCES
        }
        assurances["decoder"] = {
            "status": "evidenced",
            "consumers": ["consumer.one"],
        }
        matrix = {
            "schema": "hepta.platform-types.compatibility-matrix.v1",
            "schemaVersion": 1,
            "module": "platform.types",
            "normativeCatalog": "codex-rs/hepta-types/src/protocol_catalog_v2.rs",
            "consumerMatrix": "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json",
            "claimBoundary": "compatibility evidence; not activation authority",
            "mandatoryConsumers": ["consumer.one"],
            "optionalConsumers": [],
            "requiredAssurances": list(COMPAT.EXPECTED_ASSURANCES),
            "protocols": [
                {
                    "id": "DemoProtocolV1",
                    "wireVersion": 1,
                    "semanticVersion": 1,
                    "semanticTypeId": "demo:v1",
                    "codecOwner": "demo.owner",
                    "compatibility": "frozen",
                    "migration": "new version required",
                    "rollbackStrategy": "retain v1",
                    "consumers": ["consumer.one"],
                    "goldenVectors": ["fixtures/vector.json"],
                    "assurances": assurances,
                }
            ],
        }
        write_json(
            root / "docs/modules/platform.types/COMPATIBILITY_MATRIX_V1.json",
            matrix,
        )
        return temporary, root

    def test_valid_matrix_binds_consumers_and_source(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        value = COMPAT.validate(root)
        self.assertEqual(value["protocols"][0]["id"], "DemoProtocolV1")

    def test_missing_assurance_fails_closed(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        path = root / "docs/modules/platform.types/COMPATIBILITY_MATRIX_V1.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        del value["protocols"][0]["assurances"]["ownerRevalidation"]
        write_json(path, value)
        with self.assertRaises(COMPAT.CompatibilityMatrixError):
            COMPAT.validate(root)


class TruthMatrixTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        doc = root / "docs/modules/platform.types"
        doc.mkdir(parents=True)
        for name in (
            "SPEC_V2.md",
            "IMPLEMENTATION_STATUS.md",
            "MIGRATION_V1_TO_V2.md",
        ):
            (doc / name).write_text(f"{name}\n", encoding="utf-8")
        write_json(
            doc / "PUBLIC_API_INVENTORY_V1.json",
            {
                "schema": "hepta.platform-types.public-api-inventory.v1",
                "module": "platform.types",
                "exportCount": 3,
                "operationCount": 2,
                "sourceModuleCount": 1,
            },
        )
        write_json(
            doc / "COMPATIBILITY_MATRIX_V1.json",
            {
                "schema": "hepta.platform-types.compatibility-matrix.v1",
                "module": "platform.types",
                "protocols": [{"id": "DemoV1"}],
                "mandatoryConsumers": ["consumer.one"],
            },
        )
        write_json(
            doc / "IMPLEMENTATION_MAP.json",
            {
                "schema": "hepta.module-implementation-map.v3",
                "module": "platform.types",
                "publicApiInventory": {
                    "exportCount": 3,
                    "operationCount": 2,
                },
            },
        )
        write_json(
            doc / "implementation_status_source.json",
            {
                "schema": "platform.types/implementation-status-source/v1",
                "spec_version": "platform.types/v2",
                "owner_migration": "in_progress",
                "qualification": "unqualified",
                "approval_sha": None,
                "activation": False,
            },
        )
        write_json(
            doc / "archive/MANIFEST.json",
            {
                "schema": "hepta.platform-types.documentation-archive.v1",
                "module": "platform.types",
                "records": [{"path": "historical.md"}],
            },
        )
        write_json(
            root / "docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json",
            {},
        )
        return temporary, root

    def test_truth_projection_is_deterministic(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        expected = TRUTH.expected_truth(root)
        self.assertEqual(expected["sourceFacts"]["publicApiExportCount"], 3)
        TRUTH.write_truth(root)
        self.assertEqual(TRUTH.verify_truth(root), expected)

    def test_truth_projection_rejects_self_asserted_activation(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        source = root / "docs/modules/platform.types/implementation_status_source.json"
        value = json.loads(source.read_text(encoding="utf-8"))
        value["activation"] = True
        write_json(source, value)
        with self.assertRaises(TRUTH.TruthMatrixError):
            TRUTH.expected_truth(root)


if __name__ == "__main__":
    unittest.main()

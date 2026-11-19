"""Pure-byte catalog publication regressions; no trainer or model is imported.

The selected production function definitions retain their exact bodies and
annotations. Only their stdlib dependencies are loaded, so these tests exercise
catalog validation without constructing a checkpoint owner or executing tensors.
"""

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_definitions(path, names, namespace):
    """Compile exact selected definitions without importing model dependencies."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    selected = []
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if targets & names:
                if len(targets) != 1 or not targets <= names:
                    raise ValueError("unexpected source assignment boundary")
                selected.append(node)
                found.update(targets)
    if found != set(names):
        raise ValueError("selected production definition is missing")
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec", dont_inherit=True), namespace)
    return types.SimpleNamespace(**namespace)


SERVICE = load_module(
    "_catalog_snapshot_service_types",
    SCRIPTS / "memory_cell_service" / "service_types.py",
)
DURABILITY = load_module(
    "_catalog_snapshot_durability",
    SCRIPTS / "memory_cell_service" / "durability.py",
)
CATALOG = load_module(
    "_catalog_snapshot_metadata",
    SCRIPTS / "memory_cell_catalog" / "metadata_catalog.py",
)
TENSOR_BYTES = load_definitions(
    SCRIPTS / "memory_cell" / "tensor_contract.py",
    {"bounded_read", "strict_json"},
    {"hashlib": hashlib, "json": json, "os": os, "stat": stat, "Path": Path},
)
BACKEND = load_definitions(
    SCRIPTS / "memory_cell_service" / "training_backend.py",
    {"POLICY", "CANDIDATE_FIELDS", "seal_candidate", "verify_candidate"},
    {
        "hashlib": hashlib,
        "os": os,
        "Path": Path,
        "MetadataCatalog": CATALOG.MetadataCatalog,
        "SCHEMA": CATALOG.SCHEMA,
        "canonical": SERVICE.canonical,
        "digest": SERVICE.digest,
        "verify_snapshot": SERVICE.verify_snapshot,
        "bounded_read": TENSOR_BYTES.bounded_read,
        "strict_json": TENSOR_BYTES.strict_json,
        "sync_directory": DURABILITY.sync_directory,
    },
)


class CandidateCatalogSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.artifacts = Path(temporary.name).resolve() / "artifacts"
        self.directory = self.artifacts / "attempt" / "checkpoint"
        self.directory.mkdir(parents=True)
        facts = [
            {
                "scope": "fixture",
                "entity": "Alice",
                "relation": "color",
                "value": "red",
                "source_digest": "1" * 64,
            }
        ]
        material = {
            "schema": "hepta.memory-service.source-snapshot.v1",
            "scope": "fixture",
            "cell_id": "memory",
            "role": "semantic",
            "epoch": 1,
            "sources": [],
            "facts": facts,
            "conflicts": [],
            "roots": ["1" * 64],
            "revoked": [],
        }
        self.snapshot = material | {"digest": SERVICE.digest(material)}
        self.training = {
            "initialization": "frozen_base",
            "learned_parent_manifest_sha256": None,
            "inherited_roots": [],
            "source_facts_sha256": SERVICE.digest(facts),
            "roots": ["1" * 64],
            "source_digests": ["1" * 64],
        }
        # This is only the metadata consumed by verify_candidate. No tensor
        # checkpoint is created or admitted by a ParametricOwner.
        manifest = {
            "scope": "fixture",
            "roots": ["1" * 64],
            "training": self.training,
        }
        raw = SERVICE.canonical(manifest)
        (self.directory / "lineage.json").write_bytes(raw)
        self.candidate = BACKEND.seal_candidate(
            self.snapshot, self.directory, hashlib.sha256(raw).hexdigest()
        )
        self.path = Path(self.candidate["catalog_path"])
        self.expected_bytes = self.path.read_bytes()
        self.expected_document = json.loads(self.expected_bytes)

    def verify(self):
        return BACKEND.verify_candidate(self.candidate, self.snapshot, self.artifacts)

    def other_source_document(self):
        return self.expected_document | {
            "entries": [
                {
                    "entity": "Bob",
                    "relation": "color",
                    "source_digest": "1" * 64,
                }
            ]
        }

    def pin_document(self, document):
        raw = SERVICE.canonical(document)
        self.path.write_bytes(raw)
        self.candidate["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
        return raw

    def test_unchanged_bound_document_is_accepted(self):
        self.assertEqual(self.verify(), self.training)
        self.assertEqual(self.path.read_bytes(), self.expected_bytes)

    def test_pinned_other_source_is_rejected(self):
        self.pin_document(self.other_source_document())
        with self.assertRaisesRegex(ValueError, "differs from the sealed source"):
            self.verify()

    def test_unpinned_swap_cannot_supply_source_equality(self):
        pinned_bytes = self.pin_document(self.other_source_document())
        verified = []
        original_read = CATALOG.MetadataCatalog._read

        def swap_after_validation(catalog):
            document = original_read(catalog)
            verified.append(hashlib.sha256(SERVICE.canonical(document)).hexdigest())
            if len(verified) == 1:
                self.path.write_bytes(self.expected_bytes)
            return document

        error = None
        with patch.object(CATALOG.MetadataCatalog, "_read", swap_after_validation):
            try:
                self.verify()
            except ValueError as caught:
                error = caught
        sys.stderr.write(
            json.dumps(
                {
                    "event": "catalog_snapshot_boundary",
                    "accepted": error is None,
                    "error": str(error) if error is not None else None,
                    "independent_pin": hashlib.sha256(pinned_bytes).hexdigest(),
                    "verified_documents": verified,
                    "replacement_sha256": hashlib.sha256(
                        self.path.read_bytes()
                    ).hexdigest(),
                },
                sort_keys=True,
            )
            + "\n"
        )
        self.assertIsNotNone(
            error,
            "publication metadata mixed a pinned catalog with an unpinned replacement",
        )
        self.assertIn("differs from the sealed source", str(error))
        self.assertEqual(verified, [self.candidate["catalog_sha256"]])
        self.assertNotEqual(
            hashlib.sha256(self.path.read_bytes()).hexdigest(),
            self.candidate["catalog_sha256"],
        )

    def test_constructor_keeps_independent_pin_and_schema_guards(self):
        with self.subTest(boundary="pin"):
            self.candidate["catalog_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "retained SHA256"):
                self.verify()
        with self.subTest(boundary="schema"):
            self.pin_document(self.expected_document | {"production_accepted": True})
            with self.assertRaisesRegex(ValueError, "metadata-only catalog"):
                self.verify()

    def test_later_read_rechecks_changed_path_before_owner_or_callback(self):
        catalog = CATALOG.MetadataCatalog(self.path, self.candidate["catalog_sha256"])
        self.path.write_bytes(SERVICE.canonical(self.other_source_document()))
        owner, callback = Mock(), Mock()
        with self.assertRaisesRegex(ValueError, "retained SHA256"):
            catalog.read(
                owner,
                entity="Alice",
                relation="color",
                provider=Mock(),
                callback=callback,
            )
        owner.current.assert_not_called()
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()

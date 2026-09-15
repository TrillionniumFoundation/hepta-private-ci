"""Derived registries remain views, not independent capability evidence."""

import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "hepta_module_docs_projection_tests", Path(__file__).with_name("hepta-module-docs.py")
)
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)

MODULES = "docs/modules/MODULES.json"
BINDINGS = "docs/modules/SOURCE_BINDINGS.json"
GUIDES = "docs/modules/MODULE_DOCS.json"


class RegistryProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root_patch = patch.object(DOCS, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.module = {
            "id": "memory.test",
            "sourceStatus": "target_partially_materialized",
            "source_root_present": False,
            "production_implementation": False,
            "bootstrapWorkPackage": "WP-memory",
            "technicalDocument": "docs/modules/memory.test/TECHNICAL.md",
            "rootBindings": [{"path": "source/memory"}, {"path": "source/future"}],
            "documentationReady": True,
        }
        self.write(MODULES, {"modules": [self.module]})
        self.write(BINDINGS, {"bindings": [{
            "module": "memory.test", "sourceEvidenceRoots": ["source/memory"],
            "independentEvidence": "leave-unchanged",
        }]})
        self.write(GUIDES, {"modules": [{
            "module": "memory.test", "sha256": "optional-prose-cache",
            "bytes": 9, "words": 2,
        }]})
        for path, key in (
            ("docs/contracts/CONTRACTS.json", "contracts"),
            ("docs/contracts/PROTOCOL_SCHEMAS.json", "protocols"),
            ("docs/data/DATA_AUTHORITY.json", "domains"),
            ("docs/delivery/WORK_PACKAGES.json", "packages"),
            ("docs/security/THREAT_MODEL.json", "threats"),
        ):
            self.write(path, {key: []})
        (self.root / "source/memory").mkdir(parents=True)

    def write(self, path, value):
        value = copy.deepcopy(value)
        value.setdefault("authorityFlags", {key: False for key in DOCS.AUTHORITY_KEYS})
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(value), encoding="utf-8")

    def read(self, path):
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    def snapshot(self):
        return {path: (self.root / path).read_bytes() for path in (MODULES, BINDINGS, GUIDES)}

    def sync(self, check=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return DOCS.sync_registries(check)

    def test_presence_is_derived_but_production_is_not_promoted(self):
        self.sync()
        module = self.read(MODULES)["modules"][0]
        binding = self.read(BINDINGS)["bindings"][0]
        guide = self.read(GUIDES)["modules"][0]
        for row in (module, binding, guide):
            self.assertTrue(row["source_root_present"])
            self.assertFalse(row["production_implementation"])
            self.assertEqual(row["sourceStatus"], "target_partially_materialized")
        self.assertEqual(binding["existingDeclaredRoots"], ["source/memory"])
        self.assertEqual(binding["missingDeclaredRoots"], ["source/future"])
        self.assertEqual(binding["independentEvidence"], "leave-unchanged")

    def test_prose_caches_are_not_a_generation_gate(self):
        self.sync()
        guide = self.read(GUIDES)["modules"][0]
        self.assertEqual(
            {key: guide[key] for key in ("sha256", "bytes", "words")},
            {"sha256": "optional-prose-cache", "bytes": 9, "words": 2},
        )

    def test_generation_is_idempotent_and_preserves_noop_bytes(self):
        self.sync()
        before = self.snapshot()
        self.sync()
        self.sync(check=True)
        self.assertEqual(self.snapshot(), before)

    def test_check_mode_detects_drift_without_writing(self):
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "derived registry drift"):
            self.sync(check=True)
        self.assertEqual(self.snapshot(), before)

    def test_positive_authority_is_not_silently_erased(self):
        value = self.read(BINDINGS)
        value["authorityFlags"]["release"] = True
        self.write(BINDINGS, value)
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "positive authority"):
            self.sync()
        self.assertEqual(self.snapshot(), before)

    def test_missing_root_cannot_support_production_claim(self):
        value = self.read(MODULES)
        value["modules"][0]["production_implementation"] = True
        self.write(MODULES, value)
        (self.root / "source/memory").rmdir()
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "without source root"):
            self.sync()
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_bindings_fail_before_any_write(self):
        value = self.read(BINDINGS)
        value["bindings"].append(copy.deepcopy(value["bindings"][0]))
        self.write(BINDINGS, value)
        before = self.snapshot()
        with self.assertRaises(DOCS.DuplicateKey):
            self.sync()
        self.assertEqual(self.snapshot(), before)

    def test_missing_module_coverage_is_not_invented(self):
        self.write(GUIDES, {"modules": []})
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "projection coverage"):
            self.sync()
        self.assertEqual(self.snapshot(), before)

    def test_external_source_path_is_rejected(self):
        value = self.read(MODULES)
        value["modules"][0]["rootBindings"] = [{"path": "../outside"}]
        self.write(MODULES, value)
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "root outside"):
            self.sync()
        self.assertEqual(self.snapshot(), before)

    def test_owner_relationships_drive_both_producer_and_consumer_views(self):
        result = DOCS.registry_index(
            "m",
            [{"id": "out", "producer": "m", "consumers": ["n"]},
             {"id": "in", "producer": "n", "consumers": ["m"]}],
            [{"id": "p", "contractId": "in"}, {"id": "q", "contractId": "unrelated"}],
            [{"id": "own", "authoritativeWriter": "m", "readers": ["n"]},
             {"id": "read", "authoritativeWriter": "n", "readers": ["m"]}],
            [{"id": "a", "module": "m"},
             {"id": "b", "module": "n", "coOwnerModules": ["m"]}],
            [{"id": "threat", "owner": "m"}],
        )
        self.assertEqual(result, {
            "producedContracts": ["out"], "consumedContracts": ["in"],
            "protocols": ["p"], "ownedDomains": ["own"], "readDomains": ["read"],
            "workPackages": ["a", "b"], "threats": ["threat"],
        })

    def test_cli_uses_existing_entrypoint(self):
        with patch("sys.argv", ["hepta-module-docs.py", "sync-registries"]):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(DOCS.main(), 0)
        self.sync(check=True)


if __name__ == "__main__":
    unittest.main()

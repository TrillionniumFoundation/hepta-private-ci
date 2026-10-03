"""Projection membership is generated, not a second hand-maintained registry."""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "module_docs_membership", Path(__file__).with_name("hepta-module-docs.py")
)
docs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docs)


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(docs, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.write("docs/modules/MODULES.json", {"modules": []})
        self.write(
            "docs/modules/SOURCE_BINDINGS.json",
            {"bindings": [], "authorityFlags": {"release": False}},
        )
        self.write(
            "docs/modules/MODULE_DOCS.json",
            {"modules": [], "authorityFlags": {"release": False}},
        )
        for path, key in [
            ("contracts/CONTRACTS.json", "contracts"),
            ("contracts/PROTOCOL_SCHEMAS.json", "protocols"),
            ("data/DATA_AUTHORITY.json", "domains"),
            ("delivery/WORK_PACKAGES.json", "packages"),
            ("security/THREAT_MODEL.json", "threats"),
        ]:
            self.write("docs/" + path, {key: []})
        self.add_module("example.one")

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def add_module(self, name):
        doc = self.read("docs/modules/MODULES.json")
        guide = f"docs/modules/{name}/TECHNICAL.md"
        path = self.root / guide
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Module-specific design\n", encoding="utf-8")
        doc["modules"].append(
            {
                "id": name,
                "lifecycle": "new",
                "sourceStatus": "target_unmaterialized",
                "source_root_present": False,
                "production_implementation": False,
                "rootBindings": [{"path": "codex-rs/" + name}],
                "bootstrapWorkPackage": "BOOT",
                "technicalDocument": guide,
            }
        )
        self.write("docs/modules/MODULES.json", doc)

    def generate(self, check=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return docs.refresh_derived(check)

    def projections(self):
        return [
            (self.root / path).read_bytes()
            for path in [
                "docs/modules/SOURCE_BINDINGS.json",
                "docs/modules/MODULE_DOCS.json",
            ]
        ]

    def test_new_module_generates_both_rows_without_claim_upgrade(self):
        self.generate()
        self.add_module("example.two")
        self.generate()
        binding = self.read("docs/modules/SOURCE_BINDINGS.json")["bindings"][-1]
        guide = self.read("docs/modules/MODULE_DOCS.json")["modules"][-1]
        self.assertEqual(binding["module"], "example.two")
        self.assertEqual(guide["module"], "example.two")
        self.assertFalse(binding["production_implementation"])
        self.assertEqual(binding["sourceEvidenceRoots"], [])
        self.assertFalse(
            self.read("docs/modules/MODULE_DOCS.json")["authorityFlags"]["release"]
        )

    def test_removal_updates_projections_without_deleting_owned_source_or_guide(self):
        self.add_module("example.two")
        self.generate()
        source = self.read("docs/modules/MODULES.json")
        source["modules"].pop()
        self.write("docs/modules/MODULES.json", source)
        self.generate()
        self.assertEqual(
            len(self.read("docs/modules/SOURCE_BINDINGS.json")["bindings"]), 1
        )
        self.assertEqual(len(self.read("docs/modules/MODULE_DOCS.json")["modules"]), 1)
        self.assertTrue((self.root / "docs/modules/example.two/TECHNICAL.md").exists())

    def test_check_detects_membership_drift_without_writing(self):
        before = self.projections()
        with self.assertRaises(SystemExit):
            self.generate(check=True)
        self.assertEqual(before, self.projections())

    def test_generation_is_idempotent_and_preserves_local_metadata(self):
        self.generate()
        value = self.read("docs/modules/MODULE_DOCS.json")
        value["modules"][0]["localNote"] = (
            "do not erase module-specific evidence navigation"
        )
        self.write("docs/modules/MODULE_DOCS.json", value)
        before = self.projections()
        self.generate()
        self.generate(check=True)
        self.assertEqual(before, self.projections())

    def test_duplicate_canonical_identity_is_not_silently_overwritten(self):
        self.add_module("example.one")
        before = self.projections()
        with self.assertRaises(SystemExit):
            self.generate()
        self.assertEqual(before, self.projections())

    def test_duplicate_projection_identity_is_rejected(self):
        self.generate()
        value = self.read("docs/modules/SOURCE_BINDINGS.json")
        value["bindings"].append(value["bindings"][0])
        self.write("docs/modules/SOURCE_BINDINGS.json", value)
        with self.assertRaises(SystemExit):
            self.generate()

    def test_missing_later_guide_does_not_partially_write_either_projection(self):
        self.add_module("example.two")
        (self.root / "docs/modules/example.two/TECHNICAL.md").unlink()
        before = self.projections()
        with self.assertRaises(SystemExit):
            self.generate()
        self.assertEqual(before, self.projections())

    def test_contract_edges_come_from_their_canonical_registry(self):
        self.write(
            "docs/contracts/CONTRACTS.json",
            {
                "contracts": [
                    {
                        "id": "C1",
                        "producer": "example.one",
                        "consumers": ["example.one"],
                    }
                ]
            },
        )
        self.generate()
        row = self.read("docs/modules/MODULE_DOCS.json")["modules"][0]
        self.assertEqual(row["producedContracts"], ["C1"])
        self.assertEqual(row["consumedContracts"], ["C1"])


if __name__ == "__main__":
    unittest.main()

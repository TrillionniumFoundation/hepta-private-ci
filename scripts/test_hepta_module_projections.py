import json
from pathlib import Path
import tempfile
import unittest

from hepta_module_doc_metadata import synchronize
from hepta_module_projections import BINDINGS


class RegistryProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.modules = []
        self.add_module("feature.one")
        self.write(
            "docs/modules/MODULE_DOCS.json",
            {"authorityFlags": {"runtimeAuthority": False}, "modules": []},
        )
        self.write(
            BINDINGS, {"authorityFlags": {"runtimeAuthority": False}, "bindings": []}
        )
        (self.root / "docs/modules/README.md").write_text(
            "# Modules\n\n## Guides\n\n## Working\n\nKeep this guidance.\n"
        )
        self.write(
            "docs/contracts/CONTRACTS.json",
            {
                "contracts": [
                    {
                        "id": "Port",
                        "producer": "feature.one",
                        "consumers": ["feature.two"],
                    }
                ]
            },
        )
        self.write(
            "docs/contracts/PROTOCOL_SCHEMAS.json",
            {"protocols": [{"id": "Wire", "contractId": "Port"}]},
        )
        self.write(
            "docs/data/DATA_AUTHORITY.json",
            {
                "domains": [
                    {
                        "id": "Facts",
                        "authoritativeWriter": "feature.one",
                        "readers": ["feature.two"],
                    }
                ]
            },
        )
        self.write(
            "docs/delivery/WORK_PACKAGES.json",
            {
                "packages": [
                    {
                        "id": "Feature",
                        "module": "feature.one",
                        "coOwnerModules": ["feature.two"],
                    }
                ]
            },
        )
        self.write(
            "docs/security/THREAT_MODEL.json",
            {"threats": [{"id": "Threat", "owner": "feature.one"}]},
        )

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def add_module(self, mid):
        guide = f"docs/modules/{mid}/TECHNICAL.md"
        path = self.root / guide
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {mid}\n")
        self.modules.append(
            {
                "id": mid,
                "technicalDocument": guide,
                "sourceStatus": "target_unmaterialized",
                "source_root_present": False,
                "production_implementation": False,
                "rootBindings": [{"path": f"modules/{mid}"}],
                "sourceEvidenceRoots": [],
                "lifecycle": "planned",
                "bootstrapWorkPackage": "Feature",
            }
        )
        self.write("docs/modules/MODULES.json", {"modules": self.modules})

    def test_add_and_remove_require_no_handwritten_projection_rows(self):
        canonical = (self.root / "docs/modules/MODULES.json").read_bytes()
        synchronize(self.root, write=True, registry_projections=True)
        self.assertEqual(
            (self.root / "docs/modules/MODULES.json").read_bytes(), canonical
        )
        self.add_module("feature.two")
        synchronize(self.root, write=True, registry_projections=True)
        rows = json.loads((self.root / "docs/modules/MODULE_DOCS.json").read_text())[
            "modules"
        ]
        self.assertEqual(rows[1]["consumedContracts"], ["Port"])
        self.assertEqual(rows[1]["readDomains"], ["Facts"])
        self.modules.pop()
        self.write("docs/modules/MODULES.json", {"modules": self.modules})
        synchronize(self.root, write=True, registry_projections=True)
        self.assertEqual(
            len(json.loads((self.root / BINDINGS).read_text())["bindings"]), 1
        )
        self.assertTrue((self.root / "docs/modules/feature.two/TECHNICAL.md").exists())
        self.assertEqual(synchronize(self.root, registry_projections=True), [])

    def test_dry_run_never_writes(self):
        before = {
            path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(len(synchronize(self.root, registry_projections=True)), 3)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_contract_domain_package_and_threat_fields_are_derived(self):
        synchronize(self.root, write=True, registry_projections=True)
        result = json.loads((self.root / "docs/modules/MODULE_DOCS.json").read_text())
        row = result["modules"][0]
        self.assertEqual(
            {
                key: row[key]
                for key in (
                    "producedContracts",
                    "protocols",
                    "ownedDomains",
                    "workPackages",
                    "threats",
                )
            },
            {
                "producedContracts": ["Port"],
                "protocols": ["Wire"],
                "ownedDomains": ["Facts"],
                "workPackages": ["Feature"],
                "threats": ["Threat"],
            },
        )
        self.assertIs(row["production_implementation"], False)
        self.assertEqual(result["authorityFlags"], {"runtimeAuthority": False})
        self.assertIn(
            "Keep this guidance.", (self.root / "docs/modules/README.md").read_text()
        )

    def test_source_presence_cannot_silently_upgrade_canonical_claims(self):
        (self.root / "modules/feature.one").mkdir(parents=True)
        before = (self.root / BINDINGS).read_bytes()
        with self.assertRaisesRegex(ValueError, "canonical module source-root"):
            synchronize(self.root, write=True, registry_projections=True)
        self.assertEqual(before, (self.root / BINDINGS).read_bytes())

    def test_invalid_boolean_is_not_an_authority_fact(self):
        self.modules[0]["production_implementation"] = 0
        self.write("docs/modules/MODULES.json", {"modules": self.modules})
        with self.assertRaisesRegex(ValueError, "booleans"):
            synchronize(self.root, write=True, registry_projections=True)

    def test_duplicate_json_keys_are_rejected(self):
        path = self.root / BINDINGS
        path.write_text('{"bindings":[],"bindings":[]}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            synchronize(self.root, write=True, registry_projections=True)

    def test_path_escape_fails_before_projection_writes(self):
        self.modules[0]["rootBindings"] = [{"path": "../outside"}]
        self.write("docs/modules/MODULES.json", {"modules": self.modules})
        with self.assertRaisesRegex(ValueError, "outside repository"):
            synchronize(self.root, write=True, registry_projections=True)


if __name__ == "__main__":
    unittest.main()

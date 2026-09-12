"""Metadata regeneration preserves source authority and never writes in check mode."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from hepta_module_doc_metadata import INDEX, README, synchronize


class ModuleMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        modules, rows, lines = [], [], []
        for number in range(40):
            module_id = f"module.{number}"
            path = f"docs/modules/{module_id}/TECHNICAL.md"
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"# {module_id}\n\nExplicit implementation boundary.\n",
                encoding="utf-8",
            )
            modules.append(
                {
                    "id": module_id,
                    "technicalDocument": path,
                    "sourceStatus": "target_partially_materialized",
                    "source_root_present": True,
                    "production_implementation": False,
                }
            )
            rows.append(
                {
                    "module": module_id,
                    "path": path,
                    "sourceStatus": "stale",
                    "source_root_present": False,
                    "production_implementation": True,
                    "sha256": "0" * 64,
                    "bytes": 0,
                    "words": 0,
                    "producedContracts": ["PreserveContractV1"],
                }
            )
            lines.append(
                f"- [`{module_id}`]({module_id}/TECHNICAL.md) — `stale`, bootstrap `TEST`.\n"
            )
        self.source_path = self.root / "docs/modules/MODULES.json"
        self.source_path.write_text(json.dumps({"modules": modules}), encoding="utf-8")
        (self.root / INDEX).write_text(
            json.dumps(
                {"modules": rows, "authorityFlags": {"runtimeAuthority": False}}
            ),
            encoding="utf-8",
        )
        (self.root / README).write_text("".join(lines), encoding="utf-8")

    def test_default_mode_detects_staleness_without_writes(self):
        before = {
            path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(
            set(synchronize(self.root)), {self.root / INDEX, self.root / README}
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_explicit_write_is_idempotent_and_preserves_authority(self):
        source_before = self.source_path.read_bytes()
        synchronize(self.root, write=True)
        self.assertEqual(synchronize(self.root), [])
        self.assertEqual(source_before, self.source_path.read_bytes())
        result = json.loads((self.root / INDEX).read_text())
        self.assertEqual(result["authorityFlags"], {"runtimeAuthority": False})
        self.assertTrue(
            all(
                row["producedContracts"] == ["PreserveContractV1"]
                for row in result["modules"]
            )
        )
        self.assertTrue(
            all(
                row["sourceStatus"] == "target_partially_materialized"
                for row in result["modules"]
            )
        )
        self.assertTrue(
            all(row["source_root_present"] is True for row in result["modules"])
        )
        self.assertTrue(
            all(row["production_implementation"] is False for row in result["modules"])
        )

    def test_guide_change_is_bound_to_exact_new_digest(self):
        synchronize(self.root, write=True)
        guide = self.root / "docs/modules/module.0/TECHNICAL.md"
        guide.write_text("# Revised\n", encoding="utf-8")
        self.assertEqual(synchronize(self.root), [self.root / INDEX])
        synchronize(self.root, write=True)
        row = json.loads((self.root / INDEX).read_text())["modules"][0]
        self.assertEqual(row["sha256"], hashlib.sha256(guide.read_bytes()).hexdigest())
        self.assertEqual(row["bytes"], len(guide.read_bytes()))

    def test_missing_readme_entry_fails_before_any_write(self):
        path = self.root / README
        path.write_text("", encoding="utf-8")
        before = (self.root / INDEX).read_bytes()
        with self.assertRaisesRegex(ValueError, "README module coverage"):
            synchronize(self.root, write=True)
        self.assertEqual(before, (self.root / INDEX).read_bytes())

    def test_duplicate_module_row_is_rejected(self):
        path = self.root / INDEX
        value = json.loads(path.read_text())
        value["modules"][1] = value["modules"][0]
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "module coverage mismatch"):
            synchronize(self.root, write=True)

    def test_noncanonical_guide_path_is_rejected(self):
        path = self.root / INDEX
        value = json.loads(path.read_text())
        value["modules"][0]["path"] = "../outside.md"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "technical document path mismatch"):
            synchronize(self.root, write=True)


if __name__ == "__main__":
    unittest.main()

"""Copied public subsets preserve source roles and reject changed bytes."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ndu_real_materials.common import write_json
from .stopped_observed_inputs import load_inputs, save_inputs
from .test_stopped_diagnostics import registration


class ObservedInputTests(unittest.TestCase):
    def test_subset_copy_preserves_sources_and_detects_modified_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            dataset = {"revision": "fixture"}
            reg = registration()
            cases = [
                {"source_id": name}
                for role in ("fit", "calibration", "diagnostic")
                for name in reg[role + "_source_groups"]
            ]
            write_json(source / "registration.json", reg)
            write_json(source / "prospective-selection.json", {"fixture_only": True})
            write_json(
                source / "materials" / "public-source.json", {"pixels": "fixture"}
            )
            pin = save_inputs(source, cases, dataset)
            _, copied = load_inputs(source, root / "destination", pin, dataset)
            self.assertEqual(copied, cases)
            self.assertEqual(
                (root / "destination/input-manifest.json").read_bytes(),
                (source / "input-manifest.json").read_bytes(),
            )
            (source / "materials/public-source.json").write_text("changed")
            with self.assertRaises(ValueError):
                load_inputs(source, root / "changed", pin, dataset)
            self.assertFalse((root / "changed").exists())

    def test_roster_reassignment_is_rejected_before_any_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = {"revision": "fixture"}
            reg = registration()
            write_json(root / "registration.json", reg)
            write_json(root / "prospective-selection.json", {})
            pin = save_inputs(root, [{"source_id": "wrong"}] * 5, dataset)
            with self.assertRaisesRegex(ValueError, "roster"):
                load_inputs(root, root / "destination", pin, dataset)
            self.assertFalse((root / "destination").exists())
            manifest = json.loads((root / "input-manifest.json").read_text())
            manifest["files"][0]["path"] = "../escape.json"
            raw = json.dumps(manifest).encode()
            (root / "input-manifest.json").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "path"):
                load_inputs(
                    root, root / "escape", hashlib.sha256(raw).hexdigest(), dataset
                )


if __name__ == "__main__":
    unittest.main()

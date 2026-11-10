from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from .metacontrol_macro_contract import read_pin, validate_plan
from .test_macro_pair_fixtures import plan


class MacroContractTests(unittest.TestCase):
    def test_overlap_pin_tampering_and_sealed_future_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = plan(root)
            altered = deepcopy(p)
            altered["source_splits"]["future"] = ["s"]
            with self.assertRaises(ValueError):
                validate_plan(altered)
            altered = deepcopy(p)
            altered["source_splits"] = {"train": [], "calibration": [], "future": ["s"]}
            altered["pairs"][0]["split"] = "future"
            altered["frozen_study"] = p["source_pins"][0]
            with self.assertRaises(PermissionError):
                validate_plan(altered)
            Path(p["profile"]["weights"]).write_text("changed")
            with self.assertRaises(ValueError):
                read_pin(
                    {
                        "path": p["profile"]["weights"],
                        "sha256": p["profile"]["model_sha256"],
                    }
                )

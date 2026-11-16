import copy
import json
import unittest
from pathlib import Path
from premerge_gate import audit

S = json.loads((Path(__file__).parent / "snapshot_6382_6395.json").read_text())


class GateTests(unittest.TestCase):
    def test_actual_collisions_never_qualify(self):
        r = audit(S)
        self.assertEqual(r["result"], "HOLD")
        self.assertEqual(r["module_count"], 29)
        self.assertEqual(len(r["shared_names"]), 7)
        self.assertEqual(len(r["unresolved_paths"]), 7)
        self.assertEqual(set(r["entry_profiles"]), {"prefix_admission", "token_budget"})
        self.assertFalse(any(r["qualification"].values()))

    def test_pin_drift_fails(self):
        x = copy.deepcopy(S)
        x["owners"]["render19"]["toolchain"]["revision"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "immutable pin mismatch"):
            audit(x)

    def test_missing_collision_fails(self):
        x = copy.deepcopy(S)
        del x["path_blobs"]["hia/template_render.hepta"]
        with self.assertRaisesRegex(ValueError, "missing repository"):
            audit(x)

    def test_false_abi_resolution_fails(self):
        x = copy.deepcopy(S)
        x["path_blobs"]["hia/template_render.hepta"]["render19"] = \
            x["path_blobs"]["hia/template_render.hepta"]["prefix17"]
        with self.assertRaisesRegex(ValueError, "native render ABI"):
            audit(x)

    def test_duplicate_module_fails(self):
        x = copy.deepcopy(S)
        x["owners"]["render19"]["toolchain"]["modules"].append("uuid_find")
        with self.assertRaisesRegex(ValueError, "duplicate modules"):
            audit(x)


if __name__ == "__main__":
    unittest.main()

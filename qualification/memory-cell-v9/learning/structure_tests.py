"""Metadata-only selector checks on invented completed observations."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from structure_selection import select


class StructureSelectionTests(unittest.TestCase):
    def frame(self):
        addresses = sorted(sha256(f"development-address-{index}".encode()).hexdigest() for index in range(12))
        observations = [{"sequence": index + 1, "request_digest": sha256(f"request-{index}".encode()).hexdigest(),
                         "readout_digest": sha256(f"readout-{index}".encode()).hexdigest(),
                         "addresses": addresses[index % 3::3]} for index in range(12)]
        return {"schema": "hepta.memory.v9.structure-selection.v1", "source_cut_digest": sha256(b"dev-cut").hexdigest(),
                "addresses": addresses, "observations": observations, "resident_budget_bytes": 16384}

    def test_learns_only_completed_coaccess_and_preserves_full_fixed_inventory(self):
        frame = self.frame()
        result = select(frame)
        self.assertEqual([(item["mode"], item["count"]) for item in result["candidates"]],
                         [(mode, count) for mode in ("fixed", "learned") for count in range(1, 9)])
        self.assertTrue(any(left["routes"] != right["routes"] for left, right in
                            zip(result["candidates"][:8], result["candidates"][8:])))
        changed = deepcopy(frame)
        for item in changed["observations"]:
            item["readout_digest"] = sha256(item["readout_digest"].encode()).hexdigest()
        self.assertEqual(select(changed)["candidates"], result["candidates"])
        for forbidden in ("future", "domain", "values", "desired_shards"):
            invalid = dict(frame, **{forbidden: []})
            with self.assertRaises(ValueError):
                select(invalid)


if __name__ == "__main__":
    unittest.main()

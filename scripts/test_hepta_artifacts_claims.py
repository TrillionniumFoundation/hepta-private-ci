import copy
import unittest

import hepta_artifacts_claims as claims


class ClaimsTests(unittest.TestCase):
    def setUp(self):
        self.root = "codex-rs/hepta-learning-artifacts"
        self.path = self.root + "/src/owner_service.rs"
        self.objects = {self.root: "a" * 40, self.path: "b" * 40}
        self.value = {
            "schema": "hepta.module-implementation-map.v3", "module": "learning.artifacts",
            "productionImplementation": False,
            "sourceBase": {"commit": "historical-provenance-not-current-head"},
            "claimBoundary": {name: False for name in claims.DENIED},
            "completionDimensions": {"currentHeadQualification": "requires_two_successful_exact_candidate_receipts"},
            "sourceObjects": [{"path": p, "object": s} for p, s in self.objects.items()],
            "operations": [{"sourcePath": self.path, "sourceBlob": self.objects[self.path]}],
        }

    def check(self, value):
        return claims.validate(value, lambda path: self.objects.get(path, "missing"))

    def test_valid_source_map_keeps_historical_provenance(self):
        self.assertEqual(self.check(self.value), [])

    def test_stale_blob_and_tree_rejected(self):
        for row in range(2):
            changed = copy.deepcopy(self.value)
            changed["sourceObjects"][row]["object"] = "c" * 40
            self.assertTrue(self.check(changed))

    def test_every_activation_claim_rejected(self):
        for name in claims.DENIED:
            changed = copy.deepcopy(self.value)
            changed["claimBoundary"][name] = True
            self.assertTrue(self.check(changed))

    def test_zero_is_not_boolean_false(self):
        changed = copy.deepcopy(self.value)
        changed["claimBoundary"]["activation"] = 0
        self.assertTrue(self.check(changed))

    def test_unified_complete_and_cached_qualification_rejected(self):
        changed = copy.deepcopy(self.value)
        changed["state"] = "COMPLETE"
        self.assertTrue(self.check(changed))
        changed = copy.deepcopy(self.value)
        changed["completionDimensions"]["currentHeadQualification"] = "success"
        self.assertTrue(self.check(changed))

    def test_missing_root_and_path_escape_rejected(self):
        changed = copy.deepcopy(self.value)
        changed["sourceObjects"] = changed["sourceObjects"][1:]
        self.assertTrue(self.check(changed))
        for path in ("../secret", "/absolute", "a/../secret", "a\\b"):
            changed = copy.deepcopy(self.value)
            changed["sourceObjects"][0]["path"] = path
            self.assertTrue(self.check(changed))

    def test_missing_or_malformed_inventory_rejected(self):
        for rows in ([], [None], "not-a-list"):
            changed = copy.deepcopy(self.value)
            changed["sourceObjects"] = rows
            self.assertTrue(self.check(changed))


if __name__ == "__main__":
    unittest.main()

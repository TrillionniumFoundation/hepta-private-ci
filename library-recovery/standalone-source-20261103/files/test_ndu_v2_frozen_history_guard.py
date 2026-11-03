"""Focused source-independent checks for the proposed NDU v2 pin guard.

Not a full hepta-private-ci regression test or model/hardware qualification.
"""
import hashlib
import json
import unittest
from unittest.mock import patch

ORIGINAL_HISTORICAL_SHA256 = {
    "hepta.grounded-cohort.v1": "71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d",
    "hepta.ndu.historical-exclusions.v1": "4c2b88f85c9ef5fea08790775a652798a72e9281bed1534561f14c681e7bba9d",
}

class CohortContractError(ValueError):
    pass

def verify_frozen_history_pins(raw_documents, documents):
    """Bind each original history to its pre-registered raw-byte identity."""
    if len(raw_documents) != 2 or len(documents) != 2:
        raise CohortContractError("v2 requires both original v1 and historical exclusions")
    seen = set()
    for index, (raw, document) in enumerate(zip(raw_documents, documents)):
        if not isinstance(raw, bytes) or not isinstance(document, dict):
            raise CohortContractError(f"history:{index}: invalid original history input")
        schema = document.get("schema")
        if schema not in ORIGINAL_HISTORICAL_SHA256 or schema in seen:
            raise CohortContractError(f"history:{index}: duplicated or unknown original history schema")
        if hashlib.sha256(raw).hexdigest() != ORIGINAL_HISTORICAL_SHA256[schema]:
            raise CohortContractError(f"history:{index}: original frozen SHA256 mismatch")
        seen.add(schema)
    if seen != set(ORIGINAL_HISTORICAL_SHA256):
        raise CohortContractError("original historical evidence set is incomplete")

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.v1 = {"schema":"hepta.grounded-cohort.v1", "splits":{}}
        self.pre = {"schema":"hepta.ndu.historical-exclusions.v1", "source_sample":{}}
        self.v1raw = json.dumps(self.v1).encode()
        self.preraw = json.dumps(self.pre).encode()
    def test_forged_full_manifest_and_self_hash_never_authorized(self):
        with self.assertRaisesRegex(CohortContractError, "original frozen SHA256 mismatch"):
            verify_frozen_history_pins([self.v1raw, self.preraw], [self.v1, self.pre])
    def test_test_only_substituted_pins_accept_either_order(self):
        mocked={self.v1['schema']: hashlib.sha256(self.v1raw).hexdigest(),self.pre['schema']: hashlib.sha256(self.preraw).hexdigest()}
        with patch.dict(ORIGINAL_HISTORICAL_SHA256, mocked, clear=True):
            verify_frozen_history_pins([self.v1raw, self.preraw], [self.v1, self.pre])
            verify_frozen_history_pins([self.preraw, self.v1raw], [self.pre, self.v1])
            with self.assertRaisesRegex(CohortContractError,"original frozen SHA256 mismatch"):
                verify_frozen_history_pins([self.v1raw+b' ', self.preraw], [self.v1,self.pre])
    def test_duplicate_and_missing_history_rejected(self):
        for raw, doc in [([self.v1raw], [self.v1]), ([self.v1raw,self.v1raw],[self.v1,self.v1]), ([self.v1raw,self.preraw], [self.pre,self.v1])]:
            with self.subTest(raw=raw,doc=doc), self.assertRaises(CohortContractError):
                verify_frozen_history_pins(raw,doc)

if __name__ == '__main__':
    unittest.main()

def require_v2_dhash_floor(distance):
    if not 4 <= distance <= 64:
        raise CohortContractError("v2 CLI requires max-dhash-distance between 4 and 64")

class CliFloorTests(unittest.TestCase):
    def test_no_lower_disjointness_floor(self):
        for distance in (-1, 0, 1, 3, 65):
            with self.subTest(distance=distance), self.assertRaisesRegex(CohortContractError, "between 4 and 64"):
                require_v2_dhash_floor(distance)
    def test_default_and_stricter_floor_allowed(self):
        for distance in (4, 5, 64):
            require_v2_dhash_floor(distance)

"""Regression for parsed-protocol identity, not a scientific/model validation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from qualification import ARMS, EvidenceError, digest, validate_protocol


class ProtocolBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "plan.json"
        self.plan = {"schema": "hepta.p0-p7.research.v1", "seeds": [7, 17, 29],
                     "arms": list(ARMS), "episode_budget_us": 20_000,
                     "encoder_digest": digest(b"encoder-pinned"),
                     "encoder_generation": 1,
                     "paired_noise_protocol": "common-random-numbers-v1"}
        self.blob = json.dumps(self.plan, sort_keys=True).encode()
        self.path.write_bytes(self.blob)

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_protocol(self):
        validate_protocol(self.plan, self.path, digest(self.blob))

    def test_stale_object_with_pinned_new_plan_denied(self):
        other = copy.deepcopy(self.plan)
        other["seeds"] = [7, 17, 29, 31]
        payload = json.dumps(other, sort_keys=True).encode()
        self.path.write_bytes(payload)
        with self.assertRaisesRegex(EvidenceError, "parsed protocol differs"):
            validate_protocol(self.plan, self.path, digest(payload))

    def test_numeric_type_alias_not_equal(self):
        other = copy.deepcopy(self.plan)
        other["encoder_generation"] = True
        payload = json.dumps(other, sort_keys=True).encode()
        self.path.write_bytes(payload)
        with self.assertRaisesRegex(EvidenceError, "parsed protocol differs"):
            validate_protocol(self.plan, self.path, digest(payload))

    def test_duplicate_key_with_valid_sha_denied(self):
        payload = b'{"schema":"hepta.p0-p7.research.v1","schema":"alternate"}'
        self.path.write_bytes(payload)
        with self.assertRaises(EvidenceError):
            validate_protocol(self.plan, self.path, digest(payload))


if __name__ == "__main__":
    unittest.main()

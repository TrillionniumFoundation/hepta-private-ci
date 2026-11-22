"""Tests for the bounded lossless compact checkpoint container."""

import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_authentic_compact_checkpoint.compact import (
    CompactCheckpointError,
    INDEX256_SCHEMA,
    decode_compact_checkpoint,
    encode_compact_checkpoint,
)


def _checkpoint(index=256, schema=INDEX256_SCHEMA):
    body = {
        "coefficient": ["1", "2"],
        "exponential_sum": ["3", "2"],
        "growth_coefficient": ["5", "8"],
        "included_index": index,
        "iterate": [["1", "3"], ["-2", "5"]],
        "lane": "synthetic-test-only",
        "parent_payload_sha256": "2" * 64,
        "partial": [["7", "11"], ["-13", "17"]],
        "schema": schema,
        "source_payload_sha256": "1" * 64,
    }
    body_raw = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return json.dumps(
        {"body": body, "body_sha256": hashlib.sha256(body_raw).hexdigest()},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


class CompactCheckpointTests(unittest.TestCase):
    def test_roundtrip_is_byte_exact_and_deterministic(self):
        raw = _checkpoint()
        first = encode_compact_checkpoint(raw, INDEX256_SCHEMA, 256)
        second = encode_compact_checkpoint(raw, INDEX256_SCHEMA, 256)
        self.assertEqual(first, second)
        self.assertEqual(
            decode_compact_checkpoint(first, INDEX256_SCHEMA, 256), raw
        )

    def test_compressed_mutation_is_rejected(self):
        payload = bytearray(
            encode_compact_checkpoint(_checkpoint(), INDEX256_SCHEMA, 256)
        )
        payload[-1] ^= 1
        with self.assertRaises(CompactCheckpointError):
            decode_compact_checkpoint(bytes(payload), INDEX256_SCHEMA, 256)

    def test_noncanonical_json_is_rejected(self):
        raw = _checkpoint() + b"\n"
        with self.assertRaises(CompactCheckpointError):
            encode_compact_checkpoint(raw, INDEX256_SCHEMA, 256)

    def test_schema_and_index_are_bound(self):
        raw = _checkpoint()
        with self.assertRaises(CompactCheckpointError):
            encode_compact_checkpoint(raw, "other-schema", 256)
        with self.assertRaises(CompactCheckpointError):
            encode_compact_checkpoint(raw, INDEX256_SCHEMA, 537)

    def test_noncanonical_fraction_is_rejected(self):
        envelope = json.loads(_checkpoint())
        envelope["body"]["iterate"][0][0] = "01"
        body_raw = json.dumps(
            envelope["body"], sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        envelope["body_sha256"] = hashlib.sha256(body_raw).hexdigest()
        raw = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        with self.assertRaises(CompactCheckpointError):
            encode_compact_checkpoint(raw, INDEX256_SCHEMA, 256)


if __name__ == "__main__":
    unittest.main()

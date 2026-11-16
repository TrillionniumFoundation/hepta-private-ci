"""Small stdlib fixtures only; no N256 numerical state is constructed."""

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_canonical_serializer_intent import admission
from qualification.hcsn_currentstate_n256_canonical_serializer_intent.canonical_serializer import (
    Block,
    DecodeError,
    Envelope,
    Packet,
    cold_load,
    decode,
    encode,
    publish_atomic,
)

ROOT = Path(__file__).parent


def fixture():
    bindings = {
        "candidate_source_sha256": "0" * 64,
        "oracle_source_sha256": "1" * 64,
        "input_bundle_sha256": "2" * 64,
        "roster_identity": "3" * 64,
    }
    blocks = (
        Block("active", "<f8", (2,), struct.pack("<dd", 0.25, -0.5)),
        Block("occupation", "<f8", (1, 2), struct.pack("<dd", 1.0, 2.0)),
    )
    packets = (
        Packet("packet-0001", 1, 0, 1, "1/5", "7/25", b"alpha", b"operator"),
    )
    return Envelope({"bindings": bindings, "lane": "tiny", "time": "1/5"}, blocks, packets)


class CanonicalSerializerTest(unittest.TestCase):
    def test_deterministic_full_roundtrip(self):
        first = encode(fixture())
        second = encode(fixture())
        self.assertEqual(first, second)
        self.assertEqual(encode(decode(first, 4096)), first)

    def test_corruption_is_rejected(self):
        payload = bytearray(encode(fixture()))
        payload[16] ^= 1
        with self.assertRaises(DecodeError):
            decode(bytes(payload), 4096)

    def test_atomic_publish_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.packet"
            digest = publish_atomic(path, fixture())
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(encode(decode(path.read_bytes(), 4096)), path.read_bytes())

    def test_cold_load_rejects_before_state_read(self):
        missing = ROOT / "does-not-exist.packet"
        with self.assertRaises(admission.SerializerAdmissionRequired):
            cold_load(missing, ROOT / "REQUEST.json", None)


if __name__ == "__main__":
    unittest.main()

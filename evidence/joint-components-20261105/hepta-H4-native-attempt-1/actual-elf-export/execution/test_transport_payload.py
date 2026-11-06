"""Small local transport controls only; no native/archive execution."""
import base64
import hashlib
import unittest
import zlib
import transport_payload as T


def encoded(raw, packed=None, raw_bytes=None, raw_sha=None):
    compressed = zlib.compress(raw) if packed is None else packed
    return (base64.b64encode(compressed).decode(), len(compressed), hashlib.sha256(compressed).hexdigest(),
            len(raw) if raw_bytes is None else raw_bytes, hashlib.sha256(raw).hexdigest() if raw_sha is None else raw_sha)


class ExactTransportControls(unittest.TestCase):
    def test_valid_exact_roundtrip_retains_original_bytes(self):
        raw = b'{"fixture":true,"native_credit":false}\n' * 13
        self.assertEqual(T.decode_exact(*encoded(raw)), raw)

    def test_truncated_appended_or_second_stream_is_refused(self):
        raw = b"small original source bytes\0" * 9
        packed = zlib.compress(raw)
        for bad in (packed[:-1], packed + b"tail", packed + zlib.compress(b"second stream")):
            with self.subTest(bytes=len(bad)), self.assertRaises(ValueError):
                T.decode_exact(*encoded(raw, packed=bad))

    def test_declared_length_hash_and_expansion_bound_are_enforced(self):
        raw = b"bounded-control" * 101
        for values in (encoded(raw, raw_bytes=8), encoded(raw, raw_sha="0" * 64),
                       encoded(raw, raw_bytes=T.MAX_RAW_BYTES + 1)):
            with self.subTest(raw_bytes=values[3]), self.assertRaises(ValueError):
                T.decode_exact(*values)


if __name__ == "__main__":
    unittest.main(verbosity=2)

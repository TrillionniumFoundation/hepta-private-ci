"""Bounded decoder tests; the actual model/transform is checked physically."""

import hashlib
import io
from pathlib import Path
import struct
import unittest

from fixed_encoder_sources import decode_json, tokenizer_digest


def entry(name, kind, value):
    encoded = name.encode()
    return struct.pack("<Q", len(encoded)) + encoded + struct.pack("<I", kind) + value


def document(entries):
    return b"GGUF" + struct.pack("<IQQ", 3, 1, len(entries)) + b"".join(entries)


class DecoderTests(unittest.TestCase):
    def test_original_raw_order_not_json_or_sorted_metadata(self):
        general = entry("general.name", 8, struct.pack("<Q", 4) + b"test")
        tokens = entry("tokenizer.ggml.tokens", 9,
                       struct.pack("<IQ", 8, 2) + struct.pack("<Q", 1) + b"A" + struct.pack("<Q", 1) + b"B")
        special = entry("tokenizer.ggml.cls_token_id", 4, struct.pack("<I", 101))
        actual = tokenizer_digest(io.BytesIO(document([general, tokens, special])))
        self.assertEqual(actual, hashlib.sha256(tokens + special).hexdigest())
        self.assertNotEqual(actual, tokenizer_digest(io.BytesIO(document([special, tokens, general]))))

    def test_truncation_duplicate_unknown_and_nested_arrays_are_rejected(self):
        scalar = entry("tokenizer.id", 4, struct.pack("<I", 1))
        nested = entry("tokenizer.tokens", 9, struct.pack("<IQ", 9, 1))
        oversized = entry("tokenizer.tokens", 9, struct.pack("<IQ", 8, 65537))
        unknown = entry("tokenizer.id", 13, b"")
        for payload in [document([scalar])[:-1], document([scalar, scalar]),
                        document([nested]), document([oversized]), document([unknown]), b"GGUF"]:
            with self.subTest(payload=payload[:40]), self.assertRaises(ValueError):
                tokenizer_digest(io.BytesIO(payload))

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        for payload in [b'{"generation":1,"generation":2}', b'{"x":NaN}', b'{"x":Infinity}']:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                decode_json(payload)


if __name__ == "__main__":
    unittest.main()

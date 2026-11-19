"""Small stdlib serializer controls; no N256 state or dynamics are executed."""

import dataclasses
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
    Block,
    DecodeError,
    Envelope,
    MAGIC,
    Packet,
    Tensor,
    coordinate_counts,
    coordinate_rows,
    decode,
    encode,
    publish_atomic,
)


def tensor(shape, values):
    return Tensor("<f8", shape, struct.pack(f"<{len(values)}d", *values))


def fixture():
    blocks = (Block("active", tensor((2,), (0.25, -0.5))),)
    packets = (
        Packet(
            "packet-0001",
            2,
            1,
            2,
            "0/1",
            "1/1000",
            tensor((2, 2), (1.0, 2.0, 3.0, 4.0)),
            tensor((2, 2), (-1.0, 0.25, 0.5, -2.0)),
            tensor((2,), (0.0, 7.0)),
        ),
    )
    return Envelope({"lineage": "tiny", "time": "1/1000"}, blocks, packets)


class SerializerV2Test(unittest.TestCase):
    def test_byte_and_coordinate_roundtrip_include_output(self):
        original = fixture()
        payload = encode(original)
        restored = decode(payload, 4096)
        self.assertEqual(encode(restored), payload)
        self.assertEqual(coordinate_rows(restored), coordinate_rows(original))
        self.assertEqual(
            coordinate_counts(restored),
            {"state": 2, "packet_alpha": 4, "packet_generator": 4, "packet_output": 2, "packet": 10, "total": 12},
        )

    def test_output_mutation_changes_bytes_and_coordinate_rows(self):
        original = fixture()
        packet = original.packets[0]
        changed = dataclasses.replace(
            original,
            packets=(dataclasses.replace(packet, output=tensor((2,), (0.0, 8.0))),),
        )
        self.assertNotEqual(encode(changed), encode(original))
        self.assertNotEqual(coordinate_rows(changed), coordinate_rows(original))

    def test_missing_or_dimensionally_wrong_output_rejects(self):
        packet = fixture().packets[0]
        for output in (Tensor("<f8", (2,), b""), tensor((1,), (7.0,))):
            with self.subTest(output=output):
                envelope = dataclasses.replace(fixture(), packets=(dataclasses.replace(packet, output=output),))
                with self.assertRaises(ValueError):
                    encode(envelope)

    def test_generator_and_alpha_dimension_mismatch_reject(self):
        packet = fixture().packets[0]
        variants = (
            dataclasses.replace(packet, generator=tensor((1, 1), (1.0,))),
            dataclasses.replace(packet, alpha=tensor((2, 1), (1.0, 2.0))),
        )
        for changed in variants:
            with self.assertRaises(ValueError):
                encode(dataclasses.replace(fixture(), packets=(changed,)))

    def test_v1_magic_and_corruption_reject(self):
        payload = encode(fixture())
        with self.assertRaisesRegex(DecodeError, "magic"):
            decode(b"HCSNFSP1" + payload[len(MAGIC):], 4096)
        corrupted = bytearray(payload)
        corrupted[16] ^= 1
        with self.assertRaisesRegex(DecodeError, "checksum"):
            decode(bytes(corrupted), 4096)

    def test_size_bound_and_trailing_bytes_reject(self):
        payload = encode(fixture())
        with self.assertRaisesRegex(DecodeError, "allocation"):
            decode(payload, len(payload) - 1)
        body = payload[:-32] + b"x"
        tailed = body + hashlib.sha256(body).digest()
        with self.assertRaisesRegex(DecodeError, "trailing"):
            decode(tailed, 4096)

    def test_atomic_publish_is_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tiny.packet"
            digest = publish_atomic(path, fixture())
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            restored = decode(path.read_bytes(), 4096)
            self.assertEqual(encode(restored), path.read_bytes())
            self.assertEqual(coordinate_rows(restored), coordinate_rows(fixture()))


if __name__ == "__main__":
    unittest.main()

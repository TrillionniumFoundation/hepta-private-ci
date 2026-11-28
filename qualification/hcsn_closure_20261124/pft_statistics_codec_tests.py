"""Fixed representation controls, not statistical or learning qualification."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import time
import unittest

import numpy as np

from .pft_statistics import DIGEST_FIELDS, canonical, digest
from .pft_statistics_codec import MAX_PACKET_BYTES, decode_packet, encode_packet


RECORDS = []
HEADER = struct.Struct("<8sBHHIB32s32s32s")


def fixture(d=3, m=2, count=4):
    contract = dict(schema="pft-online-statistics-v1", model_family="hcsn-pft-readout-research-v1",
        epoch=0, dimension=d, outputs=m, regularizer=0.2, dtype="float64",
        aggregation="sum-f64-canonical-batch-id", statistics_validation="augmented-psd-rtol-1e-10-v1",
        **{key:digest(["codec", key]) for key in DIGEST_FIELDS})
    body = dict(contract_sha256=digest(contract), source_sha256=digest("representation fixture"), batch_id="codec",
                count=count, sample_ids=[f"{i:064x}" for i in range(count)],
                gram=[[0.0]*d for _ in range(d)], rhs=[[0.0]*m for _ in range(d)], yty=[[0.0]*m for _ in range(m)])
    if (d, m, count) == (3, 2, 4):
        body.update(gram=[[1.0, -0.0, 2.0], [-0.0, 4.0, 3.0], [2.0, 3.0, 9.0]],
                    rhs=[[0.0, -0.0], [float.fromhex("0x0.0000000000001p-1022"), float.fromhex("0x1.fffffffffffffp+1023")], [1.2345678901234567, -1.0]],
                    yty=[[2.0, -0.0], [-0.0, 5.0]])
    return contract, dict(body=body, payload_sha256=digest(body))


def rehash(packet):
    packet["payload_sha256"] = digest(packet["body"])
    return packet


def matrix_bits(packet):
    return b"".join(struct.pack(f"<{len(row)}d", *row) for key in ("gram", "rhs", "yty") for row in packet["body"][key])


class CodecTests(unittest.TestCase):
    def test_bits_signed_zero_extremes_and_four_layouts(self):
        for flags in range(4):
            with self.subTest(flags=flags):
                contract, packet = fixture()
                if not flags & 1:
                    packet["body"]["gram"][0][1] = 0.0
                if not flags & 2:
                    packet["body"]["yty"][0][1] = 0.0
                rehash(packet)
                encoded = encode_packet(packet, contract)
                self.assertEqual(HEADER.unpack_from(encoded)[1], flags)
                decoded = decode_packet(encoded, contract)
                self.assertEqual(decoded, packet)
                self.assertEqual(canonical(decoded), canonical(packet))
                self.assertEqual(matrix_bits(decoded), matrix_bits(packet))
                RECORDS.append(dict(control="four_layouts", flags=flags, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest()))

    def test_producer_types_shapes_identities_and_nonfinite_rejected(self):
        contract, packet = fixture()
        for value in (1, True, np.float64(1.0), float("nan"), float("inf"), -float("inf")):
            changed = copy.deepcopy(packet)
            changed["body"]["gram"][0][0] = value
            if type(value) in (int, bool):
                rehash(changed)
            with self.subTest(value=repr(value)), self.assertRaisesRegex(ValueError, "plain finite float"):
                encode_packet(changed, contract)
        for key, value in (("count", 0), ("count", True), ("count", 100001), ("sample_ids", ["0"*64]*4),
                           ("batch_id", "é"), ("batch_id", "a"*129), ("gram", [[1.0]]), ("rhs", ((1.0, 2.0),)),
                           ("contract_sha256", digest("other")), ("source_sha256", "A"*64)):
            changed = copy.deepcopy(packet)
            changed["body"][key] = value
            rehash(changed)
            with self.subTest(field=key, value=repr(value)), self.assertRaises(ValueError):
                encode_packet(changed, contract)
        changed = copy.deepcopy(packet)
        changed["payload_sha256"] = digest("wrong")
        with self.assertRaisesRegex(ValueError, "payload identity"):
            encode_packet(changed, contract)
        for key, value in (("dimension", 0), ("dimension", 1025), ("outputs", 0), ("outputs", 33)):
            with self.subTest(contract_field=key, value=value), self.assertRaises(ValueError):
                encode_packet(packet, dict(contract, **{key:value}))

    def test_corrupt_header_lengths_hashes_and_payload_rejected(self):
        contract, packet = fixture()
        encoded = encode_packet(packet, contract)
        header = list(HEADER.unpack_from(encoded))
        for index, value in ((0, b"HPFTB002"), (1, 128), (2, 65535), (3, 0), (4, 0), (4, 100001), (5, 0), (5, 255)):
            fields = header.copy()
            fields[index] = value
            changed = HEADER.pack(*fields) + encoded[HEADER.size:]
            with self.subTest(header_field=index, value=value), self.assertRaises(ValueError):
                decode_packet(changed, contract)
        for offset in (18, 50, 82, len(encoded)-1):
            changed = bytearray(encoded)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                decode_packet(bytes(changed), contract)
        for changed in (encoded[:-1], encoded+b"\0", b"", bytearray(encoded), bytes(MAX_PACKET_BYTES+1)):
            with self.subTest(length=len(changed)), self.assertRaises(ValueError):
                decode_packet(changed, contract)
        offset = HEADER.size + len(packet["body"]["batch_id"]) + 32*packet["body"]["count"]
        for value in (float("nan"), float("inf"), -float("inf")):
            changed = encoded[:offset] + struct.pack("<d", value) + encoded[offset+8:]
            with self.subTest(nonfinite=repr(value)), self.assertRaises(ValueError):
                decode_packet(changed, contract)

    def test_noncanonical_full_storage_is_rejected(self):
        contract, packet = fixture()
        encoded = encode_packet(packet, contract)
        fields = list(HEADER.unpack_from(encoded))
        fields[1] = 0
        prefix_size = HEADER.size + len(packet["body"]["batch_id"]) + 32*packet["body"]["count"]
        full = HEADER.pack(*fields) + encoded[HEADER.size:prefix_size] + matrix_bits(packet)
        with self.assertRaisesRegex(ValueError, "noncanonical binary"):
            decode_packet(full, contract)

    def test_exact_producer_bounds_and_asymmetric_overflow(self):
        contract, packet = fixture(1024, 32, 100000)
        encoded = encode_packet(packet, contract)
        decoded = decode_packet(encoded, contract)
        self.assertEqual(canonical(decoded), canonical(packet))
        RECORDS.append(dict(control="accepted_maximum_metadata", bytes=len(encoded), count=100000, dimension=1024, outputs=32))
        packet["body"]["gram"][0][1] = -0.0
        rehash(packet)
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            encode_packet(packet, contract)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CodecTests))
    with args.output.open("x") as stream:
        json.dump(dict(schema="pft-codec-controls-v1", tests=result.testsRun, failures=len(result.failures),
                       errors=len(result.errors), seconds=time.perf_counter()-started, records=RECORDS), stream, indent=2, allow_nan=False)
        stream.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)

"""Stdlib-only tests; no HCSN numerical candidate is imported or executed."""

import ast
import struct
import unittest

from qualification.hcsn_currentstate_n256_admission.verify import (
    canonical,
    payload_hex,
    read_npy,
)


def npy(values, shape):
    header = repr({"descr": "<f8", "fortran_order": False, "shape": shape})
    prefix = b"\x93NUMPY\x01\x00"
    padding = (-((len(prefix) + 2 + len(header) + 1) % 64)) % 64
    encoded = (header + " " * padding + "\n").encode("latin1")
    return prefix + len(encoded).to_bytes(2, "little") + encoded + b"".join(
        struct.pack("<d", value) for value in values
    )


class AdmissionHelpers(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(canonical({"b": 1, "a": 2}), b'{"a":2,"b":1}')

    def test_npy(self):
        shape, payload = read_npy(npy([0.0, -1.5], (2,)))
        self.assertEqual(shape, (2,))
        self.assertEqual(payload_hex(payload), ["0x0.0p+0", "-0x1.8000000000000p+0"])

    def test_header_is_literal(self):
        raw = npy([1.0], (1,))
        width = 2
        length = int.from_bytes(raw[8 : 8 + width], "little")
        header = ast.literal_eval(raw[8 + width : 8 + width + length].decode("latin1").strip())
        self.assertEqual(header["descr"], "<f8")


if __name__ == "__main__":
    unittest.main()

"""Execute the actual HIA text in a restricted source interpreter, not native HIA.

The tests are a pre-admission syntax/transition screen. Real compiler, FFI,
Rust and installed-Codex qualifications remain independently required.
"""
import itertools
from pathlib import Path
import struct
import unittest

from example_validation_source_vm import Program, encode


SOURCE = Path(__file__).resolve().parents[1] / "example_validation_continuation.hepta"


class ExampleValidationSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vm = Program(SOURCE.read_text(encoding="utf-8"))

    def test_empty_rejects_forged_match_flag_without_writes(self):
        for mode in (0, 1):
            with self.subTest(mode=mode):
                status, output, _ = self.vm.execute(encode(mode, 0, 0, 0, 1))
                self.assertEqual(status, 0xffffffff)
                self.assertEqual(output, b"\xa5" * 40)
                good_status, good_output, _ = self.vm.execute(
                    encode(mode, 0, 0, 0, 0)
                )
                self.assertEqual(good_status, 0)
                self.assertEqual(struct.unpack_from("<4Q", good_output), (0, 0, 0, 0))

    def test_real_transitions_cover_positive_negative_and_terminal(self):
        for mode, total, index, misses, hit in itertools.product(
            (0, 1), range(1, 11), range(11), range(11), (0, 1)
        ):
            if index >= total or misses > index or (mode == 0 and misses):
                continue
            with self.subTest(mode=mode, total=total, index=index, misses=misses, hit=hit):
                status, output, _ = self.vm.execute(encode(mode, total, index, misses, hit))
                self.assertEqual(status, 0)
                self.assertEqual(output[32:], b"\xa5" * 8)
                advanced = index + 1
                if mode == 0:
                    expected = (4, index, 0, 0) if hit else (
                        0 if advanced == total else 1, advanced, 0, 0
                    )
                else:
                    accumulated = misses + (1 - hit)
                    event = (0 if accumulated == 0 else (5 if hit else 3)) if advanced == total else (1 if hit else 2)
                    expected = (event, advanced, accumulated, 0)
                self.assertEqual(struct.unpack_from("<4Q", output), expected)

    def test_invalid_frames_are_nonwriting_and_output_capacity_ordered(self):
        invalid_sources = [
            encode(0, 0, 1, 0, 0), encode(1, 0, 0, 1, 0),
            encode(1, 0, 0, 0, 1), encode(2, 1, 0, 0, 1),
            encode(1, 1, 0, 0, 2), encode(1, 1, 1, 0, 0),
            encode(0, 2, 1, 1, 0), encode(1, 2, 0, 1, 0),
            encode(1, 1, 0, 0, 1, version=2),
            b"short",
        ]
        for source in invalid_sources:
            with self.subTest(source=source):
                status, output, _ = self.vm.execute(source)
                self.assertEqual(status, 0xffffffff)
                self.assertEqual(output, b"\xa5" * 40)
        status, output, _ = self.vm.execute(encode(1, 1, 0, 0, 0), output_capacity=31)
        self.assertEqual(status, 0xfffffffe)
        self.assertEqual(output, b"\xa5" * 31)
        status, output, _ = self.vm.execute(encode(1, 1, 0, 0, 0), workspace_capacity=1)
        self.assertEqual(status, 0xffffffff)
        self.assertEqual(output, b"\xa5" * 40)

    def test_large_logical_counts_without_oversize_allocation(self):
        high = (1 << 64) - 1
        for mode, misses, hit in ((0, 0, 0), (0, 0, 1), (1, high - 2, 0), (1, high - 2, 1)):
            status, output, _ = self.vm.execute(encode(mode, high, high - 2, misses, hit))
            self.assertEqual(status, 0)
            self.assertEqual(output[32:], b"\xa5" * 8)


if __name__ == "__main__":
    unittest.main()

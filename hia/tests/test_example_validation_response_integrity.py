"""Source-only adversarial response integrity for the HIA continuation candidate.

Execute the exact HIA *source text* in a restricted Python interpreter and
compare its response to an independently specified original Rust control flow.
This is not actual Hepta machine-code, Rust FFI, product, or platform testing.
"""
import hashlib
import itertools
import struct
import unittest
from pathlib import Path

from example_validation_source_vm import Program, encode

PROGRAM_FILE = Path(__file__).resolve().parents[1] / "example_validation_continuation.hepta"
EXPECTED_GIT_BLOB = "6a3911ed23138010506891bfdb827c0baa98a42a"
MASK = (1 << 64) - 1
INVALID = 0xffffffff
SHORT = 0xfffffffe


def expected(mode, total, index, misses, hit):
    """Original rule.rs loop semantics; independent from the HIA control flow."""
    if mode not in (0, 1) or hit not in (0, 1):
        return None
    if not total:
        return (0, 0, 0, 0) if not any((index, misses, hit)) else None
    if index >= total or misses > index or (mode == 0 and misses):
        return None
    if mode == 0:
        if hit:
            return (4, index, 0, 0)
        end = index + 1
        return (0 if end == total else 1, end, 0, 0)
    end = index + 1
    new_misses = misses + (not hit)
    if hit:
        tag = (0 if not misses else 5) if end == total else 1
    else:
        tag = 3 if end == total else 2
    return (tag, end, int(new_misses), 0)


def guarded_response(mode, total, index, misses, hit, payload):
    """Complete semantic acceptance predicate for an untrusted FFI response.

    This models the Rust-side fail-closed check; it is not an actual invocation
    of the Rust adapter or a behavioral claim about its compiled implementation.
    """
    return len(payload) == 4 and all(type(x) is int and 0 <= x <= MASK for x in payload) \
        and expected(mode, total, index, misses, hit) == tuple(payload)


def mutate(payload):
    """Exhaustively replace each wire word with interesting forged values."""
    for pos, original in enumerate(payload):
        vals = {0, 1, 2, 3, 4, 5, 6, MASK, (original + 1) & MASK,
                (original - 1) & MASK, original ^ (1 << 32)}
        for value in vals - {original}:
            forged = list(payload)
            forged[pos] = value
            yield tuple(forged)


class ResponseIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = PROGRAM_FILE.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != EXPECTED_GIT_BLOB:
            raise AssertionError(f"HIA source blob changed: {actual}")
        cls.program = Program(raw.decode("utf-8"))

    def test_reachable_states_and_forged_frame_words(self):
        source_calls = mutations = 0
        for mode in (0, 1):
            for total in range(16):
                states = [(0, 0, 0)] if not total else (
                    (index, misses, hit)
                    for index in range(total)
                    for misses in (range(index + 1) if mode else (0,))
                    for hit in (0, 1)
                )
                for index, misses, hit in states:
                    original = expected(mode, total, index, misses, hit)
                    status, output, _ = self.program.execute(encode(mode, total, index, misses, hit))
                    self.assertEqual(status, 0)
                    self.assertEqual(output[32:], b"\xa5" * 8)
                    actual = struct.unpack_from("<4Q", output)
                    self.assertEqual(actual, original)
                    self.assertTrue(guarded_response(mode, total, index, misses, hit, actual))
                    source_calls += 1
                    for forged in mutate(actual):
                        self.assertFalse(guarded_response(mode, total, index, misses, hit, forged))
                        mutations += 1
        self.assertGreater(source_calls, 1000)
        self.assertGreater(mutations, 10_000)

    def test_unreachable_input_frames_do_not_write(self):
        cases = list(itertools.product((0, 1, 2), (0, 1, 4),
                                        (0, 1, 5), (0, 1, 4), (0, 1, 2)))
        invalid_cases = 0
        for mode, total, index, misses, hit in cases:
            if expected(mode, total, index, misses, hit) is not None:
                continue
            status, output, _ = self.program.execute(encode(mode, total, index, misses, hit))
            self.assertEqual(status, INVALID)
            self.assertEqual(output, b"\xa5" * 40)
            invalid_cases += 1
        self.assertGreater(invalid_cases, 100)

    def test_input_validation_precedes_publication(self):
        valid = encode(1, 2, 1, 1, 1)
        for mutated in (valid[:-1], valid + b"\0", b"", encode(2, 2, 1, 1, 1),
                        encode(1, 2, 1, 1, 2), encode(1, 0, 0, 0, 1),
                        encode(1, 1, 1, 0, 0), encode(0, 2, 1, 1, 0)):
            status, output, _ = self.program.execute(mutated)
            self.assertEqual(status, INVALID)
            self.assertEqual(output, b"\xa5" * 40)
        status, output, _ = self.program.execute(valid, output_capacity=31)
        self.assertEqual(status, SHORT)
        self.assertEqual(output, b"\xa5" * 31)
        status, output, _ = self.program.execute(valid, workspace_capacity=1)
        self.assertEqual(status, INVALID)
        self.assertEqual(output, b"\xa5" * 40)

    def test_u64_boundaries_without_large_allocations(self):
        total = MASK
        for mode, index, misses, hit in ((0, MASK - 1, 0, 1),
                                         (0, MASK - 1, 0, 0),
                                         (1, MASK - 1, MASK - 2, 1),
                                         (1, MASK - 1, MASK - 2, 0)):
            status, output, _ = self.program.execute(encode(mode, total, index, misses, hit))
            self.assertEqual(status, 0)
            self.assertEqual(struct.unpack_from("<4Q", output),
                             expected(mode, total, index, misses, hit))


if __name__ == "__main__":
    unittest.main()

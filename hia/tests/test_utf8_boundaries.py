"""Native UTF-8 boundary behavior and the unchanged Rust source oracle.

Wire: little-endian u64 byte budget followed by UTF-8. On success f0 writes
an eight-byte little-endian prefix length and returns 8. Invalid input returns
0xffffffff; an output shorter than eight bytes returns 0xfffffffe. Refusals
leave every buffer unchanged. The workspace is reserved and never modified.

The HIA file owns validation and boundary computation. Python only supplies
inputs, invokes compiled machine code, and computes independent expectations.
Set HEPTA_SOURCE to the pinned Hepta checkout. CODEX_HIA_UTF8_SHARED can select
an already built native artifact, including a self-host-compiled artifact.
"""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HEPTA = Path(os.environ.get("HEPTA_SOURCE", ROOT.parent / "Hepta"))
sys.path.insert(0, str(HEPTA))

from hepta.hia_agent_assembly import assemble_program
from hepta.hia_agent_buffers import reference_observation
from hepta.hia_program_native import build_program_machine


SOURCE = ROOT / "hia" / "utf8_boundaries.hepta"
RUST_SOURCE = ROOT / "codex-rs" / "utils" / "string" / "src" / "lib.rs"
EXTENT = 1 << 20
INVALID = 0xFFFFFFFF
SHORT_OUTPUT = 0xFFFFFFFE
MAX_USIZE = (1 << 64) - 1
EXPORTS = (("f0", EXTENT),)


def expected_boundary(raw, budget):
    """Independent character-based expectation; rejects non-Unicode input."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    boundary = 0
    for character in text:
        end = boundary + len(character.encode("utf-8"))
        if end > budget:
            break
        boundary = end
    return boundary


def valid_corpus():
    yield from (
        "", "a", "hello world", "\x00a\x7f", "é", "汉字", "😀abc😀",
        "😀😀😀😀😀", "a\u0301", "👩\u200d🔬", "\n\r\t",
        "\x7f\x80\u07ff\u0800\ud7ff\ue000\uffff\U00010000\U0010ffff",
    )
    generator = random.Random(0xC0DE8)
    for _ in range(256):
        characters = []
        for _ in range(generator.randrange(41)):
            scalar = generator.randrange(0x110000 - 0x800)
            if scalar >= 0xD800:
                scalar += 0x800
            characters.append(chr(scalar))
        yield "".join(characters)


def rust_oracle_source():
    """Extract the actual public Rust function, without reimplementing it."""
    source = RUST_SOURCE.read_text(encoding="utf-8")
    match = re.search(
        r"^pub fn take_bytes_at_char_boundary\(.*?^}", source, re.MULTILINE | re.DOTALL
    )
    if match is None:
        raise AssertionError("the source Rust function was removed or changed shape")
    return match.group(0) + r'''
#[no_mangle]
pub unsafe extern "C" fn rust_prefix(data: *const u8, length: usize, budget: usize) -> usize {
    let bytes = unsafe { std::slice::from_raw_parts(data, length) };
    match std::str::from_utf8(bytes) {
        Ok(text) => take_bytes_at_char_boundary(text, budget).len(),
        Err(_) => usize::MAX,
    }
}
'''


class Utf8BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="codex-hia-utf8-")
        cls.program = assemble_program(SOURCE.read_bytes())
        supplied = os.environ.get("CODEX_HIA_UTF8_SHARED")
        if supplied:
            cls.native_path = Path(supplied).resolve(strict=True)
        else:
            cls.native_path = Path(cls.directory.name) / "utf8_boundaries.so"
            build_program_machine(
                cls.program, cls.native_path, linker="ld", foreign_buffer_exports=EXPORTS
            )
        cls.library = ctypes.CDLL(str(cls.native_path))
        cls.invoke = cls.library.f0
        cls.invoke.restype = ctypes.c_uint64
        cls.invoke.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        cls.native_calls = 0
        cls.vm_calls = 0
        cls.rust_calls = 0

    @classmethod
    def tearDownClass(cls):
        print(json.dumps({
            "suite": "codex_hia_utf8_boundaries",
            "hia_source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "core_sha256": cls.program.sha256,
            "native_sha256": hashlib.sha256(cls.native_path.read_bytes()).hexdigest(),
            "rust_source_sha256": hashlib.sha256(RUST_SOURCE.read_bytes()).hexdigest(),
            "native_calls": cls.native_calls,
            "vm_calls": cls.vm_calls,
            "rust_oracle_calls": cls.rust_calls,
        }, sort_keys=True))
        cls.directory.cleanup()

    def call_native(self, wire, output_size=8):
        source = ctypes.create_string_buffer(b"S" + wire + b"s")
        output = ctypes.create_string_buffer(b"O" + b"\xA5" * output_size + b"o")
        workspace = ctypes.create_string_buffer(b"Wreservedw")
        source_before = source.raw
        workspace_before = workspace.raw
        result = self.invoke(
            ctypes.addressof(source) + 1, len(wire),
            ctypes.addressof(output) + 1, output_size,
            ctypes.addressof(workspace) + 1, len(workspace.raw) - 3,
        )
        type(self).native_calls += 1
        self.assertEqual(result >> 32, 0, "borrowed-buffer ABI refused the invocation")
        self.assertEqual(source.raw, source_before)
        self.assertEqual(workspace.raw, workspace_before)
        self.assertEqual(output.raw[:1], b"O")
        self.assertEqual(output.raw[1 + output_size:], b"o\0")
        return result, output.raw[1:1 + output_size]

    def check_case(self, raw, budget):
        result, output = self.call_native(budget.to_bytes(8, "little") + raw)
        expected = expected_boundary(raw, budget)
        if expected is None:
            self.assertEqual((result, output), (INVALID, b"\xA5" * 8), raw.hex())
        else:
            self.assertEqual((result, output), (8, expected.to_bytes(8, "little")))
            self.assertLessEqual(expected, min(len(raw), budget))
            raw[:expected].decode("utf-8", errors="strict")

    def test_valid_unicode_and_every_selected_byte_boundary(self):
        for index, text in enumerate(valid_corpus()):
            raw = text.encode("utf-8")
            budgets = set(range(len(raw) + 3)) if index < 13 else {
                0, 1, 2, 3, len(raw) // 2, max(len(raw) - 1, 0), len(raw), len(raw) + 1,
            }
            budgets.update((0xFFFFFFFF, 1 << 32, MAX_USIZE))
            for budget in sorted(budgets):
                self.check_case(raw, budget)

    def test_all_one_and_two_byte_strings(self):
        # Exhaustive short inputs cover all legal two-byte scalars, every
        # invalid lead, lone continuations, and all truncated longer leads.
        for byte in range(256):
            self.check_case(bytes([byte]), 1)
        for value in range(1 << 16):
            self.check_case(value.to_bytes(2, "big"), 1)

    def test_long_utf8_forms_and_malformed_tail_after_budget(self):
        cases = [
            b"\xC0\x80", b"\xC1\xBF", b"\xE0\x9F\xBF", b"\xED\xA0\x80",
            b"\xED\xBF\xBF", b"\xF0\x8F\xBF\xBF", b"\xF4\x90\x80\x80",
            b"\xF5\x80\x80\x80", b"\xE2\x82", b"\xF0\x9F\x98",
            b"\xE2\x28\xA1", b"\xF0\x9F\x28\x80", b"\xF0\x9F\x98\x28",
        ]
        # Every second byte at the four restricted Unicode boundaries.
        for lead, suffix in ((0xE0, b"\x80"), (0xED, b"\xBF"),
                             (0xF0, b"\x80\x80"), (0xF4, b"\xBF\xBF")):
            for second in range(256):
                cases.append(bytes([lead, second]) + suffix)
        for raw in cases:
            for budget in (0, 1, MAX_USIZE):
                self.check_case(raw, budget)
            self.check_case(b"accepted-prefix" + raw, 3)
        for text in ("é", "汉", "😀", "\U0010ffff"):
            raw = text.encode("utf-8")
            for length in range(1, len(raw)):
                self.check_case(raw[:length], MAX_USIZE)

    def test_capacity_refusals_and_untouched_output_tail(self):
        for length in range(8):
            result, output = self.call_native(b"\0" * length)
            self.assertEqual((result, output), (INVALID, b"\xA5" * 8))
        wire = (3).to_bytes(8, "little") + "éabc".encode("utf-8")
        for size in range(8):
            result, output = self.call_native(wire, size)
            self.assertEqual((result, output), (SHORT_OUTPUT, b"\xA5" * size))
        result, output = self.call_native(wire, 24)
        self.assertEqual((result, output), (8, (3).to_bytes(8, "little") + b"\xA5" * 16))
        self.check_case(b"a" * (EXTENT - 8), MAX_USIZE)

    def test_core_vm_agrees_with_native_bytes(self):
        cases = [(b"", 0), (b"abc", 2), ("é😀汉".encode(), 5), (b"\xF4\x90\x80\x80", 0)]
        for text in list(valid_corpus())[:13]:
            raw = text.encode("utf-8")
            cases.extend((raw, budget) for budget in (0, 1, len(raw), MAX_USIZE))
        for raw, budget in cases:
            wire = budget.to_bytes(8, "little") + raw
            status, output = self.call_native(wire)
            observation = reference_observation(
                self.program,
                {"function": "f0", "arguments": [
                    {"bytes_hex": wire.hex()}, {"bytes_hex": (b"\xA5" * 8).hex()},
                    {"bytes_hex": b"reserved".hex()},
                ]},
                EXPORTS, steps=100_000, heap=0,
            )
            type(self).vm_calls += 1
            self.assertEqual(observation["status"], "returned")
            self.assertEqual(observation["values"], [status])
            self.assertEqual(observation["buffers"][1]["sha256"], hashlib.sha256(output).hexdigest())
            self.assertEqual(observation["buffers"][0]["sha256"], hashlib.sha256(wire).hexdigest())
            self.assertEqual(observation["buffers"][2]["sha256"], hashlib.sha256(b"reserved").hexdigest())
            self.assertEqual(observation["ledger"]["resources"]["live_bytes"], 0)

    def test_unchanged_rust_function_agrees_with_hia(self):
        rustc = os.environ.get("RUSTC") or shutil.which("rustc")
        if not rustc:
            raise RuntimeError("rustc is required to execute the independent original-source oracle")
        rust_source = Path(self.directory.name) / "rust_oracle.rs"
        rust_source.write_text(rust_oracle_source(), encoding="utf-8")
        library_path = Path(self.directory.name) / "rust_oracle.so"
        subprocess.run(
            [rustc, "--edition=2021", "--crate-type=cdylib", "-O", str(rust_source),
             "-o", str(library_path)], check=True, capture_output=True, text=True, timeout=60,
        )
        library = ctypes.CDLL(str(library_path))
        oracle = library.rust_prefix
        oracle.restype = ctypes.c_size_t
        oracle.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
        for text in valid_corpus():
            raw = text.encode("utf-8")
            allocation = ctypes.create_string_buffer(raw)
            for budget in set((0, 1, 2, 3, len(raw) // 2, max(0, len(raw) - 1), len(raw), MAX_USIZE)):
                expected = oracle(allocation, len(raw), budget)
                type(self).rust_calls += 1
                status, output = self.call_native(budget.to_bytes(8, "little") + raw)
                self.assertEqual((status, output), (8, expected.to_bytes(8, "little")))


if __name__ == "__main__":
    unittest.main(verbosity=2)

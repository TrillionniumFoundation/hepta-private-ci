"""Compare native HIA with this checkout's real Rust search implementation.

Requires Linux x86-64 and the six-argument borrowed-buffer native export.
--write-corpus allows the Rust oracle to run on a separate machine; the oracle
echoes every input frame and --oracle-output verifies that exact correspondence.
No Python search implementation is used as the differential reference.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import platform
import random
import shutil
import struct
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
MAGIC = b"HIASEEK1"
INVALID = 0xFFFFFFFF
NO_SPACE = 0xFFFFFFFE
U64_MAX = (1 << 64) - 1
GUARD = b"\xc7" * 32
WHITE = tuple(range(9, 14)) + (32, 0x85, 0xA0, 0x1680) + tuple(range(0x2000, 0x200B)) + (
    0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
)
PUNCTUATION = {
    **dict.fromkeys((*range(0x2010, 0x2016), 0x2212), "-"),
    **dict.fromkeys(range(0x2018, 0x201C), "'"),
    **dict.fromkeys(range(0x201C, 0x2020), '"'),
    **dict.fromkeys((0xA0, *range(0x2002, 0x200B), 0x202F, 0x205F, 0x3000), " "),
}


def make_wire(lines, pattern, start=0, eof=False, preserve=False):
    strings = [value.encode("utf-8") for value in [*lines, *pattern]]
    offsets = [0]
    for value in strings:
        offsets.append(offsets[-1] + len(value))
    header = struct.pack("<4Q", len(lines), len(pattern), start, int(eof) | (int(preserve) << 1))
    return header + struct.pack(f"<{len(offsets)}Q", *offsets) + b"".join(strings)


def corpus(seed, random_cases):
    cases = []

    def add(label, lines, pattern, start=0, eof=False, preserve=False):
        cases.append((label, make_wire(lines, pattern, start, eof, preserve), False))

    for preserve in (False, True):
        mode = int(preserve)
        for start in (0, 1, 5, U64_MAX):
            for eof in (False, True):
                add(f"empty-{mode}-{start}-{eof}", [], [], start, eof, preserve)
                add(f"empty-pattern-{mode}-{start}-{eof}", ["a"], [], start, eof, preserve)
                add(f"start-bound-{mode}-{start}-{eof}", ["a", "b"], ["b"], start, eof, preserve)
        samples = [
            ("longer-pattern", ["a"], ["a", "b"]),
            ("exact-before-trim", [" target", "target"], ["target"]),
            ("rstrip-before-trim", [" target ", "target "], ["target"]),
            ("trim-before-punctuation", ["a\u2014b", " a-b "], ["a-b"]),
            ("first-exact", ["x", "x", "x"], ["x"]),
            ("several-lines", ["x", " a ", "b\t", "c"], ["a", "b"]),
            ("empty-strings", ["", "", "x"], ["", ""]),
            ("nul", ["x\0y", "x"], ["x\0y"]),
            ("embedded-newline", ["a\nb", "c\rd"], ["a\nb", "c\rd"]),
            ("combining-distinct", ["\u00e9"], ["e\u0301"]),
            ("non-bmp", ["\U0001f600\U0010ffff"], ["\U0001f600\U0010ffff"]),
            ("long-line", ["\u6c49" * 2048 + "\U0001f600"], ["\u6c49" * 2048 + "\U0001f600"]),
            ("long-trim", ["\u3000" * 256 + "a\u2014b" + "\u3000" * 256], ["a-b"]),
        ]
        for label, lines, pattern in samples:
            add(f"{label}-{mode}", lines, pattern, preserve=preserve)
        add(f"eof-no-fallback-{mode}", ["needle", "tail"], ["needle"], eof=True, preserve=preserve)
        add(f"eof-mode-difference-{mode}", ["a", "b"], ["b"], 2, True, preserve)
    for point in WHITE:
        char = chr(point)
        add(f"white-left-{point:x}", [char + "word"], ["word"])
        add(f"white-right-{point:x}", ["word" + char], ["word"])
        add(f"white-both-{point:x}", [char + "word" + char], ["word"])
        add(f"white-only-{point:x}", [char], [""])
        add(f"white-interior-{point:x}", ["a" + char + "b"], ["a b"])
    for point, replacement in PUNCTUATION.items():
        add(f"punct-forward-{point:x}", ["a" + chr(point) + "b"], ["a" + replacement + "b"])
        add(f"punct-reverse-{point:x}", ["a" + replacement + "b"], ["a" + chr(point) + "b"])
    for point in (0x1C, 0x1D, 0x1E, 0x1F, 0x84, 0x86, 0x180E, 0x200B, 0x2060, 0xFEFF):
        add(f"not-rust-whitespace-{point:x}", [chr(point) + "word" + chr(point)], ["word"])
    for point in (0, 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFFFF, 0x10000, 0x10FFFF):
        add(f"utf8-boundary-{point:x}", ["a" + chr(point) + "b"], ["a" + chr(point) + "b"])
    rng = random.Random(seed)
    vocabulary = ["", "a", "b", "x-y", "q'v", 'q"v', "\u6c49", "\U0001f680", "\0", "\u00e9", "e\u0301", "\n"]
    padding = ["", " ", "\t", "\r", "\u3000", "\u0085", "\x1c"]
    for number in range(random_cases):
        lines = ["".join(rng.choices(vocabulary, k=rng.randrange(5))) for _ in range(rng.randrange(13))]
        if lines and rng.randrange(4):
            begin = rng.randrange(len(lines))
            pattern = lines[begin : begin + rng.randrange(5)]
        else:
            pattern = rng.choices(vocabulary, k=rng.randrange(5))
        transform = rng.randrange(5)
        if transform in (1, 2):
            lines = [(rng.choice(padding) if transform == 2 else "") + line + rng.choice(padding) for line in lines]
        elif transform == 3:
            lines = [line.replace("-", "\u2014").replace("'", "\u2019").replace('"', "\u201c") for line in lines]
        elif transform == 4 and pattern:
            pattern[rng.randrange(len(pattern))] += "!"
        add(f"random-{number}", lines, pattern, rng.choice([0, rng.randrange(len(lines) + 4), U64_MAX]),
            bool(rng.randrange(2)), bool(rng.randrange(2)))

    def invalid(label, wire):
        cases.append((label, wire, True))

    base = make_wire(["a", "b"], ["a"])
    for size in range(40):
        invalid(f"truncated-{size}", base[:size])
    for flags in (4, 8, 1 << 63, U64_MAX):
        invalid(f"flags-{flags}", base[:24] + struct.pack("<Q", flags) + base[32:])
    for lines, patterns in ((U64_MAX, 0), (0, U64_MAX), (U64_MAX, 1), (1 << 61, 0)):
        invalid(f"counts-{lines}-{patterns}", struct.pack("<4Q", lines, patterns, 0, 0) + b"\0" * 8)
    for table in ((1, 1, 2, 3), (0, 2, 1, 3), (0, 1, 2, 4), (0, 1, 2, 2), (0, U64_MAX, 2, 3)):
        invalid(f"offsets-{table}", base[:32] + struct.pack("<4Q", *table) + base[64:])
    invalid("extra-payload", base + b"x")
    invalid("unused-payload", make_wire([], []) + b"x")
    malformed = [b"\x80", b"\xbf", b"\xc0\xaf", b"\xc1\xbf", b"\xc2", b"\xe1\x80", b"\xe0\x80\x80",
                 b"\xed\xa0\x80", b"\xf0\x80\x80\x80", b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80",
                 b"\xf8\x88\x80\x80\x80", b"\xff", b"\xe2(\xa1", b"\xf0\x90(\x80"]
    for number, raw in enumerate(malformed):
        for prefix in (b"", b"a"):
            payload = prefix + raw + b"b"
            invalid(f"utf8-invalid-{number}-{len(prefix)}", struct.pack("<6Q", 1, 0, 0, 0, 0, len(payload)) + payload)
    invalid("utf8-split-span", struct.pack("<7Q", 1, 1, 0, 0, 0, 1, 2) + b"\xc2\xa0")
    return cases


def encode_stream(cases):
    return MAGIC + struct.pack("<Q", len(cases)) + b"".join(struct.pack("<Q", len(wire)) + wire for _, wire, _ in cases)


def decode_oracle(data, cases):
    if data[:16] != MAGIC + struct.pack("<Q", len(cases)):
        raise AssertionError("oracle response has the wrong header/count")
    at, results = 16, []
    for label, wire, malformed in cases:
        frame = struct.pack("<Q", len(wire)) + wire
        if data[at : at + len(frame)] != frame:
            raise AssertionError(f"oracle result does not echo exact corpus bytes: {label}")
        at += len(frame)
        result = struct.unpack_from("<3Q", data, at)
        at += 24
        if (result[0] == INVALID) != malformed or result[0] not in (16, INVALID):
            raise AssertionError(f"oracle wire validation disagrees with corpus category: {label}: {result}")
        results.append(result)
    if at != len(data):
        raise AssertionError("oracle response has trailing bytes")
    return results


class GuardedBuffer:
    def __init__(self, data):
        self.size = len(data)
        self.before = GUARD + data + GUARD
        self.storage = ctypes.create_string_buffer(self.before, len(self.before))
        self.pointer = ctypes.addressof(self.storage) + len(GUARD)

    def check(self, unchanged=False):
        actual = self.storage.raw
        if actual[:len(GUARD)] != GUARD or actual[-len(GUARD):] != GUARD:
            raise AssertionError("native call overwrote a buffer guard")
        if unchanged and actual != self.before:
            raise AssertionError("native call modified a read-only/unused buffer")
        return actual[len(GUARD):-len(GUARD)]


def invoke(entry, wire, capacity=16, workspace_size=0):
    source = GuardedBuffer(wire)
    output = GuardedBuffer(b"\xa5" * capacity)
    workspace = GuardedBuffer(b"\x69" * workspace_size)
    code = entry(source.pointer, source.size, output.pointer, output.size, workspace.pointer, workspace.size)
    if code >> 32:
        raise AssertionError(f"native borrowed-buffer ABI rejected the call: {code:#x}")
    source.check(unchanged=True)
    workspace.check(unchanged=True)
    result = output.check(unchanged=code != 16)
    if code == 16:
        if capacity < 16 or result[16:] != b"\xa5" * (capacity - 16):
            raise AssertionError("native result exceeded its 16-byte output extent")
        return (code, *struct.unpack_from("<2Q", result))
    return code, 0, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--symbol", default="f0")
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--oracle-output", type=Path)
    parser.add_argument("--rustc", default=shutil.which("rustc"))
    parser.add_argument("--write-corpus", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--random-cases", type=int, default=2048)
    args = parser.parse_args()
    if not 0 <= args.random_cases <= 50000:
        parser.error("--random-cases must be between 0 and 50000")
    cases = corpus(args.seed, args.random_cases)
    stream = encode_stream(cases)
    if args.write_corpus:
        args.write_corpus.write_bytes(stream)
        print(json.dumps({"cases": len(cases), "bytes": len(stream), "sha256": hashlib.sha256(stream).hexdigest()}))
        return
    if not args.library:
        parser.error("--library is required unless --write-corpus is used")
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        parser.error("native qualification currently targets Linux x86-64")
    with tempfile.TemporaryDirectory(prefix="codex-hia-oracle-") as temporary:
        if args.oracle_output:
            oracle_data = args.oracle_output.read_bytes()
        else:
            oracle = args.oracle
            if oracle is None:
                if not args.rustc:
                    parser.error("supply --oracle, --oracle-output or an available --rustc")
                oracle = Path(temporary) / "seek_sequence_oracle"
                subprocess.run([args.rustc, "--edition=2021", "-O", str(Path(__file__).with_name("seek_sequence_oracle.rs")),
                                "-o", str(oracle)], check=True, timeout=120)
            oracle_data = subprocess.run([str(oracle.resolve())], input=stream, capture_output=True,
                                         check=True, timeout=120).stdout
    expected = decode_oracle(oracle_data, cases)
    library = ctypes.CDLL(str(args.library.resolve()))
    entry = getattr(library, args.symbol)
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint64
    for (label, wire, _), wanted in zip(cases, expected, strict=True):
        actual = invoke(entry, wire)
        if actual != wanted:
            raise AssertionError(f"{label}: native {actual}, Rust {wanted}; wire={wire[:160].hex()}")
    boundary_calls = 0
    for index in (0, 64, 100, len(cases) - 1):
        label, wire, malformed = cases[index]
        for workspace_size in (0, 1, 7, 32, 257):
            for capacity in ((16, 17, 32) if malformed else (0, 1, 7, 8, 15, 16, 17, 32)):
                wanted = (NO_SPACE, 0, 0) if capacity < 16 else expected[index]
                actual = invoke(entry, wire, capacity, workspace_size)
                if actual != wanted:
                    raise AssertionError(f"{label}: capacity={capacity}, workspace={workspace_size}: {actual} != {wanted}")
                boundary_calls += 1
    report = {
        "schema": "codex.hia.seek-sequence-differential.v1", "status": "passed",
        "seed": args.seed, "valid_cases": sum(not row[2] for row in cases),
        "invalid_cases": sum(row[2] for row in cases), "boundary_calls": boundary_calls,
        "corpus_sha256": hashlib.sha256(stream).hexdigest(),
        "oracle_output_sha256": hashlib.sha256(oracle_data).hexdigest(),
        "rust_source_sha256": hashlib.sha256((ROOT / "codex-rs/apply-patch/src/seek_sequence.rs").read_bytes()).hexdigest(),
        "hia_source_sha256": hashlib.sha256((ROOT / "hia/seek_sequence.hepta").read_bytes()).hexdigest(),
        "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
        "symbol": args.symbol, "whole_codex_rewritten": False,
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()

"""Deterministic fixtures, without embedding any expected UUID answers."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import random
import struct

UUID = "00112233-4455-6677-8899-aabbccddeeff"
HEX = "0123456789abcdefABCDEF"


def generate(output):
    cases = []

    def add(category, text):
        data = text.encode("utf-8")
        cases.append((category, data))

    for text in ("", "x", UUID, UUID.upper(), "0" * 36, "-" * 36,
                 "x 00112233-4455-6677-8899-aabbccddeeff-k y 12345678-90ab-cdef-0123-456789abcdef",
                 "not-a-uuid-1234-5678-9abc-def0-123456789abc",
                 "🙂 55e5d6f7-8a7f-4d2a-8d88-123456789012abc"):
        add("original_and_basic", text)
    for position in range(36):
        for byte in range(128):
            add("every_ascii_byte_at_every_position", UUID[:position] + chr(byte) + UUID[position + 1:])
        add("delete_one", UUID[:position] + UUID[position + 1:])
        for ch in ("é", "汉", "🙂", "\u0301", "\u200b", "\uff10"):
            add("nonascii_replacement", UUID[:position] + ch + UUID[position + 1:])
    for position in range(37):
        for text in ("0", "a", "F", "G", "-", "\0", "é", "🙂"):
            add("insert_one", UUID[:position] + text + UUID[position:])
        add("truncation_prefix", UUID[:position])
        add("truncation_suffix", UUID[position:])
    for ch in HEX:
        add("case_version_variant_unrestricted", "-".join(ch * n for n in (8, 4, 4, 4, 12)))
    around = ("", "0", "abcdef", "-", "\0", "🙂", "汉é\r\n", "word_")
    for prefix in around:
        for suffix in around:
            add("no_word_boundary", prefix + UUID + suffix)
    for offset in range(129):
        add("byte_alignment", "x" * offset + UUID + "🙂" + UUID.upper())
    shape = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    for shift in range(1, 36):
        canvas = [None] * (shift + 36)
        compatible = True
        for start in (0, shift):
            for i, ch in enumerate(shape):
                at = start + i
                if canvas[at] is not None and canvas[at] != ch:
                    compatible = False
                canvas[at] = ch
        if compatible:
            assert shift >= 28
            for suffix in ("", UUID, "!" + UUID):
                add("compatible_overlapping_matches", "".join(canvas) + suffix)
    for count in range(1, 65):
        add("adjacent_duplicates", UUID * count)
        add("adjacent_case_preservation", (UUID + UUID.upper()) * count)
    randomizer = random.Random(0x17_9F38)
    alphabet = "0123456789abcdefABCDEF-Gxyz _\r\n\t\0é汉🙂\u0301"
    for _ in range(4000):
        pieces = []
        for _ in range(randomizer.randrange(1, 5)):
            pieces.append("".join(randomizer.choice(alphabet) for _ in range(randomizer.randrange(80))))
            if randomizer.randrange(3):
                value = "-".join("".join(randomizer.choice(HEX) for _ in range(n)) for n in (8, 4, 4, 4, 12))
                if randomizer.randrange(4) == 0:
                    at = randomizer.randrange(36)
                    value = value[:at] + randomizer.choice(alphabet) + value[at + 1:]
                pieces.append(value)
        add("seeded_structured_random", "".join(pieces))
    add("over_two_mib_without_match", "x" * (2 * 1024 * 1024 + 37))
    add("unicode_over_two_mib", "🙂é汉\0" * 220000 + UUID + "\r\n" + UUID.upper())
    add("table_larger_than_one_mib", UUID * 65537)
    output.mkdir(exist_ok=False)
    path = output / "cases.bin"
    with path.open("wb") as stream:
        stream.write(b"UUIDv1\0\0" + struct.pack("<Q", len(cases)))
        for _, data in cases:
            stream.write(struct.pack("<Q", len(data)))
            stream.write(data)
    report = {"schema": "codex.hia.uuid-fixtures.v1", "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "cases": len(cases), "categories": dict(Counter(category for category, _ in cases)),
              "fixture": {"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
              "largest_input_bytes": max(map(lambda row: len(row[1]), cases)),
              "expected_answers_embedded": False,
              "case_bindings": [{"index": i, "category": category, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                                for i, (category, data) in enumerate(cases)]}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    assert report["cases"] == 9609
    assert report["fixture"]["bytes"] == 7877471
    assert report["fixture"]["sha256"] == "dce83263f98494f792663a927817c5a0a26218e6be6ba3ae332ff062e5311e41"
    return report

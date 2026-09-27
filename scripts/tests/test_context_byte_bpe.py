"""Executable algorithm/ABI tests, not production model-accuracy attestation."""
from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "context_tokenizer" / "byte_bpe.py"
spec = importlib.util.spec_from_file_location("context_byte_bpe", MODULE)
assert spec and spec.loader
bpe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bpe
spec.loader.exec_module(bpe)


def artifact() -> dict:
    pieces = [bytes([value]) for value in range(256)] + [b"ab", b"bc", b"abc", b"abab", b"user:"]
    return {
        "schema": bpe.SCHEMA, "provider": "fixture-provider", "model": "fixture-model",
        "version": "fixture-ranked-bpe-v1", "normalization": "none", "pattern": r"(?s).+",
        "mergeable_ranks": [{"bytes_base64": base64.b64encode(piece).decode(), "rank": rank}
                            for rank, piece in enumerate(pieces)],
        "special_tokens": {"<begin>": 1000, "<end>": 1001},
        "framing": {
            "request_prefix": [{"special": "<begin>"}], "request_suffix": [{"special": "<end>"}],
            "roles": {role: {"prefix": [{"text": role + ":"}], "suffix": [{"text": "\n"}]}
                      for role in ["system", "developer", "user", "assistant"]},
            "instructions_role": "system", "ignored_fields": ["metadata", "stream"],
            "tools": {"prefix": [{"text": "tools:"}], "suffix": [{"text": "\n"}]},
        },
    }


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def reference(piece: bytes, ranks: dict[bytes, int]) -> list[int]:
    if piece in ranks:
        return [ranks[piece]]
    parts = [bytes([value]) for value in piece]
    while len(parts) > 1:
        candidates = [(ranks[left + right], index) for index, (left, right) in enumerate(zip(parts, parts[1:]))
                      if left + right in ranks]
        if not candidates:
            break
        _, index = min(candidates)
        parts[index:index + 2] = [parts[index] + parts[index + 1]]
    return [ranks[part] for part in parts]


class RankedBpeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = artifact()
        self.encoding = bpe.Encoding.from_bytes(encoded(self.data))

    def test_real_ranked_merges_not_character_count(self):
        self.assertEqual(self.encoding.ordinary_tokens("abab"), [259])
        self.assertNotEqual(len(self.encoding.ordinary_tokens("abab")), len("abab"))

    def test_heap_matches_independent_slow_reference(self):
        randomizer = random.Random(20260927)
        for _ in range(500):
            piece = bytes(randomizer.choice(b"abcxyz ") for _ in range(randomizer.randrange(1, 80)))
            self.assertEqual(self.encoding.piece_tokens(piece), reference(piece, self.encoding.ranks))

    def test_unicode_is_exact_utf8_no_normalization(self):
        for value in ["政策🧪", "\u00e9", "e\u0301", "\u0000\n\\\"", "👩🏽‍💻"]:
            self.assertEqual(self.encoding.ordinary_tokens(value), reference(value.encode(), self.encoding.ranks))
        self.assertNotEqual(self.encoding.ordinary_tokens("\u00e9"), self.encoding.ordinary_tokens("e\u0301"))

    def test_template_content_boundary_is_not_additive(self):
        # A literal ending in a and content starting in b must be merged by BPE.
        self.assertEqual(self.encoding.count_atoms(["a", "b"]), 1)
        self.assertEqual(self.encoding.count_atoms(["a", 1000, "b"]), 3)

    def test_special_spelling_in_user_content_is_ordinary(self):
        self.assertNotIn(1000, self.encoding.ordinary_tokens("<begin>"))
        self.assertEqual(self.encoding.count_atoms([1000, "ab", 1001]), 3)

    def test_provider_semantics_ignore_json_escape_length(self):
        request = {"model": "fixture-model", "input": [{"role": "user", "content": [{"type": "input_text", "text": "ab🧪\n"}]}]}
        expected = 2 + len(reference("user:ab🧪\n\n".encode(), self.encoding.ranks))
        self.assertEqual(self.encoding.provider_tokens(encoded(request)), expected)
        escaped = json.dumps(request, ensure_ascii=True, indent=2).encode()
        self.assertEqual(self.encoding.provider_tokens(escaped), expected)

    def test_metadata_does_not_become_model_tokens(self):
        request = {"model": "fixture-model", "input": "ab"}
        count = self.encoding.provider_tokens(encoded(request))
        request["metadata"] = {"audit": "NOT_MODEL_INPUT" * 100}
        self.assertEqual(self.encoding.provider_tokens(encoded(request)), count)

    def test_role_and_tool_framing_are_included(self):
        request = {"model": "fixture-model", "instructions": "ab", "input": "abc", "tools": [{"type": "function", "name": "x"}]}
        expected = "system:ab\ntools:" + json.dumps(request["tools"], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\nuser:abc\n"
        self.assertEqual(self.encoding.provider_tokens(encoded(request)), 2 + len(reference(expected.encode(), self.encoding.ranks)))

    def test_duplicate_keys_rejected_at_any_depth(self):
        for raw in [b'{"model":"fixture-model","model":"fixture-model","input":"x"}',
                    b'{"model":"fixture-model","input":[{"role":"user","role":"developer","content":"x"}]}']:
            with self.assertRaises(bpe.Rejected):
                self.encoding.provider_tokens(raw)

    def test_nonfinite_numbers_including_exponent_overflow_rejected(self):
        for numeric in [b"NaN", b"Infinity", b"1e999"]:
            with self.assertRaises(bpe.Rejected):
                self.encoding.provider_tokens(b'{"model":"fixture-model","input":"ab","metadata":{"x":' + numeric + b'}}')

    def test_wrong_model_role_and_content_type_rejected(self):
        for request in [{"model": "wrong", "input": "ab"},
                        {"model": "fixture-model", "input": [{"role": "tool", "content": "ab"}]},
                        {"model": "fixture-model", "input": [{"role": "user", "content": [{"type": "output_text", "text": "ab"}]}]}]:
            with self.assertRaises(bpe.Rejected):
                self.encoding.provider_tokens(encoded(request))

    def test_unknown_provider_fields_rejected(self):
        with self.assertRaises(bpe.Rejected):
            self.encoding.provider_tokens(encoded({"model": "fixture-model", "input": "ab", "hidden_instructions": "x"}))

    def test_unqualified_images_and_calls_rejected(self):
        for item in [{"role": "user", "content": [{"type": "input_image", "image_url": "x"}]},
                     {"type": "function_call", "name": "x", "arguments": "{}"}]:
            with self.assertRaises(bpe.Rejected):
                self.encoding.provider_tokens(encoded({"model": "fixture-model", "input": [item]}))

    def test_pattern_must_cover_every_character(self):
        self.data["pattern"] = "[a-z]+"
        encoding = bpe.Encoding.from_bytes(encoded(self.data))
        with self.assertRaises(bpe.Rejected):
            encoding.ordinary_tokens("ab!abc")

    def test_empty_matches_rejected(self):
        self.data["pattern"] = ".*?"
        encoding = bpe.Encoding.from_bytes(encoded(self.data))
        with self.assertRaises(bpe.Rejected):
            encoding.ordinary_tokens("ab")

    def test_incomplete_or_duplicate_vocabulary_rejected(self):
        for mutate in [lambda d: d["mergeable_ranks"].pop(0),
                       lambda d: d["mergeable_ranks"].append(d["mergeable_ranks"][0]),
                       lambda d: d["mergeable_ranks"][1].update(rank=0),
                       lambda d: d["mergeable_ranks"][1].update(rank=True)]:
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.assertRaises(bpe.Rejected):
                bpe.Encoding.from_bytes(encoded(data))

    def test_normalization_not_silently_changed(self):
        self.data["normalization"] = "NFC"
        with self.assertRaises(bpe.Rejected):
            bpe.Encoding.from_bytes(encoded(self.data))

    def test_special_collision_rejected(self):
        self.data["special_tokens"]["<x>"] = 1000
        with self.assertRaises(bpe.Rejected):
            bpe.Encoding.from_bytes(encoded(self.data))

    def test_pinned_framing_cannot_ignore_model_fields(self):
        self.data["framing"]["ignored_fields"].append("instructions")
        with self.assertRaises(bpe.Rejected):
            bpe.Encoding.from_bytes(encoded(self.data))

    def test_artifact_and_input_bounds(self):
        with self.assertRaises(bpe.Rejected):
            bpe.Encoding.from_bytes(b"")
        with self.assertRaises(bpe.Rejected):
            self.encoding.provider_tokens(b"")

    def test_subprocess_exact_abi_and_no_secret_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            vocabulary = Path(temporary) / "vocabulary.json"
            vocabulary.write_bytes(encoded(self.data))
            argv = [sys.executable, str(MODULE), "--provider", "fixture-provider", "--model", "fixture-model",
                    "--version", "fixture-ranked-bpe-v1", "--normalization", "none", "--vocabulary", str(vocabulary)]
            raw = encoded({"model": "fixture-model", "input": "ab🧪\n"})
            result = subprocess.run(argv, input=raw, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(int(result.stdout), self.encoding.provider_tokens(raw))
            text_result = subprocess.run([*argv, "--mode", "text"], input=b"abab", capture_output=True, timeout=10)
            self.assertEqual((text_result.returncode, text_result.stdout), (0, b"1\n"))
            marker = b"NEVER_LOG_THIS_RAW_CONTEXT"
            failed = subprocess.run(argv, input=marker, capture_output=True, timeout=10)
            self.assertEqual(failed.returncode, 2)
            self.assertNotIn(marker, failed.stderr + failed.stdout)
            self.assertEqual(failed.stdout, b"")


if __name__ == "__main__":
    unittest.main()

"""Fail-closed original archive and matched prompt parity tests."""

import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from hf_original_parity import MODEL_FILES, census, extract_allowed, sha_file


class OriginalArchiveTests(unittest.TestCase):
    def test_symlink_or_missing_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "file"
            with self.assertRaisesRegex(ValueError, "regular"):
                sha_file(source)
            source.write_text("original")
            link = Path(directory) / "link"
            link.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "regular"):
                sha_file(link)
            self.assertEqual(sha_file(source), hashlib.sha256(b"original").hexdigest())

    def test_archived_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w:gz") as tar:
                record = tarfile.TarInfo("memory-inputs/reader/config.json")
                record.type = tarfile.SYMTYPE
                record.linkname = "/etc/passwd"
                tar.addfile(record)
            with self.assertRaisesRegex(ValueError, "unsafe"):
                extract_allowed(io.BytesIO(archive.getvalue()), directory)

    def test_duplicate_and_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w:gz") as tar:
                for _ in range(2):
                    record = tarfile.TarInfo("memory-inputs/reader/config.json")
                    record.size = MODEL_FILES["config.json"]
                    tar.addfile(record, io.BytesIO(b"a" * record.size))
            with self.assertRaisesRegex(ValueError, "unsafe"):
                extract_allowed(io.BytesIO(archive.getvalue()), directory)


class OriginalParityCensusTests(unittest.TestCase):
    def test_empty_population_rejected(self):
        with self.assertRaisesRegex(ValueError, "census"):
            census({"cases": []}, {}, object(), object())

    def test_complete_64_pair_matrix_and_injected_mismatch(self):
        class NativeTokenizer:
            def render(self, messages):
                return messages[0]["content"]

            def encode(self, text):
                return list(text.encode())

        class Official:
            def __init__(self, drift=False):
                self.drift = drift

            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
                value = messages[0]["content"]
                return (
                    list(value.encode()) + ([9] if self.drift else [])
                    if tokenize
                    else value
                )

            def encode(self, text, *, add_special_tokens):
                return list(text.encode())

        reader = type("Reader", (), {"tokenizer": NativeTokenizer()})()
        plan = {"cases": [{"query": {"identity": f"q{i}"}} for i in range(8)]}
        with patch("hf_original_parity.build_messages") as messages:
            messages.side_effect = lambda case, arm, style, sources: (
                [{"content": case["query"]["identity"] + arm + style}],
                ["source"],
            )
            rows, mismatches = census(plan, {}, reader, Official())
            self.assertEqual((len(rows), len(mismatches)), (64, 0))
            _, mismatches = census(plan, {}, reader, Official(drift=True))
            self.assertEqual(len(mismatches), 64)


if __name__ == "__main__":
    unittest.main()

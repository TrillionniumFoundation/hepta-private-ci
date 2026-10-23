"""Adversarial source/history/episode custody tests; entirely synthetic.

These tests prove byte-level input admission, not real model efficacy.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from qualification import (EvidenceError, _read_pinned_artifact, main,
                           read_episodes, read_pinned_json)


def pin(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PinnedInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_source_manifest_requires_exact_frozen_bytes(self):
        frozen = b'{"sources":[{"source_id":"S1","split":"test"}]}'
        path = self.put("sources.json", frozen)
        self.assertEqual(read_pinned_json(path, pin(frozen))["sources"][0]["source_id"],
                         "S1")
        # A syntactically valid, plausible replacement cannot silently pass.
        path.write_bytes(b'{"sources":[]}')
        with self.assertRaisesRegex(EvidenceError, "SHA256 mismatch"):
            read_pinned_json(path, pin(frozen))

    def test_historical_exclusions_cannot_be_erased_after_freeze(self):
        old = b'{"source_sha256":["' + b"0" * 64 + b'"]}'
        path = self.put("history.json", old)
        self.assertEqual(read_pinned_json(path, pin(old))["source_sha256"], ["0" * 64])
        path.write_bytes(b'{"source_sha256":[]}')
        with self.assertRaisesRegex(EvidenceError, "SHA256 mismatch"):
            read_pinned_json(path, pin(old))

    def test_whitespace_and_newline_matter_to_byte_identity(self):
        raw = b'{"a":1}'
        path = self.put("input.json", raw)
        path.write_bytes(raw + b"\n")
        with self.assertRaisesRegex(EvidenceError, "SHA256 mismatch"):
            read_pinned_json(path, pin(raw))

    def test_episode_ledger_must_match_external_pin(self):
        raw = b'{"source_id":"S1","seed":7}\n{"source_id":"S2","seed":29}\n'
        path = self.put("episodes.jsonl", raw)
        self.assertEqual(len(read_episodes(path, pin(raw))), 2)
        # Removing even one valid line is denied before interpreting scores.
        path.write_bytes(b'{"source_id":"S1","seed":7}\n')
        with self.assertRaisesRegex(EvidenceError, "SHA256 mismatch"):
            read_episodes(path, pin(raw))

    def test_episode_duplicate_keys_and_nan_are_rejected(self):
        for row in (b'{"seed":7,"seed":29}\n', b'{"score":NaN}\n'):
            with self.subTest(row=row):
                path = self.put("episodes.jsonl", row)
                with self.assertRaises(EvidenceError):
                    read_episodes(path, pin(row))

    def test_forged_utf8_does_not_enter_score_parser(self):
        raw = b'{"source":"\xff"}\n'
        path = self.put("episodes.jsonl", raw)
        with self.assertRaises(UnicodeDecodeError):
            read_episodes(path, pin(raw))

    def test_symlink_input_and_parent_refused(self):
        outside = self.put("outside.json", b'{"sources":[]}')
        link = self.root / "link.json"
        link.symlink_to(outside)
        with self.assertRaises(EvidenceError):
            read_pinned_json(link, pin(outside.read_bytes()))
        (self.root / "sub-link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            read_pinned_json(self.root / "sub-link" / "outside.json",
                             pin(outside.read_bytes()))

    def test_fifo_refused_without_blocking(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("requires POSIX FIFO")
        pipe = self.root / "pipe.jsonl"
        os.mkfifo(pipe)
        with self.assertRaises(EvidenceError):
            read_episodes(pipe, pin(b""))

    def test_cap_applies_to_actual_descriptor_stream(self):
        oversized = b"x" * 65
        self.put("large.dat", oversized)
        with self.assertRaisesRegex(EvidenceError, "too large"):
            _read_pinned_artifact(self.root, "large.dat", pin(oversized),
                                  cap=64, collect=True)

    def test_missing_sha_flags_are_a_cli_error(self):
        argv = ["--protocol", "protocol.json",
                "--protocol-sha256", "0" * 64,
                "--sources", "sources.json",
                "--history", "history.json",
                "--episodes", "episodes.jsonl",
                "--artifacts-root", str(self.root)]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main(argv)
        self.assertEqual(ctx.exception.code, 2)

    def test_wrong_pinned_ledger_is_invalid_evidence_not_success(self):
        # Fail at the independently pinned protocol before reading cohort rows.
        protocol = self.put("protocol.json", b'{"schema":"hepta.p0-p7.research.v1"}')
        src = self.put("sources.json", b'{"sources":[]}')
        hist = self.put("history.json", b'{"source_sha256":[]}')
        episodes = self.put("episodes.jsonl", b"")
        argv = ["--protocol", str(protocol), "--protocol-sha256", pin(b"wrong"),
                "--sources", str(src), "--sources-sha256", pin(src.read_bytes()),
                "--history", str(hist), "--history-sha256", pin(hist.read_bytes()),
                "--episodes", str(episodes), "--episodes-sha256", pin(b""),
                "--artifacts-root", str(self.root)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(argv), 3)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["status"], "INVALID_EVIDENCE")
        self.assertFalse(receipt["model_promotion_authorized"])
        self.assertEqual(receipt["authority"], "DENY_ALL")


if __name__ == "__main__":
    unittest.main()

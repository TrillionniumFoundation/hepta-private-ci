"""Boundary controls for classifying the already registered binary evidence."""

import contextlib
import importlib.util
import io
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import zlib


OWNER = pathlib.Path(__file__).with_name("hepta-repository-integrity.py")
SPEC = importlib.util.spec_from_file_location("spelling_integrity_owner", OWNER)
INTEGRITY = importlib.util.module_from_spec(SPEC)
# The existing owner defines dataclasses, which inspect their loaded module.
sys.modules[SPEC.name] = INTEGRITY
SPEC.loader.exec_module(INTEGRITY)


class FrozenEvidenceSpellingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        for relative in (INTEGRITY.FROZEN_REPORT, *INTEGRITY.FROZEN_ARCHIVES):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(INTEGRITY.ROOT / relative, target)

    def assert_no_exclusion(self):
        output = self.root / "github-output"
        output.write_text("retained=value\n", encoding="utf-8")
        with (
            mock.patch.object(INTEGRITY, "ROOT", self.root),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = INTEGRITY.main(["spelling-inputs", "--github-output", str(output)])
        self.assertEqual((result, output.read_text()), (1, "retained=value\n"))

    def test_existing_registration_grants_only_two_exact_binary_paths(self):
        text = self.root / "keep_all_text.md"
        text.write_text(
            "Text stays in the original spelling input.\n", encoding="utf-8"
        )
        before = {
            relative: (self.root / relative).read_bytes()
            for relative in (INTEGRITY.FROZEN_REPORT, *INTEGRITY.FROZEN_ARCHIVES)
        }
        receipt = INTEGRITY.spelling_inputs(self.root)
        self.assertEqual(
            receipt["skip"].split(","),
            ["./.git", *["./" + path for path in INTEGRITY.FROZEN_ARCHIVES]],
        )
        self.assertEqual(
            [item["path"] for item in receipt["verified_archives"]],
            list(INTEGRITY.FROZEN_ARCHIVES),
        )
        self.assertEqual(
            before,
            {relative: (self.root / relative).read_bytes() for relative in before},
        )
        self.assertNotIn(text.name, receipt["skip"])

    def test_corrupt_or_plain_text_replacement_never_grants_exclusion(self):
        target = self.root / INTEGRITY.FROZEN_ARCHIVES[0]
        original = target.read_bytes()
        for replacement in (
            original[:-1],
            original + b"trailing",
            b"This is text, not evidence.\n",
        ):
            with self.subTest(bytes=len(replacement)):
                target.write_bytes(replacement)
                self.assert_no_exclusion()

    def test_changed_registration_and_unknown_archive_never_grant_exclusion(self):
        report = self.root / INTEGRITY.FROZEN_REPORT
        original = report.read_bytes()
        report.write_bytes(original + b" ")
        self.assert_no_exclusion()
        report.write_bytes(original)
        unknown = self.root / "unknown.ZLIB"
        unknown.write_bytes(zlib.compress(b"{}"))
        self.assert_no_exclusion()

    def test_exact_single_zlib_stream_is_bounded_and_complete(self):
        packed = zlib.compress(b'{"value":1}')
        self.assertEqual(INTEGRITY.unpack_frozen_evidence(packed), b'{"value":1}')
        for invalid in (
            packed[:-1],
            packed + b"suffix",
            packed + packed,
            zlib.compress(b"a" * (INTEGRITY.MAX_FROZEN_RAW_BYTES + 1)),
        ):
            with (
                self.subTest(bytes=len(invalid)),
                self.assertRaises((ValueError, zlib.error)),
            ):
                INTEGRITY.unpack_frozen_evidence(invalid)

    def test_duplicate_non_finite_and_non_utf8_json_are_rejected(self):
        for invalid in (
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b'{"a":Infinity}',
            b'{"a":1e400}',
            b'{"a":"\xff"}',
        ):
            with self.subTest(raw=invalid), self.assertRaises(ValueError):
                INTEGRITY.strict_evidence_json(invalid)


if __name__ == "__main__":
    unittest.main()

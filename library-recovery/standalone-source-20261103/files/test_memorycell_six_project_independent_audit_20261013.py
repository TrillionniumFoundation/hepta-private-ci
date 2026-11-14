"""Isolated verifier tests; the real-archive test requires external original ZIPs."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memorycell_six_project_independent_audit_20261013 import (
    audit,
    digest,
    git_digest,
    sealed,
    strict_json,
    SOURCE_ZIP_SHA,
    REOPEN_ZIP_SHA,
)


class SixProjectOriginalBytesTests(unittest.TestCase):
    def test_latin1_cannot_be_silently_utf8_normalized(self):
        raw = b'plain source with \xe9 byte'
        self.assertNotEqual(git_digest(raw), git_digest(raw.decode('latin-1').encode('utf-8')))
        self.assertEqual(git_digest(raw), hashlib.sha1(b'blob 24\0' + raw).hexdigest())

    def test_duplicate_json_and_nonfinite_rejected(self):
        for raw in (b'{"status":true,"status":false}', b'{"status":NaN}', b'{"status":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(raw)

    def test_expected_zip_pins_are_distinct(self):
        self.assertNotEqual(SOURCE_ZIP_SHA, REOPEN_ZIP_SHA)
        self.assertEqual(len(SOURCE_ZIP_SHA), 64)
        self.assertEqual(len(REOPEN_ZIP_SHA), 64)

    def test_missing_or_wrong_zip_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / 'new.zip'
            fake.write_bytes(b'not a sealed original archive')
            with self.assertRaises(ValueError):
                sealed(fake, SOURCE_ZIP_SHA)

    def test_actual_originals_pass_exact_byte_and_independent_reopen(self):
        left = os.getenv('HEPTA_SIX_PROJECT_SOURCE_ZIP')
        right = os.getenv('HEPTA_SIX_PROJECT_REOPEN_ZIP')
        if not left or not right:
            self.skipTest('externally pinned original Actions artifacts not supplied')
        report = audit(Path(left), Path(right))
        self.assertEqual(report['verified_original_blob_files'], 32)
        self.assertEqual(report['verified_original_bytes'], 1558460)
        self.assertEqual(report['source_family_proxies'], 6)
        self.assertEqual(report['non_utf8_original_blobs'], 1)
        self.assertTrue(report['independent_reopen_verified'])
        self.assertFalse(report['production_accepted'])
        with tempfile.TemporaryDirectory() as temp:
            broken = Path(temp) / 'altered.zip'
            broken.write_bytes(Path(left).read_bytes() + b'unsupported trailing bytes')
            with self.assertRaises(ValueError):
                audit(broken, Path(right))


if __name__ == '__main__':
    unittest.main()

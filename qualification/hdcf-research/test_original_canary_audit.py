"""Independent literal archive and byte-tamper regressions; fixture-only when absent."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import unittest
import zipfile

from original_canary_audit import (Denied, EXPECTED_ZIP_SHA256, _json, _safetensors_recount,
                                   audit_bytes, audit_file)

ORIGINAL = os.environ.get('HDCF_ORIGINAL_CANARY_ZIP')


class OriginalCanaryAudit(unittest.TestCase):
    def test_duplicate_json_and_nonfinite_rejected(self):
        for s in (b'{"a": 1,"a":2}', b'{"n":NaN}', b'{"n":Infinity}'):
            with self.assertRaises(Denied):
                _json(s)

    def test_incomplete_tensor_bytes_denied(self):
        for raw in (b'', struct.pack('<Q', 500000) + b'{}',
                    struct.pack('<Q',2)+b'{}'+b'\x00'):
            with self.assertRaises(Denied):
                _safetensors_recount(raw)

    def test_tensor_header_overlapping_offsets_rejected(self):
        h = json.dumps({'a':{'dtype':'F32','shape':[1], 'data_offsets':[0,4]},
                        'b':{'dtype':'F32','shape':[1], 'data_offsets':[0,4]}}).encode()
        raw = struct.pack('<Q',len(h))+h+b'\0'*8
        with self.assertRaisesRegex(Denied,'overlap'):
            _safetensors_recount(raw)

    def test_missing_member_rejected_even_if_zip_digest_matches(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('public-cell-learning/scores.json','{}')
        b=out.getvalue()
        with self.assertRaisesRegex(Denied,'incomplete'):
            audit_bytes(b,expected_sha256=hashlib.sha256(b).hexdigest())

    def test_unsigned_unrecognized_outer_sha_denied(self):
        with self.assertRaisesRegex(Denied,'ZIP SHA'):
            audit_bytes(b'PK\x03\x04not a real archive')

    @unittest.skipUnless(ORIGINAL, 'Original pinned Actions archive must be supplied explicitly')
    def test_original_archive_real_tensors_and_source(self):
        observation = audit_file(ORIGINAL)
        self.assertEqual(observation['archive_sha256'], EXPECTED_ZIP_SHA256)
        self.assertTrue(observation['original_experiment_physical_tensors_reverified'])
        self.assertEqual([o['physical_model_parameters'] for o in observation['arms'].values()],
                         [395776,395776])
        self.assertFalse(observation['independent_task_score_verified'])
        self.assertFalse(observation['encoder_outputs_exported_for_hdcf'])
        self.assertFalse(observation['native_effect_authorized'])

    @unittest.skipUnless(ORIGINAL, 'Original pinned Actions archive must be supplied explicitly')
    def test_real_original_archive_tampering_denied(self):
        b = bytearray(Path(ORIGINAL).read_bytes()); b[100] ^= 1
        with self.assertRaises(Denied):
            audit_bytes(bytes(b))


if __name__=='__main__':
    unittest.main()

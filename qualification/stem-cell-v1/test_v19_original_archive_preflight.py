"""Source-only archive negative tests: synthetic payloads, not a pretrained run."""
import io
import json
from hashlib import sha256
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import v19_original_archive_preflight as a


def archive(path, files, extra=(), duplicate=False):
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode='w:gz') as tar:
        for name, content in list(files.items()) + list(extra):
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            tar.addfile(entry, io.BytesIO(content))
        if duplicate:
            name, content = next(iter(files.items()))
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            tar.addfile(entry, io.BytesIO(content))
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(a.PAYLOAD, inner.getvalue())
    return a.sha_file(path)


class Archive(unittest.TestCase):
    def setUp(self):
        self.ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.p = Path(self.ctx.name) / 'original.zip'
        self.payloads = {name: f'synthetic-only {i}'.encode() for i, name in enumerate(a.EXPECTED)}
        self.expected = {name: (sha256(v).hexdigest(), len(v)) for name,v in self.payloads.items()}
        self.sha = archive(self.p, self.payloads)

    def check(self):
        return a.audit_archive(self.p, self.sha, self.expected)

    def test_actual_sanitized_original_archive_receipt(self):
        public = Path(__file__).with_name('V19_ORIGINAL_ARCHIVE_BYTE_RECEIPT_20261016.json')
        r = json.loads(public.read_text())
        self.assertEqual(a.verify_sanitized_result(r)['status'],
            'PHYSICAL_ARCHIVE_DIGEST_REPORT_CONSISTENT_NO_GO')

    def test_reject_false_model_forward_in_public_receipt(self):
        public = Path(__file__).with_name('V19_ORIGINAL_ARCHIVE_BYTE_RECEIPT_20261016.json')
        r = json.loads(public.read_text())
        r['new_model_forward_executed'] = True
        with self.assertRaisesRegex(ValueError,'fabricated'):
            a.verify_sanitized_result(r)

    def test_reject_modified_public_file_hash_or_census(self):
        public = Path(__file__).with_name('V19_ORIGINAL_ARCHIVE_BYTE_RECEIPT_20261016.json')
        r = json.loads(public.read_text())
        r['checked_files']['memory-inputs/locomo.json']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError,'pinned file census'):
            a.verify_sanitized_result(r)
        r = json.loads(public.read_text())
        r['tar_member_count'] += 1
        with self.assertRaisesRegex(ValueError,'archived byte census'):
            a.verify_sanitized_result(r)

    def test_reject_extra_raw_source_in_public_receipt(self):
        public = Path(__file__).with_name('V19_ORIGINAL_ARCHIVE_BYTE_RECEIPT_20261016.json')
        r = json.loads(public.read_text())
        r['original_dialogue'] = 'source must never be uploaded'
        with self.assertRaisesRegex(ValueError,'unsupported fields'):
            a.verify_sanitized_result(r)

    def test_full_original_identity_profile_fixture(self):
        r = self.check()
        self.assertEqual(len(r['checked_files']), 4)
        self.assertEqual(r['tar_member_count'], 4)
        self.assertFalse(r['new_model_forward_executed'])
        self.assertFalse(r['production_authorized'])

    def test_wrong_zip_digest(self):
        with self.assertRaisesRegex(ValueError, 'artifact bytes changed'):
            a.audit_archive(self.p, '0' * 64, self.expected)

    def test_mutated_original_file_content(self):
        self.payloads[next(iter(self.payloads))] = b'corrupted'
        self.sha = archive(self.p,self.payloads)
        with self.assertRaisesRegex(ValueError, 'source/model differs'):
            self.check()

    def test_missing_original_model(self):
        del self.payloads['memory-inputs/reader/model.safetensors']
        self.sha = archive(self.p, self.payloads)
        with self.assertRaisesRegex(ValueError,'incomplete original'):
            self.check()

    def test_duplicate_member_names(self):
        self.sha = archive(self.p, self.payloads, duplicate=True)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.check()

    def test_reject_tar_path_traversal(self):
        self.sha = archive(self.p, self.payloads, extra=[('memory-inputs/../unsafe.txt', b'evil')])
        with self.assertRaisesRegex(ValueError,'traversing'):
            self.check()

    def test_reject_unsafe_outer_name(self):
        self.p.unlink()
        with zipfile.ZipFile(self.p, 'w') as z:
            z.writestr('../memory-inputs.tar.gz', b'synthetic')
        self.sha = a.sha_file(self.p)
        with self.assertRaisesRegex(ValueError, 'outer source archive'):
            self.check()

    def test_reject_extra_outer_source(self):
        with zipfile.ZipFile(self.p, 'a') as z:
            z.writestr('extra.json', b'{}')
        self.sha = a.sha_file(self.p)
        with self.assertRaisesRegex(ValueError, 'outer source archive'):
            self.check()

    def test_reject_symlink_archive_path(self):
        alias = self.p.parent / 'alias.zip'
        alias.symlink_to(self.p)
        with self.assertRaisesRegex(ValueError,'symbolic'):
            a.audit_archive(alias, self.sha, self.expected)

    def test_reject_tar_symlink_member(self):
        inner = io.BytesIO()
        with tarfile.open(fileobj=inner, mode='w:gz') as tar:
            for name, data in self.payloads.items():
                ent = tarfile.TarInfo(name)
                ent.size = len(data)
                tar.addfile(ent, io.BytesIO(data))
            link = tarfile.TarInfo('memory-inputs/escape')
            link.type = tarfile.SYMTYPE
            link.linkname = '../../etc/passwd'
            tar.addfile(link)
        with zipfile.ZipFile(self.p,'w') as z:
            z.writestr(a.PAYLOAD, inner.getvalue())
        self.sha = a.sha_file(self.p)
        with self.assertRaisesRegex(ValueError,'member type'):
            self.check()

    def test_reject_member_count_limit(self):
        with patch.object(a,'MAX_MEMBERS',3):
            with self.assertRaisesRegex(ValueError,'member count'):
                self.check()

    def test_reject_expanded_cap(self):
        with patch.object(a,'MAX_EXPANDED_BYTES',8):
            with self.assertRaisesRegex(ValueError,'expansion ceiling'):
                self.check()


if __name__ == '__main__':
    unittest.main()

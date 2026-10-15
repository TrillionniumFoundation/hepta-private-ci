"""Negative/safety guards for provisional original three-archive readout.

These small tests NEVER claim a real original model forward. The exact real
three-archive integration run is preserved as a separate SHA-pinned readout.
"""
import json
from pathlib import Path
import tempfile
import unittest
from e2_beans_three_archive_observation import exact_mcnemar, read_seal, review
from e2_beans_original_zip_review import Reject, canon, digest


class ThreeArchiveGuards(unittest.TestCase):
    def test_exact_mcnemar_equal(self):
        self.assertEqual(exact_mcnemar(1, 1), 1.0)

    def test_exact_mcnemar_identical(self):
        self.assertEqual(exact_mcnemar(0, 0), 1.0)

    def test_exact_mcnemar_all_six_one_sided(self):
        self.assertEqual(exact_mcnemar(6, 0), 0.03125)

    def test_missing_archives_fail(self):
        with self.assertRaisesRegex(Reject, 'three original ZIP roles'):
            review({}, {}, None, '', None, '')

    def test_role_duplicate_bytes_path_fail(self):
        with self.assertRaisesRegex(Reject, 'same ZIP'):
            roles = {'source': Path('same.zip'), 'producer': Path('same.zip'),
                     'withheld': Path('later.zip')}
            review(roles, {k:'a'*64 for k in roles}, None, '', None, '')

    def test_bad_hash_pin_before_loading(self):
        with self.assertRaisesRegex(Reject, 'missing exact original ZIP'):
            roles = {'source': Path('s.zip'), 'producer': Path('p.zip'),
                     'withheld': Path('t.zip')}
            review(roles, {'source':'x', 'producer':'a'*64,'withheld':'b'*64},
                   None,'',None,'')

    def test_valid_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'seal.json'
            raw=canon({'authority':'DENY_ALL','production_accepted':False})
            f.write_bytes(raw)
            self.assertEqual(read_seal(f,digest(raw))['authority'],'DENY_ALL')

    def test_modified_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'seal.json'
            raw=canon({'authority':'DENY_ALL'})
            f.write_bytes(raw)
            with self.assertRaisesRegex(Reject, 'does not match'):
                read_seal(f,'e'*64)

    def test_duplicate_key_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'seal.json'
            raw=b'{"authority":"DENY_ALL","authority":"DENY_ALL"}\n'
            f.write_bytes(raw)
            with self.assertRaisesRegex(Reject, 'duplicate JSON field'):
                read_seal(f,digest(raw))

    def test_symlink_seal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            orig=Path(tmp)/'original.json';orig.write_bytes(canon({'a':1}))
            link=Path(tmp)/'link.json';link.symlink_to(orig)
            with self.assertRaisesRegex(Reject,'unsafe or missing'):
                read_seal(link,digest(orig.read_bytes()))

    def test_extra_noncanonical_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json';p.write_bytes(b'{"a":1}\n\n')
            with self.assertRaisesRegex(Reject, 'noncanonical'):
                read_seal(p,digest(p.read_bytes()))

if __name__=='__main__':
    unittest.main()

import tempfile
from pathlib import Path
import unittest
from hepta_p0_local import (SOURCE, PRODUCTION, LOCK, DENY, OLD_CALL, NEW_CALL,
                            OLD_IMPORT, UnsafeDrift, inspect_core, apply_core, audit)

class P0LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for p in (SOURCE, PRODUCTION, LOCK, DENY):
            (self.root / p).parent.mkdir(parents=True, exist_ok=True)
        (self.root / SOURCE).write_text(OLD_IMPORT + '\n' +
            ('fn test() {\n let z = ' + OLD_CALL + ';\n}\n')*6)
        (self.root / PRODUCTION).write_text(
            'fn map_response_events<S>(\n    api_stream: S,\n    context: ResponseEventMapContext,\n) {}')
        (self.root / LOCK).write_text('''version = 3
[[package]]
name="anymap2"
version="0.13.0"
[[package]]
name="matrix-sdk-crypto"
version="0.18.0"
[[package]]
name="unsafe-libyaml"
version="0.2.11"
''')
        (self.root / DENY).write_text('[advisories]\nignore=[]\n')

    def test_patches_all_six_only_after_exact_preimage(self):
        self.assertTrue(inspect_core(self.root)['fixable'])
        dry = apply_core(self.root, apply=False)
        self.assertIn('ResponseEventMapContext', dry['patch'])
        self.assertEqual((self.root/SOURCE).read_text().count(OLD_CALL), 6)
        apply_core(self.root, apply=True)
        result=inspect_core(self.root)
        self.assertTrue(result['all_six_calls_migrated'])
        self.assertEqual(result['new_two_argument_calls'], 6)
        self.assertEqual((self.root/SOURCE).read_text().count(NEW_CALL), 6)
        self.assertEqual(list((self.root/SOURCE).parent.glob('.hepta-p0-*')), [])
        with self.assertRaises(UnsafeDrift):
            apply_core(self.root, apply=True)

    def test_refuses_partial_or_changed_source(self):
        p=self.root/SOURCE
        raw=p.read_text()
        p.write_text(raw.replace(OLD_CALL,'invalid',1))
        with self.assertRaisesRegex(UnsafeDrift, 'expected exactly 6'):
            apply_core(self.root, apply=True)
        self.assertIn('invalid',p.read_text())

    def test_refuses_changed_production_signature(self):
        (self.root/PRODUCTION).write_text('fn map_response_events() {}')
        with self.assertRaisesRegex(UnsafeDrift,'actual production'):
            apply_core(self.root, apply=True)

    def test_identifies_exact_three_blocking_advisories(self):
        r=audit(self.root)
        self.assertEqual(set(x['advisory'] for x in r['advisories']),
            {'RUSTSEC-2026-0318','RUSTSEC-2026-0319','RUSTSEC-2024-0449'})
        self.assertFalse(r['production_qualified'])
        self.assertFalse(r['passed_all_local_structural_checks'])

    def test_no_claims_on_security_ignore_or_missing_lock(self):
        apply_core(self.root,apply=True)
        (self.root/LOCK).write_text('version=3\n')
        (self.root/DENY).write_text('[advisories]\nignore=["RUSTSEC-2026-0318"]\n')
        r=audit(self.root)
        self.assertEqual(r['advisories'],[])
        self.assertEqual(r['advisory_ignores_detected'],['RUSTSEC-2026-0318'])
        self.assertFalse(r['passed_all_local_structural_checks'])
        (self.root/LOCK).unlink()
        self.assertIn('lockfile_error',audit(self.root))

if __name__ == '__main__':
    unittest.main()

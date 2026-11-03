import unittest
from hepta_blocking_ci_fanin import EXPECTED_JOBS,allowed_skipped,check

def needs_with_skips(skips):
    return {n:{'result': 'skipped' if n in skips else 'success'} for n in EXPECTED_JOBS}

class Fanin(unittest.TestCase):
    def test_expected_set_has_all_dependencies(self):
        self.assertEqual(len(EXPECTED_JOBS),11)
    def test_valid_scopes(self):
        for native,full in [('false','false'),('true','false'),('true','true')]:
            with self.subTest(native=native,full=full):
                allowed=allowed_skipped(native,full)
                check(needs_with_skips(allowed),native,full)
                self.assertNotIn('scope',allowed)
    def test_missing_scopes(self):
        for native,full in [(None,'false'),('false',None),('','false'),('False','false'),('false','0')]:
            with self.subTest(native=native,full=full),self.assertRaises(ValueError):check(needs_with_skips(set()),native,full)
    def test_full_requires_native(self):
        with self.assertRaises(ValueError): check(needs_with_skips(set()),'false','true')
    def test_missing_job(self):
        for job in EXPECTED_JOBS:
            n=needs_with_skips(set());n.pop(job)
            with self.subTest(job=job), self.assertRaises(ValueError):check(n,'true','true')
    def test_unapproved_skip(self):
        for native,full in [('false','false'),('true','false'),('true','true')]:
            allowed=allowed_skipped(native,full)
            for job in EXPECTED_JOBS-allowed:
                with self.subTest(job=job),self.assertRaises(ValueError):check(needs_with_skips(allowed|{job}),native,full)
    def test_cancelled_or_failed(self):
        for outcome in ['failure','cancelled']:
            n=needs_with_skips(allowed_skipped('false','false'))
            n['bazel']['result']=outcome
            with self.assertRaises(ValueError): check(n,'false','false')

if __name__=='__main__':unittest.main(verbosity=2)

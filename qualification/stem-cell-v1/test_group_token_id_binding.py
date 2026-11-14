"""Research-only exact frozen Token-ID stream content tests."""
import unittest
from group_token_id_binding import token_ids_sha256

class TokenIDTests(unittest.TestCase):
    def test_same_length_distinct_content(self):
        a,b=[101,31,41,102],[101,31,42,102]
        self.assertEqual(len(a),len(b))
        self.assertNotEqual(token_ids_sha256(a),token_ids_sha256(b))
    def test_stable_canonical(self):
        self.assertEqual(token_ids_sha256([1,2]),token_ids_sha256((1,2)))
    def test_fail_closed_integer_bounds(self):
        for bad in (None,[],[True],[1.0],[-1],[2**31],[1]*257,"1,2"):
            with self.subTest(value=repr(bad)[:20]),self.assertRaises(ValueError):
                token_ids_sha256(bad)

if __name__=="__main__":
    unittest.main()

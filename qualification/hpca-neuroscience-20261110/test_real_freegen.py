import unittest
from real_freegen import parse_leading_answer
class ParserTests(unittest.TestCase):
    def test_leading_yes(self):
        self.assertEqual(parse_leading_answer("  Yes. Explanation"),"yes")
    def test_leading_no(self):
        self.assertEqual(parse_leading_answer(" no\n"),"no")
    def test_unlicensed_buried_answer(self):
        self.assertIsNone(parse_leading_answer("maybe, but yes"))
    def test_prefix_not_word(self):
        self.assertIsNone(parse_leading_answer("yesterday"))
    def test_no_ambiguous_buried_word(self):
        self.assertIsNone(parse_leading_answer("The answer is no"))
    def test_empty_or_other(self):
        self.assertIsNone(parse_leading_answer(""))
        self.assertIsNone(parse_leading_answer("I cannot say"))
if __name__=="__main__":
    unittest.main()

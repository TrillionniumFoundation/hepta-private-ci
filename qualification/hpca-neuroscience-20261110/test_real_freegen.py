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
    def test_number_underscore_and_unicode_suffixes_not_standalone(self):
        for raw in ("yes1", "No42", "NO_foo", "yesé", "noβ", "yes文章"):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_leading_answer(raw))
    def test_standalone_leading_labels_keep_punctuation(self):
        for raw, expected in (("YES!", "yes"), ("No: details", "no"),
                              (" yes\n", "yes"), (" No", "no")):
            with self.subTest(raw=raw):
                self.assertEqual(parse_leading_answer(raw), expected)
    def test_no_ambiguous_buried_word(self):
        self.assertIsNone(parse_leading_answer("The answer is no"))
    def test_empty_or_other(self):
        self.assertIsNone(parse_leading_answer(""))
        self.assertIsNone(parse_leading_answer("I cannot say"))
if __name__=="__main__":
    unittest.main()

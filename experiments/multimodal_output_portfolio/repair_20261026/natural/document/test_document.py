import unittest

from .ocr import extract
from .run import score


class DocumentTests(unittest.TestCase):
    def test_layout_rules_keep_total_distinct_from_subtotal_and_change(self):
        texts = ["ACME TRADING SDN BHD", "NO. 7 JALAN MAWAR", "81200 JOHOR BAHRU", "TEL 01234567",
                 "DATE 25/12/2018", "SUBTOTAL 11.00", "GRAND TOTAL 10.00", "CASH 20.00", "CHANGE 10.00"]
        lines = [{"text": t, "box": [0, i*30, 200, i*30+20], "confidence": 90} for i,t in enumerate(texts)]
        answers, _ = extract(lines, 800)
        self.assertEqual(answers, {"company": texts[0], "address": texts[1]+" "+texts[2], "date": "25/12/2018", "total": "10.00"})

    def test_missing_fields_do_not_match_missing_references(self):
        result = score(dict.fromkeys(("company", "date", "address", "total"), ""),
                       dict.fromkeys(("company", "date", "address", "total"), ""))
        self.assertEqual(result["field_fraction"], 0)


if __name__ == "__main__":
    unittest.main()

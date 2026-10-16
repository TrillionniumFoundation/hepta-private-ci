"""Original ZIP-backed adversarial review; run only with real material explicitly staged."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from v18_original_independent_review import Invalid, verify

ORIGINAL_ENV = "HEPTA_V18_ORIGINAL_ZIP"
REPORT_ENV = "HEPTA_V18_ORIGINAL_REPORT"
LOGITS_ENV = "HEPTA_V18_ORIGINAL_PRIVATE_LOGITS"


class OriginalPhysicalAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for var in (ORIGINAL_ENV, REPORT_ENV, LOGITS_ENV):
            if var not in os.environ:
                raise RuntimeError("actual original input required: " + var)
        cls.original = Path(os.environ[ORIGINAL_ENV])
        cls.report = Path(os.environ[REPORT_ENV])
        cls.logits = Path(os.environ[LOGITS_ENV])
        cls.original_report = json.loads(cls.report.read_text())
        cls.original_logits = json.loads(cls.logits.read_text())

    def test_original_independent_recount(self):
        result = verify(self.original, self.report, self.logits)
        self.assertEqual(result["independently_recounted_physical_arms"], 15)
        self.assertEqual(result["decision"], "RECOUNT_CONSISTENT_RESEARCH_NO_GO")

    def changed(self, report=None, logits=None):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "report.json", Path(d) / "private.json"
            a.write_text(json.dumps(report if report is not None else self.original_report))
            b.write_text(json.dumps(logits if logits is not None else self.original_logits))
            with self.assertRaises(Invalid):
                verify(self.original, a, b)

    def test_edited_calibration_brier(self):
        r = copy.deepcopy(self.original_report)
        r["seeds"][0]["arms"]["no_change"]["metrics"]["historical_calibration"]["multiclass_brier"] = 0.0
        self.changed(report=r)

    def test_edited_calibration_logits(self):
        p = copy.deepcopy(self.original_logits)
        p["records"][0]["logits"]["calibration"][0][0] += 0.25
        self.changed(logits=p)

    def test_edited_source_attestation(self):
        r = copy.deepcopy(self.original_report)
        r["seeds"][0]["arms"]["no_change"]["research_authorized"] = True
        self.changed(report=r)

    def test_removed_arm(self):
        p = copy.deepcopy(self.original_logits)
        p["records"].pop()
        self.changed(logits=p)

    def test_fake_future(self):
        r = copy.deepcopy(self.original_report)
        r["future_window_count"] = 2
        self.changed(report=r)

    def test_missing_blind_logits(self):
        p = copy.deepcopy(self.original_logits)
        p["records"][0]["logits"]["blind"].pop()
        self.changed(logits=p)


if __name__ == "__main__":
    unittest.main()

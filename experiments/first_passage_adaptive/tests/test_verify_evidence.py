import hashlib
from pathlib import Path
import tempfile
import unittest

from experiments.first_passage_adaptive.verify_evidence import consistent, verify_sources


class EvidenceVerifierTests(unittest.TestCase):
    def test_gate_consistency_accepts_either_outcome(self):
        for primary,cross in [(False,False),(True,False),(True,True)]:
            value = {"primary_gate":primary,"cross_stratum_gate":cross,"effect":.01}
            consistent(dict(value),value)
        with self.assertRaises(ValueError):
            consistent({"primary_gate":True},{"primary_gate":False})
        with self.assertRaises(ValueError):
            consistent({"primary_gate":1},{"primary_gate":True})

    def test_source_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)/"experiments"/"first_passage_adaptive"
            package.mkdir(parents=True)
            source = package/"operator.py"
            source.write_text("value = 1\n")
            identity = {"source_sha256":{"operator.py":hashlib.sha256(source.read_bytes()).hexdigest()}}
            self.assertEqual(len(verify_sources(package,identity)),1)
            source.write_text("value = 2\n")
            with self.assertRaisesRegex(ValueError,"source digest"):
                verify_sources(package,identity)

    def test_structural_or_nonfinite_statistic_changes_are_rejected(self):
        consistent({"interval":[.1,.2]},{"interval":[.1+1e-15,.2]})
        for actual in [{"interval":[.1,.3]},{"interval":[float("nan"),.2]},
                       {"interval":[.1,.2],"extra":True}]:
            with self.assertRaises(ValueError):
                consistent(actual,{"interval":[.1,.2]})


if __name__ == "__main__":
    unittest.main()

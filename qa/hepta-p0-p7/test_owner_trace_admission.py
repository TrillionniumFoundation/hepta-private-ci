"""Strict, synthetic Group/Encoder receipt admission regressions.

No signed physical forward, causal learning or scientific capability is asserted.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from qualification import (EvidenceError, digest, report_status, validate_episode,
                           validate_sources)
from test_qualification import generate_fixture


def reseal(row):
    actions = [step["action"] for step in row["decisions"]]
    actions_bytes = json.dumps(actions, ensure_ascii=True,
                               separators=(",", ":")).encode()
    row["action_digest"] = digest(b"hepta.group.actions.v1\0" + actions_bytes)
    trace_bytes = json.dumps(row["decisions"], sort_keys=True,
                             separators=(",", ":")).encode()
    row["trace_sha256"] = digest(b"hepta.group.trace.v1\0" + trace_bytes)


class GroupTraceAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.protocol, cls.sources, cls.history, cls.by_id,
         cls.records) = generate_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def base(self):
        return copy.deepcopy(next(r for r in self.records if r["arm"] == "base"))

    def ndu(self):
        return copy.deepcopy(next(r for r in self.records if r["arm"] == "ndu"))

    def test_valid_original_synthetic_ndu_is_still_admitted(self):
        validate_episode(self.root, self.ndu(), self.by_id, self.protocol)

    def test_bool_is_not_one_physical_encoder_forward(self):
        row = self.base()
        row["owner"]["forward_calls"] = True
        with self.assertRaisesRegex(EvidenceError, "Encoder forward"):
            validate_episode(self.root, row, self.by_id, self.protocol)

    def test_bool_is_not_encoder_generation_one(self):
        row = self.base()
        row["owner"]["generation"] = True
        with self.assertRaisesRegex(EvidenceError, "Encoder forward"):
            validate_episode(self.root, row, self.by_id, self.protocol)

    def test_bool_is_not_observed_one_step(self):
        row = self.base()
        row["actual_steps"] = True
        with self.assertRaisesRegex(EvidenceError, "observed steps"):
            validate_episode(self.root, row, self.by_id, self.protocol)

    def test_stop_cannot_be_followed_by_replayed_actions(self):
        row = self.ndu()
        row["decisions"][0]["action"] = "STOP"
        reseal(row)
        with self.assertRaisesRegex(EvidenceError, "terminal decision followed"):
            validate_episode(self.root, row, self.by_id, self.protocol)

    def test_abstain_cannot_be_followed_by_replayed_actions(self):
        row = self.ndu()
        row["decisions"][1]["action"] = "ABSTAIN"
        reseal(row)
        with self.assertRaisesRegex(EvidenceError, "terminal decision followed"):
            validate_episode(self.root, row, self.by_id, self.protocol)

    def test_completed_ndu_requires_explicit_final_decision(self):
        row = self.ndu()
        row["decisions"][-1]["action"] = "VERIFY"
        reseal(row)
        with self.assertRaisesRegex(EvidenceError, "record its terminal decision"):
            validate_episode(self.root, row, self.by_id, self.protocol)

    def test_empty_source_modality_set_does_not_qualify(self):
        sources = copy.deepcopy(self.sources)
        sources["sources"][0]["modalities"] = []
        with self.assertRaisesRegex(EvidenceError, "source modalities"):
            validate_sources(self.root, sources, self.history)


    def test_no_covariance_arm_must_match_realized_cost(self):
        rows = copy.deepcopy(self.records)
        comparison = next(r for r in rows if r["arm"] == "ndu_no_cov")
        comparison["cost_us"]["head"] += 2000
        comparison["total_us"] += 2000
        # This is a well-formed physical cost observation. The earlier summary
        # excluded the no-covariance arm and incorrectly reported matched=True.
        validate_episode(self.root, comparison, self.by_id, self.protocol)
        report = report_status(self.by_id, self.protocol, rows)
        self.assertFalse(
            report["mechanism_checks"]["actual_cost_and_coverage_matched"]
        )



if __name__ == "__main__":
    unittest.main()

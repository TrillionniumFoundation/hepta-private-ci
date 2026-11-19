import copy
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_roster_resolved_hold.roster_hold import (
    REMAINING_FIELDS,
    RosterHoldError,
    validate_roster_resolved_hold,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold"


class RosterResolvedHoldTests(unittest.TestCase):
    def setUp(self):
        self.parent = json.loads(
            (
                ROOT
                / "qualification/hcsn_currentstate_n256_uniformization_admission_contract/REQUEST.json"
            ).read_text()
        )
        self.roster = json.loads(
            (
                ROOT
                / "qualification/hcsn_currentstate_n256_operator_segment_roster/REQUEST.json"
            ).read_text()
        )
        self.record = json.loads((PACKAGE / "REQUEST.json").read_text())

    def test_exact_two_rosters_resolve_and_nine_fields_remain_missing(self):
        self.assertTrue(
            validate_roster_resolved_hold(self.record, self.parent, self.roster)
        )
        evidence = self.record["evidence_state"]
        self.assertEqual(len(REMAINING_FIELDS), 9)
        self.assertEqual(sum(value is not None for value in evidence.values()), 2)
        self.assertEqual(sum(value is None for value in evidence.values()), 9)

    def test_parent_rewrite_is_rejected(self):
        parent = copy.deepcopy(self.parent)
        parent["missing_external_evidence"]["operator_roster_sha256"] = "a" * 64
        with self.assertRaisesRegex(RosterHoldError, "rewritten"):
            validate_roster_resolved_hold(self.record, parent, self.roster)

    def test_roster_identity_change_is_rejected(self):
        roster = copy.deepcopy(self.roster)
        roster["operator_roster_sha256"] = "b" * 64
        with self.assertRaisesRegex(RosterHoldError, "operator roster identity"):
            validate_roster_resolved_hold(self.record, self.parent, roster)

    def test_unbacked_evidence_or_admission_is_rejected(self):
        record = copy.deepcopy(self.record)
        record["evidence_state"]["host_snapshot_sha256"] = "c" * 64
        with self.assertRaisesRegex(RosterHoldError, "unbacked"):
            validate_roster_resolved_hold(record, self.parent, self.roster)
        record = copy.deepcopy(self.record)
        record["provider_admitted"] = True
        with self.assertRaisesRegex(RosterHoldError, "preserve HOLD"):
            validate_roster_resolved_hold(record, self.parent, self.roster)


if __name__ == "__main__":
    unittest.main()

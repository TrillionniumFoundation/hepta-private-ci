"""One-shot archive/claim-boundary tests; no model or experiment execution."""

import argparse
import copy
import json
from pathlib import Path
import sys
import unittest

import evidence_bridge as bridge


class EvidenceBridgeTests(unittest.TestCase):
    records = None

    def documents(self):
        return {k: bridge.parse_record(v) for k, v in self.records.items()
                if k not in ("candidate", "population")}

    def test_complete_archive_has_only_bounded_identity_pass(self):
        report = bridge.assess(self.records)
        self.assertEqual(report["status"], "PASSED_BOUNDED")
        self.assertEqual(report["scope"], "retained_archive_identity_linkage_only")
        self.assertEqual({k: v["status"] for k, v in report["scientific_claims"].items()}, {
            "independent_A_to_B_to_cold_reuse": "INSUFFICIENT",
            "old_capability_retention": "INSUFFICIENT",
        })
        self.assertFalse(report["original_turn_authorization_verified"])
        self.assertFalse(report["production_authorization_available"])

    def test_missing_role_is_insufficient(self):
        records = dict(self.records)
        del records["candidate"]
        report = bridge.assess(records)
        self.assertEqual((report["status"], report["missing_archive_roles"]),
                         ("INSUFFICIENT", ["candidate"]))

    def test_changed_candidate_is_rejected(self):
        records = dict(self.records)
        raw = bytearray(records["candidate"])
        raw[len(raw) // 2] ^= 1
        records["candidate"] = bytes(raw)
        self.assertEqual(bridge.assess(records)["status"], "REJECTED")

    def test_old_central_candidate_cannot_inherit_this_archive(self):
        previous = "87ed31e17899f4ae18cbad3ea7a9b7af05cf42662da4ffd94a1c2c83cde9ef88"
        self.assertEqual(bridge.assess(self.records, previous)["status"], "REJECTED")

    def test_json_reencoding_is_not_the_exact_retained_record(self):
        records = dict(self.records)
        records["cold"] = json.dumps(json.loads(records["cold"]), indent=2).encode()
        self.assertEqual(bridge.assess(records)["status"], "REJECTED")

    def test_caller_authority_cannot_create_an_admission(self):
        records = dict(self.records)
        records["authority"] = b'{"verified":true,"independent_people":true}'
        self.assertEqual(bridge.assess(records)["status"], "REJECTED")

    def test_missing_and_corrupted_is_rejected_not_merely_incomplete(self):
        records = dict(self.records)
        del records["profile"]
        records["trial"] = b"{}"
        self.assertEqual(bridge.assess(records)["status"], "REJECTED")

    def test_candidate_state_splice_is_rejected_by_links(self):
        doc = self.documents()
        doc["numeric"]["model_state_sha256"] = "0" * 64
        with self.assertRaises(bridge.Refused):
            bridge.check_links(doc)

    def test_task_splice_is_rejected_by_links(self):
        doc = self.documents()
        doc["numeric"]["task_id"] = "unseen-task-label"
        with self.assertRaises(bridge.Refused):
            bridge.check_links(doc)

    def test_source_and_protocol_splices_are_rejected_by_links(self):
        for role, field in (("trial", "protocol_sha256"), ("numeric", "source_binding_sha256")):
            with self.subTest(role=role):
                doc = self.documents()
                doc[role][field] = "0" * 64
                with self.assertRaises(bridge.Refused):
                    bridge.check_links(doc)

    def test_same_fixture_cannot_be_promoted_to_independent_use(self):
        for field in ("genuine_independent_users", "natural_task_benefit_claim", "candidate_adopted"):
            with self.subTest(field=field):
                doc = self.documents()
                doc["cold"][field] = True
                with self.assertRaises(bridge.Refused):
                    bridge.check_links(doc)

    def test_original_failure_cannot_be_upgraded(self):
        doc = self.documents()
        doc["trial"]["original_smooth_status"] = "PASSED"
        with self.assertRaises(bridge.Refused):
            bridge.check_links(doc)

    def test_peer_receipt_splice_is_rejected(self):
        doc = self.documents()
        doc["edit"]["learning_receipt_sha256"] = "0" * 64
        with self.assertRaises(bridge.Refused):
            bridge.check_links(doc)

    def test_duplicate_nonfinite_and_overlarge_json_are_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e400}', b" " * 65537):
            with self.subTest(raw_length=len(raw)):
                with self.assertRaises(bridge.Refused):
                    bridge.parse_record(raw)

    def test_inputs_are_not_modified(self):
        original = copy.deepcopy(self.records)
        bridge.assess(self.records)
        self.assertEqual(self.records, original)

    def test_no_model_framework_imported(self):
        self.assertFalse(any(name.split(".")[0] in {"torch", "numpy", "transformers"}
                             for name in sys.modules))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    EvidenceBridgeTests.records = bridge.load_records(args.evidence_root)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceBridgeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()

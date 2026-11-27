import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_uniformization_admission_contract.admission_contract import (
    ADMISSION_SCHEMA,
    AdmissionContractError,
    PARENT_IDENTITY_FIELDS,
    require_current_hold,
    validate_future_admission,
)


def _digest(record):
    payload = dict(record)
    payload.pop("admission_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class AdmissionContractTests(unittest.TestCase):
    def setUp(self):
        self.parents = {
            field: format(index + 1, "064x")
            for index, field in enumerate(PARENT_IDENTITY_FIELDS)
        }
        self.record = {
            "schema": ADMISSION_SCHEMA,
            **self.parents,
            "runtime_profile_sha256": "1" * 64,
            "host_snapshot_sha256": "2" * 64,
            "ancestor_cgroup_snapshot_sha256": "3" * 64,
            "allocation_sha256": "4" * 64,
            "calendar_sha256": "5" * 64,
            "operator_roster_sha256": "6" * 64,
            "segment_roster_sha256": "7" * 64,
            "provider_author_identity_sha256": "8" * 64,
            "external_reviewer_identity_sha256": "9" * 64,
            "external_reviewer_custody_sha256": "a" * 64,
            "external_review_artifact_sha256": "b" * 64,
            "execution_request_sha256": "c" * 64,
            "execution_key": "synthetic-contract-fixture-only",
            "created_at_utc": "2026-11-14T00:00:00Z",
            "implementation_independence_passed": True,
            "external_reviewer_independence_certified": True,
            "historical_negative_and_unknown_preserved": True,
            "admitted": True,
            "largegrid_qualification": False,
            "production_adoption": False,
        }
        self.record["admission_sha256"] = _digest(self.record)

    def test_complete_synthetic_shape_is_identity_bound(self):
        result = validate_future_admission(self.record, self.parents)
        self.assertTrue(result.admitted)
        self.assertEqual(result.required_hash_count, 18)
        self.assertFalse(result.largegrid_qualification)
        self.assertFalse(result.production_adoption)
        self.assertEqual(result.n256_provider_calls, 0)

    def test_missing_resource_and_custody_fail_closed(self):
        for field in (
            "host_snapshot_sha256",
            "ancestor_cgroup_snapshot_sha256",
            "external_reviewer_custody_sha256",
        ):
            changed = dict(self.record)
            changed[field] = None
            changed["admission_sha256"] = _digest(changed)
            with self.subTest(field=field):
                with self.assertRaisesRegex(AdmissionContractError, "SHA-256"):
                    validate_future_admission(changed, self.parents)

    def test_self_review_and_changed_parent_fail_closed(self):
        changed = dict(self.record)
        changed["external_reviewer_identity_sha256"] = changed[
            "provider_author_identity_sha256"
        ]
        changed["admission_sha256"] = _digest(changed)
        with self.assertRaisesRegex(AdmissionContractError, "not separated"):
            validate_future_admission(changed, self.parents)
        changed = dict(self.record)
        changed["provider_source_sha256"] = "f" * 64
        changed["admission_sha256"] = _digest(changed)
        with self.assertRaisesRegex(AdmissionContractError, "parent identity"):
            validate_future_admission(changed, self.parents)

    def test_current_hold_requires_all_missing_values_to_remain_null(self):
        fields = {
            "runtime_profile_sha256",
            "host_snapshot_sha256",
            "ancestor_cgroup_snapshot_sha256",
            "allocation_sha256",
            "calendar_sha256",
            "operator_roster_sha256",
            "segment_roster_sha256",
            "provider_author_identity_sha256",
            "external_reviewer_identity_sha256",
            "external_reviewer_custody_sha256",
            "external_review_artifact_sha256",
        }
        request = {
            "provider_admitted": False,
            "numerical_execution_allowed": False,
            "execution_key": None,
            "external_reviewer_independence_certified": False,
            "missing_external_evidence": {field: None for field in fields},
        }
        self.assertTrue(require_current_hold(request))
        request["missing_external_evidence"]["host_snapshot_sha256"] = "d" * 64
        with self.assertRaisesRegex(AdmissionContractError, "silently populated"):
            require_current_hold(request)


if __name__ == "__main__":
    unittest.main()

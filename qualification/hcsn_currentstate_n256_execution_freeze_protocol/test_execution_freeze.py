import hashlib
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_execution_freeze_protocol.execution_freeze import (
    EXTERNAL_NAMES,
    PARENT_REQUEST_SHA256,
    PROVIDER_SOURCE_SHA256,
    RESOURCE_NAMES,
    SCHEMA,
    ExecutionFreezeError,
    require_current_hold,
    validate_future_execution_freeze,
)


def _digest(record):
    payload = dict(record)
    payload.pop("freeze_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ExecutionFreezeTests(unittest.TestCase):
    def setUp(self):
        originals = {}
        for index, name in enumerate(RESOURCE_NAMES, start=1):
            originals[name] = {
                "sha256": format(index, "064x"),
                "capture_session_id": "synthetic-session-only",
                "host_alias": "synthetic-host-only",
                "captured_at_utc": "2026-11-14T01:00:00Z",
            }
        originals["allocation"]["captured_at_utc"] = "2026-11-14T00:55:00Z"
        originals["calendar"]["captured_at_utc"] = "2026-11-14T00:50:00Z"
        self.record = {
            "schema": SCHEMA,
            "parent_roster_resolved_request_sha256": PARENT_REQUEST_SHA256,
            "provider_source_sha256": PROVIDER_SOURCE_SHA256,
            "capture_session_id": "synthetic-session-only",
            "host_alias": "synthetic-host-only",
            "resource_originals": originals,
            "provider_author_identity_sha256": "6" * 64,
            "external_reviewer_identity_sha256": "7" * 64,
            "external_reviewer_custody_sha256": "8" * 64,
            "external_review_artifact_sha256": "9" * 64,
            "execution_request_sha256": "a" * 64,
            "execution_key": "synthetic-key-only",
            "execution_not_before_utc": "2026-11-14T02:00:00Z",
            "execution_not_after_utc": "2026-11-14T03:00:00Z",
            "external_reviewer_independence_certified": True,
            "historical_negative_and_unknown_preserved": True,
            "largegrid_qualification": False,
            "production_adoption": False,
        }
        self.record["freeze_sha256"] = _digest(self.record)

    def test_complete_synthetic_shape_is_atomic_and_identity_bound(self):
        result = validate_future_execution_freeze(self.record)
        self.assertTrue(result.complete)
        self.assertEqual(result.resource_original_count, 5)
        self.assertEqual(result.external_original_count, 4)
        self.assertTrue(result.execution_key_bound)
        self.assertEqual(result.provider_calls, 0)
        self.assertFalse(result.largegrid_qualification)

    def test_mixed_session_host_and_late_capture_fail_closed(self):
        cases = (
            ("runtime_profile", "capture_session_id", "other-session"),
            ("host_snapshot", "host_alias", "other-host"),
            ("ancestor_cgroup_snapshot", "captured_at_utc", "2026-11-14T02:30:00Z"),
        )
        for resource, field, value in cases:
            changed = json.loads(json.dumps(self.record))
            changed["resource_originals"][resource][field] = value
            changed["freeze_sha256"] = _digest(changed)
            with self.subTest(resource=resource, field=field):
                with self.assertRaises(ExecutionFreezeError):
                    validate_future_execution_freeze(changed)

    def test_missing_original_and_self_review_fail_closed(self):
        changed = json.loads(json.dumps(self.record))
        changed["resource_originals"]["host_snapshot"]["sha256"] = None
        changed["freeze_sha256"] = _digest(changed)
        with self.assertRaisesRegex(ExecutionFreezeError, "SHA-256"):
            validate_future_execution_freeze(changed)
        changed = json.loads(json.dumps(self.record))
        changed["external_reviewer_identity_sha256"] = changed[
            "provider_author_identity_sha256"
        ]
        changed["freeze_sha256"] = _digest(changed)
        with self.assertRaisesRegex(ExecutionFreezeError, "not separated"):
            validate_future_execution_freeze(changed)

    def test_current_request_preserves_all_nulls_and_zero_work(self):
        request = json.loads(
            Path(
                "qualification/hcsn_currentstate_n256_execution_freeze_protocol/REQUEST.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(require_current_hold(request))
        self.assertEqual(sum(request["work_counts"].values()), 0)
        self.assertEqual(set(request["future_originals"]), {
            "runtime_profile_sha256",
            "host_snapshot_sha256",
            "ancestor_cgroup_snapshot_sha256",
            "allocation_sha256",
            "calendar_sha256",
            *EXTERNAL_NAMES,
            "execution_request_sha256",
        })


if __name__ == "__main__":
    unittest.main()

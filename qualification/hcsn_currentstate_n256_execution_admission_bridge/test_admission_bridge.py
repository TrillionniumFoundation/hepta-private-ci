import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_execution_admission_bridge import (
    admission_bridge,
)
from qualification.hcsn_currentstate_n256_provider_fullstate_bridge import bridge
from qualification.hcsn_currentstate_n256_uniformization_admission_contract import (
    admission_contract,
)
from qualification.hcsn_currentstate_n256_uniformization_provider_intent import provider


def _sha(label):
    return hashlib.sha256(label.encode()).hexdigest()


def _seal(record, field):
    payload = dict(record)
    payload.pop(field, None)
    record[field] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record


def _records():
    session = "capture-20261115-001"
    host = "authorized-host-a"
    resources = {
        name: {
            "sha256": _sha(name),
            "capture_session_id": session,
            "host_alias": host,
            "captured_at_utc": "2026-11-15T00:50:00Z",
        }
        for name in (
            "runtime_profile",
            "host_snapshot",
            "ancestor_cgroup_snapshot",
            "allocation",
            "calendar",
        )
    }
    external = {
        "provider_author_identity_sha256": _sha("provider-author"),
        "external_reviewer_identity_sha256": _sha("external-reviewer"),
        "external_reviewer_custody_sha256": _sha("external-custody"),
        "external_review_artifact_sha256": _sha("external-review-artifact"),
    }
    request_sha = _sha("execution-request")
    execution_key = "hcsn-n256-synthetic-fixture-key"
    freeze = {
        "schema": "hcsn-n256-uniformization-execution-freeze-v1",
        "parent_roster_resolved_request_sha256": "029402a1ac56d47c28939671ed083b1fec1780b4c60d3db4621a20fbd4a1eb13",
        "provider_source_sha256": bridge.PROVIDER_SOURCE_SHA256,
        "capture_session_id": session,
        "host_alias": host,
        "resource_originals": resources,
        **external,
        "execution_request_sha256": request_sha,
        "execution_key": execution_key,
        "execution_not_before_utc": "2026-11-15T01:10:00Z",
        "execution_not_after_utc": "2026-11-15T02:10:00Z",
        "external_reviewer_independence_certified": True,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
    }
    _seal(freeze, "freeze_sha256")
    admission = {
        "schema": admission_contract.ADMISSION_SCHEMA,
        **admission_bridge.EXPECTED_PARENT_IDENTITIES,
        "runtime_profile_sha256": resources["runtime_profile"]["sha256"],
        "host_snapshot_sha256": resources["host_snapshot"]["sha256"],
        "ancestor_cgroup_snapshot_sha256": resources["ancestor_cgroup_snapshot"]["sha256"],
        "allocation_sha256": resources["allocation"]["sha256"],
        "calendar_sha256": resources["calendar"]["sha256"],
        "operator_roster_sha256": bridge.OPERATOR_ROSTER_SHA256,
        "segment_roster_sha256": bridge.SEGMENT_ROSTER_SHA256,
        **external,
        "execution_request_sha256": request_sha,
        "execution_key": execution_key,
        "created_at_utc": "2026-11-15T01:00:00Z",
        "implementation_independence_passed": True,
        "external_reviewer_independence_certified": True,
        "historical_negative_and_unknown_preserved": True,
        "admitted": True,
        "largegrid_qualification": False,
        "production_adoption": False,
    }
    _seal(admission, "admission_sha256")
    identity = _sha("shared-coordinate-identity")
    manifest = {
        "input_bundle_sha256": bridge.INPUT_BUNDLE_SHA256,
        "roster_identity": bridge.ROSTER_IDENTITY,
        "operator_roster_sha256": bridge.OPERATOR_ROSTER_SHA256,
        "segment_roster_sha256": bridge.SEGMENT_ROSTER_SHA256,
        "provider_source_sha256": bridge.PROVIDER_SOURCE_SHA256,
        "serializer_source_sha256": bridge.SERIALIZER_SOURCE_SHA256,
        "comparator_source_sha256": bridge.COMPARATOR_SOURCE_SHA256,
        "execution_protocol_request_sha256": bridge.EXECUTION_PROTOCOL_REQUEST_SHA256,
        "coordinate_denominator": bridge.COORDINATE_DENOMINATOR,
        "frame_coordinates": bridge.FRAME_COORDINATES,
        "frame_count": bridge.FRAME_COUNT,
        "final_frame_coordinates": bridge.FINAL_FRAME_COORDINATES,
        "execution_freeze_sha256": freeze["freeze_sha256"],
        "provider_admission_sha256": admission["admission_sha256"],
        "certificate_set_sha256": _sha("certificate-set"),
        "streams": {
            name: {
                "coordinate_count": bridge.COORDINATE_DENOMINATOR,
                "frame_count": bridge.FRAME_COUNT,
                "maximum_buffer_bytes": bridge.FRAME_BYTES,
                "coordinate_identity_root_sha256": identity,
                "payload_root_sha256": _sha(name),
            }
            for name in bridge.STREAM_NAMES
        },
        "byte_exact_pairs": [
            {
                "name": name,
                "producer_sha256": _sha(name),
                "cold_loader_sha256": _sha(name),
                "bytes": 128,
            }
            for name in bridge.CHECKPOINT_PAIR_NAMES
        ],
        "signed_error_cancellation_used": False,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
    }
    return admission, freeze, manifest


class ExecutionAdmissionBridgeTests(unittest.TestCase):
    def test_v2_pre_and_postexecution_records_cross_bind(self):
        admission, freeze, manifest = _records()
        pre = admission_bridge.validate_preexecution_bundle(admission, freeze)
        self.assertTrue(pre.bundle_consistent)
        self.assertEqual(pre.resource_original_count, 5)
        self.assertEqual(pre.external_original_count, 4)
        self.assertEqual(pre.provider_calls, 0)
        post = admission_bridge.validate_postexecution_bundle(
            admission, freeze, manifest
        )
        self.assertTrue(post.manifest_bound)
        self.assertEqual(post.preexecution, pre)

    def test_individually_valid_execution_key_and_resource_mismatches_reject(self):
        admission, freeze, _manifest = _records()
        changed = dict(freeze)
        changed["execution_key"] = "other-synthetic-key"
        _seal(changed, "freeze_sha256")
        with self.assertRaisesRegex(admission_bridge.AdmissionBridgeError, "execution key"):
            admission_bridge.validate_preexecution_bundle(admission, changed)
        changed = dict(admission)
        changed["runtime_profile_sha256"] = _sha("other-runtime")
        _seal(changed, "admission_sha256")
        with self.assertRaisesRegex(admission_bridge.AdmissionBridgeError, "runtime_profile"):
            admission_bridge.validate_preexecution_bundle(changed, freeze)

    def test_late_admission_and_unbound_manifest_reject(self):
        admission, freeze, manifest = _records()
        late = dict(admission)
        late["created_at_utc"] = "2026-11-15T01:11:00Z"
        _seal(late, "admission_sha256")
        with self.assertRaisesRegex(admission_bridge.AdmissionBridgeError, "after execution start"):
            admission_bridge.validate_preexecution_bundle(late, freeze)
        changed = dict(manifest)
        changed["provider_admission_sha256"] = _sha("other-admission")
        with self.assertRaisesRegex(admission_bridge.AdmissionBridgeError, "provider admission"):
            admission_bridge.validate_postexecution_bundle(admission, freeze, changed)

    def test_legacy_provider_schema_is_preserved_not_relabelled(self):
        self.assertEqual(
            provider.ADMISSION_SCHEMA,
            admission_bridge.LEGACY_PROVIDER_ADMISSION_SCHEMA,
        )
        self.assertEqual(
            admission_contract.ADMISSION_SCHEMA,
            admission_bridge.CURRENT_ADMISSION_SCHEMA,
        )
        self.assertNotEqual(provider.ADMISSION_SCHEMA, admission_contract.ADMISSION_SCHEMA)


if __name__ == "__main__":
    unittest.main()

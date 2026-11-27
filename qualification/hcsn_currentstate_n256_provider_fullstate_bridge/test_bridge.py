import hashlib
import unittest

from qualification.hcsn_currentstate_n256_provider_fullstate_bridge import bridge


def _sha(label):
    return hashlib.sha256(label.encode()).hexdigest()


class ProviderFullstateBridgeTests(unittest.TestCase):
    def test_small_stream_is_bounded_deterministic_and_exact(self):
        frames = []
        records = [(f"{index:08d}/lane/warm/value", index / 8.0) for index in range(11)]
        summary = bridge._write_stream(records, frames.append, 11, 4)
        self.assertEqual([item.coordinate_count for item in frames], [4, 4, 3])
        self.assertEqual([item.start_coordinate for item in frames], [0, 4, 8])
        self.assertEqual(summary.coordinate_count, 11)
        self.assertEqual(summary.frame_count, 3)
        self.assertEqual(summary.maximum_buffer_bytes, 32)
        repeated = []
        self.assertEqual(summary, bridge._write_stream(records, repeated.append, 11, 4))
        self.assertEqual(frames, repeated)

    def test_short_long_duplicate_and_nonfinite_reject(self):
        cases = (
            ([("00000000/a", 1.0)], 2, "shorter"),
            ([("00000000/a", 1.0), ("00000001/b", 2.0)], 1, "exceeds"),
            ([("00000000/a", 1.0), ("00000000/a", 2.0)], 2, "ordinal"),
            ([("00000000/a", float("nan"))], 1, "non-finite"),
        )
        for records, total, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                bridge.BridgeError, message
            ):
                bridge._write_stream(records, lambda _frame: None, total, 2)

    def test_n256_frame_geometry_is_exact(self):
        self.assertEqual(
            (bridge.FRAME_COUNT - 1) * bridge.FRAME_COORDINATES
            + bridge.FINAL_FRAME_COORDINATES,
            bridge.COORDINATE_DENOMINATOR,
        )
        self.assertEqual(bridge.FRAME_BYTES, 524_288)

    def test_future_manifest_requires_three_identity_equal_streams_and_pairs(self):
        identity = _sha("shared-coordinate-identity")
        streams = {
            name: {
                "coordinate_count": bridge.COORDINATE_DENOMINATOR,
                "frame_count": bridge.FRAME_COUNT,
                "maximum_buffer_bytes": bridge.FRAME_BYTES,
                "coordinate_identity_root_sha256": identity,
                "payload_root_sha256": _sha(name),
            }
            for name in bridge.STREAM_NAMES
        }
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
            "execution_freeze_sha256": _sha("freeze"),
            "provider_admission_sha256": _sha("admission"),
            "certificate_set_sha256": _sha("certificates"),
            "streams": streams,
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
        self.assertTrue(bridge.validate_future_manifest(manifest))
        changed = {**manifest, "streams": {key: dict(value) for key, value in streams.items()}}
        changed["streams"]["oracle"]["coordinate_identity_root_sha256"] = _sha("other")
        with self.assertRaisesRegex(bridge.BridgeError, "share coordinate identity"):
            bridge.validate_future_manifest(changed)
        changed = {**manifest, "byte_exact_pairs": [dict(item) for item in manifest["byte_exact_pairs"]]}
        changed["byte_exact_pairs"][1]["cold_loader_sha256"] = _sha("different")
        with self.assertRaisesRegex(bridge.BridgeError, "not byte exact"):
            bridge.validate_future_manifest(changed)


if __name__ == "__main__":
    unittest.main()

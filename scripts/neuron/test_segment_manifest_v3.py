import copy
import unittest

import segment_manifest_v3 as manifest_v3


SHA256 = "b" * 64


def segment(kind: str, index: int = 0) -> dict:
    return {
        "segmentId": f"{kind}-{index}",
        "segmentKind": kind,
        "firstSequence": index,
        "lastSequence": index,
        "recordCount": 1,
        "logicalBytes": 128,
        "physicalBytes": 96,
        "contentSha256": SHA256,
        "formatVersion": 3,
        "immutable": True,
    }


def valid_manifest() -> dict:
    value = {
        "schema": manifest_v3.SCHEMA,
        "sourceFormats": ["HPTNGS02", "HPTNGI02", "HPTNGW02"],
        "targetFormats": ["HPTNGM03", "HPTNGS03", "HPTNGI03", "HPTNGW03"],
        "generation": 3,
        "predecessorManifestDigest": None,
        "productionActivation": False,
        "release": False,
        "identities": {
            "subjectScopeDigest": SHA256,
            "objectiveScopeDigest": SHA256,
            "bodyBundleDigest": SHA256,
            "modelSemanticDigest": SHA256,
            "configurationDigest": SHA256,
        },
        "segments": [
            segment(kind, index)
            for index, kind in enumerate(sorted(manifest_v3.SEGMENT_KINDS))
        ],
        "frontiers": {
            "operationCount": 7,
            "successCount": 3,
            "failureCount": 2,
            "reservationCount": 1,
            "dispatchCount": 4,
            "witnessPendingCount": 1,
            "checkpointAnchorDigest": SHA256,
            "witnessFrontierDigest": SHA256,
        },
        "retention": {
            flag: True for flag in manifest_v3.RETENTION_FLAGS
        },
        "migration": {
            "sourceGenerationStoreSha256": SHA256,
            "sourceRuntimeIndexSha256": SHA256,
            "sourceWitnessSha256": SHA256,
            "migrationBinarySha256": SHA256,
            "sourceBinarySha256": SHA256,
            "sourceV2ReadOnly": True,
            "deterministicReplayPassed": True,
            "historicalQueryParityPassed": True,
            "crashCuts": {
                cut: {"status": "passed", "logSha256": SHA256}
                for cut in manifest_v3.CRASH_CUTS
            },
        },
    }
    value["manifestDigest"] = manifest_v3.expected_digest(value)
    return value


class SegmentManifestV3Tests(unittest.TestCase):
    def test_complete_manifest_is_qualified_without_activation(self):
        result = manifest_v3.validate_manifest(valid_manifest())
        self.assertTrue(result["migrationQualified"])
        self.assertFalse(result["productionActivation"])
        self.assertFalse(result["release"])
        self.assertEqual(
            set(result["segmentKinds"]),
            manifest_v3.SEGMENT_KINDS,
        )

    def test_overlapping_segments_of_the_same_kind_are_rejected(self):
        value = valid_manifest()
        duplicate = copy.deepcopy(value["segments"][0])
        duplicate["segmentId"] = "overlap"
        value["segments"].append(duplicate)
        value["manifestDigest"] = manifest_v3.expected_digest(value)
        with self.assertRaisesRegex(manifest_v3.ManifestError, "overlapping"):
            manifest_v3.validate_manifest(value)

    def test_missing_failure_history_is_rejected(self):
        value = valid_manifest()
        value["retention"]["failureTombstonesRetained"] = False
        value["manifestDigest"] = manifest_v3.expected_digest(value)
        with self.assertRaisesRegex(
            manifest_v3.ManifestError,
            "failureTombstonesRetained",
        ):
            manifest_v3.validate_manifest(value)

    def test_incomplete_crash_cut_matrix_is_rejected(self):
        value = valid_manifest()
        del value["migration"]["crashCuts"]["manifest_parent_sync"]
        value["manifestDigest"] = manifest_v3.expected_digest(value)
        with self.assertRaisesRegex(manifest_v3.ManifestError, "crash cut set mismatch"):
            manifest_v3.validate_manifest(value)

    def test_manifest_digest_tampering_is_rejected(self):
        value = valid_manifest()
        value["frontiers"]["operationCount"] += 1
        with self.assertRaisesRegex(manifest_v3.ManifestError, "manifest digest mismatch"):
            manifest_v3.validate_manifest(value)

    def test_v2_source_must_remain_read_only(self):
        value = valid_manifest()
        value["migration"]["sourceV2ReadOnly"] = False
        value["manifestDigest"] = manifest_v3.expected_digest(value)
        with self.assertRaisesRegex(manifest_v3.ManifestError, "V2 source"):
            manifest_v3.validate_manifest(value)

    def test_source_format_is_not_reinterpreted(self):
        value = valid_manifest()
        value["sourceFormats"] = ["HPTNGS03", "HPTNGI03", "HPTNGW03"]
        value["manifestDigest"] = manifest_v3.expected_digest(value)
        with self.assertRaisesRegex(manifest_v3.ManifestError, "source format mismatch"):
            manifest_v3.validate_manifest(value)

    def test_validation_does_not_mutate_manifest(self):
        value = valid_manifest()
        before = copy.deepcopy(value)
        manifest_v3.validate_manifest(value)
        self.assertEqual(value, before)


if __name__ == "__main__":
    unittest.main()

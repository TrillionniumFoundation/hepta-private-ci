from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_readiness_projection.py"
spec = importlib.util.spec_from_file_location("channel_matrix_readiness_projection_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReadinessProjectionTests(unittest.TestCase):
    def manifest(self) -> dict[str, object]:
        sha = "a" * 40
        digest = "b" * 64
        return {
            "schema": "hepta.channel-matrix-readiness.v1",
            "candidate_key": "c" * 64,
            "source_head_sha": sha,
            "base_sha": "d" * 40,
            "deterministic_merge_sha": "e" * 40,
            "github_merge_sha": "f" * 40,
            "final_merge_sha": None,
            "workflow_sha": "1" * 40,
            "workflow_run_id": "123",
            "attempt_id": "1",
            "Cargo.lock_hash": digest,
            "test_set_hash": "2" * 64,
            "migration_hash": "3" * 64,
            "implementation_map_hash": "4" * 64,
            "documentation_hash": "5" * 64,
            "artifact_hashes": {"source-head/manifest.json": "6" * 64},
            "runner_image": {"source_head": "ubuntu", "deterministic_merge": "ubuntu"},
            "target_triple": {"source_head": "x86_64", "deterministic_merge": "x86_64"},
            "required_lanes": {"repository": [], "merge": [], "production": []},
            "lane_status": {
                "source_head": "passed",
                "deterministic_merge": "passed",
                "target_qualification": "not_proved",
                "independent_acceptance": "not_proved",
            },
            "repositoryQualified": True,
            "mergeReady": False,
            "productionQualified": False,
            "activation": False,
            "promotion": False,
            "release": False,
            "authorityGranted": False,
        }

    def test_bundle_is_atomic_and_non_mixable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "readiness.json"
            raw = module.canonical_bytes(self.manifest())
            manifest.write_bytes(raw)
            output = root / "status"
            row, read_raw = module.read_manifest(manifest)
            module.validate(row)
            digest = module.digest_bytes(read_raw)
            module.write_bundle(output, module.projections(row, digest), digest)
            self.assertEqual(set(path.name for path in output.iterdir()), set(module.OUTPUT_NAMES) | {"STATUS_BUNDLE.json"})
            status = json.loads((output / "MODULE_STATUS.json").read_text())
            self.assertTrue(status["repositoryQualified"])
            self.assertFalse(status["productionQualified"])
            self.assertFalse(status["authorityGranted"])
            bundle = json.loads((output / "STATUS_BUNDLE.json").read_text())
            self.assertTrue(bundle["atomicProjection"])
            self.assertEqual(bundle["readinessManifestSha256"], module.digest_bytes(raw))
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                module.write_bundle(output, module.projections(row, digest), digest)

    def test_missing_artifact_hashes_fail_closed(self) -> None:
        row = self.manifest()
        row["artifact_hashes"] = {}
        with self.assertRaisesRegex(ValueError, "artifact hashes"):
            module.validate(row)

    def test_repository_manifest_cannot_grant_release(self) -> None:
        row = self.manifest()
        row["release"] = True
        with self.assertRaisesRegex(ValueError, "release"):
            module.validate(row)


if __name__ == "__main__":
    unittest.main()

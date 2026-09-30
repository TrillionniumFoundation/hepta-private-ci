import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kernel_evidence_readiness as readiness


class KernelEvidenceReadinessTests(unittest.TestCase):
    def fixture(self, directory: Path) -> tuple[Path, str, str]:
        source = "a" * 40
        base = "b" * 40
        files = {
            "codex-rs/Cargo.lock": "lock\n",
            "codex-rs/hepta-evidence/migrations/0011.sql": "CREATE TABLE x(y);\n",
            "codex-rs/hepta-evidence/src/frontier_merge_tests.rs": "#[test] fn x() {}\n",
            "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs": "#[test] fn y() {}\n",
            "scripts/tests/test_kernel_evidence_readiness.py": "fixture\n",
            "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json": "{}\n",
            "docs/modules/kernel.evidence/TECHNICAL.md": "technical\n",
            "docs/lane-a-foundation/kernel.evidence/STORE_V1.md": "store\n",
            "qualification/kernel-evidence/STATUS_SOURCE.json": json.dumps(
                {"asOfCommit": "c" * 40}
            ),
        }
        for relative, content in files.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return directory, source, base

    def test_complete_local_receipts_still_do_not_self_activate_or_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, source, base = self.fixture(Path(temporary))
            receipts = root / "receipts"
            crashes = root / "crashes"
            receipts.mkdir()
            crashes.mkdir()
            qualification = {}
            for name in readiness.REQUIRED_QUALIFICATION_RECEIPTS:
                path = receipts / f"{name}.json"
                path.write_text(
                    json.dumps({"passed": True, "testedSha": source}), encoding="utf-8"
                )
                qualification[name] = path
            for scenario in readiness.REQUIRED_CRASH_SCENARIOS:
                (crashes / f"{scenario}.json").write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "module": "kernel.evidence",
                            "scenario": scenario,
                            "testedSha": source,
                            "targetTriple": "x86_64-unknown-linux-gnu",
                            "status": "passed",
                            "command": "qualified-scenario",
                            "exitCode": 0,
                            "startedAtUnixMs": 1,
                            "finishedAtUnixMs": 2,
                            "logSha256": "d" * 64,
                        }
                    ),
                    encoding="utf-8",
                )
            artifact = root / "artifact.json"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = readiness.build_manifest(
                root=root,
                source_head_sha=source,
                base_sha=base,
                deterministic_merge_sha="d" * 40,
                github_synthetic_merge_sha="e" * 40,
                workflow_sha="f" * 40,
                final_merge_sha=None,
                workflow_run_id="123",
                runner_image="ubuntu-24.04",
                target_triple="x86_64-unknown-linux-gnu",
                status_source=root / "qualification/kernel-evidence/STATUS_SOURCE.json",
                qualification_receipts=qualification,
                artifacts={"receipt": artifact},
                crash_receipts=crashes,
            )
            self.assertTrue(manifest["readiness"]["local_integrity_ready"])
            self.assertTrue(manifest["readiness"]["crash_matrix_ready"])
            self.assertFalse(manifest["readiness"]["production_activation"])
            self.assertFalse(manifest["readiness"]["release_approved"])
            self.assertEqual(manifest["status_identity"]["runtime_as_of_commit"], source)
            self.assertIn("real_merge_sha_not_requalified", manifest["blockers"])

    def test_missing_or_cross_candidate_receipts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, source, base = self.fixture(Path(temporary))
            bad = root / "bad.json"
            bad.write_text(
                json.dumps({"passed": True, "testedSha": "9" * 40}), encoding="utf-8"
            )
            manifest = readiness.build_manifest(
                root=root,
                source_head_sha=source,
                base_sha=base,
                deterministic_merge_sha=None,
                github_synthetic_merge_sha=None,
                workflow_sha="f" * 40,
                final_merge_sha=None,
                workflow_run_id="124",
                runner_image="ubuntu-24.04",
                target_triple="x86_64-unknown-linux-gnu",
                status_source=root / "qualification/kernel-evidence/STATUS_SOURCE.json",
                qualification_receipts={"exact_source": bad},
                artifacts={},
                crash_receipts=None,
            )
            self.assertFalse(manifest["readiness"]["local_integrity_ready"])
            self.assertFalse(manifest["readiness"]["exact_source_qualified"])
            self.assertFalse(manifest["readiness"]["crash_matrix_ready"])
            self.assertTrue(manifest["blockers"])


if __name__ == "__main__":
    unittest.main()

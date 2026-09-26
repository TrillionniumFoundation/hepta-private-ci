from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2.qualification_profile import build_host_profile


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class QualificationProfileTests(unittest.TestCase):
    def test_tail_percentiles_do_not_underreport_small_samples(self):
        from control_engineering_v2.qualification_profile import _percentiles
        result = _percentiles([1.0, 2.0, 100.0])
        self.assertEqual((result["medianMillis"], result["p95Millis"], result["p99Millis"]), (2.0, 100.0, 100.0))

    def test_fixture_profile_measures_owner_recovery_failure_and_sandbox_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            git(root, "init")
            git(root, "config", "user.email", "profile@example.invalid")
            git(root, "config", "user.name", "Qualification Profile")
            (root / "src").mkdir()
            (root / "src" / "a.txt").write_text("a\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "base")
            report = build_host_profile(root, iterations=2, sandbox_mode="fixture")
        self.assertEqual(report["schema"], "hepta.control-engineering-host-profile.v2")
        self.assertFalse(report["authorityGranted"])
        self.assertFalse(report["runtimeAuthority"])
        self.assertFalse(report["mergeAuthority"])
        self.assertFalse(report["releaseAuthority"])
        measurements = report["measurements"]
        self.assertEqual(measurements["storeOpen"]["count"], 2)
        for key in (
            "planMillis",
            "claimTransactionMillis",
            "heartbeatTransactionMillis",
            "expiryRecoveryMillis",
            "sqliteLockHandoffMillis",
            "auditVerificationMillis",
            "backupMillis",
            "restoreOpenAndVerifyMillis",
            "sandboxMillis",
        ):
            self.assertGreaterEqual(measurements[key], 0)
        self.assertTrue(measurements["backupSnapshotMatched"])
        self.assertTrue(measurements["diskFullRollback"]["observed"])
        self.assertEqual(measurements["sandboxState"], "fixture_tested")
        self.assertTrue(measurements["diskFullRollback"]["reopenSnapshotMatched"])
        for name, distribution in measurements["latencyMillis"].items():
            self.assertEqual(distribution["count"], 2, name)
            self.assertEqual(len(measurements["samplesMillis"][name]), 2)
        self.assertEqual(measurements["sandboxSequential"]["latencyMillis"]["count"], 2)
        self.assertGreater(measurements["sandboxSequential"]["executionsPerSecond"], 0)
        self.assertEqual(len(report["profileDigest"]), 64)


if __name__ == "__main__":
    unittest.main()

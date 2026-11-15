"""Synthetic qualification gates; no tests delete repository files."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from check_hia_retirement_gate import EXPECTED_CAPABILITIES, REQUIRED_PLATFORMS, check


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class RetirementGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.invalid"], check=True)
        self.requirements = [f"verified requirement {n}" for n in range(6)]
        self.data = {
            "schema": "codex.hia.migration.v1",
            "whole_codex_rewritten": True,
            "production_dispatch_migrated": True,
            "default_release_migrated": True,
            "workspace_qualified": True,
            "performance_qualified": True,
            "legacy_source_retired": False,
            "retirement": {"ready": True, "approved_paths": ["codex-rs/superseded.rs"],
                           "requirements": self.requirements},
            "capabilities": [{"id": key, "migration_status": "qualified_native",
                              "production_dispatch_migrated": True}
                             for key in sorted(EXPECTED_CAPABILITIES)],
            "baseline": {"codex_rs_cargo_manifest_count": 2},
            "rust_components": [
                {"manifest": f"codex-rs/{name}/Cargo.toml",
                 "migration_status": "qualified_native", "production_dispatch_migrated": True}
                for name in ("app", "core")
            ],
            "candidate_modules": [{"id": "test_owner", "retire_legacy": True,
                                    "production_dispatch_migrated": True}],
        }
        (self.repo / "hia").mkdir()
        (self.repo / "evidence").mkdir()
        self.migration = self.repo / "hia" / "migration.json"
        self.migration.write_text(json.dumps(self.data))
        for idx in range(6):
            (self.repo / "evidence" / f"gate{idx}.json").write_text(json.dumps({"id": idx}))
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.evidence = self.repo / "release-evidence.json"
        self.document = {
            "schema": "codex.hia.retirement-evidence.v1",
            "source_revision": git(self.repo, "rev-parse", "HEAD"),
            "source_tree": git(self.repo, "rev-parse", "HEAD^{tree}"),
            "platforms": sorted(REQUIRED_PLATFORMS),
            "requirements": [
                {"index": i, "requirement": self.requirements[i],
                 "status": "passed", "artifact": f"evidence/gate{i}.json",
                 "sha256": hashlib.sha256((self.repo / "evidence" / f"gate{i}.json").read_bytes()).hexdigest()}
                for i in range(6)
            ],
        }
        self.save()

    def save(self):
        self.migration.write_text(json.dumps(self.data))
        self.evidence.write_text(json.dumps(self.document))

    def report(self):
        return check(self.repo, self.migration, self.evidence)

    def test_full_bound_evidence_passes(self):
        self.assertTrue(self.report()["ready"])

    def test_current_unqualified_migration_is_not_releasable(self):
        self.data["whole_codex_rewritten"] = False
        self.data["capabilities"][0]["migration_status"] = "partial_opt_in_caller"
        self.data["rust_components"][0]["production_dispatch_migrated"] = False
        self.data["retirement"]["ready"] = False
        self.save()
        report = self.report()
        self.assertFalse(report["ready"])
        self.assertGreaterEqual(len(report["problems"]), 4)

    def test_premature_retirement_flag_fails(self):
        self.data["legacy_source_retired"] = True
        self.save()
        self.assertFalse(self.report()["ready"])

    def test_missing_or_deduplicated_inventory_fails(self):
        self.data["capabilities"] = self.data["capabilities"][:-1]
        self.data["rust_components"].append(copy.deepcopy(self.data["rust_components"][0]))
        self.save()
        self.assertFalse(self.report()["ready"])

    def test_missing_platform_or_attestation_fails(self):
        self.document["platforms"].remove("windows-aarch64-msvc")
        self.document["requirements"] = self.document["requirements"][:-1]
        self.save()
        self.assertFalse(self.report()["ready"])

    def test_artifact_mutation_fails(self):
        (self.repo / "evidence" / "gate3.json").write_text("tampered")
        self.assertFalse(self.report()["ready"])

    def test_head_tree_binding_fails(self):
        self.document["source_tree"] = "a" * 40
        self.save()
        self.assertFalse(self.report()["ready"])

    def test_untracked_evidence_absence_fails(self):
        self.evidence.unlink()
        self.assertFalse(self.report()["ready"])

    def test_duplicate_json_keys_fail(self):
        self.evidence.write_text('{"schema":"x","schema":"y"}')
        self.assertFalse(self.report()["ready"])

    def test_symbolic_evidence_is_rejected(self):
        original = self.repo / "evidence" / "gate2.json"
        original.unlink()
        original.symlink_to("gate1.json")
        self.assertFalse(self.report()["ready"])


if __name__ == "__main__":
    unittest.main()

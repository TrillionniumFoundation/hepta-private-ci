"""Real CLI subprocess, exact-source pins, no false approvals or overwrites."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from amcn_core import canonical, digest
from amcn_quarantine_cli import LINEAGE_SCHEMA, SOURCE_SCHEMA
from amcn_quarantine_ledger import ZERO_SHA
import test_amcn_revocation as fixture


class OwnedSourceQuarantineCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.artifacts, self.sources = fixture.ParameterLineageTests().network()
        self.lineage = self.home / "artifacts.json"
        self.frontier = self.home / "current-source.json"
        self.journal = self.home / "journal"
        self.script = Path(__file__).with_name("amcn_quarantine_cli.py")
        self._material()

    def _material(self):
        bundle = {
            "schema": LINEAGE_SCHEMA, "scope": "tenant:lab", "generation": "g1",
            "artifacts": [asdict(a) for a in self.artifacts],
        }
        source = {
            "schema": SOURCE_SCHEMA, "scope": "tenant:lab", "generation": "g1",
            "sources": [asdict(s) for s in self.sources],
        }
        self.lineage.write_bytes(canonical(bundle) + b"\n")
        self.frontier.write_bytes(canonical(source) + b"\n")

    def invoke(self, action, head, *, candidate=None, pin_override=None, output=None):
        target = output or self.home / (action + "-" + str(len(list(self.home.glob("*.receipt")))) + ".receipt")
        args = [sys.executable, str(self.script), action,
                "--journal", str(self.journal),
                "--lineage", str(self.lineage),
                "--lineage-sha256", sha256(self.lineage.read_bytes()).hexdigest(),
                "--current-sources", str(self.frontier),
                "--current-sources-sha256", sha256(self.frontier.read_bytes()).hexdigest(),
                "--source-frontier-sha256", pin_override or fixture.pinned(self.sources),
                "--expected-journal-head-sha256", head,
                "--output", str(target)]
        if candidate is not None:
            args.extend(["--artifact-id", candidate])
        env = __import__("os").environ.copy()
        import_path = str(self.script.parent)
        env["PYTHONPATH"] = import_path + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=15)
        return result, target

    def test_durable_cli_bootstrap_revoke_and_refuse(self):
        bootstrap, out = self.invoke("bootstrap", ZERO_SHA)
        self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
        head = json.loads(out.read_text())["metrics"]["journal_head_sha256"]
        valid, _ = self.invoke("preflight", head, candidate=self.artifacts[2].artifact_id)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        from dataclasses import replace
        self.sources[0] = replace(self.sources[0], revoked=True)
        self._material()
        stale, target = self.invoke("preflight", head, candidate=self.artifacts[0].artifact_id)
        self.assertNotEqual(stale.returncode, 0)
        self.assertFalse(target.exists())
        updated, output = self.invoke("update", head)
        self.assertEqual(updated.returncode, 0, updated.stderr)
        latest = json.loads(output.read_text())["metrics"]["journal_head_sha256"]
        refused, _ = self.invoke("preflight", latest, candidate=self.artifacts[0].artifact_id)
        self.assertNotEqual(refused.returncode, 0)
        allowed, valid_path = self.invoke("preflight", latest, candidate=self.artifacts[2].artifact_id)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertFalse(json.loads(valid_path.read_text())["production_accepted"])

    def test_partial_commit_can_only_be_recovered_with_existing_head_and_fresh_pin(self):
        from amcn_quarantine_ledger import ShadowQuarantineLedger
        first_result, first_path = self.invoke("bootstrap", ZERO_SHA)
        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        head = json.loads(first_path.read_text())["metrics"]["journal_head_sha256"]
        interrupted = ShadowQuarantineLedger(self.journal).apply(
            self.artifacts, self.sources,
            scope="tenant:lab", generation="g1",
            expected_previous_sha256=head,
            externally_pinned_frontier_sha256=fixture.pinned(self.sources),
            crash_at="prepared",
        )
        self.assertFalse(interrupted["metrics"]["recorded"])
        failed, _ = self.invoke("preflight", head, candidate=self.artifacts[2].artifact_id)
        self.assertNotEqual(failed.returncode, 0)
        restored, new_output = self.invoke("recover", head)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        latest = json.loads(new_output.read_text())["metrics"]["journal_head_sha256"]
        allowed, _ = self.invoke("preflight", latest, candidate=self.artifacts[2].artifact_id)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_tampered_rehashed_lineage_does_not_pass_real_artifact_constructor(self):
        initial, output = self.invoke("bootstrap", ZERO_SHA)
        self.assertEqual(initial.returncode, 0)
        head = json.loads(output.read_text())["metrics"]["journal_head_sha256"]
        fake = json.loads(self.lineage.read_text())
        fake["artifacts"][0]["manifest_sha256"] = digest("self-rehashed-but-invalid")
        self.lineage.write_bytes(canonical(fake) + b"\n")
        probe, target = self.invoke("preflight", head, candidate=self.artifacts[2].artifact_id)
        self.assertNotEqual(probe.returncode, 0)
        self.assertFalse(target.exists())

    def test_mismatched_source_sha_and_file_reuse_do_not_mutate_owner(self):
        broken, _ = self.invoke("bootstrap", ZERO_SHA,
                                pin_override=digest("forged"))
        self.assertNotEqual(broken.returncode, 0)
        self.assertFalse(list(self.journal.glob("events/*.json")))
        original, output = self.invoke("bootstrap", ZERO_SHA)
        self.assertEqual(original.returncode, 0)
        head = json.loads(output.read_text())["metrics"]["journal_head_sha256"]
        reused, _ = self.invoke("update", head, output=output)
        self.assertNotEqual(reused.returncode, 0)
        self.assertEqual(len(list(self.journal.glob("events/*.json"))), 1)


if __name__ == "__main__":
    unittest.main()

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2 import readiness_manifest
import test_readiness_manifest as fixture_module


class ReadinessRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Readiness test")
        self.git("config", "user.email", "readiness@example.invalid")
        files = {
            "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql": "schema",
            "tools/hepta-engineering-control/control_engineering_v2/control_plane.py": "owner",
            "tools/hepta-engineering-control/control_engineering_v2/qualification_profile.py": "profile",
            "docs/modules/control.engineering/IMPLEMENTATION_MAP.json": "{}",
            "docs/modules/control.engineering/TRACEABILITY.json": "{}",
            "docs/modules/control.engineering/COMPONENTS.json": "{}",
            "docs/modules/control.engineering/TECHNICAL.md": "technical guide",
        }
        for relative, value in files.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value, encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.tree = self.git("rev-parse", "HEAD^{tree}")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def test_repository_evidence_is_bound_to_committed_objects(self):
        before = readiness_manifest.capture_repository_evidence(
            self.root, source_tree_sha1=self.tree
        )
        guide = self.root / "docs/modules/control.engineering/TECHNICAL.md"
        guide.write_text("uncommitted guide", encoding="utf-8")
        self.assertEqual(before, readiness_manifest.capture_repository_evidence(
            self.root, source_tree_sha1=self.tree
        ))
        self.git("add", ".")
        self.git("commit", "-qm", "changed guide")
        with self.assertRaisesRegex(EngineeringError, "readiness_source_tree_checkout_mismatch"):
            readiness_manifest.capture_repository_evidence(self.root, source_tree_sha1=self.tree)

    def test_cli_retains_non_authoritative_manifest_from_real_repository(self):
        fixture = fixture_module.CanonicalReadinessManifestTests()
        pair = fixture.pair()
        pair["sourceTree"] = self.tree
        pair.pop("pairDigest")
        pair["pairDigest"] = fixture_module.digest(pair)
        arguments = []
        for name, value in (
            ("pair", pair), ("jobs", fixture.jobs()),
            ("runner-profile", fixture.runner()), ("artifact-hashes", fixture.artifacts()),
        ):
            path = self.root / (name + ".json")
            path.write_text(json.dumps(value), encoding="utf-8")
            arguments.extend(("--" + name, str(path)))
        destination = self.root / "manifest.json"
        arguments.extend(("--repository", str(self.root), "--output", str(destination),
                          "--workflow-sha", fixture.workflow_sha, "--now-ns", str(fixture.now)))
        for name in fixture.required_jobs:
            arguments.extend(("--required-job", name))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(readiness_manifest.main(arguments), 0)
        manifest = json.loads(destination.read_text(encoding="utf-8"))
        self.assertTrue(manifest["internalEvidenceReady"])
        self.assertFalse(manifest["mergeReady"])
        self.assertFalse(manifest["productionQualified"])
        self.assertFalse(manifest["runtimeAuthority"])
        readiness_manifest.verify_canonical_readiness_manifest(
            manifest, now_ns=fixture.now, expected_required_job_names=fixture.required_jobs
        )

    def test_oversized_evidence_file_is_rejected_before_json_decode(self):
        path = self.root / "oversized.json"
        with path.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(EngineeringError, "readiness_document_budget"):
            readiness_manifest._load(path)

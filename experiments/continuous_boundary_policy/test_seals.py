"""Real Git publication and inherited-source mutation rejection checks."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from . import study
from .common import canonical, sha

REMOTE = "refs/remotes/origin/research/continuous-boundary-flow-20261028"


class PublicationSealTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hepta-policy-seal-")
        self.addCleanup(self.directory.cleanup)
        self.repository = Path(self.directory.name)
        self.package = self.repository / "experiments/continuous_boundary_policy"
        self.prior = self.repository / "experiments/continuous_boundary_flow"
        self.package.mkdir(parents=True)
        self.prior.mkdir()
        self.git("init", "--initial-branch=fixture")
        self.git("config", "user.name", "Research fixture")
        self.git("config", "user.email", "research-fixture@example.invalid")
        self.actor = self.package / "actor.py"
        self.actor.write_text("VALUE = 1\n")
        self.inherited = self.prior / "math.py"
        self.inherited.write_text("FROZEN_VALUE = 1\n")
        relative = str(self.inherited.relative_to(self.repository))
        old_binary = self.prior / "native.fixture.bin"
        old_binary.write_bytes(b"original native fixture\n")
        old_receipt_path = self.prior / "preflight/BUILD_RECEIPT.json"
        old_receipt_path.parent.mkdir()
        old_receipt_path.write_bytes(
            canonical(
                {
                    "binary_sha256": sha(old_binary.read_bytes()),
                    "source_sha256": {relative: sha(self.inherited.read_bytes())},
                }
            )
            + b"\n"
        )
        (self.prior / "SOURCE_SEAL.json").write_bytes(
            canonical(
                {
                    "source_files": {relative: sha(self.inherited.read_bytes())},
                    "native_binary_sha256": sha(old_binary.read_bytes()),
                    "native_build_receipt_path": str(
                        old_receipt_path.relative_to(self.repository)
                    ),
                    "native_build_receipt_sha256": sha(old_receipt_path.read_bytes()),
                }
            )
            + b"\n"
        )
        native = self.package / "native"
        preflight = native / "preflight"
        preflight.mkdir(parents=True)
        source_hashes = {}
        for name in ("score_host.rs", "protocol.rs", "decision.rs"):
            source = native / name
            source.write_text("// Local source-binding fixture only.\n")
            source_hashes[str(source.relative_to(self.repository))] = sha(
                source.read_bytes()
            )
        score_binary = native / "score.fixture.bin"
        score_binary.write_bytes(b"score-only native fixture\n")
        manifest = canonical(source_hashes)
        (preflight / "SOURCE_MANIFEST.json").write_bytes(manifest)
        (preflight / "BUILD_RECEIPT.json").write_bytes(
            canonical(
                {
                    "binary_sha256": sha(score_binary.read_bytes()),
                    "source_manifest_digest": sha(manifest),
                    "source_sha256": source_hashes,
                }
            )
            + b"\n"
        )
        self.repo_patch = patch.object(study, "REPOSITORY", self.repository)
        self.package_patch = patch.object(study, "PACKAGE", self.package)
        self.repo_patch.start()
        self.package_patch.start()
        self.addCleanup(self.repo_patch.stop)
        self.addCleanup(self.package_patch.stop)

    def git(self, *args):
        return (
            subprocess.check_output(
                ["git", *args], cwd=self.repository, stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def commit(self, label):
        self.git("add", ".")
        self.git("commit", "-m", label)
        return self.git("rev-parse", "HEAD")

    def test_exact_published_artifact_and_ancestor_are_accepted_but_changed_bytes_reject(
        self,
    ):
        artifact = self.package / "selection.json"
        original = canonical({"selected": "candidate.one"}) + b"\n"
        artifact.write_bytes(original)
        published = self.commit("published source")
        self.actor.write_text("VALUE = 2\n")
        head = self.commit("later published source")
        self.git("update-ref", REMOTE, head)
        relative = str(artifact.relative_to(self.repository))
        study.verify_publication(published, relative, original)
        with self.assertRaisesRegex(ValueError, "does not match"):
            study.verify_publication(
                published, relative, original.replace(b"one", b"two")
            )
        for invalid in ("x" * 40, published.upper(), published[:12], None):
            with self.assertRaisesRegex(ValueError, "full published Git"):
                study.verify_publication(invalid, relative, original)

    def test_local_unpublished_descendant_rejects_until_remote_ref_contains_it(self):
        artifact = self.package / "selection.json"
        artifact.write_bytes(canonical({"selected": 0}) + b"\n")
        published = self.commit("published selection")
        self.git("update-ref", REMOTE, published)
        changed = canonical({"selected": 1}) + b"\n"
        artifact.write_bytes(changed)
        unpublished = self.commit("local unpublished selection")
        relative = str(artifact.relative_to(self.repository))
        with self.assertRaises(subprocess.CalledProcessError):
            study.verify_publication(unpublished, relative, changed)
        self.git("update-ref", REMOTE, unpublished)
        study.verify_publication(unpublished, relative, changed)

    def test_inherited_source_drift_cannot_be_silently_resealed(self):
        study.freeze_source()
        seal_path = self.package / "SOURCE_SEAL.json"
        prior_seal = seal_path.read_bytes()
        frozen = json.loads(prior_seal)
        relative = str(self.inherited.relative_to(self.repository))
        self.assertEqual(
            frozen["source_files"][relative], sha(self.inherited.read_bytes())
        )
        self.inherited.write_text("FROZEN_VALUE = 2\n")
        with self.assertRaisesRegex(
            ValueError, "Prior frozen scientific source changed"
        ):
            study.freeze_source()
        self.assertEqual(seal_path.read_bytes(), prior_seal)


if __name__ == "__main__":
    unittest.main()

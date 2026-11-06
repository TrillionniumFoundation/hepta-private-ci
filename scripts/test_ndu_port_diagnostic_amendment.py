"""Bind reviewed SDK diagnostics; exercise real Git and unchanged source checks."""

import copy
import json
import shutil
import unittest

import ndu_port_candidate_common as common
from ndu_port_integration_test_support import git
import test_ndu_port_dependency_amendment as dependency_fixture


class DiagnosticAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = dependency_fixture.DependencyAmendmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.path = self.root / common.DIAGNOSTIC_AMENDMENT
        self.amendment = json.loads(self.path.read_bytes())
        self.calls = 0

    def verify(self, record=None, artifact=None):
        self.calls += 1
        runner = common.Recorder(
            self.root,
            self.fixture.base / f"diagnostic-evidence-{self.calls}",
            "diagnostic-source-test",
        )
        return common.verify_integrated_source(
            runner, self.fixture.recipe, record, artifact
        )

    def test_exact_two_successors_preserve_all_parents_locks_and_snapshot_paths(self):
        parents = common.describe(self.root, self.amendment["parents"])
        locks = common.describe(self.root, common.LOCKS)
        manifest, binding, tree = self.verify()
        self.assertEqual(len(manifest["files"]), 320)
        self.assertEqual(set(self.amendment["changes"]), common.DIAGNOSTIC_SOURCES)
        self.assertEqual(
            binding["diagnostic_amendment"]["sha256"],
            common.DIAGNOSTIC_AMENDMENT_SHA256,
        )
        for name, change in self.amendment["changes"].items():
            self.assertEqual(manifest["files"][name], change["after"])
        self.assertEqual(common.describe(self.root, self.amendment["parents"]), parents)
        self.assertEqual(common.describe(self.root, common.LOCKS), locks)
        self.assertEqual(
            tree, git(self.root, "rev-parse", "HEAD^{tree}").decode().strip()
        )
        self.assertEqual(git(self.root, "status", "--porcelain"), b"")

    def test_missing_or_self_resealed_amendment_cannot_authorize_current_sources(self):
        raw = self.path.read_bytes()
        self.path.unlink()
        with self.assertRaisesRegex(
            ValueError, r"Expected a regular file: .*SOURCE_AMENDMENT\.v7\.4\.json"
        ):
            self.verify()
        for change in ("promotion_allowed", "after", "path", "source"):
            with self.subTest(change=change):
                altered = copy.deepcopy(self.amendment)
                name = sorted(common.DIAGNOSTIC_SOURCES)[0]
                if change == "promotion_allowed":
                    altered[change] = True
                elif change == "after":
                    altered["changes"][name]["after"]["sha256"] = "0" * 64
                elif change == "path":
                    altered["changes"]["codex-rs/core/src/lib.rs"] = altered[
                        "changes"
                    ].pop(name)
                else:
                    altered["reviewed_source"]["commit"] = "0" * 40
                self.path.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, "fixed review seal"):
                    self.verify()
        self.path.write_bytes(raw)

    def test_each_successor_bytes_mode_and_symlink_are_exact(self):
        for name in sorted(common.DIAGNOSTIC_SOURCES):
            with self.subTest(path=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"\n")
                with self.assertRaisesRegex(ValueError, "reviewed successor"):
                    self.verify()
                path.write_bytes(raw)
                path.chmod(0o755)
                with self.assertRaisesRegex(ValueError, "reviewed successor"):
                    self.verify()
                path.chmod(0o644)
                path.unlink()
                path.symlink_to(self.root / "codex-rs/Cargo.toml")
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    self.verify()
                path.unlink()
                path.write_bytes(raw)

    def test_historical_parents_locks_and_proofs_cannot_drift(self):
        for name in (
            *self.amendment["parents"],
            *common.LOCKS,
            *self.amendment["proofs"],
        ):
            with self.subTest(path=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"\n")
                with self.assertRaises(ValueError):
                    self.verify()
                path.write_bytes(raw)

    def test_other_original_source_remains_exact(self):
        path = self.root / "codex-rs/hepta-matrix-sdk/src/config.rs"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "Integrated source or lock bytes"):
            self.verify()

    def test_new_record_and_proof_must_be_committed_with_the_same_git_mode(self):
        proof = sorted(self.amendment["proofs"])[0]
        git(self.root, "update-index", "--chmod=+x", proof)
        with self.assertRaisesRegex(ValueError, "Integrated index"):
            self.verify()
        git(self.root, "update-index", "--chmod=-x", proof)
        git(self.root, "rm", "--cached", common.DIAGNOSTIC_AMENDMENT)
        git(self.root, "commit", "-qm", "Remove only the committed diagnostic seal")
        with self.assertRaisesRegex(ValueError, "missing from the committed HEAD"):
            self.verify()

    def test_exported_amendment_and_resealed_result_are_not_substitutable(self):
        manifest, binding, tree = self.verify()
        artifact = self.fixture.base / "diagnostic-artifact"
        artifact.mkdir()
        transports = (
            (common.INTEGRATION, "integration.json"),
            (common.SOURCE_AMENDMENT, "source-amendment.json"),
            (common.DEPENDENCY_AMENDMENT, "dependency-amendment.json"),
            (common.BUILD_AMENDMENT, "build-amendment.json"),
            (common.DIAGNOSTIC_AMENDMENT, "diagnostic-amendment.json"),
            (common.LOCK_AMENDMENT, "lock-amendment.json"),
        )
        for source, name in transports:
            shutil.copyfile(self.root / source, artifact / name)
        (artifact / "candidate.patch").write_bytes(b"")
        record = {
            "source_mode": "integrated",
            "integration": binding,
            "source_tree": tree,
            "files": manifest["files"],
            "policy_inputs": manifest["policy_inputs"],
            "changed_paths": [],
            "artifacts": common.describe(
                artifact, ("candidate.patch", *(n for _, n in transports))
            ),
        }
        self.verify(record, artifact)
        exported = artifact / "diagnostic-amendment.json"
        raw = exported.read_bytes()
        exported.write_bytes(raw + b"\n")
        with self.assertRaisesRegex(ValueError, "transport changed"):
            self.verify(record, artifact)
        altered = copy.deepcopy(record)
        altered["artifacts"].update(common.describe(artifact, (exported.name,)))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(altered, artifact)
        exported.write_bytes(raw)
        del record["integration"]["diagnostic_amendment"]
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(record, artifact)


if __name__ == "__main__":
    unittest.main()

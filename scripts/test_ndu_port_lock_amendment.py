"""Verify the fixed native lock successor with real Git and preserved old seals."""

import copy
import gzip
import json
import shutil
import unittest

import ndu_port_candidate_common as common
from ndu_port_integration_test_support import git
import test_ndu_port_dependency_amendment as dependency_fixture


class LockAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = dependency_fixture.DependencyAmendmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.path = self.root / common.LOCK_AMENDMENT
        self.amendment = json.loads(self.path.read_bytes())
        self.calls = 0

    def verify(self, record=None, artifact=None):
        self.calls += 1
        runner = common.Recorder(
            self.root,
            self.fixture.base / f"lock-evidence-{self.calls}",
            "fixed-native-lock-source-test",
        )
        return common.verify_integrated_source(
            runner, self.fixture.recipe, record, artifact
        )

    def reverse_native_patch(self):
        name = next(
            n for n in self.amendment["proofs"] if n.endswith("proposal.patch.gz")
        )
        patch = self.fixture.base / "original-native.patch"
        patch.write_bytes(gzip.decompress((self.root / name).read_bytes()))
        git(self.root, "apply", "--reverse", str(patch))

    def test_exact_native_pair_preserves_every_historical_parent_and_other_path(self):
        parents = common.describe(self.root, self.amendment["parents"])
        manifest, binding, tree = self.verify()
        self.assertEqual(len(manifest["files"]), 320)
        self.assertEqual(set(self.amendment["changes"]), set(common.LOCKS))
        self.assertEqual(
            binding["lock_amendment"]["sha256"], common.LOCK_AMENDMENT_SHA256
        )
        for name, change in self.amendment["changes"].items():
            self.assertEqual(manifest["files"][name], change["after"])
        self.assertEqual(common.describe(self.root, self.amendment["parents"]), parents)
        self.assertEqual(
            tree, git(self.root, "rev-parse", "HEAD^{tree}").decode().strip()
        )
        self.assertEqual(git(self.root, "status", "--porcelain"), b"")

    def test_missing_record_rejects_successor_but_exact_historical_pair_still_works(
        self,
    ):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "source or lock identity"):
            self.verify()
        self.reverse_native_patch()
        git(self.root, "add", "--update")
        git(self.root, "commit", "-qm", "Controlled historical fixture only")
        manifest, binding, _tree = self.verify()
        self.assertNotIn("lock_amendment", binding)
        for name, change in self.amendment["changes"].items():
            self.assertEqual(manifest["files"][name], change["before"])

    def test_self_resealed_record_cannot_change_paths_outputs_or_native_authority(self):
        for field in ("promotion", "path", "after", "run", "before"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.amendment)
                if field == "promotion":
                    changed["promotion_allowed"] = True
                elif field == "path":
                    changed["changes"]["codex-rs/Cargo.toml"] = changed["changes"].pop(
                        common.LOCKS[0]
                    )
                elif field == "run":
                    changed["native_proposal"]["run_id"] += 1
                else:
                    changed["changes"][common.LOCKS[0]][field]["sha256"] = "0" * 64
                self.path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "fixed review seal"):
                    self.verify()

    def test_each_lock_bytes_mode_symlink_and_partial_rollback_fail(self):
        current = {name: (self.root / name).read_bytes() for name in common.LOCKS}
        self.reverse_native_patch()
        previous = {name: (self.root / name).read_bytes() for name in common.LOCKS}
        for name, raw in current.items():
            (self.root / name).write_bytes(raw)
        for name in common.LOCKS:
            with self.subTest(path=name):
                path = self.root / name
                for raw in (current[name] + b"\n", previous[name]):
                    path.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, "source or lock identity"):
                        self.verify()
                path.write_bytes(current[name])
                path.chmod(0o755)
                with self.assertRaisesRegex(ValueError, "source or lock identity"):
                    self.verify()
                path.chmod(0o644)
                path.unlink()
                path.symlink_to(self.root / "codex-rs/Cargo.toml")
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    self.verify()
                path.unlink()
                path.write_bytes(current[name])

    def test_every_parent_and_native_proof_stays_exact(self):
        for name in (*self.amendment["parents"], *self.amendment["proofs"]):
            with self.subTest(path=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"\n")
                with self.assertRaises(ValueError):
                    self.verify()
                path.write_bytes(raw)

    def test_historical_input_mapping_cannot_silently_replace_another_predecessor(self):
        original = {n: c["before"] for n, c in self.amendment["changes"].items()}
        self.assertEqual(
            common.effective_lock_inputs(self.root, original),
            {n: c["after"] for n, c in self.amendment["changes"].items()},
        )
        for name in common.LOCKS:
            changed = copy.deepcopy(original)
            changed[name]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "fixed predecessors"):
                common.effective_lock_inputs(self.root, changed)

    def test_artifact_binding_and_resealed_transport_cannot_replace_new_record(self):
        manifest, binding, tree = self.verify()
        artifact = self.fixture.base / "lock-artifact"
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
        exported = artifact / "lock-amendment.json"
        raw = exported.read_bytes()
        exported.write_bytes(raw + b"\n")
        with self.assertRaisesRegex(ValueError, "transport changed"):
            self.verify(record, artifact)
        record["artifacts"].update(common.describe(artifact, (exported.name,)))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(record, artifact)

    def test_committed_record_and_index_modes_cannot_drift(self):
        git(self.root, "update-index", "--chmod=+x", common.LOCK_AMENDMENT)
        with self.assertRaisesRegex(ValueError, "Integrated index"):
            self.verify()
        git(self.root, "update-index", "--chmod=-x", common.LOCK_AMENDMENT)
        git(self.root, "rm", "--cached", common.LOCK_AMENDMENT)
        git(self.root, "commit", "-qm", "Remove only the committed new seal in fixture")
        with self.assertRaisesRegex(ValueError, "missing from the committed HEAD"):
            self.verify()


if __name__ == "__main__":
    unittest.main()

"""Real Git source/transport checks; no SDK, Cargo or Windows qualification."""

import copy
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

import ndu_port_candidate_common as common
from ndu_port_integration_test_support import git
import test_ndu_port_dependency_amendment as historical_fixture


ROOT = Path(__file__).resolve().parents[1]


class SdkAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = historical_fixture.DependencyAmendmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.path = self.root / common.SDK_AMENDMENT
        self.amendment = json.loads((ROOT / common.SDK_AMENDMENT).read_bytes())
        names = {
            common.SDK_AMENDMENT,
            *self.amendment["changes"],
            *self.amendment["proofs"],
        }
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        historical_fixture.restore_pre_asm_source(
            self.root, self.fixture.base, set(common.LOCKS) & common.SDK_EXISTING_INPUTS
        )
        git(self.root, "add", "--force", "--", *sorted(names))
        git(self.root, "commit", "-qm", "Complete SDK fixture; no native qualification")
        self.calls = 0

    def runner(self):
        self.calls += 1
        return common.Recorder(
            self.root,
            self.fixture.base / f"sdk-evidence-{self.calls}",
            "sdk-source-guard-test",
        )

    def verify(self, record=None, artifact=None):
        return common.verify_integrated_source(
            self.runner(), self.fixture.recipe, record, artifact
        )

    def original_patch(self):
        name = next(
            n
            for n in self.amendment["proofs"]
            if n.endswith("original-native.patch.gz")
        )
        path = self.fixture.base / "sdk-native.patch"
        path.write_bytes(gzip.decompress((self.root / name).read_bytes()))
        return path

    def export(self):
        manifest, binding, tree = self.verify()
        artifact = self.fixture.base / "sdk-artifact"
        artifact.mkdir()
        common.copy_files(self.root, artifact / "files", manifest["files"])
        transports = (
            (common.INTEGRATION, "integration.json"),
            (common.SOURCE_AMENDMENT, "source-amendment.json"),
            (common.DEPENDENCY_AMENDMENT, "dependency-amendment.json"),
            (common.BUILD_AMENDMENT, "build-amendment.json"),
            (common.DIAGNOSTIC_AMENDMENT, "diagnostic-amendment.json"),
            (common.LOCK_AMENDMENT, "lock-amendment.json"),
            (common.SDK_AMENDMENT, "sdk-amendment.json"),
            (self.fixture.recipe["patch_path"], "source.patch"),
            (common.RECIPE, "recipe.json"),
        )
        for source, name in transports:
            shutil.copyfile(self.root / source, artifact / name)
        (artifact / "candidate.patch").write_bytes(b"")
        record = {
            "schema": common.SCHEMA,
            "status": "candidate_generated",
            "source_commit": git(self.root, "rev-parse", "HEAD").decode().strip(),
            "source_mode": "integrated",
            "integration": binding,
            "source_tree": tree,
            "files": manifest["files"],
            "policy_inputs": manifest["policy_inputs"],
            "changed_paths": [],
            "original_dependency_policy_unchanged": True,
            "recipe_sha256": common.checksum(self.root / common.RECIPE),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "artifacts": common.describe(
                artifact, ("candidate.patch", *(n for _, n in transports))
            ),
        }
        (artifact / "RESULT.json").write_text(json.dumps(record))
        common.load_candidate(
            self.runner(),
            artifact,
            common.checksum(artifact / "RESULT.json"),
            record["source_commit"],
        )
        return record, artifact

    def test_complete_successor_preserves_all_historical_seals_and_adds_exact_four_inputs(
        self,
    ):
        parents = common.describe(self.root, self.amendment["parents"])
        manifest, binding, tree = self.verify()
        self.assertEqual(len(manifest["files"]), 324)
        self.assertEqual(
            binding["sdk_amendment"]["sha256"], common.SDK_AMENDMENT_SHA256
        )
        for name, change in self.amendment["changes"].items():
            self.assertEqual(manifest["files"][name], change["after"])
            self.assertEqual(manifest["file_modes"][name], "100644")
        self.assertEqual(common.describe(self.root, self.amendment["parents"]), parents)
        self.assertEqual(
            tree, git(self.root, "rev-parse", "HEAD^{tree}").decode().strip()
        )
        self.assertEqual(git(self.root, "status", "--porcelain"), b"")

    def test_missing_seal_rejects_successor_but_exact_original_patch_restores_history(
        self,
    ):
        patch = self.original_patch()
        self.path.unlink()
        with self.assertRaises(ValueError):
            self.verify()
        git(self.root, "apply", "--reverse", str(patch))
        git(self.root, "add", "--update")
        git(
            self.root,
            "commit",
            "-qm",
            "Actual reverse native patch; historical fixture",
        )
        manifest, binding, _tree = self.verify()
        self.assertEqual(len(manifest["files"]), 320)
        self.assertNotIn("sdk_amendment", binding)
        for name in common.SDK_EXISTING_INPUTS:
            self.assertEqual(
                manifest["files"][name], self.amendment["changes"][name]["before"]
            )

    def test_each_of_seven_bytes_modes_missing_files_and_symlinks_is_rejected(self):
        for name in self.amendment["changes"]:
            with self.subTest(path=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"\n")
                with self.assertRaisesRegex(ValueError, "SDK complete successor"):
                    self.verify()
                path.write_bytes(raw)
                path.chmod(0o755)
                with self.assertRaisesRegex(ValueError, "SDK complete successor"):
                    self.verify()
                path.chmod(0o644)
                path.unlink()
                with self.assertRaises((ValueError, OSError)):
                    self.verify()
                path.symlink_to(self.root / "codex-rs/Cargo.toml")
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    self.verify()
                path.unlink()
                path.write_bytes(raw)

    def test_mixed_old_and_new_sources_never_authorize_partial_success(self):
        current = {n: (self.root / n).read_bytes() for n in self.amendment["changes"]}
        git(self.root, "apply", "--reverse", str(self.original_patch()))
        old = {
            n: (self.root / n).read_bytes() if (self.root / n).exists() else None
            for n in current
        }
        for name, raw in current.items():
            (self.root / name).write_bytes(raw)
        for name, raw in old.items():
            with self.subTest(path=name):
                path = self.root / name
                if raw is None:
                    path.unlink()
                else:
                    path.write_bytes(raw)
                with self.assertRaises((ValueError, OSError)):
                    self.verify()
                path.write_bytes(current[name])

    def test_new_and_historical_records_proofs_and_unchanged_module_remain_exact(self):
        for name in (
            common.SDK_AMENDMENT,
            *self.amendment["parents"],
            *self.amendment["proofs"],
            "MODULE.bazel.lock",
        ):
            with self.subTest(path=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"\n")
                with self.assertRaises(ValueError):
                    self.verify()
                path.write_bytes(raw)

    def test_mapping_accepts_only_declared_predecessors_and_keeps_old_lock_semantics(
        self,
    ):
        old = {
            n: self.amendment["changes"][n]["before"]
            for n in common.SDK_EXISTING_INPUTS
        }
        self.assertEqual(
            common.effective_sdk_inputs(self.root, old),
            {n: self.amendment["changes"][n]["after"] for n in old},
        )
        for name in old:
            changed = copy.deepcopy(old)
            changed[name] = self.amendment["changes"][name]["after"]
            with self.assertRaisesRegex(ValueError, "fixed predecessor"):
                common.effective_sdk_inputs(self.root, changed)
        locked = json.loads((self.root / common.LOCK_AMENDMENT).read_bytes())
        self.assertEqual(
            common.effective_lock_inputs(
                self.root, {n: c["before"] for n, c in locked["changes"].items()}
            ),
            {n: c["after"] for n, c in locked["changes"].items()},
        )

    def test_result_and_raw_transport_cannot_be_resealed_to_replace_sdk_record(self):
        record, artifact = self.export()
        self.verify(record, artifact)
        exported = artifact / "sdk-amendment.json"
        original = exported.read_bytes()
        exported.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "transport changed"):
            self.verify(record, artifact)
        record["artifacts"].update(common.describe(artifact, (exported.name,)))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(record, artifact)

    def test_resealed_candidate_cannot_drop_an_added_snapshot(self):
        record, artifact = self.export()
        record["files"].pop(sorted(common.SDK_ADDED_INPUTS)[0])
        (artifact / "RESULT.json").write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "snapshot/path set"):
            common.load_candidate(
                self.runner(),
                artifact,
                common.checksum(artifact / "RESULT.json"),
                record["source_commit"],
            )

    def test_committed_sdk_record_and_index_modes_are_required(self):
        git(self.root, "update-index", "--chmod=+x", common.SDK_AMENDMENT)
        with self.assertRaisesRegex(ValueError, "Integrated index"):
            self.verify()
        git(self.root, "update-index", "--chmod=-x", common.SDK_AMENDMENT)
        git(self.root, "rm", "--cached", common.SDK_AMENDMENT)
        git(self.root, "commit", "-qm", "Remove only fixture seal from HEAD")
        with self.assertRaisesRegex(ValueError, "missing from the committed HEAD"):
            self.verify()

    def test_actual_arm_source_transport_copies_the_same_sdk_record_and_tree(self):
        fixtures = ROOT / "codex-rs/hepta-matrixd/tests/fixtures"
        previous = list(sys.path)
        sys.path.insert(0, str(fixtures))
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous))
        from linux_synapse.commands import Commands
        from linux_synapse.files import describe
        from linux_synapse.source import ENTRY, prepare_source

        for directory in self.fixture.recipe["vendor_dirs"]:
            if not (self.root / directory).exists():
                shutil.copytree(ROOT / directory, self.root / directory)
        helper = self.root / "scripts/ndu_port_candidate_common.py"
        helper.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "scripts/ndu_port_candidate_common.py", helper)
        for name in (
            "justfile",
            "scripts/run-nextest.py",
            "codex-rs/.config/nextest.toml",
            ENTRY,
            "codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs",
            "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh",
            "codex-rs/hepta-matrixd/tests/fixtures/synapse-loopback-proxy.py",
        ):
            target = self.root / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# Source transport fixture; never executed\n")
        git(self.root, "add", "--force", ".")
        git(self.root, "commit", "-qm", "Source transport fixture inputs")
        record, artifact = self.export()
        output = self.fixture.base / "arm-source-evidence"
        output.mkdir()
        executable = Path(shutil.which("git")).resolve()
        commands = Commands(
            output / "commands",
            {"git": {"path": str(executable), **describe(executable)}},
            {
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_OPTIONAL_LOCKS": "0",
            },
            self.root,
        )
        seal = prepare_source(
            self.root,
            artifact,
            common.checksum(artifact / "RESULT.json"),
            record["source_commit"],
            self.fixture.base / "private-source",
            output,
            commands,
        )
        self.assertEqual(
            (output / "producer/sdk-amendment.json").read_bytes(),
            self.path.read_bytes(),
        )
        self.assertEqual(
            seal["producer_integration"]["sdk_amendment"],
            record["integration"]["sdk_amendment"],
        )
        self.assertEqual(seal["qualification_tree"], record["source_tree"])
        self.assertEqual({row["tool"] for row in commands.records}, {"git"})


if __name__ == "__main__":
    unittest.main()

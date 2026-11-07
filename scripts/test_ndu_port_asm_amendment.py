"""Exercise exact byte, real Git and transport gates; no native qualification."""

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
import test_ndu_port_sdk_amendment as sdk_fixture


ROOT = Path(__file__).resolve().parents[1]


class AsmAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.sdk = sdk_fixture.SdkAmendmentTests()
        self.sdk.setUp()
        self.addCleanup(self.sdk.doCleanups)
        self.fixture = self.sdk.fixture
        self.root = self.sdk.root
        self.path = self.root / common.ASM_AMENDMENT
        self.amendment = json.loads((ROOT / common.ASM_AMENDMENT).read_bytes())
        names = {
            common.ASM_AMENDMENT,
            *self.amendment["changes"],
            *self.amendment["proofs"],
        }
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        git(self.root, "add", "--force", "--", *sorted(names))
        git(
            self.root, "commit", "-qm", "Complete ASM fixture; not native qualification"
        )
        self.calls = 0

    def runner(self):
        self.calls += 1
        return common.Recorder(
            self.root,
            self.fixture.base / f"asm-evidence-{self.calls}",
            "asm-source-guard-test",
        )

    def verify(self, record=None, artifact=None):
        return common.verify_integrated_source(
            self.runner(), self.fixture.recipe, record, artifact
        )

    def native_patch(self):
        proof = next(
            name
            for name in self.amendment["proofs"]
            if name.endswith("original-native.patch.gz")
        )
        target = self.fixture.base / "asm.patch"
        target.write_bytes(gzip.decompress((self.root / proof).read_bytes()))
        return target

    def export(self):
        manifest, binding, tree = self.verify()
        artifact = self.fixture.base / "asm-artifact"
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
            (common.ASM_AMENDMENT, "asm-amendment.json"),
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

    def test_complete_successor_preserves_eight_seals_and_all_other_inputs(self):
        parents = common.describe(self.root, self.amendment["parents"])
        manifest, binding, tree = self.verify()
        self.assertEqual(len(manifest["files"]), 325)
        self.assertEqual(
            binding["asm_amendment"]["sha256"], common.ASM_AMENDMENT_SHA256
        )
        for name, change in self.amendment["changes"].items():
            self.assertEqual(manifest["files"][name], change["after"])
            self.assertEqual(manifest["file_modes"][name], "100644")
        self.assertEqual(common.describe(self.root, self.amendment["parents"]), parents)
        self.assertEqual(
            tree, git(self.root, "rev-parse", "HEAD^{tree}").decode().strip()
        )

    def test_missing_new_seal_cannot_accept_new_product_bytes(self):
        self.path.unlink()
        git(self.root, "add", "--force", common.ASM_AMENDMENT)
        git(self.root, "commit", "-qm", "Missing new seal fixture")
        with self.assertRaises(ValueError):
            self.verify()

    def test_each_stale_predecessor_and_wrong_mode_is_rejected(self):
        patch = self.native_patch()
        for name in self.amendment["changes"]:
            with self.subTest(name=name, mutation="old-native-before"):
                target = self.root / name
                original = target.read_bytes()
                git(self.root, "apply", "--reverse", "--include=" + name, str(patch))
                try:
                    with self.assertRaisesRegex(ValueError, "ASM complete successor"):
                        self.verify()
                finally:
                    target.write_bytes(original)
            with self.subTest(name=name, mutation="executable-mode"):
                target.chmod(0o755)
                rejection = (
                    "Lock amendment source or lock identity differs"
                    if name == "MODULE.bazel.lock"
                    else "ASM complete successor"
                )
                try:
                    with self.assertRaisesRegex(ValueError, rejection):
                        self.verify()
                finally:
                    target.chmod(0o644)

    def test_fixed_record_all_parent_records_and_each_new_proof_are_required(self):
        paths = {
            common.ASM_AMENDMENT,
            *self.amendment["parents"],
            *self.amendment["proofs"],
        }
        for parent in self.amendment["parents"]:
            previous = json.loads((self.root / parent).read_bytes())
            paths.update(previous.get("proofs", {}))
        for name in sorted(paths):
            with self.subTest(name=name):
                target = self.root / name
                original = target.read_bytes()
                target.write_bytes(original + b"\n")
                with self.assertRaises(ValueError):
                    self.verify()
                target.write_bytes(original)

    def test_exact_mapping_rejects_already_mapped_or_wrong_predecessor(self):
        old = {
            name: change["before"] for name, change in self.amendment["changes"].items()
        }
        old["unchanged-control"] = {"bytes": 1, "sha256": "0" * 64}
        expected = {
            **old,
            **{
                name: change["after"]
                for name, change in self.amendment["changes"].items()
            },
        }
        self.assertEqual(common.effective_asm_inputs(self.root, old), expected)
        for name in self.amendment["changes"]:
            with self.subTest(name=name):
                wrong = copy.deepcopy(old)
                wrong[name] = self.amendment["changes"][name]["after"]
                with self.assertRaisesRegex(ValueError, "ASM historical input"):
                    common.effective_asm_inputs(self.root, wrong)

    def test_record_and_raw_transport_cannot_replace_the_fixed_asm_record(self):
        record, artifact = self.export()
        self.verify(record, artifact)
        transported = artifact / "asm-amendment.json"
        transported.write_bytes(transported.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "transport changed"):
            self.verify(record, artifact)
        record["artifacts"].update(common.describe(artifact, (transported.name,)))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(record, artifact)

    def test_resealed_candidate_cannot_drop_the_new_source_input(self):
        record, artifact = self.export()
        record["files"].pop(next(iter(common.ASM_ADDED_INPUTS)))
        (artifact / "RESULT.json").write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "snapshot/path set"):
            common.load_candidate(
                self.runner(),
                artifact,
                common.checksum(artifact / "RESULT.json"),
                record["source_commit"],
            )

    def test_committed_record_and_index_modes_are_required(self):
        git(self.root, "update-index", "--chmod=+x", common.ASM_AMENDMENT)
        with self.assertRaisesRegex(ValueError, "Integrated index"):
            self.verify()
        git(self.root, "update-index", "--chmod=-x", common.ASM_AMENDMENT)
        git(self.root, "rm", "--cached", common.ASM_AMENDMENT)
        git(self.root, "commit", "-qm", "Untracked new seal fixture")
        with self.assertRaisesRegex(ValueError, "missing from the committed HEAD"):
            self.verify()

    def test_actual_arm_transport_copies_the_same_asm_record_and_source_tree(self):
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
            (output / "producer/asm-amendment.json").read_bytes(),
            self.path.read_bytes(),
        )
        self.assertEqual(
            seal["producer_integration"]["asm_amendment"],
            record["integration"]["asm_amendment"],
        )
        self.assertEqual(seal["qualification_tree"], record["source_tree"])
        self.assertEqual({row["tool"] for row in commands.records}, {"git"})


if __name__ == "__main__":
    unittest.main()

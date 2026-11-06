"""Exercise the exact alias, real Git and transport; native CI remains separate."""

import copy
import shutil
import unittest
from unittest.mock import patch

import ndu_port_candidate_common as common
from ndu_port_integration_test_support import git
import test_ndu_port_dependency_amendment as dependency_fixture


class BuildAmendmentTests(unittest.TestCase):
    def setUp(self):
        fixture = dependency_fixture.DependencyAmendmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f = fixture
        self.path = fixture.root / common.BUILD_AMENDMENT
        self.amendment = common.load_build_amendment(fixture.root, fixture.recipe)
        self.directory = common.I18N_BUILD_FILE.rsplit("/", 1)[0]
        self.verification_count = 0

    def verify(self, record=None, artifact=None):
        self.verification_count += 1
        runner = common.Recorder(
            self.f.root,
            self.f.base / f"build-evidence-{self.verification_count}",
            "build-guard-test",
        )
        return common.verify_integrated_source(runner, self.f.recipe, record, artifact)

    def verify_vendors(self):
        """Read all real i18n/backport bytes; other unchanged vendors are controlled."""
        real_tree_files = common.tree_files
        formatting = common.load_source_amendment(self.f.root, self.f.recipe)

        def inventory(path):
            name = path.relative_to(self.f.root).as_posix()
            if name == self.directory or name in self.f.amendment["vendor_dirs"]:
                return real_tree_files(path)
            expected = copy.deepcopy(self.f.recipe["vendor_dirs"][name])
            for changed, change in formatting["changes"].items():
                if changed.startswith(name + "/"):
                    expected[changed[len(name) + 1 :]] = change["after"]
            return expected

        with patch.object(common, "tree_files", side_effect=inventory):
            common.verify_vendor(self.f.root, self.f.recipe, source_mode="integrated")

    def test_exact_alias_retains_the_complete_original_i18n_inventory(self):
        parents = common.describe(self.f.root, self.amendment["parents"])
        expected = copy.deepcopy(self.f.recipe["vendor_dirs"][self.directory])
        formatting = common.load_source_amendment(self.f.root, self.f.recipe)
        expected["src/lib.rs"] = formatting["changes"][self.directory + "/src/lib.rs"][
            "after"
        ]
        expected["BUILD.bazel"] = self.amendment["changes"][common.I18N_BUILD_FILE][
            "after"
        ]
        self.assertEqual(common.tree_files(self.f.root / self.directory), expected)
        self.assertEqual(len(expected), 14)
        self.verify_vendors()
        self.assertEqual(
            common.describe(self.f.root, self.amendment["parents"]), parents
        )
        original_raw = self.path.read_bytes()
        self.path.unlink()
        with self.assertRaisesRegex(
            ValueError, r"Expected a regular file: .*BUILD_AMENDMENT\.v7\.3\.json"
        ):
            self.verify()
        self.path.write_bytes(original_raw)

    def test_every_old_record_and_the_new_review_seal_remain_immutable(self):
        for name in [common.BUILD_AMENDMENT, *self.amendment["parents"]]:
            with self.subTest(path=name):
                path = self.f.root / name
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaises(ValueError):
                    common.load_build_amendment(self.f.root, self.f.recipe)
                path.write_bytes(original)

    def test_alias_bytes_mode_missing_file_and_symlink_are_rejected(self):
        path = self.f.root / common.I18N_BUILD_FILE
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "source identity or mode"):
            self.verify()
        path.write_bytes(original)
        path.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "source identity or mode"):
            self.verify()
        path.chmod(0o644)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()
        path.symlink_to(self.f.root / self.directory / "Cargo.toml")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.verify()
        path.unlink()
        path.write_bytes(original)

    def test_other_i18n_sources_license_and_extra_files_still_fail_inventory(self):
        for name in ("Cargo.toml", "LICENSE.txt", "src/lib.rs"):
            with self.subTest(path=name):
                path = self.f.root / self.directory / name
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, "Vendor inventory differs"):
                    self.verify_vendors()
                path.write_bytes(original)
        extra = self.f.root / self.directory / "extra.rs"
        extra.write_text("unreviewed source\n")
        with self.assertRaisesRegex(ValueError, "Vendor inventory differs"):
            self.verify_vendors()
        extra.unlink()
        license_path = self.f.root / self.directory / "LICENSE.txt"
        license_path.unlink()
        with self.assertRaisesRegex(ValueError, "Vendor inventory differs"):
            self.verify_vendors()

    def test_alias_git_index_and_committed_blob_are_required(self):
        name = common.I18N_BUILD_FILE
        raw = self.f.root / name
        original_blob = git(self.f.root, "hash-object", str(raw)).decode().strip()
        replacement = self.f.base / "index-only"
        replacement.write_text("unreviewed staged bytes\n")
        other = git(self.f.root, "hash-object", "-w", str(replacement)).decode().strip()
        git(self.f.root, "update-index", "--cacheinfo", f"100644,{other},{name}")
        with self.assertRaisesRegex(ValueError, "Integrated index"):
            self.verify()
        git(
            self.f.root, "update-index", "--cacheinfo", f"100644,{original_blob},{name}"
        )
        git(self.f.root, "rm", "--cached", name)
        git(self.f.root, "commit", "-qm", "remove only committed alias from fixture")
        with self.assertRaisesRegex(ValueError, "missing from the committed HEAD"):
            self.verify()

    def test_resealed_transport_and_changed_result_cannot_replace_the_alias(self):
        manifest, binding, tree = self.verify()
        artifact = self.f.base / "artifact"
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
            shutil.copyfile(self.f.root / source, artifact / name)
        (artifact / "candidate.patch").write_bytes(b"")
        record = {
            "source_mode": "integrated",
            "integration": binding,
            "source_tree": tree,
            "files": manifest["files"],
            "policy_inputs": manifest["policy_inputs"],
            "changed_paths": [],
            "artifacts": common.describe(
                artifact, ("candidate.patch", *(name for _, name in transports))
            ),
        }
        self.verify(record, artifact)
        exported = artifact / "build-amendment.json"
        raw = exported.read_bytes()
        exported.write_bytes(raw + b"\n")
        record["artifacts"].update(common.describe(artifact, (exported.name,)))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(record, artifact)
        exported.write_bytes(raw)
        record["artifacts"].update(common.describe(artifact, (exported.name,)))
        del record["files"][common.I18N_BUILD_FILE]
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.verify(record, artifact)


if __name__ == "__main__":
    unittest.main()

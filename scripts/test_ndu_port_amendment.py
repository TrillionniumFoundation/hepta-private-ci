"""Real Git/artifact checks for an explicit source and vendor formatting revision."""

import copy
import json
import shutil
import unittest

import ndu_port_candidate_common as common
from ndu_port_integration_test_support import amend_fixture
from ndu_port_integration_test_support import git
from ndu_port_integration_test_support import integrate_fixture
import test_ndu_port_candidate as artifact_fixture
import test_ndu_port_integrated as integrated_fixture


class SourceAmendmentTests(unittest.TestCase):
    def setUp(self):
        fixture = artifact_fixture.PortArtifactTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.restore(fixture.runner("original-restore"))
        self.vendor_source = fixture.vendor + "/src/lib.rs"
        path = fixture.root / self.vendor_source
        path.parent.mkdir()
        path.write_text("pub fn vendor() {}\n")
        fixture.recipe["vendor_dirs"][fixture.vendor] = common.tree_files(
            path.parent.parent
        )
        recipe_path = fixture.root / common.RECIPE
        recipe_path.write_text(json.dumps(fixture.recipe))
        fixture.record["recipe_sha256"] = common.checksum(recipe_path)
        shutil.copyfile(recipe_path, fixture.artifact / "recipe.json")
        fixture.record["artifacts"].update(
            common.describe(fixture.artifact, ("recipe.json",))
        )
        fixture.seal()
        git(fixture.root, "add", "--", self.vendor_source, common.RECIPE)
        fixture.record, fixture.result_sha = integrate_fixture(
            fixture.root, fixture.recipe, fixture.record, fixture.artifact
        )
        self.parent_bytes = (fixture.root / common.INTEGRATION).read_bytes()
        self.recipe_bytes = recipe_path.read_bytes()
        fixture.record, fixture.result_sha = amend_fixture(
            fixture.root,
            fixture.recipe,
            fixture.record,
            fixture.artifact,
            {
                fixture.source_file: b"reviewed source  \n",
                self.vendor_source: b"pub fn vendor() { }\n",
            },
        )
        fixture.source = fixture.record["source_commit"]
        self.f = fixture

    def test_explicit_amendment_preserves_parent_recipe_locks_and_legacy_vendor_guard(
        self,
    ):
        runner = self.f.runner()
        record, recipe = self.f.restore(runner)
        common.verify_tree(runner, record, recipe)
        self.assertEqual(
            (self.f.root / common.INTEGRATION).read_bytes(), self.parent_bytes
        )
        self.assertEqual((self.f.root / common.RECIPE).read_bytes(), self.recipe_bytes)
        self.assertEqual(
            common.describe(self.f.root, common.LOCKS),
            {name: record["files"][name] for name in common.LOCKS},
        )
        common.verify_vendor(self.f.root, recipe, source_mode="integrated")
        with self.assertRaisesRegex(ValueError, "Vendor inventory"):
            common.verify_vendor(self.f.root, recipe)
        self.assertFalse(
            any("apply" in row["command"] for row in runner.record["commands"])
        )

    def test_generation_seals_amendment_and_requires_both_lock_commands(self):
        runner, seen = integrated_fixture.IntegratedSourceTests.generate(self)
        self.assertIn(["just", "bazel-lock-update"], seen)
        self.assertIn(["just", "bazel-lock-check"], seen)
        self.assertEqual(
            (runner.output / "source-amendment.json").read_bytes(),
            (self.f.root / common.SOURCE_AMENDMENT).read_bytes(),
        )
        self.assertEqual(runner.record["integration"], self.f.record["integration"])
        common.restore_candidate(
            self.f.runner("generated-restore"),
            runner.output,
            common.checksum(runner.output / "RESULT.json"),
            self.f.source,
        )

    def test_lock_drift_cannot_be_authorized_by_a_source_amendment(self):
        with self.assertRaises(ValueError):
            integrated_fixture.IntegratedSourceTests.generate(self, lock_drift=True)
        result = json.loads((self.f.base / "generate/RESULT.json").read_text())
        self.assertNotEqual(result["status"], "candidate_generated")

    def test_wrong_predecessor_parent_recipe_mode_and_non_source_paths_are_rejected(
        self,
    ):
        path = self.f.root / common.SOURCE_AMENDMENT
        original = json.loads(path.read_text())
        variants = []
        bad = copy.deepcopy(original)
        bad["parent"]["sha256"] = "f" * 64
        variants.append(bad)
        bad = copy.deepcopy(original)
        bad["recipe"]["sha256"] = "f" * 64
        variants.append(bad)
        bad = copy.deepcopy(original)
        bad["changes"][self.f.source_file]["before"]["sha256"] = "f" * 64
        variants.append(bad)
        bad = copy.deepcopy(original)
        bad["changes"][self.f.source_file]["mode"] = "100755"
        variants.append(bad)
        for name in [common.LOCKS[0], common.POLICIES[0], "codex-rs/unknown.rs"]:
            bad = copy.deepcopy(original)
            bad["changes"][name] = bad["changes"].pop(self.f.source_file)
            variants.append(bad)
        for index, bad in enumerate(variants):
            with self.subTest(index=index):
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    common.load_source_amendment(self.f.root, self.f.recipe)
        path.write_text(json.dumps(original, indent=2) + "\n")

    def test_unbound_vendor_change_and_extra_vendor_file_are_rejected(self):
        original = (self.f.root / self.vendor_source).read_bytes()
        (self.f.root / self.vendor_source).write_bytes(b"unreviewed vendor mutation\n")
        with self.assertRaises(ValueError):
            common.verify_tree(self.f.runner("mutated"), self.f.record, self.f.recipe)
        (self.f.root / self.vendor_source).write_bytes(original)
        (self.f.root / self.f.vendor / "extra.rs").write_text("extra\n")
        with self.assertRaisesRegex(ValueError, "Vendor inventory"):
            common.verify_vendor(self.f.root, self.f.recipe, source_mode="integrated")

    def test_amendment_must_be_exact_in_head_not_merely_current_worktree(self):
        path = self.f.root / common.SOURCE_AMENDMENT
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "committed HEAD"):
            common.verify_integrated_source(self.f.runner(), self.f.recipe)

    def test_resealed_download_cannot_change_the_committed_amendment(self):
        path = self.f.artifact / "source-amendment.json"
        path.write_bytes(path.read_bytes() + b"\n")
        self.f.record["artifacts"].update(
            common.describe(self.f.artifact, ("source-amendment.json",))
        )
        self.f.seal()
        with self.assertRaisesRegex(ValueError, "Integrated candidate"):
            self.f.restore(self.f.runner())

    def test_missing_amendment_cannot_inherit_the_revised_source_identity(self):
        (self.f.root / common.SOURCE_AMENDMENT).unlink()
        with self.assertRaisesRegex(ValueError, "Integrated source or lock"):
            common.verify_integrated_source(self.f.runner(), self.f.recipe)


if __name__ == "__main__":
    unittest.main()

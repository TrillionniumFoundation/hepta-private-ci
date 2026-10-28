"""Actual Git identity checks with controlled external resolver processes."""

import copy
import json
import os
import sys
import unittest
from unittest.mock import patch

import ndu_port_candidate_common as common
import ndu_port_integrated as integrated
from ndu_port_integration_test_support import git
from ndu_port_integration_test_support import integrate_fixture
import test_ndu_port_candidate as artifact_fixture


class IntegratedSourceTests(unittest.TestCase):
    def setUp(self):
        fixture = artifact_fixture.PortArtifactTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.restore(fixture.runner("original-restore"))
        fixture.record, fixture.result_sha = integrate_fixture(
            fixture.root, fixture.recipe, fixture.record, fixture.artifact
        )
        fixture.source = fixture.record["source_commit"]
        self.f = fixture

    def test_exact_committed_source_restores_without_applying_a_patch(self):
        runner = self.f.runner()
        before = git(self.f.root, "rev-parse", "HEAD^{tree}")
        record, recipe = self.f.restore(runner)
        common.verify_tree(runner, record, recipe)
        self.assertEqual(git(self.f.root, "rev-parse", "HEAD^{tree}"), before)
        self.assertEqual(record["files"], common.describe(self.f.root, record["files"]))
        self.assertEqual(record["source_mode"], "integrated")
        self.assertFalse(
            any("apply" in c["command"] for c in runner.record["commands"])
        )
        self.assertEqual(git(self.f.root, "status", "--porcelain"), b"")

    def test_index_only_delta_is_rejected_even_when_worktree_equals_head(self):
        replacement = self.f.base / "index-only.rs"
        replacement.write_text("unapproved staged contents\n")
        blob = git(self.f.root, "hash-object", "-w", str(replacement)).decode().strip()
        git(
            self.f.root,
            "update-index",
            "--cacheinfo",
            f"100644,{blob},{self.f.source_file}",
        )
        self.assertEqual(git(self.f.root, "diff", "--name-only", "HEAD"), b"")
        self.assertNotEqual(git(self.f.root, "diff", "--cached", "--name-only"), b"")
        with self.assertRaisesRegex(ValueError, "Integrated index"):
            common.verify_tree(self.f.runner(), self.f.record, self.f.recipe)

    def test_declared_integrated_mode_rejects_a_nonempty_resealed_patch(self):
        (self.f.artifact / "candidate.patch").write_bytes(b"unapproved delta\n")
        self.f.record["artifacts"].update(
            common.describe(self.f.artifact, ("candidate.patch",))
        )
        self.f.seal()
        with self.assertRaisesRegex(ValueError, "Integrated candidate"):
            self.f.restore(self.f.runner())

    def test_empty_integrated_artifact_cannot_masquerade_as_legacy_patch_mode(self):
        self.f.record["source_mode"] = "patched"
        self.f.seal()
        with self.assertRaisesRegex(ValueError, "complete source delta"):
            self.f.restore(self.f.runner())

    def test_unknown_mode_and_changed_tree_or_manifest_binding_are_rejected(self):
        original = copy.deepcopy(self.f.record)
        mutations = [
            ("source_mode", "trust-me"),
            ("source_tree", "f" * 40),
            ("changed_paths", [self.f.source_file]),
            (
                "integration",
                {**original["integration"], "origin_result_sha256": "f" * 64},
            ),
        ]
        for index, (key, value) in enumerate(mutations):
            with self.subTest(key=key):
                self.f.record = copy.deepcopy(original)
                self.f.record[key] = value
                self.f.seal()
                with self.assertRaises(ValueError):
                    self.f.restore(self.f.runner(f"reject-{index}"))

    def test_another_workflow_attempt_cannot_consume_the_integrated_artifact(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "different"}):
            with self.assertRaisesRegex(ValueError, "different workflow run/attempt"):
                self.f.restore(self.f.runner())

    def test_integrated_generator_rejects_committed_policy_and_recipe_drift(self):
        for index, name in enumerate([common.POLICIES[0], common.RECIPE]):
            with self.subTest(name=name):
                original = (self.f.root / name).read_bytes()
                (self.f.root / name).write_bytes(original + b"\n")
                git(self.f.root, "add", name)
                git(self.f.root, "commit", "-qm", "controlled committed drift")
                head = git(self.f.root, "rev-parse", "HEAD").decode().strip()
                with patch.object(integrated, "check_toolchain") as compiler:
                    with self.assertRaisesRegex(
                        ValueError, "recipe or original policy"
                    ):
                        integrated.generate_integrated(
                            self.f.runner(f"drift-{index}"), head
                        )
                    compiler.assert_not_called()
                (self.f.root / name).write_bytes(original)
                git(self.f.root, "add", name)
                git(self.f.root, "commit", "-qm", "restore fixture input")

    def test_committed_file_bytes_and_executable_mode_must_match_origin(self):
        path = self.f.root / self.f.source_file
        for index, change in enumerate(["content", "mode"]):
            with self.subTest(change=change):
                original = path.read_bytes()
                if change == "content":
                    path.write_text("unreviewed replacement\n")
                else:
                    path.chmod(0o755)
                git(self.f.root, "add", self.f.source_file)
                git(self.f.root, "commit", "-qm", "controlled source drift")
                head = git(self.f.root, "rev-parse", "HEAD").decode().strip()
                with patch.object(integrated, "check_toolchain") as compiler:
                    with self.assertRaisesRegex(ValueError, "Integrated"):
                        integrated.generate_integrated(
                            self.f.runner(f"file-drift-{index}"), head
                        )
                    compiler.assert_not_called()
                path.write_bytes(original)
                path.chmod(0o644)
                git(self.f.root, "add", self.f.source_file)
                git(self.f.root, "commit", "-qm", "restore fixture source")

    def generate(self, *, lock_drift=False, graph_drift=False):
        runner = self.f.runner("generate")
        real_run = runner.run
        seen = []
        updated = False

        def resolver(label, command, **kwargs):
            nonlocal updated
            if command[0] == "git":
                return real_run(label, command, **kwargs)
            seen.append(command)
            if command[:2] == ["cargo", "metadata"]:
                metadata = copy.deepcopy(self.f.metadata)
                if updated and graph_drift:
                    metadata["resolve"]["nodes"][0]["features"].append("unexpected")
                return real_run(
                    label,
                    [
                        sys.executable,
                        "-c",
                        "import sys; print(sys.argv[1])",
                        json.dumps(metadata),
                    ],
                    **kwargs,
                )
            if command == ["just", "bazel-lock-update"]:
                updated = True
                if lock_drift:
                    (self.f.root / common.LOCKS[1]).write_text("resolver drift\n")
            elif command not in (["just", "bazel-lock-check"], ["bazel", "--version"]):
                raise AssertionError(
                    f"Unexpected integrated resolver command: {command}"
                )
            return real_run(
                label,
                [
                    sys.executable,
                    "-c",
                    "print('controlled resolver; no Rust qualification')",
                ],
                **kwargs,
            )

        with (
            patch.object(integrated, "check_toolchain"),
            patch.object(runner, "run", side_effect=resolver),
        ):
            integrated.generate_integrated(runner, self.f.source)
        runner.save()
        return runner, seen

    def test_generation_runs_lock_commands_and_seals_a_same_run_clean_tree(self):
        runner, seen = self.generate()
        self.assertIn(["just", "bazel-lock-update"], seen)
        self.assertIn(["just", "bazel-lock-check"], seen)
        self.assertFalse(any(c[:2] == ["cargo", "update"] for c in seen))
        self.assertEqual(runner.record["status"], "candidate_generated")
        self.assertFalse(runner.record["integration_lock_drift"])
        self.assertEqual(runner.record["changed_paths"], [])
        self.assertEqual((runner.output / "candidate.patch").read_bytes(), b"")
        common.restore_candidate(
            self.f.runner("generated-restore"),
            runner.output,
            common.checksum(runner.output / "RESULT.json"),
            self.f.source,
        )

    def test_actual_lock_or_graph_drift_cannot_produce_an_integrated_pass(self):
        for name in ("lock", "graph"):
            with self.subTest(name=name):
                # Each subcase gets independent Git/evidence paths.
                if name == "graph":
                    self.setUp()
                with self.assertRaises(ValueError):
                    self.generate(
                        lock_drift=name == "lock", graph_drift=name == "graph"
                    )
                record = json.loads((self.f.base / "generate/RESULT.json").read_text())
                self.assertNotEqual(record["status"], "candidate_generated")


if __name__ == "__main__":
    unittest.main()

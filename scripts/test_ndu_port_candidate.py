"""Exercise real Git artifact transport and rejection before Rust execution."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import ndu_port_candidate_common as common
import ndu_port_candidate as candidate


def git(root, *arguments):
    return subprocess.check_output(
        ["git", *arguments], cwd=root, stderr=subprocess.STDOUT
    )


class PortArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Port transport fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "config", "commit.gpgsign", "false")
        self.source_file = "codex-rs/fixture.rs"
        self.binary_file = "codex-rs/binary.fixture"
        self.vendor = "codex-rs/third_party/example-1.0.0"
        self.patch_name = "inputs/source.patch"
        fixture_name = "inputs/matrix-fixture.patch"
        for name in (
            *common.POLICIES,
            *common.LOCKS,
            self.source_file,
            f"{self.vendor}/Cargo.toml",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"initial {name}\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "initial fixture")
        (self.root / self.source_file).write_text("reviewed source\n")
        (self.root / self.binary_file).write_bytes(b"\x00bound binary\xff")
        git(self.root, "add", ".")
        patch = git(
            self.root, "diff", "--binary", "--full-index", "--no-renames", "HEAD"
        )
        git(self.root, "reset", "--hard", "HEAD")
        (self.root / "inputs").mkdir()
        (self.root / self.patch_name).write_bytes(patch)
        (self.root / fixture_name).write_text("fixture patch input\n")
        self.recipe = {
            "schema": "hepta.port-remediation.recipe.v1",
            "patch_path": self.patch_name,
            "patch_sha256": common.checksum(self.root / self.patch_name),
            "allowed_paths": [self.source_file, self.binary_file],
            "vendor_dirs": {self.vendor: common.tree_files(self.root / self.vendor)},
            "expected_packages": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "source": "path",
                    "required_features": ["crypto"],
                }
            ],
            "forbidden_packages": ["abandoned"],
            "cargo_updates": [{"package": "example", "precise": "1.0.0"}],
            "matrix_baseline": {
                "source_sha": common.OLD_SOURCE,
                "fixture_patch_path": fixture_name,
                "fixture_patch_sha256": common.checksum(self.root / fixture_name),
            },
            "aws_qualification": {
                "vendor_dir": self.vendor,
                "resources": {
                    name: {
                        "path": fixture_name,
                        **common.describe(self.root, (fixture_name,))[fixture_name],
                    }
                    for name in ("Cargo.lock", ".config/nextest.toml")
                },
                "expected_total": 245,
                "expected_executed": 244,
                "expected_ignored": 1,
                "ignored_tests": ["ecs::test::real_dns_lookup"],
            },
        }
        recipe_path = self.root / common.RECIPE
        recipe_path.parent.mkdir(parents=True)
        recipe_path.write_text(json.dumps(self.recipe))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "reviewed recipe and inputs")
        self.source = git(self.root, "rev-parse", "HEAD").decode().strip()
        self.policy = common.describe(self.root, common.POLICIES)
        git(self.root, "apply", "--index", str(self.root / self.patch_name))
        self.lock = 'version = 4\n[[package]]\nname = "example"\nversion = "1.0.0"\n'
        (self.root / common.LOCKS[0]).write_text(self.lock)
        (self.root / common.LOCKS[1]).write_text("candidate Bazel lock\n")
        self.artifact = self.base / "artifact"
        self.artifact.mkdir()
        shutil.copyfile(recipe_path, self.artifact / "recipe.json")
        shutil.copyfile(self.root / self.patch_name, self.artifact / "source.patch")
        self.metadata = {
            "workspace_root": str(self.root / "codex-rs"),
            "packages": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "id": "example-id",
                    "source": None,
                    "manifest_path": str(self.root / self.vendor / "Cargo.toml"),
                }
            ],
            "resolve": {"nodes": [{"id": "example-id", "features": ["crypto"]}]},
        }
        (self.artifact / "metadata.json").write_text(json.dumps(self.metadata))
        git(
            self.root,
            "diff",
            "--binary",
            "--full-index",
            "--no-renames",
            f"--output={self.artifact / 'candidate.patch'}",
            "HEAD",
        )
        inventory = common.describe(
            self.root, (*self.recipe["allowed_paths"], *common.LOCKS)
        )
        common.copy_files(self.root, self.artifact / "files", inventory)
        self.record = {
            "schema": common.SCHEMA,
            "status": "candidate_generated",
            "source_commit": self.source,
            "original_dependency_policy_unchanged": True,
            "policy_inputs": self.policy,
            "recipe_sha256": common.checksum(recipe_path),
            "files": inventory,
            "changed_paths": sorted(inventory),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "artifacts": common.describe(
                self.artifact,
                ("recipe.json", "source.patch", "candidate.patch", "metadata.json"),
            ),
        }
        self.seal()
        git(self.root, "reset", "--hard", "HEAD")

    def seal(self):
        (self.artifact / "RESULT.json").write_text(json.dumps(self.record))
        self.result_sha = common.checksum(self.artifact / "RESULT.json")

    def runner(self, name="run"):
        return common.Recorder(self.root, self.base / name, "test")

    def restore(self, runner):
        return common.restore_candidate(
            runner, self.artifact, self.result_sha, self.source
        )

    def generate_with_final_features(self, features):
        """Use real Git/process evidence with controlled external resolver results."""
        runner = self.runner("generate")
        run = runner.run
        final_metadata = copy.deepcopy(self.metadata)
        final_metadata["resolve"]["nodes"][0]["features"] = features
        bazel_updated = False

        def controlled_resolver(label, command, **kwargs):
            nonlocal bazel_updated
            if command[0] == "git":
                return run(label, command, **kwargs)
            if command[:2] == ["cargo", "update"]:
                (self.root / common.LOCKS[0]).write_text(self.lock)
            elif command[:2] == ["cargo", "metadata"]:
                metadata = final_metadata if bazel_updated else self.metadata
                return run(
                    label,
                    [
                        sys.executable,
                        "-c",
                        "import sys; print(sys.argv[1])",
                        json.dumps(metadata),
                    ],
                    **kwargs,
                )
            elif command == ["just", "bazel-lock-update"]:
                bazel_updated = True
                (self.root / common.LOCKS[1]).write_text("resolved Bazel lock\n")
            elif command not in (["just", "bazel-lock-check"], ["bazel", "--version"]):
                raise AssertionError(f"Unexpected resolver command: {command}")
            return run(
                label,
                [sys.executable, "-c", "print('controlled resolver completed')"],
                **kwargs,
            )

        with (
            patch.object(candidate, "check_toolchain"),
            patch.object(runner, "run", side_effect=controlled_resolver),
        ):
            candidate.generate(runner, self.source)
        return runner, final_metadata

    def test_generated_candidate_seals_final_graph_and_preserves_before_graph(self):
        runner, final_metadata = self.generate_with_final_features(
            ["crypto", "bazel-selected"]
        )
        self.assertEqual(
            json.loads((runner.output / "metadata.json").read_text()), final_metadata
        )
        self.assertEqual(
            json.loads((runner.output / "metadata-before-bazel.json").read_text()),
            self.metadata,
        )
        self.assertEqual(runner.record["status"], "candidate_generated")
        stdout = [row["stdout"] for row in runner.record["commands"] if "stdout" in row]
        self.assertEqual(
            {row["file"] for row in stdout},
            {"metadata-before-bazel.json", "metadata.json"},
        )
        for row in stdout:
            self.assertEqual(
                common.checksum(runner.output / row["file"]), row["sha256"]
            )
            self.assertEqual(
                runner.record["artifacts"][row["file"]]["sha256"], row["sha256"]
            )

    def test_final_resolver_feature_loss_cannot_reuse_pre_bazel_graph(self):
        with self.assertRaisesRegex(ValueError, "features"):
            self.generate_with_final_features([])
        record = json.loads((self.base / "generate/RESULT.json").read_text())
        self.assertNotEqual(record["status"], "candidate_generated")
        final = json.loads((self.base / "generate/metadata.json").read_text())
        self.assertEqual(final["resolve"]["nodes"][0]["features"], [])

    def test_exact_binary_patch_reconstructs_source_and_both_locks(self):
        runner = self.runner()
        record, recipe = self.restore(runner)
        self.assertEqual(common.describe(self.root, record["files"]), record["files"])
        self.assertEqual(
            (self.root / self.binary_file).read_bytes(), b"\x00bound binary\xff"
        )
        self.assertEqual(recipe, self.recipe)
        for command in runner.record["commands"]:
            self.assertEqual(command["exit_code"], 0)
            self.assertEqual(
                common.checksum(runner.output / command["log"]), command["log_sha256"]
            )

    def test_tampered_result_patch_snapshot_or_metadata_rejected_before_apply(self):
        names = [
            "RESULT.json",
            "candidate.patch",
            f"files/{common.LOCKS[0]}",
            "metadata.json",
        ]
        for index, name in enumerate(names):
            with self.subTest(name=name):
                path = self.artifact / name
                original = path.read_bytes()
                path.write_bytes(original + b"tamper")
                with self.assertRaises(ValueError):
                    self.restore(self.runner(f"tamper-{index}"))
                path.write_bytes(original)
                self.assertFalse((self.root / self.binary_file).exists())

    def test_another_head_cannot_use_the_artifact(self):
        git(self.root, "commit", "--allow-empty", "-qm", "another source")
        with self.assertRaisesRegex(ValueError, "HEAD"):
            self.restore(self.runner())

    def test_extra_vendor_file_or_policy_edit_after_restore_is_detected(self):
        runner = self.runner()
        record, recipe = self.restore(runner)
        extra = self.root / self.vendor / "unexpected.rs"
        extra.write_text("unreviewed extra source")
        with self.assertRaisesRegex(ValueError, "Vendor inventory"):
            common.verify_tree(runner, record, recipe)
        extra.unlink()
        (self.root / common.POLICIES[0]).write_text("weakened policy")
        with self.assertRaisesRegex(ValueError, "policy"):
            common.verify_tree(runner, record, recipe)
        self.assertFalse(runner.record["original_dependency_policy_unchanged"])

    def test_recipe_cannot_approve_policy_edits_or_untyped_update_arguments(self):
        path = self.root / common.RECIPE
        original = path.read_bytes()
        self.recipe["allowed_paths"].append(common.POLICIES[0])
        path.write_text(json.dumps(self.recipe))
        with self.assertRaisesRegex(ValueError, "policy"):
            common.load_recipe(self.root)
        path.write_bytes(original)
        recipe = json.loads(original)
        recipe["cargo_updates"][0]["arguments"] = ["--ignore-rust-version"]
        path.write_text(json.dumps(recipe))
        with self.assertRaisesRegex(ValueError, "typed"):
            common.load_recipe(self.root)

    def test_recipe_keeps_the_exact_original_aws_inventory_and_ignore(self):
        path = self.root / common.RECIPE
        self.assertEqual(
            common.load_recipe(self.root)["aws_qualification"]["expected_executed"], 244
        )
        original = copy.deepcopy(self.recipe)
        for field, value in (
            ("ignored_tests", ["ecs::tests::real_dns_lookup"]),
            ("ignored_tests", []),
            ("expected_total", 244),
            ("expected_executed", 243),
            ("expected_ignored", 2),
        ):
            with self.subTest(field=field, value=value):
                recipe = copy.deepcopy(original)
                recipe["aws_qualification"][field] = value
                path.write_text(json.dumps(recipe))
                with self.assertRaisesRegex(ValueError, "frozen upstream inventory"):
                    common.load_recipe(self.root)

    def test_deleted_policy_cannot_retain_an_earlier_true_attestation(self):
        runner = self.runner()
        record, recipe = self.restore(runner)
        self.assertTrue(runner.record["original_dependency_policy_unchanged"])
        (self.root / common.POLICIES[0]).unlink()
        with self.assertRaises(ValueError):
            common.verify_tree(runner, record, recipe)
        saved = json.loads((runner.output / "RESULT.json").read_text())
        self.assertFalse(saved["original_dependency_policy_unchanged"])

    def test_graph_rejects_old_implementation_or_missing_features(self):
        (self.root / common.LOCKS[0]).write_text(self.lock)
        common.validate_graph(self.root, self.recipe, self.metadata)
        self.metadata["resolve"]["nodes"][0]["features"] = []
        with self.assertRaisesRegex(ValueError, "features"):
            common.validate_graph(self.root, self.recipe, self.metadata)
        (self.root / common.LOCKS[0]).write_text(
            self.lock + '[[package]]\nname = "abandoned"\nversion = "1.0.0"\n'
        )
        with self.assertRaisesRegex(ValueError, "forbidden"):
            common.validate_graph(self.root, self.recipe, self.metadata)

    def test_graph_rejects_extra_features_when_an_exact_set_is_frozen(self):
        (self.root / common.LOCKS[0]).write_text(self.lock)
        self.recipe["expected_packages"][0]["exact_features"] = ["crypto"]
        common.validate_graph(self.root, self.recipe, self.metadata)
        self.metadata["resolve"]["nodes"][0]["features"].append("paging")
        with self.assertRaisesRegex(ValueError, "Exact effective features"):
            common.validate_graph(self.root, self.recipe, self.metadata)

    def test_graph_requires_a_resolved_node_even_with_no_required_features(self):
        (self.root / common.LOCKS[0]).write_text(self.lock)
        self.recipe["expected_packages"][0]["required_features"] = []
        self.recipe["expected_packages"][0]["exact_features"] = []
        self.metadata["resolve"]["nodes"] = []
        with self.assertRaisesRegex(ValueError, "resolved dependency graph"):
            common.validate_graph(self.root, self.recipe, self.metadata)

    def test_recipe_rejects_an_untyped_exact_feature_constraint(self):
        self.recipe["expected_packages"][0]["exact_features"] = "crypto"
        (self.root / common.RECIPE).write_text(json.dumps(self.recipe))
        with self.assertRaisesRegex(ValueError, "exact_features"):
            common.load_recipe(self.root)

    def test_renamed_or_traversing_paths_are_not_artifact_inputs(self):
        for name in ("../outside", "/absolute", "a//b", "a/./b", "a\\b", "a\nb"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                common.relative_path(name)
        external = self.base / "outside"
        external.write_text("external")
        linked = self.root / self.vendor / "linked"
        linked.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            common.tree_files(self.root / self.vendor)


class RealCommandEvidenceTests(unittest.TestCase):
    def test_inherited_compiler_override_is_recorded_and_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            runner = common.Recorder(root, base / "result", "test")
            with patch.dict(
                os.environ, {"RUSTC_WRAPPER": "/unqualified/compiler-wrapper"}
            ):
                with self.assertRaisesRegex(ValueError, "compiler/wrapper"):
                    common.check_toolchain(runner, "1.96.0")
            saved = json.loads((runner.output / "RESULT.json").read_text())
            self.assertEqual(
                saved["inherited_compiler_overrides"]["RUSTC_WRAPPER"],
                "/unqualified/compiler-wrapper",
            )
            self.assertEqual(saved["commands"], [])

    def test_failed_process_keeps_stderr_stdout_status_and_next_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = base / "repo"
            repo.mkdir()
            runner = common.Recorder(repo, base / "result", "test")
            status = runner.run(
                "negative",
                [
                    sys.executable,
                    "-c",
                    "import sys; print('stdout'); print('stderr',file=sys.stderr); sys.exit(9)",
                ],
                required=False,
            )
            self.assertEqual(status, 9)
            result = runner.json_command(
                "json",
                [
                    sys.executable,
                    "-c",
                    "import sys; print('{\"value\": 7}'); print('diagnostic',file=sys.stderr)",
                ],
            )
            self.assertEqual(result, {"value": 7})
            record = json.loads((runner.output / "RESULT.json").read_text())
            self.assertEqual([row["exit_code"] for row in record["commands"]], [9, 0])
            self.assertEqual(
                set(
                    (runner.output / record["commands"][0]["log"])
                    .read_text()
                    .splitlines()
                ),
                {"stdout", "stderr"},
            )
            self.assertEqual(
                (runner.output / record["commands"][1]["log"]).read_text().strip(),
                "diagnostic",
            )
            self.assertEqual(
                common.checksum(runner.output / "json.json"),
                record["commands"][1]["stdout"]["sha256"],
            )

    def test_required_failure_is_written_before_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = base / "repo"
            repo.mkdir()
            runner = common.Recorder(repo, base / "result", "test")
            with self.assertRaises(RuntimeError):
                runner.run("negative", [sys.executable, "-c", "raise SystemExit(17)"])
            record = json.loads((runner.output / "RESULT.json").read_text())
            self.assertEqual(record["commands"][0]["exit_code"], 17)
            self.assertIn("log_sha256", record["commands"][0])


if __name__ == "__main__":
    unittest.main()

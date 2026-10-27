"""Real Git and controlled subprocess fixtures for the scoped Clippy tests."""

import argparse
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
import ndu_post_qualification_fix as fix


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.STDOUT)


class PostQualificationFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.target = self.base / "target"
        self.target.mkdir()
        self.tools = self.base / "tools"
        self.tools.mkdir()
        self.action = self.base / "action.json"
        self.action.write_text("{}")
        self.stamp = self.base / "fix-invocations.json"
        self.source = "codex-rs/hepta-matrix-sdk/src/lib.rs"
        self.yaml = "codex-rs/utils/yaml/src/lib.rs"
        self.vendor = "codex-rs/third_party/example-1.0.0"
        for name in (
            *common.LOCKS,
            *common.POLICIES,
            self.source,
            self.yaml,
            "codex-rs/hepta-matrixd/src/lib.rs",
            f"{self.vendor}/Cargo.toml",
        ):
            self.put(name, "original source\n")
        self.put(".gitignore", "ignored*\n")
        self.put(
            "justfile",
            "fix *args:\n    cargo clippy --fix --tests --allow-dirty {args}\n",
        )
        self.put("codex-rs/vendor/bubblewrap/LICENSE.target", "license\n")
        (self.root / "codex-rs/vendor/bubblewrap/LICENSE").symlink_to("LICENSE.target")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Controlled post qualification fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "config", "commit.gpgsign", "false")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "baseline")
        self.put(self.source, "reviewed candidate source\n")
        source_patch = git(
            self.root, "diff", "--binary", "--full-index", "--no-renames", "HEAD"
        )
        git(self.root, "checkout", "--", self.source)
        self.put("inputs/source.patch", source_patch)
        self.put("inputs/fixture.patch", "controlled fixture input\n")
        description = common.describe(self.root, ("inputs/fixture.patch",))[
            "inputs/fixture.patch"
        ]
        self.recipe = {
            "schema": "hepta.port-remediation.recipe.v1",
            "patch_path": "inputs/source.patch",
            "patch_sha256": common.checksum(self.root / "inputs/source.patch"),
            "allowed_paths": [self.source],
            "vendor_dirs": {self.vendor: common.tree_files(self.root / self.vendor)},
            "expected_packages": [
                {"name": "example", "version": "1.0.0", "source": "path"}
            ],
            "forbidden_packages": ["abandoned"],
            "cargo_updates": [{"package": "example", "precise": "1.0.0"}],
            "matrix_baseline": {
                "source_sha": common.OLD_SOURCE,
                "fixture_patch_path": "inputs/fixture.patch",
                "fixture_patch_sha256": description["sha256"],
            },
            "aws_qualification": {
                "vendor_dir": self.vendor,
                "resources": {
                    name: {"path": "inputs/fixture.patch", **description}
                    for name in ("Cargo.lock", ".config/nextest.toml")
                },
                "expected_total": 245,
                "expected_executed": 244,
                "expected_ignored": 1,
                "ignored_tests": ["ecs::test::real_dns_lookup"],
            },
        }
        self.put(common.RECIPE, json.dumps(self.recipe))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "sealed inputs")
        self.head = git(self.root, "rev-parse", "HEAD").decode().strip()
        git(self.root, "apply", "--index", str(self.root / "inputs/source.patch"))
        self.put(common.LOCKS[0], "candidate Cargo lock\n")
        self.put(common.LOCKS[1], "candidate Bazel lock\n")
        git(self.root, "add", "--", *common.LOCKS)
        self.artifact = self.base / "producer"
        self.artifact.mkdir()
        (self.artifact / "source.patch").write_bytes(source_patch)
        shutil.copyfile(self.root / common.RECIPE, self.artifact / "recipe.json")
        (self.artifact / "candidate.patch").write_bytes(
            git(self.root, "diff", "--binary", "--full-index", "--no-renames", "HEAD")
        )
        files = common.describe(self.root, (self.source, *common.LOCKS))
        common.copy_files(self.root, self.artifact / "files", files)
        self.candidate = {
            "schema": common.SCHEMA,
            "status": "candidate_generated",
            "source_commit": self.head,
            "original_dependency_policy_unchanged": True,
            "recipe_sha256": common.checksum(self.root / common.RECIPE),
            "policy_inputs": common.describe(self.root, common.POLICIES),
            "files": files,
            "changed_paths": sorted(files),
            "github_run_id": "controlled",
            "github_run_attempt": "1",
            "artifacts": common.describe(
                self.artifact, ("source.patch", "recipe.json", "candidate.patch")
            ),
        }
        (self.artifact / "RESULT.json").write_text(json.dumps(self.candidate))
        self.candidate_sha = common.checksum(self.artifact / "RESULT.json")
        self.consumer = self.base / "consumer"
        self.consumer.mkdir()
        self.make_test_receipt("matrix")
        self.make_tools()
        environment = {
            "PATH": str(self.tools) + os.pathsep + os.environ.get("PATH", ""),
            "CARGO_TARGET_DIR": str(self.target),
            "POSTFIX_TEST_ACTION": str(self.action),
            "POSTFIX_TEST_STAMP": str(self.stamp),
            "GITHUB_RUN_ID": "controlled",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        for key in (
            "RUSTC",
            "RUSTC_WRAPPER",
            "RUSTC_WORKSPACE_WRAPPER",
            "CARGO_BUILD_RUSTC",
            "CARGO_BUILD_RUSTC_WRAPPER",
            "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER",
            "CLIPPY_CONF_DIR",
            "CLIPPY_ARGS",
        ):
            environment[key] = ""
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.index_before = (self.root / ".git/index").read_bytes()

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else value.encode())

    def make_test_receipt(self, group):
        commands = []
        rows = []

        def command(argv):
            name = f"{len(commands):02d}-controlled.log"
            path = self.consumer / name
            path.write_text(
                "Controlled receipt fixture: no Rust behavior is represented.\n"
            )
            commands.append(
                {
                    "command": argv,
                    "cwd": str(self.root),
                    "exit_code": 0,
                    "log": name,
                    "log_bytes": path.stat().st_size,
                    "log_sha256": common.checksum(path),
                }
            )
            return len(commands) - 1

        for package in fix.GROUPS[group]["tests"]:
            index = command(
                [
                    "just",
                    "test",
                    "--locked",
                    "--cargo-profile",
                    "ci-test",
                    "-p",
                    package,
                ]
            )
            rows.append({"package": package, "exit_code": 0, "command_index": index})
        result = {
            "schema": common.SCHEMA,
            "mode": "test",
            "status": "targeted_tests_passed",
            "test_group": group,
            "failed_tests": [],
            "toolchain": "1.96.0",
            "original_dependency_policy_unchanged": True,
            "source_commit": self.head,
            "candidate_result_sha256": self.candidate_sha,
            "candidate_patch_sha256": self.candidate["artifacts"]["candidate.patch"][
                "sha256"
            ],
            "recipe_sha256": self.candidate["recipe_sha256"],
            "github_run_id": "controlled",
            "github_run_attempt": "1",
            "commands": commands,
            "test_results": rows,
        }
        if group == "matrix":
            binary = self.consumer / "binary.fixture"
            binary.write_bytes(b"Controlled retained binary fixture; never executed")
            junit = self.consumer / "reopen-junit.xml"
            junit.write_text(
                '<testsuites tests="1" failures="0" errors="0"><testsuite><testcase name="reopen_old_version_fixture" classname="codex-hepta-matrix-sdk::store_version_migration"/></testsuite></testsuites>'
            )
            config = self.consumer / "nextest-store.toml"
            store = str(self.consumer / "nextest-store")
            config.write_text("[store]\ndir = " + json.dumps(store) + "\n")
            storage = {
                "directory": store,
                "config_file": config.name,
                "config": common.describe(self.consumer, (config.name,))[config.name],
                "tool_config_argument": "hepta-port:" + str(config),
            }
            index = command(
                [
                    "just",
                    "test",
                    "--locked",
                    "--cargo-profile",
                    "ci-test",
                    "-p",
                    "codex-hepta-matrix-sdk",
                    "--test",
                    "store_version_migration",
                    "--tool-config-file",
                    storage["tool_config_argument"],
                    "--profile",
                    "default",
                    "--run-ignored",
                    "only",
                    "-E",
                    "test(=reopen_old_version_fixture)",
                    "--retries",
                    "0",
                    "--no-tests",
                    "fail",
                ]
            )
            result["migration_phase"] = {
                "name": "reopen_old_version_fixture",
                "exit_code": 0,
                "binary_unchanged_after_execution": True,
                "store_config_unchanged_after_execution": True,
                "fresh_junit_count": 1,
                "observed_junit_paths": [store + "/default/junit.xml"],
                "nextest_storage": storage,
                "command_index": index,
                "binary": binary.name,
                "binary_sha256": common.checksum(binary),
                "junit": {"file": junit.name, "sha256": common.checksum(junit)},
                "cargo_target_directory": str(self.target),
            }
            result["old_fixture_input"] = {
                "old_source": common.OLD_SOURCE,
                "driver_source": self.head,
                "recipe_sha256": self.candidate["recipe_sha256"],
                "producer_fixture_unchanged_after_reopen": True,
                "files_before_reopen": {"db": "controlled"},
                "files_after_reopen": {"db": "controlled reopened"},
            }
        self.test_record = result
        self.write_receipt()

    def write_receipt(self):
        (self.consumer / "RESULT.json").write_text(json.dumps(self.test_record))

    def make_tools(self):
        body = """import json, os
from pathlib import Path
import sys
name = Path(sys.argv[0]).name
action = json.loads(Path(os.environ["POSTFIX_TEST_ACTION"]).read_text())
if name == "rustup":
    print(Path(sys.argv[0]).parent / sys.argv[-1])
elif name == "rustc":
    print("rustc 1.96.0 controlled\\nrelease: 1.96.0")
elif name == "cargo":
    print("cargo 1.96.0 (controlled fixture)")
elif name in ("cargo-clippy", "clippy-driver"):
    print("clippy " + action.get("version", "0.1.96") + " (controlled fixture)")
elif name == "just" and sys.argv[1:] == ["--version"]:
    print("just 1.51.0 controlled")
elif name == "just":
    Path(os.environ["POSTFIX_TEST_STAMP"]).write_text(json.dumps(sys.argv[1:]))
    for path, content in action.get("writes", {}).items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    print("Controlled real subprocess completed; no Rust compiler invoked")
    sys.exit(action.get("exit", 0))
else:
    sys.exit(98)
"""
        for name in (
            "rustup",
            "rustc",
            "cargo",
            "cargo-clippy",
            "clippy-driver",
            "just",
        ):
            path = self.tools / name
            path.write_text("#!" + sys.executable + "\n" + body)
            path.chmod(0o755)

    def run_fix(self, group="matrix", *, name="fix-output", action=None):
        if action is not None:
            self.action.write_text(json.dumps(action))
        args = argparse.Namespace(
            repository=self.root,
            output=self.base / name,
            candidate=self.artifact,
            expected_source=self.head,
            expected_result_sha256=self.candidate_sha,
            group=group,
            test_result=self.consumer / "RESULT.json",
        )
        status = fix.execute(args)
        output = args.output
        return status, json.loads((output / "RESULT.json").read_text()), output

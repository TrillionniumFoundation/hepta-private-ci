"""Only provenance guards, using tiny synthetic files; no native qualification."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from b16_build_only import MODE, load_build_only, observed_host, verify_current_outputs
from b16_capacity import cache_and_capacity
from b16_family import load_family
from b16_guard import record
from b16_native import HELPERS


class BuildOnlyGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-b16-build-only-guard-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.target = self.root / "source", self.root / "target"
        self.source.mkdir()
        self.target.mkdir()
        frozen_path = Path(__file__).parent / "foundation-output-family.json"
        self.family = json.loads(frozen_path.read_bytes())
        self.names = [Path(path).name for path in self.family["complete_helper_relative_paths"]]
        package_names = sorted({row["package_name"] for row in self.family["complete_catalog_layout"]} | set(HELPERS))
        package_names += ["inactive-fixture-" + str(n) for n in range(193 - len(package_names))]
        ids = {name: "path+file://" + str(self.source / name) + "#" + name for name in package_names}
        self.metadata = {
            "workspace_root": str(self.source / "codex-rs"), "target_directory": str(self.target),
            "workspace_members": list(ids.values()), "workspace_default_members": list(ids.values()),
            "resolve": {"nodes": [{"id": value, "features": [], "deps": []} for value in ids.values()] +
                                 [{"id": "registry-fixture-" + str(n), "features": [], "deps": []} for n in range(1501 - len(ids))]},
            "packages": [{"id": value, "name": name, "manifest_path": str(self.source / name / "Cargo.toml"),
                          "features": {}, "targets": []} for name, value in ids.items()],
        }
        self.metadata["packages"] += [{"id": "registry-fixture-" + str(n), "name": "registry-fixture-" + str(n),
            "manifest_path": str(self.root / "registry" / str(n) / "Cargo.toml"), "features": {}, "targets": []}
            for n in range(1501 - len(ids))]
        helpers = [self.executable("dev-small/" + name) for name in self.names]
        programs, suites = [], {}
        for row in self.family["complete_catalog_layout"]:
            program = {"binary_id": row["binary_id"], **self.executable(row["relative_path"])}
            programs.append(program)
            suites[row["binary_id"]] = {
                "binary-name": row["binary_name"], "package-name": row["package_name"],
                "package-id": ids[row["package_name"]], "kind": row["kind"], "build-platform": row["build_platform"],
                "binary-path": program["path"], "testcases": {"fixture": {"filter-match": {"status": "matches"}}},
            }
        self.catalog = {"rust-build-meta": {"target-directory": str(self.target),
                           "non-test-binaries": [{"kind": "bin-exe", "path": row["path"]} for row in helpers]},
                        "rust-suites": suites}
        normal, messages = [], []
        argv = ["cargo", "build", "--locked", "--profile", "dev-small", "--message-format=json-render-diagnostics"]
        for package, binaries in HELPERS.items():
            argv += ["-p", package]
            for binary in binaries:
                argv += ["--bin", binary]
                path = self.target / "dev-small" / binary
                normal.append({"target": binary, "package_id": ids[package], "features": [], "fresh": False, **record(path)})
                messages.append({"reason": "compiler-artifact", "target": {"name": binary}, "package_id": ids[package],
                                 "features": [], "fresh": False, "executable": str(path)})
        messages.append({"reason": "build-finished", "success": True})
        outputs = [self.write("normal.log", "".join(json.dumps(row) + "\n" for row in messages)),
                   self.write("metadata.json", self.metadata), self.write("catalog.json", self.catalog)]
        commands = []
        argvs = [argv, ["cargo", "metadata", "--locked", "--format-version=1"],
                 ["cargo", "nextest", "list", "--locked", "--cargo-profile", "dev-small", "--message-format=json"]]
        tree, head = "4" * 40, "2" * 40
        for index, args in enumerate(argvs):
            commands.append({"argv": args, "cwd": str(self.source / "codex-rs"), "exit_code": 0,
                             "source_before": tree, "source_after": tree, "stdout": outputs[index],
                             "stderr": self.write(str(index) + ".stderr", "")})
        index = self.write("ordinary-index", "fixture ordinary index")
        locks = {name: self.write(name.replace("/", "-"), "fixture lock " + name)
                 for name in ("codex-rs/Cargo.lock", "MODULE.bazel.lock")}
        tools = [{"name": name, **self.write("tool-" + name, "fixture " + name)}
                 for name in ("git", "cargo", "rustc", "just", "cargo-nextest", "bazel")]
        recipes = [{"path": name, "bytes": 1, "sha256": "a" * 64}
                   for name in ("justfile", "scripts/run-nextest.py", "scripts/check-module-bazel-lock.sh", ".bazelrc", "defs.bzl")]
        historical = {"source": self.family["last_tested_A_tree"], "cargo_profile": "dev-small", "nextest_profile": "local",
                      "packages": package_names,
                      "helpers_after_catalog_before_just": [{**row, "path": "/historical-rog/dev-small/" + Path(row["path"]).name} for row in helpers]}
        historical_pin = self.write("historical-tested-A.json", historical)
        self.binding = {
            "authorized_epoch": "foundation", "target_reuse_mode": MODE, "final_A_tree": tree, "initial_tree": tree,
            "ordinary_head": head, "ordinary_index": index, "locks": locks, "tools": tools, "recipe_sources": recipes,
            "source_directory": str(self.source), "target_directory": str(self.target),
            "final_A_target_directory": "/historical-rog/target", "build_only_cache_owner": "synthetic-guard-fixture",
            "build_only_host": {"alias": "synthetic-test-host", **observed_host()},
            "last_tested_A_tree": self.family["last_tested_A_tree"], "last_tested_A_artifacts": historical_pin,
            "last_tested_A_to_final_A_review": "synthetic-relation-only", "A_helper_basename_roster": self.names,
            "baseline_metadata": {**outputs[1], "source_tree": tree}, "environment": {"CARGO_BUILD_JOBS": "4"},
        }
        guard = {"working_tree": tree, "head_tree": tree, "head": head, "ordinary_index": index,
                 "guarded_files": [{**row, "path": str(self.source / key)} for key, row in locks.items()], "untracked": []}
        self.receipt = {
            "schema": "hepta-b16-current-host-build-only-baseline-v1", "role": MODE, "tests_executed": False,
            "test_qualification": False, "host": self.binding["build_only_host"], "cache_owner": self.binding["build_only_cache_owner"],
            "source_tree": tree, "source_commit": head, "source_directory": str(self.source), "target_directory": str(self.target),
            "ordinary_index": index, "locks": locks, "cargo_profile": "dev-small", "tools": tools, "recipe_sources": recipes,
            "environment": self.binding["environment"], "source_guards": [self.write("guard-" + str(n) + ".json", guard) for n in range(6)],
            "commands": commands, "metadata": outputs[1], "catalog": outputs[2], "normal_helpers_before_catalog": normal,
            "normal_helpers_after_catalog": [{"target": row["target"], **record(row["path"])} for row in normal],
            "programs_after_catalog": programs, "helpers_after_catalog": helpers,
        }
        self.pin_receipt()

    def write(self, name, content):
        path = self.root / name
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        return record(path)

    def executable(self, relative):
        path = self.target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic artifact; never executed\n")
        path.chmod(0o700)
        return record(path)

    def pin_receipt(self):
        self.binding["current_host_build_only_baseline"] = self.write("build-only.json", self.receipt)

    def test_actual_context_is_accepted_but_different_host_or_source_is_rejected(self):
        context = load_build_only(self.binding)
        verify_current_outputs(context)
        self.assertFalse(context["receipt"]["tests_executed"])
        self.assertFalse(context["receipt"]["test_qualification"])
        for field, replacement in (("build_only_host", {"alias": "another-host", **observed_host()}), ("final_A_tree", "8" * 40)):
            changed = copy.deepcopy(self.binding)
            changed[field] = replacement
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                load_build_only(changed)

    def test_missing_physical_program_is_rejected_after_complete_receipt(self):
        context = load_build_only(self.binding)
        Path(self.receipt["programs_after_catalog"][0]["path"]).unlink()
        with self.assertRaisesRegex(RuntimeError, "artifact is missing"):
            verify_current_outputs(context)

    def test_build_only_cannot_masquerade_as_tested_or_hide_failed_build(self):
        for field, value in (("tests_executed", True), ("test_qualification", True)):
            self.receipt[field] = value
            self.pin_receipt()
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "without A test qualification"):
                load_build_only(self.binding)
            self.receipt[field] = False
        self.receipt["commands"][2]["exit_code"] = 1
        self.pin_receipt()
        with self.assertRaisesRegex(RuntimeError, "zero return code"):
            load_build_only(self.binding)
        self.receipt["commands"][2]["exit_code"] = 0
        self.pin_receipt()
        changed = copy.deepcopy(self.binding)
        changed["target_reuse_mode"] = "reuse_final_A"
        changed["last_tested_A_artifacts"] = changed["current_host_build_only_baseline"]
        with self.assertRaisesRegex(RuntimeError, "not historical tested-A"):
            cache_and_capacity(changed, self.metadata)

    def test_original_family_remains_historical_and_current_family_does_not_relabel_it(self):
        family_pin = record(Path(__file__).parent / "foundation-output-family.json")
        binding = {**self.binding, "approved_foundation_output_family_sha256": family_pin["sha256"]}
        # This original file is the actual old family object, not relabeled data.
        binding["last_tested_A_artifacts"]["sha256"] = self.family["last_tested_A_artifact_sha256"]
        binding["target_reuse_mode"] = "reuse_final_A"
        self.assertEqual(load_family(binding), self.family)
        # Restore the test-only receipt pin and exercise the new branch separately.
        binding["last_tested_A_artifacts"] = record(self.root / "historical-tested-A.json")
        binding["target_reuse_mode"] = MODE
        from b16_build_only import current_family
        current = current_family(binding, self.family)
        self.assertEqual(current["source_tree"], self.binding["final_A_tree"])
        self.assertNotIn("last_tested_A_tree", current)
        self.assertEqual(current["historical_roster_reference"]["source_tree"], self.family["last_tested_A_tree"])
        self.assertFalse(current["test_qualification"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

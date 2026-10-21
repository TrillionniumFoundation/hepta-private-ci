"""Behavioral regressions for exact-revision Cargo impact selection."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "hepta_ci_dependencies.py"
spec = importlib.util.spec_from_file_location("hepta_ci_dependencies", SCRIPT)
ci = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ci
spec.loader.exec_module(ci)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.graph = ci.Graph(
            {f"codex-rs/{n}": n for n in ("leaf", "owner", "host", "unrelated")},
            frozenset({("leaf", "owner", False), ("owner", "host", False)}),
        )

    def test_reverse_transitive_closure_not_all_packages(self):
        result = ci.select_packages(
            ["codex-rs/leaf/src/lib.rs"], self.graph, self.graph
        )
        self.assertEqual(
            result,
            {
                "packages": ["host", "leaf", "owner"],
                "full_workspace": False,
                "changed_packages": ["leaf"],
                "reasons": [],
            },
        )

    def test_does_not_run_dependencies_own_unrelated_tests(self):
        result = ci.select_packages(
            ["codex-rs/host/src/lib.rs"], self.graph, self.graph
        )
        self.assertEqual(result["packages"], ["host"])

    def test_dev_edge_selects_direct_consumer_not_its_downstream(self):
        graph = ci.Graph(
            self.graph.owners,
            frozenset({("leaf", "owner", True), ("owner", "host", False)}),
        )
        self.assertEqual(
            ci.select_packages(["codex-rs/leaf/tests/a.rs"], graph, graph)["packages"],
            ["leaf", "owner"],
        )

    def test_normal_edge_dominates_parallel_dev_edge(self):
        graph = ci.Graph(
            self.graph.owners, self.graph.edges | {("leaf", "owner", True)}
        )
        self.assertEqual(
            ci.select_packages(["codex-rs/leaf/src/lib.rs"], graph, graph)["packages"],
            ["host", "leaf", "owner"],
        )

    def test_removed_dependency_edge_is_not_lost(self):
        after = ci.Graph(self.graph.owners, frozenset())
        self.assertEqual(
            ci.select_packages(["codex-rs/leaf/Cargo.toml"], self.graph, after)[
                "packages"
            ],
            ["host", "leaf", "owner"],
        )

    def test_removed_package_is_not_passed_to_cargo(self):
        after = ci.Graph(
            {k: v for k, v in self.graph.owners.items() if v != "leaf"}, frozenset()
        )
        self.assertEqual(
            ci.select_packages(["codex-rs/leaf/src/lib.rs"], self.graph, after)[
                "packages"
            ],
            ["host", "owner"],
        )

    def test_same_directory_package_rename_keeps_old_consumers(self):
        after = ci.Graph(self.graph.owners | {"codex-rs/leaf": "new-leaf"}, frozenset())
        self.assertEqual(
            ci.select_packages(["codex-rs/leaf/Cargo.toml"], self.graph, after)[
                "packages"
            ],
            ["host", "new-leaf", "owner"],
        )

    def test_shared_unknown_and_build_inputs_fall_back(self):
        for path in (
            "codex-rs/Cargo.lock",
            "codex-rs/owner/build.rs",
            "assets/table.bin",
            ".github/workflows/test.yml",
            "scripts/hepta_ci_scope.py",
        ):
            with self.subTest(path=path):
                result = ci.select_packages([path], self.graph, self.graph)
                self.assertTrue(result["full_workspace"])
                self.assertEqual(result["packages"], sorted(self.graph.owners.values()))

    def test_invalid_paths_rejected(self):
        for path in ("", "/tmp/file", "codex-rs/../other", "foo\\bar", "a\0b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                ci.select_packages([path], self.graph, self.graph)

    def test_empty_exact_diff_runs_no_native_tests(self):
        self.assertEqual(ci.select_packages([], self.graph, self.graph)["packages"], [])


class ShardedExecutionTests(unittest.TestCase):
    def test_all_reverse_consumers_are_covered_exactly_once(self):
        source = {
            "packages": ["agentd", "codec", "executor", "infer", "ledger", "wire", "worker"],
            "full_workspace": False,
            "changed_packages": ["infer"],
            "reasons": [],
        }
        shards = [ci.shard_execution_plan(source, index=i, count=4) for i in range(4)]
        self.assertEqual(source["packages"], [
            "agentd", "codec", "executor", "infer", "ledger", "wire", "worker"
        ])
        self.assertEqual(
            sorted(name for plan in shards for name in plan["packages"]),
            source["packages"],
        )
        self.assertEqual(
            len(set(name for plan in shards for name in plan["packages"])),
            len(source["packages"]),
        )
        self.assertEqual({p["shard"]["count"] for p in shards}, {4})
        self.assertEqual(
            {p["shard"]["full_selection_sha256"] for p in shards},
            {shards[0]["shard"]["full_selection_sha256"]},
        )
        self.assertTrue(all(p["full_workspace"] is False for p in shards))
        for shard in shards:
            self.assertEqual(
                ci.execution_command(shard, "test"),
                ["just", "test", "--locked", *sum(
                    (["-p", package] for package in shard["packages"]), []
                )],
            )

    def test_conservative_full_workspace_fallback_is_sharded_not_waived(self):
        source = {
            "packages": ["agentd", "codec", "executor", "infer", "ledger"],
            "full_workspace": True,
            "changed_packages": [],
            "reasons": ["shared CI input: scripts/hepta_ci_dependencies.py"],
        }
        shards = [ci.shard_execution_plan(source, index=i, count=4) for i in range(4)]
        self.assertEqual(
            sorted(p for shard in shards for p in shard["packages"]),
            source["packages"],
        )
        self.assertTrue(all(shard["shard"]["original_full_workspace"] for shard in shards))
        self.assertTrue(all(shard["reasons"] == source["reasons"] for shard in shards))
        self.assertTrue(all("--workspace" not in ci.execution_command(shard, "test")
                            for shard in shards))

    def test_missing_or_duplicate_tests_cannot_enter_the_shard_planner(self):
        for bad in [
            ["b", "a"], ["a", "a"], ["a", "b", "a"]
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ci.shard_execution_plan({"packages": bad, "full_workspace": False},
                                        index=0, count=2)
        source = {"packages": ["a", "b"], "full_workspace": False}
        for index, count in [(-1, 4), (4, 4), (0, 0), (0, 9)]:
            with self.subTest(index=index, count=count), self.assertRaises(ValueError):
                ci.shard_execution_plan(source, index=index, count=count)
        with self.assertRaises(ValueError):
            ci.shard_execution_plan(source, index=True, count=4)

    def test_empty_shards_do_not_invent_successful_test_invocations(self):
        source = {"packages": ["neuron"], "full_workspace": False}
        outputs = [ci.shard_execution_plan(source, index=i, count=4) for i in range(4)]
        self.assertEqual([p["packages"] for p in outputs], [["neuron"], [], [], []])
        self.assertIsNone(ci.execution_command(outputs[1], "test"))
        self.assertEqual(ci.execution_command(outputs[0], "test"),
                         ["just", "test", "--locked", "-p", "neuron"])


class GitGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI regression")
        self.git("config", "user.email", "ci@example.invalid")
        self.write(
            "codex-rs/Cargo.toml",
            """[workspace]
members = ["leaf", "owner", "host", "unrelated"]
[workspace.dependencies]
renamed = { package = "leaf", path = "leaf" }
""",
        )
        for name in ("leaf", "owner", "host", "unrelated"):
            self.write(
                f"codex-rs/{name}/Cargo.toml",
                f'[package]\nname = "{name}"\nversion = "0.1.0"\n',
            )
            self.write(f"codex-rs/{name}/src/lib.rs", "pub fn value() -> u32 { 1 }\n")
        self.base = self.commit()

    def git(self, *args):
        return ci.git(self.root, *args).decode().strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_workspace_alias_optional_target_and_build_dependencies(self):
        with (self.root / "codex-rs/owner/Cargo.toml").open("a") as stream:
            stream.write(
                "[target.'cfg(windows)'.dependencies]\nrenamed = { workspace = true, optional = true }\n"
            )
        with (self.root / "codex-rs/host/Cargo.toml").open("a") as stream:
            stream.write('[build-dependencies]\nowner = { path = "../owner" }\n')
        head = self.commit()
        graph = ci.graph(self.root, head)
        self.assertEqual(
            graph.edges, {("leaf", "owner", False), ("owner", "host", False)}
        )
        self.assertEqual(
            ci.select_packages(["codex-rs/leaf/src/lib.rs"], graph, graph)["packages"],
            ["host", "leaf", "owner"],
        )

    def test_git_diff_is_zero_delimited_and_base_is_exact(self):
        self.write("codex-rs/leaf/src/a\nfile.rs", "// changed\n")
        head = self.commit()
        self.assertEqual(ci.plan(self.root, self.base, head)["packages"], ["leaf"])
        self.assertTrue(ci.plan(self.root, "missing", head)["full_workspace"])
        self.assertTrue(ci.plan(self.root, "f" * 40, head)["full_workspace"])

    def test_glob_members_and_excludes(self):
        self.write(
            "codex-rs/Cargo.toml",
            '[workspace]\nmembers = ["*"]\nexclude = ["unrelated"]\n',
        )
        head = self.commit()
        self.assertEqual(
            set(ci.graph(self.root, head).owners.values()), {"leaf", "owner", "host"}
        )

    def test_cli_rejects_dirty_or_wrong_checkout(self):
        command = [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(self.root),
            "--base",
            self.base,
        ]
        wrong = subprocess.run(command + ["--tested", "f" * 40], capture_output=True)
        self.assertNotEqual(wrong.returncode, 0)
        clean = subprocess.run(command + ["--tested", self.base], capture_output=True)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(json.loads(clean.stdout)["packages"], [])
        # A caller cannot ask for an unpaired or unsupported shard action.
        for bad_flags in (
            ["--test-shard-index", "0"],
            ["--test-shard-index", "0", "--test-shard-count", "4"],
            ["--action", "test", "--test-shard-index", "4", "--test-shard-count", "4"],
        ):
            denied = subprocess.run(
                command + ["--tested", self.base, *bad_flags],
                capture_output=True,
            )
            self.assertNotEqual(denied.returncode, 0)
        valid = subprocess.run(
            command + [
                "--tested", self.base, "--action", "test",
                "--test-shard-index", "0", "--test-shard-count", "4",
            ],
            capture_output=True,
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        exact = json.loads(valid.stdout)
        self.assertEqual(exact["shard"]["count"], 4)
        self.assertEqual(exact["packages"], [])
        self.write("codex-rs/leaf/src/lib.rs", "// dirty\n")
        dirty = subprocess.run(command + ["--tested", self.base], capture_output=True)
        self.assertNotEqual(dirty.returncode, 0)

    def test_malformed_head_does_not_silently_skip(self):
        self.write("codex-rs/Cargo.toml", "this is not toml")
        head = self.commit()
        with self.assertRaises(tomllib.TOMLDecodeError):
            ci.plan(self.root, self.base, head)


class DocumentInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Regression")
        self.git("config", "user.email", "regression@example.invalid")
        self.write(
            "codex-rs/Cargo.toml", '[workspace]\nmembers=["leaf","host","other"]\n'
        )
        for name in ("leaf", "host", "other"):
            self.write(
                f"codex-rs/{name}/Cargo.toml",
                f'[package]\nname="{name}"\nversion="0.1.0"\n',
            )
            self.write(f"codex-rs/{name}/src/lib.rs", "pub fn value() -> u32 { 1 }\n")
        self.write(
            "codex-rs/host/Cargo.toml",
            '[package]\nname="host"\nversion="0.1.0"\n[dependencies]\nleaf={path="../leaf"}\n',
        )
        self.doc = "docs/modules/example/TECHNICAL.md"
        self.write(self.doc, "# Module\n")
        self.base = self.commit()

    def git(self, *args):
        return ci.git(self.root, *args).decode().strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_code_and_module_guide_stay_scoped(self):
        self.write("codex-rs/leaf/src/lib.rs", "pub fn value() -> u32 { 2 }\n")
        self.write(self.doc, "# Updated explanation\n")
        result = ci.plan(self.root, self.base, self.commit())
        self.assertFalse(result["full_workspace"])
        self.assertEqual(result["packages"], ["host", "leaf"])

    def test_pure_documentation_requires_no_cargo(self):
        self.write(self.doc, "# Only explanation changed\n")
        result = ci.plan(self.root, self.base, self.commit())
        self.assertFalse(result["full_workspace"])
        self.assertEqual(result["packages"], [])

    def test_embedded_markdown_still_selects_its_consumer(self):
        self.write(
            "codex-rs/leaf/src/lib.rs",
            'const DOC: &str = include_str!("../../../' + self.doc + '");\n',
        )
        base = self.commit()
        self.write(self.doc, "# Compiled input changed\n")
        result = ci.plan(self.root, base, self.commit())
        self.assertFalse(result["full_workspace"])
        self.assertEqual(result["packages"], ["host", "leaf"])

    def test_removed_include_edge_keeps_former_consumer(self):
        self.write(
            "codex-rs/leaf/src/lib.rs",
            'const DOC: &str = include_str!("../../../' + self.doc + '");\n',
        )
        base = self.commit()
        self.write("codex-rs/leaf/src/lib.rs", "// include removed\n")
        self.write(self.doc, "# Updated\n")
        self.assertEqual(
            ci.plan(self.root, base, self.commit())["packages"], ["host", "leaf"]
        )

    def test_rust_includes_follow_external_rust_sources(self):
        self.write(
            "codex-rs/leaf/src/lib.rs", 'include!("../../../shared/helper.rs");\n'
        )
        self.write(
            "shared/helper.rs",
            'const DOC: &str = include_str!("../' + self.doc + '");\n',
        )
        base = self.commit()
        self.write(self.doc, "# Transitive input\n")
        self.assertEqual(
            ci.plan(self.root, base, self.commit())["packages"], ["host", "leaf"]
        )

    def test_raw_multiline_include_and_filename_newline(self):
        self.write(
            "codex-rs/leaf/src/a\nfile.rs",
            'const DOC: &str = include_str! (\nr##"../../../' + self.doc + '"##\n);\n',
        )
        base = self.commit()
        self.write(self.doc, "# Raw-string input\n")
        self.assertEqual(
            ci.plan(self.root, base, self.commit())["packages"], ["host", "leaf"]
        )

    def test_computed_include_is_conservative_per_consumer(self):
        self.write(
            "codex-rs/leaf/src/lib.rs",
            'const DOC: &str = include_str!(concat!(env!("ROOT"), "/guide.md"));\n',
        )
        base = self.commit()
        self.write(self.doc, "# Potential computed input\n")
        self.assertEqual(
            ci.plan(self.root, base, self.commit())["packages"], ["host", "leaf"]
        )

    def test_unrelated_workspace_does_not_force_all_packages(self):
        self.write(
            "apps/independent/src/lib.rs",
            'const X: &str = include_str!(concat!(env!("ROOT"), "/x"));\n',
        )
        base = self.commit()
        self.write(self.doc, "# Plain prose\n")
        self.assertEqual(ci.plan(self.root, base, self.commit())["packages"], [])

    def test_canonical_json_is_not_classified_as_prose(self):
        self.write("docs/modules/MODULES.json", '{"modules":[]}\n')
        self.assertTrue(ci.plan(self.root, self.base, self.commit())["full_workspace"])

    def test_embedded_catalog_has_real_dependency(self):
        path = "docs/modules/MODULES.json"
        self.write(path, "{}\n")
        self.write(
            "codex-rs/leaf/src/lib.rs",
            'const C: &str = include_str!("../../../' + path + '");\n',
        )
        base = self.commit()
        self.write(path, '{"modules":[]}\n')
        result = ci.plan(self.root, base, self.commit())
        self.assertFalse(result["full_workspace"])
        self.assertEqual(result["packages"], ["host", "leaf"])

    def test_unknown_input_plus_prose_still_falls_back(self):
        self.write("assets/unknown.dat", "input")
        self.write(self.doc, "# Updated\n")
        self.assertTrue(ci.plan(self.root, self.base, self.commit())["full_workspace"])

    def test_missing_base_does_not_become_document_only_success(self):
        self.write(self.doc, "# Updated\n")
        self.assertTrue(ci.plan(self.root, "f" * 40, self.commit())["full_workspace"])

    def test_outer_scope_keeps_plain_documentation_lightweight(self):
        self.write(self.doc, "# Only explanation changed\n")
        head = self.commit()
        scope_script = SCRIPT.with_name("hepta_ci_scope.py")
        result = subprocess.run(
            [sys.executable, str(scope_script), "--base", self.base, "--head", head],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertFalse(json.loads(result.stdout)["scope"]["native"])

    def test_outer_scope_cannot_skip_an_embedded_document(self):
        self.write(
            "codex-rs/leaf/src/lib.rs",
            'const DOC: &str = include_str!("../../../' + self.doc + '");\n',
        )
        base = self.commit()
        self.write(self.doc, "# Compiled input changed\n")
        head = self.commit()
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT.with_name("hepta_ci_scope.py")),
                "--base",
                base,
                "--head",
                head,
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertTrue(json.loads(result.stdout)["scope"]["native"])


if __name__ == "__main__":
    unittest.main()

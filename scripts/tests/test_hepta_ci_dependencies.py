"""Behavioral regressions for exact-revision Cargo impact selection."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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


class FixturePreparationTests(unittest.TestCase):
    def invoke(
        self,
        *,
        packages=("codex-arg0", "codex-core"),
        action="test",
        platform="linux",
        full=False,
        results=(0, 0),
        dirty=False,
        source_error=False,
        record_output=None,
        compatibility_run=False,
    ):
        root = Path(tempfile.gettempdir()) / "fixture workspace with spaces"
        tested = "a" * 40
        selected = {
            "packages": list(packages),
            "full_workspace": full,
            "changed_packages": [],
            "reasons": [],
        }
        argv = ["dependencies", "--root", str(root), "--tested", tested]
        argv += ["--run"] if compatibility_run else ["--action", action]
        if full:
            argv += ["--full"]
        if record_output:
            argv += ["--record-output", str(record_output)]
        diff_calls = 0

        def git(_root, *args):
            nonlocal diff_calls
            self.assertEqual(_root, root)
            if args == ("rev-parse", "HEAD"):
                return tested.encode()
            self.assertEqual(args, ("diff", "--no-ext-diff", "--quiet", "HEAD", "--"))
            diff_calls += 1
            if diff_calls == 2:
                if source_error:
                    raise OSError("source check unavailable")
                if dirty:
                    raise subprocess.CalledProcessError(1, ["git", "diff"])
            return b""

        outputs = [
            value
            if isinstance(value, BaseException)
            else subprocess.CompletedProcess([], value)
            for value in results
        ]
        stream = io.StringIO()
        code = 0
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(sys, "platform", platform),
            mock.patch.object(ci, "plan", return_value=selected) as planned,
            mock.patch.object(ci, "git", side_effect=git),
            mock.patch.object(ci.subprocess, "run", side_effect=outputs) as run,
            redirect_stdout(stream),
        ):
            try:
                ci.main()
            except SystemExit as error:
                code = error.code
        planned.assert_called_once_with(root, None, tested, force_full=full)
        calls = [(call.args[0], call.kwargs) for call in run.call_args_list]
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(
            records[0], {"tested_sha": tested, "base_sha": None, **selected}
        )
        for _, kwargs in calls:
            self.assertEqual(kwargs, {"cwd": root / "codex-rs", "check": False})
        return code, calls, records[1:]

    def test_build_precedes_unchanged_scoped_or_full_suite(self):
        for full, compatibility_run in ((False, False), (True, False), (False, True)):
            with self.subTest(full=full, compatibility_run=compatibility_run):
                code, calls, records = self.invoke(
                    full=full, compatibility_run=compatibility_run
                )
                self.assertEqual(code, 0)
                self.assertEqual(
                    calls[0][0],
                    [
                        "cargo",
                        "build",
                        "--locked",
                        "-p",
                        "codex-arg0",
                        "--bin",
                        "test_arg0_preflight",
                    ],
                )
                self.assertEqual(
                    calls[1][0],
                    [
                        "just",
                        "test",
                        "--locked",
                        *(
                            ["--workspace"]
                            if full
                            else ["-p", "codex-arg0", "-p", "codex-core"]
                        ),
                    ],
                )
                self.assertEqual(
                    [item["status"] for item in records], ["running", "passed"]
                )
                self.assertEqual(records[-1]["exit_code"], 0)
                self.assertIs(records[-1]["source_unchanged"], True)

    def test_preparation_is_limited_to_selected_linux_tests(self):
        cases = [
            {"packages": ("codex-core",)},
            {"packages": ("codex-core",), "full": True},
            {"packages": ()},
            {"action": "plan"},
            {"action": "fmt"},
            {"action": "clippy"},
            {"platform": "darwin"},
            {"platform": "win32"},
        ]
        for case in cases:
            with self.subTest(case=case):
                code, calls, records = self.invoke(**case)
                self.assertEqual(code, 0)
                self.assertEqual(records, [])
                self.assertLessEqual(len(calls), 1)
                self.assertTrue(
                    all(command[:2] != ["cargo", "build"] for command, _ in calls)
                )

    def test_build_failure_or_signal_stops_suite_and_preserves_exit(self):
        for returncode, expected in ((7, 7), (101, 101), (-15, 143), (-9, 137)):
            with self.subTest(returncode=returncode):
                code, calls, records = self.invoke(results=(returncode,))
                self.assertEqual(code, expected)
                self.assertEqual(len(calls), 1)
                self.assertEqual(records[-1]["returncode"], returncode)
                self.assertEqual(records[-1]["exit_code"], expected)
                self.assertEqual(records[-1]["status"], "failed")

    def test_dirty_preparation_stops_suite_without_hiding_build_exit(self):
        for returncode, expected in ((0, 1), (7, 7)):
            with self.subTest(returncode=returncode):
                code, calls, records = self.invoke(results=(returncode,), dirty=True)
                self.assertEqual(code, expected)
                self.assertEqual(len(calls), 1)
                self.assertIs(records[-1]["source_unchanged"], False)

    def test_dispatch_or_post_build_source_error_is_not_success(self):
        for options in (
            {"results": (OSError("cargo absent"),)},
            {"source_error": True},
        ):
            with self.subTest(options=options):
                code, calls, records = self.invoke(**options)
                self.assertEqual(code, 2)
                self.assertEqual(len(calls), 1)
                self.assertEqual(records[-1]["status"], "failed")
                self.assertIn("error", records[-1])

    def test_original_suite_nonzero_and_signal_exit_are_preserved(self):
        for result, expected in ((100, 100), (-15, 143)):
            with self.subTest(result=result):
                code, calls, records = self.invoke(results=(0, result))
                self.assertEqual(code, expected)
                self.assertEqual(len(calls), 2)
                self.assertEqual(records[-1]["status"], "passed")

    def test_explicit_records_use_distinct_paths_and_keep_suite_command(self):
        output = Path(tempfile.gettempdir()) / "receipts with spaces" / "suite.json"
        code, calls, records = self.invoke(record_output=output)
        self.assertEqual(code, 0)
        prefix = [sys.executable, str(SCRIPT.with_name("hepta_ci_exec.py")), "--output"]
        preparation_output = str(
            output.resolve().with_name(output.name + ".arg0-preflight-build.json")
        )
        self.assertEqual(
            calls[0][0],
            [
                *prefix,
                preparation_output,
                "--",
                "cargo",
                "build",
                "--locked",
                "-p",
                "codex-arg0",
                "--bin",
                "test_arg0_preflight",
            ],
        )
        self.assertEqual(
            calls[1][0],
            [
                *prefix,
                str(output.resolve()),
                "--",
                "just",
                "test",
                "--locked",
                "-p",
                "codex-arg0",
                "-p",
                "codex-core",
            ],
        )
        self.assertEqual(records[-1]["record_output"], preparation_output)


if __name__ == "__main__":
    unittest.main()

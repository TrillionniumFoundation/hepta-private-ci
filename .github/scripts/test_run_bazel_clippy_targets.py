#!/usr/bin/env python3
"""Keep native Clippy helpers complete while honoring their declared platform."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
NATIVE = "//codex-rs/core:core-all-test-bin"
CROSS = "//codex-rs/core:core-all-test-windows-cross-bin"
UNIT = "//codex-rs/hepta-neuron:hepta-neuron-unit-tests-bin"
UNIX = "//codex-rs/hepta-agentd:hepta-agentd-cognitive-readonly-product-test-bin"
OTHER_NATIVE = "//codex-rs/example:another-compatible-test-bin"
PREFIX = ["//codex-rs/...", "-//codex-rs/v8-poc:all"]
QUERY = 'kind("rust_test rule", attr(tags, "manual", //codex-rs/... except //codex-rs/v8-poc/...))'


class ClippyTargetSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (
            "scripts/list-bazel-clippy-targets.sh",
            ".github/scripts/run-bazel-query-ci.sh",
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            target.chmod(0o755)
        self.selector = self.root / "scripts/list-bazel-clippy-targets.sh"
        self.query = self.root / ".github/scripts/run-bazel-query-ci.sh"
        wrapper = self.root / ".github/scripts/run_bazel_with_buildbuddy.py"
        wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "record = {'args': sys.argv[1:], 'msys': os.environ.get('MSYS2_ARG_CONV_EXCL')}\n"
            "for arg in sys.argv[1:]:\n"
            "    if arg.startswith('--query_file='):\n"
            "        record['query_file'] = arg.split('=', 1)[1]\n"
            "        record['query_text'] = pathlib.Path(record['query_file']).read_text()\n"
            "history = pathlib.Path(os.environ['CLIPPY_QUERY_ARGUMENTS'])\n"
            "calls = json.loads(history.read_text()) if history.exists() else []\n"
            "history.write_text(json.dumps(calls + [record]))\n"
            "stage = sys.argv[1]\n"
            "if os.environ.get('CLIPPY_QUERY_FAIL') == '1' or os.environ.get('CLIPPY_QUERY_STAGE_FAIL') == stage:\n"
            f"    print({UNIT!r}); sys.exit(29 if stage == 'query' else 37)\n"
            f"raw = {[UNIT, NATIVE, CROSS, UNIX, OTHER_NATIVE]!r}\n"
            f"configured = {[UNIT, NATIVE, '', '', OTHER_NATIVE]!r}\n"
            "inputs = json.loads(pathlib.Path(os.environ['CLIPPY_QUERY_INPUTS']).read_text())\n"
            "raw = inputs.get('raw', raw); configured = inputs.get('configured', configured)\n"
            "selected = configured if stage == 'cquery' else raw\n"
            "if os.environ.get('CLIPPY_QUERY_EMPTY') == '1' or os.environ.get('CLIPPY_QUERY_STAGE_EMPTY') == stage: selected = ['', '']\n"
            "newline = '\\r\\n' if os.environ.get('CLIPPY_QUERY_CRLF') == '1' else '\\n'\n"
            "sys.stdout.buffer.write((newline.join(selected) + newline).encode())\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash, "Bash is required for target selection")

    def run_script(
        self,
        script,
        runner,
        *args,
        fail=False,
        empty=False,
        crlf=False,
        fail_stage="",
        empty_stage="",
        inputs=None,
    ):
        (self.root / "arguments.json").unlink(missing_ok=True)
        (self.root / "query-inputs.json").write_text(json.dumps(inputs or {}))
        env = dict(os.environ)
        env.update(
            RUNNER_OS=runner,
            CLIPPY_QUERY_FAIL="1" if fail else "0",
            CLIPPY_QUERY_EMPTY="1" if empty else "0",
            CLIPPY_QUERY_CRLF="1" if crlf else "0",
            CLIPPY_QUERY_ARGUMENTS=str(self.root / "arguments.json"),
            CLIPPY_QUERY_INPUTS=str(self.root / "query-inputs.json"),
            CLIPPY_QUERY_STAGE_FAIL=fail_stage,
            CLIPPY_QUERY_STAGE_EMPTY=empty_stage,
            BAZEL_REPOSITORY_CACHE="fixture-repository-cache",
            BAZEL_REPO_CONTENTS_CACHE="fixture-contents-cache",
        )
        return subprocess.run(
            [self.bash, str(script), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def invocation(self):
        return json.loads((self.root / "arguments.json").read_text())[-1]

    def test_linux_and_macos_preserve_native_and_unix_manual_helpers(self):
        for runner in ("Linux", "macOS"):
            with self.subTest(runner=runner):
                result = self.run_script(self.selector, runner)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.splitlines(),
                    PREFIX + [UNIT, NATIVE, UNIX, OTHER_NATIVE],
                )
                self.assertEqual(self.invocation()["args"][0], "query")
                self.assertEqual(self.invocation()["args"][-1], QUERY)

    def test_native_windows_keeps_all_configured_manual_helpers(self):
        for crlf in (False, True):
            with self.subTest(crlf=crlf):
                result = self.run_script(self.selector, "Windows", crlf=crlf)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.splitlines(), PREFIX + [UNIT, NATIVE, OTHER_NATIVE]
                )
                invocation = self.invocation()
                self.assertEqual(invocation["msys"], "*")
                args = invocation["args"]
                self.assertEqual(args[0], "cquery")
                calls = json.loads((self.root / "arguments.json").read_text())
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0]["args"][0], "query")
                self.assertEqual(calls[0]["args"][-1], QUERY)
                self.assertEqual(
                    invocation["query_text"],
                    "config(set(\n"
                    + "".join(
                        f'"{label}"\n'
                        for label in [UNIT, NATIVE, CROSS, UNIX, OTHER_NATIVE]
                    )
                    + "), target)\n",
                )
                self.assertEqual(args[-1], "--query_file=" + invocation["query_file"])
                self.assertFalse(Path(invocation["query_file"]).is_absolute())
                self.assertEqual(list(self.root.glob(".bazel-clippy-query.*")), [])
                for argument in (
                    "--config=ci-windows",
                    "--config=clippy",
                    "--platforms=//:windows_x86_64_msvc",
                    "--host_platform=//:local_windows_msvc",
                    "--output=starlark",
                    "--repository_cache=fixture-repository-cache",
                    "--repo_contents_cache=fixture-contents-cache",
                ):
                    self.assertIn(argument, args)
                self.assertFalse(any("skip_incompatible" in arg for arg in args))

    def test_explicit_windows_cross_leg_preserves_cross_helpers(self):
        result = self.run_script(self.selector, "Windows", "--windows-cross-compile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), PREFIX + [UNIT, CROSS])
        self.assertEqual(self.invocation()["args"][0], "query")
        self.assertEqual(self.invocation()["args"][-1], QUERY)

    def test_failed_query_emits_no_partial_target_list(self):
        for runner in ("Linux", "Windows"):
            with self.subTest(runner=runner):
                result = self.run_script(self.selector, runner, fail=True)
                self.assertEqual(result.returncode, 29, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_empty_configured_helpers_do_not_silently_drop_test_lints(self):
        for crlf in (False, True):
            with self.subTest(crlf=crlf):
                result = self.run_script(
                    self.selector, "Windows", empty=True, crlf=crlf
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("no manual Rust test helpers", result.stderr)

    def test_unknown_selector_and_malformed_configured_query_are_rejected(self):
        for script, args in (
            (self.selector, ("--invalid-selector",)),
            (self.query, ("--configured", "missing-separator")),
        ):
            with self.subTest(script=script):
                result = self.run_script(script, "Windows", *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Usage:", result.stderr)
                self.assertFalse((self.root / "arguments.json").exists())

    def test_configured_failure_preserves_no_partial_patterns_and_cleans_query(self):
        result = self.run_script(self.selector, "Windows", fail_stage="cquery")
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.invocation()["args"][0], "cquery")
        self.assertEqual(list(self.root.glob(".bazel-clippy-query.*")), [])

    def test_empty_set_at_either_stage_is_fatal_before_build_output(self):
        for stage in ("query", "cquery"):
            with self.subTest(stage=stage):
                result = self.run_script(self.selector, "Windows", empty_stage=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("no manual Rust test helpers", result.stderr)
                self.assertEqual(list(self.root.glob(".bazel-clippy-query.*")), [])

    def test_large_complete_set_uses_a_query_file_and_keeps_literal_label_words(self):
        labels = [
            f"//codex-rs/long_package_{index:04}:long_manual_rust_test_helper+variant=bin"
            for index in range(1000)
        ]
        labels += [
            "//codex-rs/a package:single'quote",
            '//codex-rs/example:double"quote',
        ]
        result = self.run_script(
            self.selector, "Windows", inputs={"raw": labels, "configured": labels}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), PREFIX + labels)
        invocation = self.invocation()
        self.assertGreater(len(invocation["query_text"]), 32767)
        self.assertLess(sum(len(arg) for arg in invocation["args"]), 4096)
        self.assertEqual(
            [line[1:-1] for line in invocation["query_text"].splitlines()[1:-1]], labels
        )
        self.assertEqual(list(self.root.glob(".bazel-clippy-query.*")), [])

    def test_unrepresentable_label_fails_instead_of_omitting_a_required_helper(self):
        labels = [UNIT, "//codex-rs/example:both'\"quotes"]
        result = self.run_script(self.selector, "Windows", inputs={"raw": labels})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("both query quote characters", result.stderr)
        self.assertEqual(len(json.loads((self.root / "arguments.json").read_text())), 1)
        self.assertEqual(list(self.root.glob(".bazel-clippy-query.*")), [])

    def test_explicit_query_file_transport_does_not_change_wrapper_scope(self):
        query = self.root / "relative query file.query"
        query.write_text('config(set(\n"//example:literal+target=bin"\n), target)\n')
        for arguments, command in (((), "query"), (("--configured",), "cquery")):
            with self.subTest(command=command):
                result = self.run_script(
                    self.query,
                    "Windows",
                    *arguments,
                    "--output=label",
                    "--query-file",
                    query.name,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                invocation = self.invocation()
                self.assertEqual(invocation["args"][0], command)
                self.assertEqual(invocation["args"][-1], "--query_file=" + query.name)
                self.assertEqual(invocation["query_text"], query.read_text())
                self.assertEqual(invocation["msys"], "*")
                self.assertFalse(
                    any(arg.startswith("--platforms=") for arg in invocation["args"])
                )


if __name__ == "__main__":
    unittest.main()

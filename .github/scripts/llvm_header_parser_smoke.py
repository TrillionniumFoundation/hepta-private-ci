#!/usr/bin/env python3
"""Exercise a real LLVM header-parser helper with a Python compiler probe.

Run with --header-parser PATH, or build the real MSVC target on Windows with
--bazel-msvc. The current Python executable stands in for clang so argument
boundaries and exit status are visible.
"""

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import run_bazel_with_buildbuddy


PROBE = (
    "import json, os, sys; "
    "print(json.dumps(sys.argv[1:])); "
    "sys.exit(int(os.environ.get('HEADER_PARSER_PROBE_EXIT', '0')))"
)


def build_msvc_header_parser(env: Mapping[str, str]) -> Path:
    # This probe must exercise _MSC_VER, even when the main cross build uses
    # Linux RBE. Keep its local environment separate from other CI steps.
    bazel_env = {**env, "RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": ""}
    repository_root = Path(__file__).resolve().parents[2]
    flags = (
        "--config=ci-windows-cross",
        "--platforms=//:windows_x86_64_msvc",
        "--compilation_mode=opt",
    )
    target = "@llvm//tools/internal:header-parser"
    subprocess.run(
        run_bazel_with_buildbuddy.bazel_command("build", *flags, target, env=bazel_env),
        cwd=repository_root,
        env=bazel_env,
        check=True,
    )
    files = subprocess.run(
        run_bazel_with_buildbuddy.bazel_command(
            "cquery", *flags, "--output=files", target, env=bazel_env
        ),
        cwd=repository_root,
        env=bazel_env,
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout.splitlines()
    executables = [path.strip() for path in files if path.strip().endswith(".exe")]
    if len(executables) != 1:
        raise RuntimeError("Bazel must report exactly one header-parser executable")
    execution_root = subprocess.run(
        run_bazel_with_buildbuddy.bazel_command(
            "info", *flags, "execution_root", env=bazel_env
        ),
        cwd=repository_root,
        env=bazel_env,
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(execution_root) / executables[0]


class HeaderParserSmokeTest(unittest.TestCase):
    binary: Path

    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="header parser ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stamp = self.root / "parse header stamp"
        self.env = {
            **os.environ,
            "PARSE_HEADER": str(self.stamp),
            "LLVM_CLANGXX": sys.executable,
            "HEADER_PARSER_PROBE_EXIT": "0",
        }

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.binary), "-c", PROBE, *arguments],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_creates_stamp_and_preserves_argument_boundaries(self) -> None:
        arguments = [
            "plain",
            "",
            "two words",
            "tab\tseparated",
            'embedded"quote',
            'backslash\\"quote',
            "trailing\\",
            "two trailing\\\\",
            "@response file",
            "%PATH% & literal | $(argument)",
        ]
        arguments.extend("\\" * count + '"quoted' for count in (1, 2, 3, 4))
        result = self.invoke(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), arguments)
        self.assertEqual(self.stamp.read_bytes(), b"")

    def test_touch_preserves_existing_contents(self) -> None:
        contents = b"existing header stamp\x00\r\n"
        self.stamp.write_bytes(contents)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertEqual(self.stamp.read_bytes(), contents)

    def test_compiler_failure_is_propagated(self) -> None:
        self.env["HEADER_PARSER_PROBE_EXIT"] = "37"
        result = self.invoke("compiler ran")
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["compiler ran"])
        self.assertTrue(self.stamp.exists())

    def test_missing_or_empty_configuration_rejects(self) -> None:
        configured = self.env.copy()
        for variable in ("PARSE_HEADER", "LLVM_CLANGXX"):
            for value in (None, ""):
                with self.subTest(variable=variable, value=value):
                    self.env = configured.copy()
                    if value is None:
                        del self.env[variable]
                    else:
                        self.env[variable] = value
                    result = self.invoke()
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(f"required env var {variable} is not set", result.stderr)

    def test_invalid_stamp_rejects_before_compiler(self) -> None:
        self.env["PARSE_HEADER"] = str(self.root)
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("failed to touch", result.stderr)

    def test_missing_compiler_reports_launch_failure(self) -> None:
        self.env["LLVM_CLANGXX"] = str(self.root / "missing compiler.exe")
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("failed", result.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--header-parser", type=Path)
    source.add_argument("--bazel-msvc", action="store_true")
    options = parser.parse_args()
    binary = options.header_parser
    if options.bazel_msvc:
        if os.name != "nt":
            parser.error("--bazel-msvc requires native Windows execution")
        binary = build_msvc_header_parser(os.environ)
    HeaderParserSmokeTest.binary = binary.resolve(strict=True)
    unittest.main(argv=[sys.argv[0]])

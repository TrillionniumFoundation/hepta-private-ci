#!/usr/bin/env python3
"""Exercise the real native Windows Rust process wrapper with locked outputs."""

import argparse
from collections.abc import Mapping
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import run_bazel_with_buildbuddy


PROBE = """
import json, os, pathlib, sys
arguments = sys.argv[1:]
expanded = []
for argument in arguments:
    if argument.startswith('@'):
        expanded.extend(pathlib.Path(argument[1:]).read_text().splitlines())
    else:
        expanded.append(argument)
paths = [pathlib.Path(arg.removeprefix('-Ldependency='))
         for arg in expanded if arg.startswith('-Ldependency=')]
print(json.dumps({
    'arguments': expanded,
    'paths': [str(path) for path in paths],
    'files': [{item.name: item.read_bytes().hex() for item in path.iterdir()}
              for path in paths],
}))
sys.exit(int(os.environ.get('PROCESS_WRAPPER_PROBE_EXIT', '0')))
"""


def build_msvc_process_wrapper(env: Mapping[str, str]) -> Path:
    # Build a real ordinary Rust target, then select the wrapper from its
    # configured dependency graph. This preserves the toolchain's bootstrap
    # transition instead of invoking a separate test implementation.
    bazel_env = {**env, "RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": ""}
    repository_root = Path(__file__).resolve().parents[2]
    flags = (
        "--config=ci-windows-cross",
        "--platforms=//:windows_x86_64_msvc",
        "--compilation_mode=opt",
    )
    target = "//codex-rs/hepta-paths:hepta-paths"
    subprocess.run(
        run_bazel_with_buildbuddy.bazel_command("build", *flags, target, env=bazel_env),
        cwd=repository_root,
        env=bazel_env,
        check=True,
    )
    query = f'filter("//util/process_wrapper:process_wrapper$", deps({target}))'
    files = subprocess.run(
        run_bazel_with_buildbuddy.bazel_command(
            "cquery", *flags, "--output=files", query, env=bazel_env
        ),
        cwd=repository_root,
        env=bazel_env,
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout.splitlines()
    executables = sorted(
        {path.strip() for path in files if path.strip().endswith("process_wrapper.exe")}
    )
    if len(executables) != 1:
        raise RuntimeError("Bazel must report exactly one native Rust process wrapper")
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


@contextmanager
def exclusive_read_handle(path: Path):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not kernel32.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class ProcessWrapperSmokeTest(unittest.TestCase):
    binary: Path

    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="rust wrapper ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dependencies = self.root / "dependency files"
        self.dependencies.mkdir()
        self.env = {**os.environ, "PROCESS_WRAPPER_PROBE_EXIT": "0"}

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.binary), "--", sys.executable, "-c", PROBE, *arguments],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def assert_copied_and_cleaned(self, result, expected) -> dict:
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["files"], [expected])
        self.assertEqual(len(observed["paths"]), 1)
        self.assertFalse(Path(observed["paths"][0]).exists())
        return observed

    def test_locked_executable_in_response_path_preserves_all_libraries(self) -> None:
        libraries = {
            "libordinary.rlib": b"ordinary library",
            "libmetadata.rmeta": b"metadata only",
            "macro.dll": b"proc macro library",
            "native.lib": b"native import library",
            "tool.exe.lib": b"executable import library",
            "tool.exe.dll": b"library with executable in its name",
        }
        for name, data in libraries.items():
            (self.dependencies / name).write_bytes(data)
        executable = (
            self.dependencies / "hepta-supervisor-paired_process_product-test.exe"
        )
        executable.write_bytes(b"unrelated executable product")
        (self.dependencies / "other.EXE").write_bytes(b"another executable")
        (self.dependencies / "temporary.exe.tmp123").write_bytes(b"temporary")
        (self.dependencies / "object.rcgu.o").write_bytes(b"codegen object")
        arguments = self.root / "rustc arguments.params"
        arguments.write_text(
            f"-L\ndependency={self.dependencies}\n-Lnative=native search path\nliteral\n",
            encoding="utf-8",
        )
        with exclusive_read_handle(executable):
            with self.assertRaises(PermissionError):
                executable.read_bytes()
            result = self.invoke(f"@{arguments}")
        observed = self.assert_copied_and_cleaned(
            result, {name: data.hex() for name, data in libraries.items()}
        )
        self.assertEqual(
            observed["arguments"][:-1], ["-Lnative=native search path", "literal"]
        )

    def test_direct_dependency_paths_preserve_first_directory_precedence(self) -> None:
        second = self.root / "second dependency directory"
        second.mkdir()
        (self.dependencies / "same.rlib").write_bytes(b"first")
        (second / "same.rlib").write_bytes(b"second")
        (second / "other.rmeta").write_bytes(b"metadata")
        result = self.invoke(
            f"-Ldependency={self.dependencies}", "-L", f"dependency={second}"
        )
        self.assert_copied_and_cleaned(
            result, {"same.rlib": b"first".hex(), "other.rmeta": b"metadata".hex()}
        )

    def test_executable_products_are_excluded_without_requiring_a_lock(self) -> None:
        (self.dependencies / "program.EXE").write_bytes(b"executable")
        (self.dependencies / "program.exe.lib").write_bytes(b"import library")
        (self.dependencies / "program.exe.dll").write_bytes(b"shared library")
        result = self.invoke(f"-Ldependency={self.dependencies}")
        self.assert_copied_and_cleaned(
            result,
            {
                "program.exe.lib": b"import library".hex(),
                "program.exe.dll": b"shared library".hex(),
            },
        )

    def test_inaccessible_library_still_rejects_before_child_execution(self) -> None:
        library = self.dependencies / "required.rlib"
        library.write_bytes(b"required library")
        with exclusive_read_handle(library):
            with self.assertRaises(PermissionError):
                library.read_bytes()
            result = self.invoke(f"-Ldependency={self.dependencies}")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("required.rlib", result.stderr)
        self.assertIn("unable to copy", result.stderr)

    def test_child_failure_keeps_its_status_and_cleans_dependency_directory(
        self,
    ) -> None:
        (self.dependencies / "required.rlib").write_bytes(b"required library")
        self.env["PROCESS_WRAPPER_PROBE_EXIT"] = "37"
        result = self.invoke(f"-Ldependency={self.dependencies}")
        self.assertEqual(result.returncode, 37, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(
            observed["files"], [{"required.rlib": b"required library".hex()}]
        )
        self.assertEqual(len(observed["paths"]), 1)
        self.assertFalse(Path(observed["paths"][0]).exists())

    def test_arguments_without_dependency_paths_stay_unchanged(self) -> None:
        arguments = ["-Lnative=native path", "literal with spaces"]
        result = self.invoke(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"arguments": arguments, "paths": [], "files": []},
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--process-wrapper", type=Path)
    source.add_argument("--bazel-msvc", action="store_true")
    options = parser.parse_args()
    if os.name != "nt":
        parser.error(
            "the process-wrapper lock regression requires native Windows execution"
        )
    binary = options.process_wrapper
    if options.bazel_msvc:
        binary = build_msvc_process_wrapper(os.environ)
    ProcessWrapperSmokeTest.binary = binary.resolve(strict=True)
    unittest.main(argv=[sys.argv[0]])

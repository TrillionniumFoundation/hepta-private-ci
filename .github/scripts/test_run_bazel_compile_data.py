"""Check fleet's include_str! input in a minimal declared-input compiler sandbox."""

import ast
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("codex-rs/hepta-fleet/src/module_catalog.rs")
RUSTC = os.environ.get("RUSTC") or shutil.which("rustc")


def calls(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


@unittest.skipUnless(RUSTC, "rustc is needed to exercise compile-time input resolution")
class FleetCompileDataTests(unittest.TestCase):
    def compile_fixture(self, *, omit_catalog):
        declarations = calls(
            ROOT / "codex-rs/hepta-fleet/BUILD.bazel", "codex_rust_crate"
        )
        self.assertEqual(len(declarations), 1)
        keywords = {entry.arg: entry.value for entry in declarations[0].keywords}
        labels = (
            ast.literal_eval(keywords["compile_data"])
            if "compile_data" in keywords
            else []
        )
        include = re.search(r'include_str!\("([^"]+)"\)', (ROOT / SOURCE).read_text())
        self.assertIsNotNone(include)
        relative = include.group(1)
        required = (ROOT / SOURCE.parent / relative).resolve().relative_to(ROOT)
        exports = calls(ROOT / "BUILD.bazel", "exports_files")
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            source = sandbox / SOURCE
            source.parent.mkdir(parents=True)
            source.write_text(
                f'pub const CATALOG: &str = include_str!("{relative}");\n'
            )
            for label in labels:
                self.assertTrue(
                    label.startswith("//:"),
                    "fixture expects an explicit root file label",
                )
                path = Path(label[3:])
                self.assertEqual(
                    path,
                    required,
                    "fleet must not receive unrelated compile-time inputs",
                )
                export = next(
                    (
                        call
                        for call in exports
                        if path.as_posix() in ast.literal_eval(call.args[0])
                    ),
                    None,
                )
                self.assertIsNotNone(
                    export, "cross-package input must be explicitly exported"
                )
                visibility = next(
                    entry.value
                    for entry in export.keywords
                    if entry.arg == "visibility"
                )
                self.assertEqual(
                    ast.literal_eval(visibility), ["//codex-rs/hepta-fleet:__pkg__"]
                )
                if omit_catalog:
                    continue
                destination = sandbox / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, destination)
            return subprocess.run(
                [
                    RUSTC,
                    "--crate-type=lib",
                    "--emit=metadata",
                    str(source),
                    "--out-dir",
                    str(sandbox),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )

    def test_declared_input_resolves_actual_include_path(self):
        result = self.compile_fixture(omit_catalog=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_declared_input_fails_compilation(self):
        result = self.compile_fixture(omit_catalog=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MODULES.json", result.stderr)


if __name__ == "__main__":
    unittest.main()

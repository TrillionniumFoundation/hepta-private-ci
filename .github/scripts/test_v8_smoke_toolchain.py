#!/usr/bin/env python3
"""Exercise the actual canary shell with a spy, without compiling or running V8."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]


def smoke_step():
    workflow = (ROOT / ".github/workflows/v8-canary.yml").read_text()
    step = workflow.split("      - name: Smoke test staged artifact with Cargo\n", 1)[
        1
    ].split("\n      - name:", 1)[0]
    environment, script = step.split("        run: |\n", 1)
    overrides = {}
    for line in environment.splitlines():
        if line.startswith("          RUSTUP_TOOLCHAIN:"):
            overrides["RUSTUP_TOOLCHAIN"] = json.loads(line.split(":", 1)[1])
    return textwrap.dedent(script), overrides


class V8SmokeToolchainTests(unittest.TestCase):
    def invoke(self, target, host, sandbox, *, missing=False, exit_code=0):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex-rs").mkdir()
            dependency = root / "registry/v8-150.4.0"
            dependency.mkdir(parents=True)
            (dependency / "rust-toolchain.toml").write_text(
                '[toolchain]\nchannel = "1.91.0"\n'
            )
            stage = root / "dist" / target
            stage.mkdir(parents=True)
            (stage / "librusty_v8_fixture.a.gz").touch()
            if not missing:
                (stage / "src_binding_fixture.rs").touch()
            temporary = root / "job-temp"
            temporary.mkdir()
            binary_dir = root / "bin"
            binary_dir.mkdir()
            uname = binary_dir / "uname"
            uname.write_text(f'#!/bin/sh\nprintf "%s\\n" "{host}"\n')
            uname.chmod(0o755)
            output = root / "observation.json"
            cargo = binary_dir / "cargo-spy"
            cargo.write_text(
                f"#!{sys.executable}\n"
                "import json,os,pathlib,sys\n"
                "keys=('RUSTUP_TOOLCHAIN','CARGO_TARGET_DIR','RUSTY_V8_ARCHIVE',"
                "'RUSTY_V8_SRC_BINDING_PATH')\n"
                "record={'args':sys.argv[1:],'cwd':os.getcwd(),"
                "'env':{k:os.environ.get(k) for k in keys}}\n"
                "os.chdir(os.environ['SPY_DEPENDENCY'])\n"
                "record['dependency_toolchain']=os.environ.get('RUSTUP_TOOLCHAIN')\n"
                "pathlib.Path(os.environ['SPY_OUTPUT']).write_text(json.dumps(record))\n"
                "sys.exit(int(os.environ['SPY_EXIT']))\n"
            )
            cargo.chmod(0o755)
            script, overrides = smoke_step()
            env = dict(
                os.environ,
                PATH=f"{binary_dir}{os.pathsep}{os.environ['PATH']}",
                TARGET=target,
                SANDBOX=sandbox,
                RUNNER_TEMP=str(temporary),
                GITHUB_WORKSPACE=str(root),
                CARGO_1_95=str(cargo),
                RUSTUP_TOOLCHAIN="1.91.0",
                SPY_DEPENDENCY=str(dependency),
                SPY_OUTPUT=str(output),
                SPY_EXIT=str(exit_code),
            )
            env.update(overrides)
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", script],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            record = json.loads(output.read_text()) if output.exists() else None
            if record is not None:
                record["expected_target_dir"] = str(
                    temporary / f"rusty-v8-cargo-smoke-{target}-{sandbox}"
                )
                record["expected_cwd"] = str(root / "codex-rs")
                record["expected_archive"] = str(stage / "librusty_v8_fixture.a.gz")
                record["expected_binding"] = str(stage / "src_binding_fixture.rs")
            return result, record

    def test_actual_shell_pins_children_and_preserves_all_native_smoke_selectors(self):
        for target, host in (
            ("x86_64-apple-darwin", "x86_64"),
            ("aarch64-apple-darwin", "arm64"),
            ("x86_64-unknown-linux-gnu", "x86_64"),
            ("aarch64-unknown-linux-gnu", "aarch64"),
        ):
            for sandbox in ("false", "true"):
                with self.subTest(target=target, sandbox=sandbox):
                    result, record = self.invoke(target, host, sandbox)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(record["env"]["RUSTUP_TOOLCHAIN"], "1.96.0")
                    self.assertEqual(record["dependency_toolchain"], "1.96.0")
                    expected = ["test", "-p", "codex-v8-poc"]
                    if sandbox == "true":
                        expected += ["--features", "sandbox"]
                    self.assertEqual(record["args"], expected)
                    self.assertEqual(record["cwd"], record["expected_cwd"])
                    for name, expected_key in (
                        ("CARGO_TARGET_DIR", "expected_target_dir"),
                        ("RUSTY_V8_ARCHIVE", "expected_archive"),
                        ("RUSTY_V8_SRC_BINDING_PATH", "expected_binding"),
                    ):
                        self.assertEqual(record["env"][name], record[expected_key])

    def test_actual_shell_keeps_missing_staged_binding_fatal(self):
        result, record = self.invoke(
            "x86_64-apple-darwin", "x86_64", "false", missing=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(record)
        self.assertIn("Missing staged archive or binding", result.stdout)

    def test_actual_shell_propagates_smoke_failure(self):
        result, record = self.invoke(
            "x86_64-apple-darwin", "x86_64", "true", exit_code=37
        )
        self.assertEqual(result.returncode, 37)
        self.assertEqual(record["env"]["RUSTUP_TOOLCHAIN"], "1.96.0")


if __name__ == "__main__":
    unittest.main()

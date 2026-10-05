"""Run the workflow's actual inline toolchain pin against isolated TOML inputs.

These tests execute Python only. They neither install Rust nor demonstrate
Cargo artifact reuse; the native CI job records both compiler identities.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-architecture-convergence.yml"
PIN_STEP = "      - name: Pin native Rust toolchain from workspace\n"
IDENTITY_STEP = "      - name: Verify pinned Rust identity across working directories\n"
EXISTING_ENV = b"PREEXISTING_ENV=preserved\n"


def production_pin_python() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    if workflow.count(PIN_STEP) != 1:
        raise AssertionError("expected one production toolchain pin step")
    block = workflow.split(PIN_STEP, 1)[1].split("      - name:", 1)[0]
    shell = textwrap.dedent(block.split("        run: |\n", 1)[1])
    matches = re.findall(r"python3 - <<'PY'\n(.*?)\nPY(?:\n|$)", shell, re.DOTALL)
    if len(matches) != 1:
        raise AssertionError("expected one production inline Python program")
    return matches[0]


class NativeToolchainWorkflowTests(unittest.TestCase):
    def execute_configs(self, configurations: list[str | None]):
        program = production_pin_python()
        with tempfile.TemporaryDirectory(
            prefix="hepta-toolchain-workflow-"
        ) as directory:
            root = Path(directory)
            (root / "codex-rs").mkdir()
            configuration = root / "codex-rs/rust-toolchain.toml"
            environment = root / "github.env"
            environment.write_bytes(EXISTING_ENV)
            results = []
            for content in configurations:
                if content is None:
                    configuration.unlink(missing_ok=True)
                else:
                    configuration.write_text(content, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-c", program],
                    cwd=root,
                    env=dict(
                        os.environ,
                        GITHUB_ENV=str(environment),
                        PYTHONDONTWRITEBYTECODE="1",
                    ),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                results.append((result, environment.read_bytes()))
        return results

    def test_dynamic_channels_append_without_replacing_existing_environment(self):
        channels = [f"fixture-{uuid.uuid4().hex}" for _ in range(2)]
        configurations = [
            "[toolchain]\nchannel = " + json.dumps(channel) + "\n"
            for channel in channels
        ]
        expected = EXISTING_ENV
        for channel, (result, environment) in zip(
            channels, self.execute_configs(configurations), strict=True
        ):
            self.assertEqual(result.returncode, 0, result.stderr)
            expected += f"RUSTUP_TOOLCHAIN={channel}\n".encode()
            self.assertEqual(environment, expected)

    def test_invalid_channels_cannot_inject_or_append_environment(self):
        channels = (
            "",
            " ",
            " leading",
            "trailing ",
            "nightly\nINJECTED=1",
            "nightly\rINJECTED=1",
            "nightly\tINJECTED=1",
            "nightly=other",
            "--help",
            "/absolute/toolchain",
            "非ASCII",
            123,
            [],
        )
        for channel in channels:
            with self.subTest(channel=channel):
                configuration = "[toolchain]\nchannel = " + json.dumps(channel) + "\n"
                [(result, environment)] = self.execute_configs([configuration])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(environment, EXISTING_ENV)

    def test_missing_config_or_channel_cannot_append_environment(self):
        for configuration in (
            None,
            "[toolchain]\n",
            "[unrelated]\nchannel = 'stable'\n",
        ):
            with self.subTest(configuration=configuration):
                [(result, environment)] = self.execute_configs([configuration])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(environment, EXISTING_ENV)

    def test_malformed_toml_cannot_append_environment(self):
        [(result, environment)] = self.execute_configs(
            ["[toolchain\nchannel = 'stable'\n"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(environment, EXISTING_ENV)

    def test_pin_and_identity_check_precede_native_rust_commands(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        checkout = workflow.index("      - name: Check out exact candidate\n")
        pin = workflow.index(PIN_STEP)
        identity = workflow.index(IDENTITY_STEP)
        self.assertLess(checkout, pin)
        self.assertLess(pin, identity)
        for name in (
            "Resolve verified V8 artifacts",
            "Verify Cargo lock resolution and print exact resolver drift",
            "Inference owner regressions and streaming digest",
        ):
            self.assertLess(identity, workflow.index("      - name: " + name + "\n"))
        block = workflow.split(IDENTITY_STEP, 1)[1].split("      - name:", 1)[0]
        self.assertIn('root_rustc="$(rustc -Vv)"', block)
        self.assertIn('root_cargo="$(cargo -V)"', block)
        self.assertIn('workspace_rustc="$(cd codex-rs && rustc -Vv)"', block)
        self.assertIn('workspace_cargo="$(cd codex-rs && cargo -V)"', block)
        self.assertIn('test "$root_rustc" = "$workspace_rustc"', block)
        self.assertIn('test "$root_cargo" = "$workspace_cargo"', block)


if __name__ == "__main__":
    unittest.main()

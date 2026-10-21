import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ("v8-canary.yml", "rusty-v8-release.yml")


class V8CargoSmokeTest(unittest.TestCase):
    def run_smoke(self, workflow, step_name, target, sandbox):
        source = (ROOT / ".github/workflows" / workflow).read_text()
        step = source.split(f"      - name: {step_name}\n", 1)[1]
        run = step.split("        run: |\n", 1)[1]
        lines = []
        for line in run.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])

        with tempfile.TemporaryDirectory(prefix="v8 smoke ") as directory:
            root = Path(directory)
            (root / "codex-rs").mkdir()
            staged = root / "dist" / target
            staged.mkdir(parents=True)
            archive_name = (
                "rusty_v8_fixture.lib.gz"
                if "windows" in target
                else "librusty_v8_fixture.a.gz"
            )
            archive = staged / archive_name
            binding = staged / "src_binding_fixture.rs"
            archive.touch()
            binding.touch()

            binary_dir = root / "bin"
            binary_dir.mkdir()
            cargo = binary_dir / "cargo"
            cargo.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s\\0' \"$@\" > \"$CAPTURE_ARGS\"\n"
                "printf '%s\\0' \"$RUSTY_V8_ARCHIVE\" "
                "\"$RUSTY_V8_SRC_BINDING_PATH\" \"$PWD\" > \"$CAPTURE_ENV\"\n"
            )
            cargo.chmod(0o755)
            # Exercise the native x86_64 branch on any host running this test.
            uname = binary_dir / "uname"
            uname.write_text("#!/usr/bin/env bash\nprintf '%s\\n' x86_64\n")
            uname.chmod(0o755)
            args_file = root / "cargo-args"
            env_file = root / "cargo-env"
            environment = {
                **os.environ,
                "PATH": str(binary_dir) + os.pathsep + os.environ["PATH"],
                "CARGO_1_95": str(cargo),
                "CAPTURE_ARGS": str(args_file),
                "CAPTURE_ENV": str(env_file),
                "GITHUB_WORKSPACE": str(root),
                "RUNNER_TEMP": str(root),
                "TARGET": target,
                "SANDBOX": str(sandbox).lower(),
            }
            result = subprocess.run(
                ["bash", "-c", "\n".join(lines)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(args_file.exists(), "the Cargo smoke must execute")
            self.assertEqual(
                env_file.read_bytes().decode().split("\0")[:-1],
                [str(archive), str(binding), str(root / "codex-rs")],
            )
            return args_file.read_bytes().decode().split("\0")[:-1]

    def test_native_smokes_select_the_staged_artifact_feature(self):
        for workflow in WORKFLOWS:
            for sandbox in (False, True):
                with self.subTest(workflow=workflow, sandbox=sandbox):
                    args = self.run_smoke(
                        workflow,
                        "Smoke test staged artifact with Cargo",
                        "x86_64-unknown-linux-gnu",
                        sandbox,
                    )
                    expected = [
                        "test",
                        "-p",
                        "codex-v8-poc",
                        "--no-default-features",
                    ]
                    if sandbox:
                        expected.extend(["--features", "sandbox"])
                    self.assertEqual(args, expected)

    def test_windows_smokes_link_the_explicit_sandbox_feature(self):
        for workflow in WORKFLOWS:
            for target in ("x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc"):
                with self.subTest(workflow=workflow, target=target):
                    args = self.run_smoke(
                        workflow, "Smoke link staged artifact with Cargo", target, True
                    )
                    self.assertEqual(
                        args,
                        [
                            "+1.95.0",
                            "test",
                            "-p",
                            "codex-v8-poc",
                            "--no-default-features",
                            "--target",
                            target,
                            "--features",
                            "sandbox",
                            "--no-run",
                        ],
                    )


if __name__ == "__main__":
    unittest.main()

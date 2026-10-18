#!/usr/bin/env python3
"""Exercise host defaults at the real shell wrapper's argument handoff."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPTS = Path(__file__).resolve().parent
RECORDER = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

assert len(sys.argv) == 3 and sys.argv[1] == '--wrapper-args-file'
raw = Path(sys.argv[2]).read_bytes()
assert raw.endswith(b'\\0')
args = [item.decode('utf-8') for item in raw[:-1].split(b'\\0')]
Path(os.environ['HOST_PLATFORM_LOG']).write_text(json.dumps(args), encoding='utf-8')
sys.exit(int(os.environ.get('HOST_PLATFORM_EXIT', '0')))
"""


class HostPlatformHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory(prefix="host platform ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.wrapper = self.root / "run-bazel-ci.sh"
        shutil.copyfile(SCRIPTS / self.wrapper.name, self.wrapper)
        recorder = self.root / "run_bazel_with_buildbuddy.py"
        recorder.write_text(RECORDER, encoding="utf-8")
        recorder.chmod(0o755)
        git_bash = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Git/bin/bash.exe"
        )
        self.bash = (
            str(git_bash)
            if os.name == "nt" and git_bash.is_file()
            else shutil.which("bash")
        )
        self.assertIsNotNone(self.bash, "Bash is required for the shell handoff test")
        self.log = self.root / "arguments.json"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                ("BAZEL_", "BUILDBUDDY_", "CODEX_BAZEL_", "GITHUB_", "HOST_PLATFORM_")
            )
        }
        self.env.update(
            RUNNER_OS="Windows",
            HOST_PLATFORM_LOG=str(self.log),
            CODEX_BAZEL_WINDOWS_PATH="C:/toolchain/bin",
            INCLUDE="C:/toolchain/include",
            LIB="C:/toolchain/lib",
            LIBPATH="C:/toolchain/libpath",
            UniversalCRTSdkDir="C:/sdk/ucrt",
            VCToolsInstallDir="C:/toolchain",
            WindowsSdkDir="C:/sdk",
        )

    def invoke(self, options: list[str], targets: list[str]) -> list[str]:
        result = subprocess.run(
            [
                self.bash,
                str(self.wrapper),
                "--windows-msvc-host-platform",
                "--",
                "build",
                *options,
                "--",
                *targets,
            ],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            int(self.env.get("HOST_PLATFORM_EXIT", "0")),
            result.stdout + result.stderr,
        )
        args = json.loads(self.log.read_text(encoding="utf-8"))
        self.assertEqual(args[args.index("--") + 1 :], targets)
        return args[: args.index("--")]

    def test_default_is_supplied_when_the_caller_omits_host(self) -> None:
        args = self.invoke([], ["//fake:target"])
        self.assertEqual(args.count("--host_platform=//:local_windows_msvc"), 1)

    def test_explicit_host_survives_both_option_spellings(self) -> None:
        for options in (
            ["--host_platform=//:explicit_host"],
            ["--host_platform", "//:explicit_host"],
        ):
            with self.subTest(options=options):
                args = self.invoke(options, ["//fake:target"])
                self.assertNotIn("--host_platform=//:local_windows_msvc", args)
                start = args.index("build") + 1
                self.assertEqual(args[start : start + len(options)], options)

    def test_target_payload_cannot_suppress_the_host_default(self) -> None:
        args = self.invoke([], ["//fake:target", "--host_platform=//:payload"])
        self.assertEqual(args.count("--host_platform=//:local_windows_msvc"), 1)

    def test_similarly_named_option_is_not_a_host_override(self) -> None:
        args = self.invoke(["--host_platform_extra=//:other"], ["//fake:target"])
        self.assertEqual(args.count("--host_platform=//:local_windows_msvc"), 1)

    def test_explicit_host_does_not_swallow_the_downstream_failure(self) -> None:
        self.env["HOST_PLATFORM_EXIT"] = "37"
        args = self.invoke(["--host_platform", "//:explicit_host"], ["//fake:target"])
        self.assertNotIn("--host_platform=//:local_windows_msvc", args)


if __name__ == "__main__":
    unittest.main()

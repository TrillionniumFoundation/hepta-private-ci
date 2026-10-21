import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class ClippyQueryCrLfTests(unittest.TestCase):
    def test_native_crlf_labels_and_embedded_cr(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "scripts/list-bazel-clippy-targets.sh"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrapper = root / "scripts/list-bazel-clippy-targets.sh"
            query = root / ".github/scripts/run-bazel-query-ci.sh"
            wrapper.parent.mkdir(parents=True)
            query.parent.mkdir(parents=True)
            shutil.copyfile(source, wrapper)
            query.write_text(
                "#!/usr/bin/env bash\n"
                "printf '//fake:one\\r\\n//fake:two\\rbroken\\r\\n'\n",
                encoding="utf-8",
            )
            query.chmod(0o755)
            for runner in ("Windows", "Linux", "macOS"):
                result = subprocess.run(
                    ["bash", str(wrapper)],
                    cwd=root,
                    env={**os.environ, "RUNNER_OS": runner},
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout,
                    (
                        b"//codex-rs/...\n"
                        b"-//codex-rs/v8-poc:all\n"
                        b"//fake:one\n"
                        b"//fake:two\rbroken\n"
                    ),
                )


if __name__ == "__main__":
    unittest.main()

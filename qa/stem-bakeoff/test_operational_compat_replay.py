import json
from pathlib import Path
import sys
import tempfile
import unittest

from operational_compat_replay import compatibility_execute


class OperationalCompatibilityTests(unittest.TestCase):
    def test_normal_build_is_observed_and_failed_build_never_creates_success_label(self):
        for build_fails in (False, True):
            with self.subTest(build_fails=build_fails), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cwd = root / "black-1" / "implementation-0"
                cwd.mkdir(parents=True)
                (cwd / "sample.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_a(self): self.assertEqual(2,2)\n")
                source = "raise RuntimeError('build failed')" if build_fails else "from pathlib import Path\nPath('_black_version.py').write_text(\"version = 'actual-build'\\n\")\n"
                (cwd / "setup.py").write_text(source)
                result = compatibility_execute({"id": "check", "runner": "unittest", "args": ["-q", "sample.T.test_a"]},
                    sys.executable, cwd, root / "output", {"cpu_seconds": 2,
                        "address_space_bytes": 512 * 1024**2, "log_file_bytes": 1024 * 1024, "wall_timeout_seconds": 5})
                self.assertEqual(result["observation"]["outcome"], "pass")
                self.assertEqual(result["outcome"], "infrastructure_error" if build_fails else "pass")
                self.assertEqual(result, json.loads((root / "output/execution.json").read_text()))
                build = result["compatibility"]["build"]
                if not build_fails:
                    self.assertEqual(build["generated_version_file"]["contents"], "version = 'actual-build'\n")
                self.assertFalse(result["compatibility"]["source_implementation_changed"])


if __name__ == "__main__":
    unittest.main()

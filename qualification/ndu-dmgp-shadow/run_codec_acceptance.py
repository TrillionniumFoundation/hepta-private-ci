"""Dedicated real-codec acceptance; ordinary unittest discovery may still skip."""
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


def require_tools():
    for name in ("ffmpeg", "ffprobe"):
        executable = shutil.which(name)
        if executable is None:
            raise RuntimeError(f"required codec tool unavailable: {name}")
        # No shell/pipeline: missing, broken or nonzero tools cannot be masked.
        subprocess.run([executable, "-version"], check=True, timeout=30,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_acceptance(suite, stream=None):
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    accepted = (result.testsRun > 0 and result.wasSuccessful()
                and not result.skipped and not result.expectedFailures)
    print(f"codec-acceptance: tests={result.testsRun} skipped={len(result.skipped)} "
          f"accepted={accepted}", file=stream or sys.stderr)
    return 0 if accepted else 1


def main():
    try:
        require_tools()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"codec-acceptance rejected: {exc}", file=sys.stderr)
        return 1
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parent), pattern="test_*media*.py")
    return run_acceptance(suite)


if __name__ == "__main__":
    sys.exit(main())

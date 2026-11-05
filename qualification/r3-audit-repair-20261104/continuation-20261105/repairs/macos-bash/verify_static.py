"""Check the candidate in an isolated cloud Git directory; do not run CI tests."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
RELATIVE = ".github/scripts/run-bazel-ci.sh"


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


records = []
env = os.environ.copy()
for key in (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR",
):
    env.pop(key, None)

with tempfile.TemporaryDirectory(prefix="isolated-git-", dir=ROOT) as temporary:
    work = Path(temporary)
    source = work / RELATIVE
    source.parent.mkdir(parents=True)
    original = (ROOT / "preimage" / RELATIVE).read_bytes()
    expected = (ROOT / "candidate" / RELATIVE).read_bytes()
    source.write_bytes(original)
    source.chmod(0o755)
    for argv in (
        ["git", "init", "--quiet"],
        ["git", "add", "--", RELATIVE],
        ["git", "apply", "--check", str(ROOT / "macos-empty-array.patch")],
        ["git", "apply", str(ROOT / "macos-empty-array.patch")],
        ["git", "diff", "--check"],
        ["bash", "-n", RELATIVE],
    ):
        result = subprocess.run(argv, cwd=work, env=env, capture_output=True, text=True)
        records.append({"argv": argv, "exit_code": result.returncode,
                        "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise RuntimeError(records[-1])
    assert source.read_bytes() == expected
    assert source.stat().st_mode & 0o777 == 0o755
    receipt = {
        "schema": "hepta-macos-bash-empty-array-isolated-static-check-v1",
        "scope": "Cloud isolated Git application and syntax parsing only; no wrapper execution, Bazel, original 57 tests, or native-host action.",
        "preimage": identity(original),
        "expected_postimage": identity(expected),
        "applied_postimage": identity(source.read_bytes()),
        "applied_mode": "100755",
        "records": records,
        "all_checks_exit_zero": True,
        "original_test_gate_executed": False,
        "macos_execution_qualification": False,
        "shared_source_or_index_changed": False,
    }
(ROOT / "static-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({"verification": identity((ROOT / "static-verification.json").read_bytes()),
                  "checks": len(records), "all_exit_zero": True}))

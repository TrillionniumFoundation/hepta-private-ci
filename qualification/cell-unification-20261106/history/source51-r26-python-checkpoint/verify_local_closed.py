"""Read existing closed r26 Python artifacts; no native or Rust execution."""
from pathlib import Path
import hashlib
import json
import re


HERE = Path(__file__).parent
ROOT = HERE.parent
STEM = "native-source51-project-r26-python-runner"


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


error = {
    "schema": "hepta.local-artifact-readback-error.v1",
    "attempt": 1,
    "original_stderr": "Traceback (most recent call last):\n  File \"<string>\", line 16, in <module>\nAssertionError\n",
    "cause": "Local inline verifier overescaped its regular-expression backslashes. The actual original resources contain Exit status: 0.",
    "original_native_evidence_changed": False,
    "native_gate_repeated": False,
    "native_job_id": "1a1b1b739ee-fc05-7a70",
    "correction": "This standalone verifier uses ordinary raw Python regex literals and reads the same already copied originals.",
}
with (HERE / "LOCAL-READBACK-ATTEMPT-1-ERROR.json").open("x") as out:
    out.write(json.dumps(error, indent=2) + "\n")

receipt = json.loads((HERE / (STEM + "-receipt.json")).read_bytes())
raw = json.loads((HERE / (STEM + "-raw-process-result.json")).read_bytes())
review = json.loads((HERE / (STEM + "-result-review.json")).read_bytes())
post = json.loads((HERE / (STEM + "-source-post-verification.json")).read_bytes())
log = (HERE / (STEM + ".log")).read_bytes()
resources = (HERE / (STEM + "-resources.txt")).read_bytes()
assert raw["exit_code"] == receipt["exit_code"] == receipt["effective_exit_code"] == 0
assert receipt["phase_pass"] is True and receipt["issues"] == []
assert receipt["source_guards_pass"] is True and post["pass"] is True
assert receipt["log_sha256"] == pin(log)["sha256"]
assert receipt["resources_sha256"] == pin(resources)["sha256"]
assert review["log"] == pin(log) and review["pass"] is True
assert review["reported_test_count"] == 32 and review["reported_skipped"] == 0 and review["skip_lines"] == []
assert re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resources, re.M) == [b"0"]
text = log.decode()
names = re.findall(r"^(test_\w+) \(([^)]+)\) \.\.\.", text, re.M)
summary = re.findall(r"^Ran (\d+) tests? in ([0-9.]+)s$", text, re.M)
assert summary == [("32", "59.132")] and re.findall(r"^OK$", text, re.M) == ["OK"]
assert len(names) == len(set(names)) == 32
source = "native-source51-project-r26"
names_to_pin = [
    source + "-environment.json",
    source + "-preconditions.json",
    source + "-source-pre-verification.json",
    *[STEM + suffix for suffix in (
        ".log", "-resources.txt", "-raw-process-result.json", "-receipt.json",
        "-source-pre-verification.json", "-source-post-verification.json", "-result-review.json",
    )],
    "observed-running-process-status.json",
    "progress-original-process-read.json",
    "progress-original-stdout.txt",
    "progress-original-stderr.txt",
]
pins = [{"path": name, **pin((HERE / name).read_bytes())} for name in names_to_pin]
report = {
    "schema": "hepta.source51-r26-python-closed-local-readback.v1",
    "source_commit": receipt["source_commit"],
    "source_tree": receipt["source_tree"],
    "job_id": "1a1b1b739ee-fc05-7a70",
    "python_original_exit": 0,
    "python_effective_exit": 0,
    "reported_tests": 32,
    "observed_unique_unittest_names": 32,
    "unittest_names": [{"name": name, "qualified_name": qualified} for name, qualified in names],
    "reported_skipped": 0,
    "unittest_reported_seconds": float(summary[0][1]),
    "whole_command_elapsed_seconds": receipt["elapsed_seconds"],
    "all_source_and_dual_lock_guards_pass": True,
    "strict_started_from_original_stdout": True,
    "strict_terminal": None,
    "tests_terminal": None,
    "outer_terminal": None,
    "files": pins,
    "local_verification_attempt1_error_preserved": "LOCAL-READBACK-ATTEMPT-1-ERROR.json",
    "original_native_execution_repeated": False,
}
report_raw = (json.dumps(report, indent=2) + "\n").encode()
with (HERE / "LOCAL-READBACK.json").open("xb") as out:
    out.write(report_raw)
current = ROOT / "current-state.json"
with (ROOT / "current-state-before-r26-python-pass.json").open("xb") as out:
    out.write(current.read_bytes())
value = json.loads(current.read_bytes())
value.update(
    latest_gate_observation="RUNNING_STRICT_AFTER_PYTHON32_PASS",
    python_result={"exit_code": 0, "tests": 32, "skipped": 0, "elapsed_seconds": receipt["elapsed_seconds"]},
    strict_result=None, tests_result=None, first_control_error_preserved=True,
)
current.write_text(json.dumps(value, indent=2) + "\n")
print(json.dumps({"readback": pin(report_raw), "actual_unique_python_names": len(names)}))

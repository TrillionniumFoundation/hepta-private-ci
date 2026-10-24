"""Check only pinned, self-authored fixtures; never accepts an arbitrary candidate.

This preparation check is not an OS sandbox and is not an A/B model run. It
executes only the initial and reference source hashes in the reviewed index.
For model-produced source, use an external admitted sandbox and pack.py judge.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=pack.ROOT / "operator" / "author-selfcheck.json")
    args = parser.parse_args()
    destination = args.output
    if destination.exists() or destination.is_symlink():
        raise ValueError("refusing to overwrite a preparation receipt; choose a new --output")
    validation = pack.validate()
    records = []
    runner = pack.ROOT / "public" / "candidate_runner.py"
    for task in pack.read_index()["tasks"]:
        requests = b"".join(pack.canonical(item) + b"\n" for item in pack.requests_for(task))
        for kind in ("initial", "reference"):
            path = (pack.ROOT / "tasks" / task["slug"] / "repair_target.py" if kind == "initial"
                    else pack.ROOT / "private" / task["slug"] / "reference.py")
            expected_sha = task["initial_source_sha256" if kind == "initial" else "reference_sha256"]
            if path.is_symlink() or pack.digest(path.read_bytes()) != expected_sha:
                raise ValueError("untrusted source refused by author-only check")
            with tempfile.TemporaryDirectory(prefix="hepta-author-check-") as directory:
                process = subprocess.run([sys.executable, "-I", "-B", str(runner), "--candidate", str(path)],
                                         input=requests, capture_output=True, cwd=directory,
                                         env={"PYTHONHASHSEED": "0", "LC_ALL": "C.UTF-8"}, timeout=10)
            grade = pack.judge(task, process.stdout, expected_sha)
            record = {"task_id": task["task_id"], "slug": task["slug"], "kind": kind,
                      "source_sha256": expected_sha, "returncode": process.returncode,
                      "stderr": process.stderr.decode(errors="replace"), "grade": grade}
            records.append(record)
            if process.returncode != 0 or (kind == "reference" and not grade.get("success")):
                print(json.dumps(record, indent=2, ensure_ascii=False))
                raise SystemExit("author reference/adapter preparation defect; fix before freezing")
            if kind == "initial" and (grade.get("functional_status") != "fail" or grade.get("passed", 0) == 0):
                print(json.dumps(record, indent=2, ensure_ascii=False))
                raise SystemExit("initial must run, pass at least one case, and fail at least one case")
    result = {"schema": "hepta.native-ab.author-preparation-check.v1", "status": "completed",
              "validation": validation, "python_version": sys.version,
              "model_invocations": 0, "external_code_executed": False,
              "model_candidate_qualification": False, "records": records}
    destination.write_bytes(pack.canonical(result) + b"\n")
    print(json.dumps({"status": "completed", "tasks": len(records) // 2,
                      "references_all_passed": True, "initials_all_failed_with_some_passing_cases": True,
                      "receipt": str(destination), "receipt_sha256": pack.digest(destination.read_bytes())}))


if __name__ == "__main__":
    main()

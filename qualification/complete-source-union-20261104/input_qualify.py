#!/usr/bin/env python3
"""Run original strict readers and generate the isolated bridge lock for review."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qualification/fleet-private-registration-current"))
from common import identity, require, snapshot

LOCK = "tools/hia-ndu-bridge/Cargo.lock"
REBASE = "qualification/complete-source-union-20261104/sixth-ci/WINDOWS_MUTATION_REBASE.json"

def main():
    require(__debug__, "optimized Python is not accepted")
    output = Path(os.environ["RUNNER_TEMP"]) / "original-input-qualification"
    output.mkdir(exist_ok=False)
    before = snapshot(verify_index=True)
    head = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(head == os.environ["GITHUB_SHA"], "unexpected source commit")
    receipt = {"source_commit": head, "status": "failed", "commands": [], "run_id": os.environ["GITHUB_RUN_ID"]}
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")

    def run(name, argv, allow_failure=False):
        started = time.monotonic()
        result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output / (name + ".stdout")).write_bytes(result.stdout)
        (output / (name + ".stderr")).write_bytes(result.stderr)
        row = {"name": name, "argv": argv, "exit_code": result.returncode, "seconds": time.monotonic() - started,
               "stdout": identity(result.stdout), "stderr": identity(result.stderr)}
        receipt["commands"].append(row)
        print(json.dumps(row), flush=True)
        if result.returncode or "controls" in name:
            print(result.stdout.decode("utf-8", errors="replace"), flush=True)
            print(result.stderr.decode("utf-8", errors="replace"), flush=True)
        require(allow_failure or result.returncode == 0, "original command failed: " + name)
        return result

    def controls(directory, pattern, count):
        code = ("import unittest; s=unittest.defaultTestLoader.discover(" + repr(directory) + ",pattern=" + repr(pattern) + "); "
                "assert s.countTestCases()==" + str(count) + "; "
                "r=unittest.TextTestRunner(verbosity=2).run(s); "
                "assert r.wasSuccessful() and r.testsRun==" + str(count) + " and not (r.skipped or r.expectedFailures or r.unexpectedSuccesses)")
        run("reader-controls-" + str(count), ["python3", "-c", code])

    try:
        controls("qualification/fleet-private-registration-current", "test_readers.py", 32)
        controls(".github/scripts", "test_check_windows_private_state_acquisition.py", 8)
        for name in ("run_native.py", "run_bazel.py"):
            result = run("optimized-reader-" + name, ["python3", "-O", "qualification/fleet-private-registration-current/" + name], True)
            require(result.returncode != 0 and b"optimized Python is not accepted" in result.stderr,
                    "optimized strict reader was not rejected")
        rebase = json.loads((ROOT / REBASE).read_bytes())
        source = ROOT / rebase["production_path"]
        original = source.read_bytes()
        require(identity(original)["sha256"] == rebase["production_sha256"], "wrong mutation source")
        receipt["mutations"] = []
        for mutation in rebase["mutations"]:
            try:
                patch = ROOT / mutation["patch_path"]
                require(identity(patch.read_bytes())["sha256"] == mutation["patch_sha256"], "wrong mutation patch")
                run(mutation["lane"] + "-check", ["git", "apply", "--check", "--unidiff-zero", str(patch)])
                run(mutation["lane"] + "-apply", ["git", "apply", "--unidiff-zero", str(patch)])
                actual = identity(source.read_bytes())
                require(actual == mutation["mutant"], "actual applied mutant differs from reviewed bytes")
                require(subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).strip()
                        == rebase["production_path"], "mutation changed another source")
                (output / (mutation["lane"] + ".rs")).write_bytes(source.read_bytes())
                receipt["mutations"].append({"lane": mutation["lane"], "actual": actual, "patch": mutation["patch_path"]})
            finally:
                source.write_bytes(original)
                require(source.read_bytes() == original, "source restore failed")
        require(snapshot() == before, "reader or mutation check changed original source")
        lock = ROOT / LOCK
        shutil.copyfile(lock, output / "Cargo.lock.original")
        argv = ["cargo", "metadata", "--manifest-path", "tools/hia-ndu-bridge/Cargo.toml", "--format-version", "1"]
        first = run("original-committed-bridge-metadata", [*argv, "--locked", "--no-deps"], True)
        receipt["committed_first_exit"] = first.returncode
        if first.returncode:
            require(b"--locked was passed" in first.stderr, "committed-first failed for an unrelated reason")
            run("actual-bridge-lock-resolution", argv)
        run("resolved-bridge-locked-metadata", [*argv, "--locked"])
        after = snapshot()
        changes = sorted(path for path in before if before[path] != after.get(path))
        require(set(before) == set(after) and set(changes) <= {LOCK}, "unexpected input drift")
        receipt["changed_paths"] = changes
        receipt["other_inputs_unchanged"] = True
        raw = lock.read_bytes()
        row = {"path": LOCK, **identity(raw)}
        receipt["generated_lock"] = row
        (output / "Cargo.lock.generated").write_bytes(raw)
        receipt["packages"] = tomllib.loads(raw.decode())["package"]
        print("ORIGINAL_INPUT_BEGIN=" + json.dumps(row), flush=True)
        for offset in range(0, len(raw), 32768):
            part = raw[offset:offset + 32768]
            print("ORIGINAL_INPUT_PART=" + json.dumps({"path": LOCK, "offset": offset, "bytes": len(part), "base64": base64.b64encode(part).decode("ascii")}), flush=True)
        print("ORIGINAL_INPUT_END=" + json.dumps({"path": LOCK}), flush=True)
        receipt["status"] = "generated-needs-adoption" if changes else "committed-lock-unchanged"
    finally:
        after = snapshot()
        (output / "source-after.json").write_text(json.dumps(after, indent=2) + "\n")
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("ORIGINAL_INPUT_RESULT=" + json.dumps({key: value for key, value in receipt.items() if key != "packages"}), flush=True)

if __name__ == "__main__":
    main()

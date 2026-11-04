#!/usr/bin/env python3
"""Run the original three unfiltered library targets with fresh Bazel reports."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

from generate import ROOT, HERE, digest, require, snapshot

TARGETS = {
    "path": "//codex-rs/utils/path-utils:path-utils-unit-tests",
    "state": "//codex-rs/state:state-unit-tests",
    "memory": "//codex-rs/hepta-memory:hepta-memory-unit-tests",
}


def test_counts(raw, allowed_ignored):
    log = raw.decode("utf-8")
    summaries = re.findall(
        r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out",
        log)
    require(summaries, "missing Rust test completion")
    require(summaries[-1][0] == "ok", "final Rust result failed")
    passed, failed, ignored, measured, filtered = map(int, summaries[-1][1:])
    require(passed > 0 and failed == measured == filtered == 0, "incomplete original library")
    names = re.findall(r"^test (\S+) \.\.\. ignored(?:,.*)?$", log, re.MULTILINE)
    require(len(names) == len(set(names)) == ignored and set(names) == set(allowed_ignored),
            "original ignored set changed")
    require("skipping test:" not in log.lower(), "early-return skip reported")
    return {"passed": passed, "failed": failed, "original_ignored": names,
            "measured": measured, "filtered": filtered, "rust_summaries": summaries}


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    head = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", "HEAD"],
                                   cwd=ROOT, text=True).strip()
    config = json.loads((HERE / "scope.json").read_bytes())
    receipt = {"source_commit": head, "status": "failed", "commands": [], "targets": {},
               "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
               "host": platform.platform(),
               "scope": "Original Linux GNU Bazel library targets and scoped Clippy; other platforms use original native Cargo controls."}
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")

    def run(name, argv):
        started = time.monotonic()
        with (output / (name + ".stdout")).open("wb") as out, (output / (name + ".stderr")).open("wb") as err:
            process = subprocess.run(argv, cwd=ROOT, stdout=out, stderr=err)
        row = {"name": name, "argv": argv, "exit_code": process.returncode,
               "seconds": time.monotonic() - started}
        receipt["commands"].append(row)
        print(json.dumps(row), flush=True)
        if process.returncode:
            for suffix in ("stdout", "stderr"):
                print((output / (name + "." + suffix)).read_text(encoding="utf-8", errors="replace")[-20000:],
                      flush=True)
        return process.returncode

    try:
        require(head == os.environ["HEPTA_EXPECTED_COMMIT"], "unexpected source head")
        require(platform.system() == "Linux" and os.environ.get("BUILDBUDDY_API_KEY"),
                "requires original authenticated Linux GNU Bazel configuration")
        require(run("initial-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]) == 0,
                "dirty initial source")
        for name, command in (
            ("committed-lock-first", ["just", "bazel-lock-check"]),
            ("original-lock-update", ["just", "bazel-lock-update"]),
            ("original-lock-check", ["just", "bazel-lock-check"]),
        ):
            require(run(name, command) == 0, name + " failed")
        bash = str(Path(os.environ["MEMORY_QUALIFICATION_BASH"]).resolve(strict=True))
        receipt["bash_executable"] = bash
        startup = [f"--output_user_root={os.environ['BAZEL_OUTPUT_USER_ROOT']}"] if os.environ.get("BAZEL_OUTPUT_USER_ROOT") else []
        info = ["python3", "./.github/scripts/run_bazel_with_buildbuddy.py", *startup,
                "--noexperimental_remote_repo_contents_cache", "info", "--config=ci-linux", "bazel-testlogs"]
        require(run("original-testlog-location", info) == 0, "cannot locate original reports")
        directory = Path((output / "original-testlog-location.stdout").read_text().strip())
        reports = {}
        for name, target in TARGETS.items():
            package, label = target.removeprefix("//").split(":")
            reports[name] = directory / package / label
            for suffix in ("log", "xml"):
                path = reports[name] / ("test." + suffix)
                if path.exists():
                    path.unlink()
        wrapper = [bash, "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
                   "--print-failed-action-summary", "--remote-download-toplevel", "--"]
        code = run("original-library-targets", [*wrapper, "test", "--keep_going",
                   "--nocache_test_results", "--test_output=all", "--", *TARGETS.values()])
        for name, directory in reports.items():
            for suffix in ("log", "xml"):
                source = directory / ("test." + suffix)
                if source.is_file():
                    shutil.copyfile(source, output / (name + "." + suffix))
        require(code == 0, "original library target failed")
        combined = "".join((output / ("original-library-targets." + suffix)).read_text(
                           encoding="utf-8", errors="replace") for suffix in ("stdout", "stderr"))
        require(re.search(r"Executed 3 out of 3 tests?: 3 tests? pass", combined) is not None,
                "not all three targets actually executed")
        for name in TARGETS:
            allowed = config["original_ignored_memory_cases"] if name == "memory" else []
            receipt["targets"][name] = test_counts((output / (name + ".log")).read_bytes(), allowed)
            root = ET.fromstring((output / (name + ".xml")).read_bytes())
            require(list(root.iter("testcase")), "empty Bazel XML")
            require(not any(e.tag in {"failure", "error", "skipped"} for e in root.iter()),
                    "Bazel XML failure or skip")
            suites = list(root.iter("testsuite"))
            require(suites and all(int(s.get(k, "0")) == 0 for s in suites
                                   for k in ("failures", "errors", "skipped")), "bad wrapper counters")
        require(run("original-scoped-clippy", [*wrapper, "build", "--config=clippy", "--",
                    *(target + "-bin" for target in TARGETS.values())]) == 0,
                "original scoped Clippy failed")
        require(snapshot() == before, "source or committed lock changed")
        require(run("final-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]) == 0,
                "dirty final source")
        receipt["status"] = "passed"
    finally:
        receipt["source_after"] = snapshot()
        receipt["source_inputs_unchanged"] = receipt["source_after"] == before
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("BAZEL_QUALIFICATION_RESULT=" + json.dumps({
            key: value for key, value in receipt.items() if key not in {"source_after", "outputs"}
        }), flush=True)


if __name__ == "__main__":
    main()

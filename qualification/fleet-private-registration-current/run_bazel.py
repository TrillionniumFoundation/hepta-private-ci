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

from common import ROOT, HERE, BAZEL_GROUPS, BAZEL_SHARDS, digest, require, snapshot

def libtest_inventory(raw, allow_empty=False):
    text = raw.decode("utf-8").replace("\r\n", "\n")
    rows = re.findall(r"^(\S+): (test|benchmark)$", text, re.MULTILINE)
    require(all(kind == "test" for _, kind in rows), "unexpected benchmark inventory")
    names = [name for name, _ in rows]
    require(len(names) == len(set(names)) and (names or allow_empty),
            "empty or duplicate original inventory")
    return sorted(names)


def shard_index(name, count):
    value = 2166136261
    for byte in name.encode("utf-8"):
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value % count


def complete_shard_counts(logs, listed, allowed_ignored):
    require(logs and listed and len(listed) == len(set(listed)), "missing complete library inventory")
    allowed = set(allowed_ignored)
    require(allowed <= set(listed), "ignored cases missing from original inventory")
    all_names, ignored_names, summaries, shard_cases = [], [], [], []
    for index, raw in enumerate(logs):
        text = raw.decode("utf-8").replace("\r\n", "\n")
        matches = list(re.finditer(
            r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
            r"(\d+) measured; (\d+) filtered out", text))
        require(len(matches) == 1, "missing, duplicated or retried original shard summary")
        summary = matches[0]
        counts = list(map(int, summary.groups()[1:]))
        rows = re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)(?:,.*)?$",
                          text[:summary.start()], re.MULTILINE)
        require(not any(line.startswith("test ") for line in text[summary.end():].splitlines()),
                "unaccounted test output after shard completion")
        actual = [sum(status == value for _, status in rows) for value in ("ok", "FAILED", "ignored")]
        require(summary.group(1) == "ok" and actual == counts[:3] and counts[1] == counts[3] == 0,
                "original shard outcomes failed or do not match its counters")
        expected = {name for name in listed if shard_index(name, len(logs)) == index}
        names = [name for name, _ in rows]
        require(len(names) == len(set(names)) and set(names) == expected,
                "shard does not cover its complete original assigned cases")
        require(counts[4] == len(listed) - len(names), "shard filter count does not conserve the original universe")
        require("skipping test:" not in text.lower(), "early-return skip reported")
        all_names.extend(names)
        ignored_names.extend(name for name, status in rows if status == "ignored")
        summaries.append(counts)
        shard_cases.append(names)
    require(len(all_names) == len(set(all_names)) == len(listed) and set(all_names) == set(listed),
            "shards do not cover the complete disjoint original inventory")
    require(set(ignored_names) == allowed and len(ignored_names) == len(allowed),
            "original ignored set changed")
    passed = sum(row[0] for row in summaries)
    require(passed > 0, "zero original cases executed")
    return {"passed": passed, "failed": 0, "original_ignored": ignored_names,
            "measured": 0, "filtered": 0, "shard_counts": summaries, "shard_cases": shard_cases,
            "inventory": listed, "complete_disjoint_coverage": True}


def test_counts(raw, allowed_ignored):
    # The unsharded reader uses the actual case rows as its local inventory.
    # Runtime qualification additionally compares against independent --list output.
    text = raw.decode("utf-8").replace("\r\n", "\n")
    listed = sorted(re.findall(r"^test (\S+) \.\.\. (?:ok|FAILED|ignored)(?:,.*)?$", text, re.MULTILINE))
    return complete_shard_counts([raw], listed, allowed_ignored)


def report_members(directory, count):
    expected = ([Path("test.log")] if count == 1 else
                [Path(f"shard_{index + 1}_of_{count}") / "test.log" for index in range(count)])
    actual_logs = {path.relative_to(directory) for path in directory.rglob("test.log")}
    actual_xml = {path.relative_to(directory) for path in directory.rglob("test.xml")}
    require(actual_logs == set(expected) and actual_xml == {path.with_suffix(".xml") for path in expected},
            "missing, stale, extra or retried original shard reports")
    return [(directory / path, directory / path.with_suffix(".xml")) for path in expected]


def validate_wrapper_xml(raw):
    root = ET.fromstring(raw)
    cases = list(root.iter("testcase"))
    suites = list(root.iter("testsuite"))
    require(cases and suites, "empty Bazel shard XML")
    require(sum(int(suite.get("tests", "-1")) for suite in suites) == len(cases),
            "Bazel shard XML counters differ")
    bad = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
    require(not any(node.tag in bad for node in root.iter()), "Bazel shard failed, retried or skipped")
    require(all(int(suite.get(key, "0")) == 0 for suite in suites
                for key in ("failures", "errors", "skipped")), "bad wrapper counters")


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", choices=tuple(BAZEL_GROUPS), required=True)
    args = parser.parse_args()
    targets = BAZEL_GROUPS[args.group]
    shard_counts = BAZEL_SHARDS[args.group]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot(verify_index=True)
    head = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", "HEAD"],
                                   cwd=ROOT, text=True).strip()
    config = json.loads((HERE / "scope.json").read_bytes())
    receipt = {"source_commit": head, "group": args.group, "status": "failed", "commands": [], "targets": {},
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
        for name, target in targets.items():
            package, label = target.removeprefix("//").split(":")
            reports[name] = directory / package / label
            # Remove only this qualification's known generated target reports,
            # including every prior shard and retry, before the original test.
            if reports[name].exists():
                require(not reports[name].is_symlink(), "unexpected target-report symlink")
                shutil.rmtree(reports[name])
        wrapper = [bash, "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
                   "--print-failed-action-summary", "--remote-download-toplevel", "--"]
        # Bazel run supports one test execution artifact. Disable sharding only
        # for listing; the original test command below retains all four state shards.
        inventories = {}
        receipt["inventories"] = inventories
        for name, target in targets.items():
            require(run("original-inventory-" + name,
                        [*wrapper, "run", "--test_sharding_strategy=disabled", target, "--", "--list", "--format", "terse"]) == 0,
                    "original library inventory failed: " + name)
            require(run("original-ignored-inventory-" + name,
                        [*wrapper, "run", "--test_sharding_strategy=disabled", target, "--", "--list", "--format", "terse", "--ignored"]) == 0,
                    "original ignored inventory failed: " + name)
            listed = libtest_inventory((output / ("original-inventory-" + name + ".stdout")).read_bytes())
            ignored = libtest_inventory(
                (output / ("original-ignored-inventory-" + name + ".stdout")).read_bytes(), allow_empty=True)
            expected_ignored = config["original_ignored_memory_cases"] if name == "memory" else []
            require(set(ignored) == set(expected_ignored) and set(ignored) <= set(listed),
                    "original ignored inventory changed")
            inventories[name] = {"all_cases": listed, "original_ignored": ignored}
        code = run("original-library-targets", [*wrapper, "test", "--keep_going",
                   "--nocache_test_results", "--test_output=all", "--", *targets.values()])
        copied = {}
        for name, directory in reports.items():
            # Retain every actual report before enforcing completeness, also on failure.
            copied[name] = []
            for source in sorted(directory.rglob("*")):
                if source.is_file() and source.name in {"test.log", "test.xml"}:
                    relative = source.relative_to(directory).as_posix()
                    destination = name + "--" + relative.replace("/", "--")
                    shutil.copyfile(source, output / destination)
                    copied[name].append({"relative": relative, "file": destination})
        receipt["retained_reports"] = copied
        require(code == 0, "original library target failed")
        combined = "".join((output / ("original-library-targets." + suffix)).read_text(
                           encoding="utf-8", errors="replace") for suffix in ("stdout", "stderr"))
        require(re.search(r"Executed 3 out of 3 tests?: 3 tests? pass", combined) is not None,
                "not all three targets actually executed")
        for name, directory in reports.items():
            pairs = report_members(directory, shard_counts[name])
            for _, xml in pairs:
                validate_wrapper_xml(xml.read_bytes())
            allowed = config["original_ignored_memory_cases"] if name == "memory" else []
            receipt["targets"][name] = complete_shard_counts(
                [log.read_bytes() for log, _ in pairs], inventories[name]["all_cases"], allowed)
        require(run("original-scoped-clippy", [*wrapper, "build", "--config=clippy", "--",
                    *(target + "-bin" for target in targets.values())]) == 0,
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

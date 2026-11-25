"""One exact-source native run, admitted only after both locks are accepted.

The original command owner and original JUnit collector retain their authority.
This adds source/lock pins and the exact 25-name roster; it does not create a
JUnit report, retry a test, update a lock, or qualify the remaining Chrono uses.
"""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import xml.etree.ElementTree as ET


SPEC_PATH = "scripts/hepta_chrono_native_inputs_v1.json"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
LOCKS = {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
NATIVE_CAP_SECONDS = 2400
EXACT_TESTS = 25


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def json_value(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def read_regular(path, maximum=64 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode) and before.st_size <= maximum,
            "input is not a bounded regular file",
        )
        chunks, total = [], 0
        while chunk := os.read(fd, min(64 * 1024, maximum + 1 - total)):
            total += len(chunk)
            require(total <= maximum, "input exceeded its bound")
            chunks.append(chunk)
        after = os.fstat(fd)
        stable = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        require(
            stable(before) == stable(after) and total == before.st_size,
            "input changed during the same-descriptor read",
        )
        return b"".join(chunks), before
    finally:
        os.close(fd)


def put(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def git(root, *arguments):
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        timeout=10,
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0"),
    )
    return result.stdout


def original_module(path, name):
    module_spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(value)
    return value


def load_inputs(root):
    raw, _ = read_regular(root / SPEC_PATH, 1024 * 1024)
    spec = json_value(raw)
    require(
        spec["schema"] == "hepta.chrono-native-accepted-inputs.v1"
        and spec["activated"] is True,
        "native candidate has not been admitted after lock review",
    )
    require(
        os.environ["GITHUB_REPOSITORY"] == REPOSITORY
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["CHRONO_EVENT_ACTION"] == "opened"
        and os.environ["CHRONO_PR_AUTHOR"] == "ProfHepta"
        and os.environ["CHRONO_PR_DRAFT"] == "true"
        and os.environ["CHRONO_HEAD_REPO"] == REPOSITORY
        and os.environ["CHRONO_HEAD_BRANCH"] == spec["branch"],
        "this is not the one original owned Draft opening",
    )
    head = os.environ["SOURCE_SHA"]
    require(
        re.fullmatch(r"[0-9a-f]{40}", head) is not None
        and os.environ["TESTED_SHA"] == head
        and os.environ["HEPTA_CI_LANE"] == "source-head",
        "source identity or lane is absent",
    )
    require(
        git(root, "rev-parse", "HEAD").decode().strip() == head
        and not git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        "native source is not the original clean event head",
    )
    headers = (
        git(root, "cat-file", "-p", head).split(b"\n\n", 1)[0].decode().splitlines()
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", spec["parent"] or "") is not None
        and [line[7:] for line in headers if line.startswith("parent ")]
        == [spec["parent"]],
        "native candidate has an unexpected parent",
    )
    require(
        all(
            row.startswith(b"H ")
            for row in git(root, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "native input hides files through index flags",
    )
    rows = spec["reviewed_sources"]
    require(
        len(rows) == len({row["path"] for row in rows}), "source pins repeat a path"
    )
    required = {
        "scripts/hepta_ci_exec.py",
        "scripts/hepta_ci_junit.py",
        "scripts/run-nextest.py",
        "scripts/just-shell.py",
        "justfile",
        "codex-rs/.config/nextest.toml",
        "codex-rs/rust-toolchain.toml",
        "scripts/run_chrono_native_controls_v1.py",
        ".github/workflows/hepta-chrono-native-controls-v1.yml",
    }
    require(
        required <= {row["path"] for row in rows},
        "an original execution input is not pinned",
    )
    for row in rows:
        relative = Path(row["path"])
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "source pin leaves checkout",
        )
        data, observed = read_regular(root / relative)
        require(
            len(data) == row["bytes"]
            and sha256(data) == row["sha256"]
            and row["mode"] in ("100644", "100755")
            and bool(observed.st_mode & 0o111) == (row["mode"] == "100755"),
            "source differs from the reviewed candidate: " + row["path"],
        )
    accepted = spec["accepted_locks"]
    require(
        isinstance(accepted, dict) and set(accepted) == LOCKS,
        "both independently accepted generated locks are required",
    )
    for relative, row in accepted.items():
        data, _ = read_regular(root / relative)
        require(
            len(data) == row["bytes"] and sha256(data) == row["sha256"],
            "native source does not contain the accepted lock original",
        )
    require(
        re.fullmatch(r"[0-9a-f]{64}", spec["lock_acceptance_review_sha256"] or "")
        is not None
        and re.fullmatch(r"[0-9a-f]{40}", spec["lock_generation_source"] or "")
        is not None,
        "independent lock acceptance has not been bound",
    )
    roster = [(row["package"], row["name"]) for row in spec["controls"]]
    require(
        len(roster) == len(set(roster)) == EXACT_TESTS
        and spec["native_cap_seconds"] == NATIVE_CAP_SECONDS,
        "the fixed 25-name roster or original command cap changed",
    )
    for package, name in roster:
        require(
            re.fullmatch(r"[a-z][a-z0-9-]+", package) is not None
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:]*", name) is not None,
            "a test selector contains unsupported syntax",
        )
    packages = sorted({package for package, _ in roster})
    command = ["just", "test", "--locked"]
    for package in packages:
        command.extend(["-p", package])
    command.extend(
        [
            "--lib",
            "--retries",
            "0",
            "--test-threads",
            "1",
            "-E",
            " | ".join(
                f"(package(={package}) & test(={name}))" for package, name in roster
            ),
        ]
    )
    require(
        command == spec["command"], "command differs from the source-defined roster"
    )
    return (
        spec,
        {
            "head": head,
            "tree": next(line[5:] for line in headers if line.startswith("tree ")),
            "spec_sha256": sha256(raw),
            "parent": spec["parent"],
        },
        command,
    )


def execute(root, evidence, spec, identity, command):
    require(
        not (root / "codex-rs/target/nextest/local/junit.xml").exists(),
        "native JUnit must not exist before the original run",
    )
    put(
        evidence / "admitted-inputs.json",
        {
            "source": identity,
            "accepted_locks": spec["accepted_locks"],
            "lock_generation_source": spec["lock_generation_source"],
            "lock_acceptance_review_sha256": spec["lock_acceptance_review_sha256"],
            "controls": spec["controls"],
            "command": command,
            "automatic_retry": False,
            "old_scientific_budget_used": 0,
        },
    )
    owner = original_module(
        root / "scripts/hepta_ci_exec.py", "original_chrono_native_command_owner"
    )
    exit_code = owner.run(
        evidence / "controls.json",
        command,
        minimum_tests=EXACT_TESTS,
        timeout_seconds=NATIVE_CAP_SECONDS,
    )
    raw, _ = read_regular(evidence / "controls.json", 1024 * 1024)
    record = json_value(raw)
    require(
        exit_code == 0
        and record["status"] == "passed"
        and record["observed_passed_tests"] == EXACT_TESTS
        and record["observed_failed_tests"] == 0,
        "the one original command did not observe all 25 controls passing",
    )
    return {
        "status": "NATIVE_COMMAND_PASSED_REQUIRES_JUNIT",
        "source": identity,
        "execution_sha256": sha256(raw),
        "observed_passed_tests": EXACT_TESTS,
    }


def collect(root, evidence, spec, identity, command):
    collector = original_module(
        root / "scripts/hepta_ci_junit.py", "original_chrono_native_junit_owner"
    )
    output = evidence / "controls.junit.xml"
    exit_code = collector.collect(
        evidence / "controls.json",
        root / "codex-rs/target/nextest/local/junit.xml",
        output,
    )
    require(
        exit_code == 0, "the original native JUnit collector rejected this observation"
    )
    raw, _ = read_regular(output)
    summary_raw, _ = read_regular(output.with_suffix(".summary.json"), 1024 * 1024)
    summary = json_value(summary_raw)
    require(
        summary["status"] == "passed"
        and summary["junit_sha256"] == sha256(raw)
        and summary["junit_bytes"] == len(raw)
        and summary["source_sha"] == identity["head"]
        and summary["source_tree"] == identity["tree"]
        and summary["command"] == command,
        "retained native original does not match the collector's exact source observation",
    )
    document = ET.fromstring(
        raw, parser=ET.XMLParser(target=collector.NoDoctypeTreeBuilder())
    )
    cases = list(document.iter("testcase"))
    require(
        not any(
            case.find(tag) is not None
            for case in cases
            for tag in ("skipped", "failure", "error")
        ),
        "native JUnit contains a skipped, failed, or errored control",
    )
    actual = Counter(
        (case.attrib.get("classname"), case.attrib.get("name")) for case in cases
    )
    expected = Counter((row["package"], row["name"]) for row in spec["controls"])
    require(
        len(cases) == EXACT_TESTS and actual == expected,
        "native JUnit does not contain exactly the 25 original package/name pairs",
    )
    return {
        "status": "EXACT_25_NATIVE_CONTROLS_PASSED",
        "source": identity,
        "junit_sha256": sha256(raw),
        "collector_summary_sha256": sha256(summary_raw),
        "names": [{"package": key[0], "name": key[1]} for key in sorted(actual)],
        "chrono_advisory_closed": False,
        "old_scientific_qualification_transferred": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("execute", "collect"))
    mode = parser.parse_args().mode
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    evidence = Path(os.environ["CHRONO_NATIVE_EVIDENCE"]).resolve(strict=True)
    require(
        not evidence.is_relative_to(root) and not root.is_relative_to(evidence),
        "native evidence must remain outside the source checkout",
    )
    started = time.monotonic()
    result = {
        "status": "FAIL",
        "mode": mode,
        "original_scope_reopened": False,
        "resolver_executions": 0,
        "automatic_retry": False,
    }
    try:
        spec, identity, command = load_inputs(root)
        if mode == "execute":
            result.update(execute(root, evidence, spec, identity, command))
        else:
            result.update(collect(root, evidence, spec, identity, command))
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        put(evidence / (mode + ".RESULT.json"), result)
        print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())

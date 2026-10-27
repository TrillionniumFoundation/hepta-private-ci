#!/usr/bin/env python3
"""CI-only archive/replay of the frozen original dependency-impact scope."""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

SOURCE = "4223fc77944e9beb5651df063158b22ae1a4f701"
TREE = "7c19c9903d4e82baf3a61111214ff3fe46605cef"
BASE = "de0ddaa41bd91c4f46a2f1b6034d25fa84c4469c"
SHARDS = 4
ARCHIVE_LIMIT = 8 * 1024**3
JSON_LIMIT = 64 * 1024**2
HELPERS = ("codex-linux-sandbox", "codex-execve-wrapper")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(), f"missing regular file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    require(path.stat().st_size <= JSON_LIMIT, f"oversized JSON: {path}")
    return json.loads(path.read_text())


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def output(command, root):
    return subprocess.check_output(command, cwd=root, text=True, timeout=60).strip()


def identity(root):
    require(os.geteuid() != 0, "ordinary scoped tests must not run as Root")
    require(output(["git", "rev-parse", "HEAD"], root) == SOURCE, "wrong source SHA")
    require(
        output(["git", "rev-parse", "HEAD^{tree}"], root) == TREE, "wrong source tree"
    )
    require(not output(["git", "status", "--porcelain"], root), "dirty product source")
    target = Path(os.environ["CARGO_TARGET_DIR"]).resolve()
    require(
        target == Path(os.environ["RUNNER_TEMP"]) / "hepta-scoped-4223/target",
        "unexpected target path",
    )
    versions = {
        name: output(args, root / "codex-rs")
        for name, args in {
            "rustc": ["rustc", "-vV"],
            "cargo": ["cargo", "--version"],
            "nextest": ["cargo", "nextest", "--version"],
            "just": ["just", "--version"],
        }.items()
    }
    require("release: 1.96.0" in versions["rustc"].splitlines(), "wrong compiler")
    require(versions["cargo"].startswith("cargo 1.96.0 "), "wrong Cargo")
    require(versions["nextest"].startswith("cargo-nextest 0.9.103 "), "wrong nextest")
    require(versions["just"] == "just 1.51.0", "wrong just")
    implementation = Path(__file__).resolve().parents[1]
    require(
        output(["git", "rev-parse", "HEAD"], implementation)
        == os.environ["WORKFLOW_SHA"],
        "wrong workflow implementation",
    )
    return {
        "source_sha": SOURCE,
        "source_tree": TREE,
        "base_sha": BASE,
        "source_path": str(root),
        "target_path": str(target),
        "tools": versions,
        "workflow_sha": os.environ["WORKFLOW_SHA"],
        "qualification_helper_sha256": digest(Path(__file__).resolve()),
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "inputs": {
            p: digest(root / p)
            for p in (
                "codex-rs/Cargo.lock",
                "codex-rs/rust-toolchain.toml",
                "codex-rs/.config/nextest.toml",
                "justfile",
                "scripts/run-nextest.py",
                "scripts/hepta_ci_dependencies.py",
            )
        },
    }


def recorded(root, out, name, command, seconds, minimum=0):
    record = out / f"{name}.json"
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/hepta_ci_exec.py"),
            "--output",
            str(record),
            "--timeout-seconds",
            str(seconds),
            "--minimum-tests",
            str(minimum),
            "--",
            *command,
        ],
        cwd=root / "codex-rs",
        check=True,
    )
    value = load(record)
    require(
        value["status"] == "passed"
        and value["exit_code"] == 0
        and value["tested_sha"] == SOURCE
        and not value["timed_out"],
        "command did not pass",
    )
    return value


def capture(root, path, command):
    with path.open("xb") as stream, path.with_suffix(".stderr").open("xb") as errors:
        subprocess.run(
            command,
            cwd=root / "codex-rs",
            stdout=stream,
            stderr=errors,
            timeout=600,
            check=True,
        )
    return load(path)


def native_command(root, plan):
    require(
        plan["base_sha"] == BASE and plan["tested_sha"] == SOURCE,
        "wrong impact comparison",
    )
    require(
        plan["full_workspace"] is False
        and len(plan["packages"]) == 124
        and len(set(plan["packages"])) == 124,
        "unexpected frozen scope",
    )
    sys.path.insert(0, str(root))
    original = importlib.import_module("scripts.hepta_ci_dependencies")
    require(
        Path(original.__file__).resolve() == root / "scripts/hepta_ci_dependencies.py",
        "wrong planner",
    )
    command = original.execution_command(plan, "test")
    require(
        command[:3] == ["just", "test", "--locked"], "changed original test entrypoint"
    )
    return command


def inventory(document, packages, partition=False):
    all_tests, selected, ignored = set(), set(), set()
    for binary, suite in document["rust-suites"].items():
        require(
            binary == suite["binary-id"] and suite["status"] == "listed",
            "unlisted/aliased binary",
        )
        require(suite["package-name"] in packages, "binary outside selected packages")
        for name, case in suite["testcases"].items():
            key = (binary, name)
            require(
                key not in all_tests and type(case["ignored"]) is bool,
                "invalid test identity",
            )
            all_tests.add(key)
            match = case["filter-match"]
            if case["ignored"]:
                require(
                    match == {"status": "mismatch", "reason": "ignored"},
                    "ignored boundary changed",
                )
                ignored.add(key)
            elif match == {"status": "matches"}:
                selected.add(key)
            else:
                require(
                    partition
                    and match == {"status": "mismatch", "reason": "partition"},
                    "unexpected filter",
                )
    require(
        document["test-count"] == len(all_tests) and selected,
        "empty/incomplete test inventory",
    )
    return all_tests, selected, ignored


def junit_passes(path, expected):
    require(path.stat().st_size <= JSON_LIMIT, "oversized JUnit")
    data = path.read_bytes()
    require(b"<!DOCTYPE" not in data, "unexpected JUnit document type")
    root = ET.fromstring(data)
    require(
        root.tag == "testsuites" and int(root.attrib["tests"]) == len(expected),
        "JUnit count differs",
    )
    require(
        root.attrib.get("failures") == "0" and root.attrib.get("errors") == "0",
        "JUnit failed",
    )
    observed, retried = set(), []
    for suite in root.findall("testsuite"):
        cases = suite.findall("testcase")
        require(int(suite.attrib["tests"]) == len(cases), "incomplete JUnit suite")
        for case in cases:
            key = (suite.attrib["name"], case.attrib["name"])
            require(
                case.attrib["classname"] == key[0] and key not in observed,
                "aliased/duplicate JUnit test",
            )
            require(
                not any(
                    case.find(tag) is not None
                    for tag in ("failure", "error", "skipped")
                ),
                "test did not pass",
            )
            observed.add(key)
            attempts = len(case.findall("flakyFailure")) + len(
                case.findall("flakyError")
            )
            if attempts:
                retried.append((*key, attempts))
    require(observed == expected, "JUnit identities differ from selected inventory")
    return sorted(retried)


def archive_arguments(root, artifact):
    target = Path(os.environ["CARGO_TARGET_DIR"])
    target.parent.mkdir(parents=True, exist_ok=True)
    # Let nextest restore binaries and its archived libdir on every invocation.
    # Its binaries-only JSON still contains producer paths in version 0.9.103.
    return [
        "--archive-file",
        str(artifact / "tests.tar.zst"),
        "--extract-to",
        str(target.parent),
        "--extract-overwrite",
        "--workspace-remap",
        str(root / "codex-rs"),
    ]


def prepare(root, out):
    out.mkdir(parents=True, exist_ok=False)
    save(out / "identity.json", identity(root))
    save(
        out / "resources.json",
        {
            "cpu_count": os.cpu_count(),
            "disk": shutil.disk_usage(out)._asdict(),
            "meminfo": Path("/proc/meminfo").read_text(),
            "build_jobs": os.environ["CARGO_BUILD_JOBS"],
            "test_threads": 2,
            "archive_command_seconds": 7200,
            "replay_command_seconds": 3600,
            "archive_bytes_limit": ARCHIVE_LIMIT,
        },
    )
    recorded(
        root,
        out,
        "plan-command",
        [
            sys.executable,
            str(root / "scripts/hepta_ci_dependencies.py"),
            "--root",
            str(root),
            "--base",
            BASE,
            "--tested",
            SOURCE,
            "--output",
            str(out / "plan.json"),
        ],
        600,
    )
    save(out / "original-command.json", native_command(root, load(out / "plan.json")))


def archive(root, out, artifact):
    require(identity(root) == load(out / "identity.json"), "prepared identity changed")
    artifact.mkdir(parents=True, exist_ok=False)
    command = native_command(root, load(out / "plan.json"))
    # Build the two original helpers first: archive construction then leaves
    # any helper included by the complete feature graph at its final bytes.
    recorded(
        root,
        out,
        "helper-command",
        [
            "cargo",
            "build",
            "--locked",
            "-p",
            "codex-linux-sandbox",
            "--bin",
            HELPERS[0],
            "-p",
            "codex-shell-escalation",
            "--bin",
            HELPERS[1],
        ],
        1200,
    )
    recorded(
        root,
        out,
        "archive-command",
        [
            "cargo",
            "nextest",
            "archive",
            *command[2:],
            "--archive-file",
            str(artifact / "tests.tar.zst"),
        ],
        7200,
    )
    require(
        (artifact / "tests.tar.zst").stat().st_size <= ARCHIVE_LIMIT,
        "archive exceeds declared 8 GiB budget",
    )
    for name in HELPERS:
        source = Path(os.environ["CARGO_TARGET_DIR"]) / "debug" / name
        require(source.stat().st_size <= 256 * 1024**2, "runtime helper exceeds budget")
        shutil.copyfile(source, artifact / name)
    reuse = archive_arguments(root, artifact)
    full = capture(
        root,
        out / "inventory.json",
        ["cargo", "nextest", "list", *reuse, "--message-format", "json"],
    )
    for name in HELPERS:
        require(
            digest(Path(os.environ["CARGO_TARGET_DIR"]) / "debug" / name)
            == digest(artifact / name),
            "archive/helper bytes differ",
        )
    all_tests, selected, ignored = inventory(full, load(out / "plan.json")["packages"])
    require(
        identity(root) == load(out / "identity.json"), "archive changed source identity"
    )
    for name in ("identity.json", "plan.json", "inventory.json"):
        shutil.copyfile(out / name, artifact / name)
    manifest = {
        "status": "built",
        "identity": load(out / "identity.json"),
        "files": {
            p.name: {"sha256": digest(p), "bytes": p.stat().st_size}
            for p in artifact.iterdir()
        },
        "all_tests": len(all_tests),
        "runnable_tests": len(selected),
        "ignored_tests": len(ignored),
        "records": {
            name: digest(out / name)
            for name in (
                "plan-command.json",
                "archive-command.json",
                "helper-command.json",
            )
        },
    }
    save(out / "manifest.json", manifest)
    save(artifact / "manifest.json", manifest)


def replay(root, out, artifact, shard):
    require(1 <= shard <= SHARDS, "invalid shard")
    out.mkdir(parents=True, exist_ok=False)
    manifest = load(artifact / "manifest.json")
    require(
        manifest["status"] == "built" and manifest["identity"] == identity(root),
        "archive/source identity mismatch",
    )
    require(
        set(manifest["files"])
        == {"tests.tar.zst", *HELPERS, "identity.json", "plan.json", "inventory.json"},
        "archive inputs differ",
    )
    for name, expected in manifest["files"].items():
        path = artifact / name
        require(
            path.stat().st_size == expected["bytes"]
            and digest(path) == expected["sha256"],
            "artifact bytes changed",
        )
    target = Path(os.environ["CARGO_TARGET_DIR"])
    require(not target.exists(), "replay target is not fresh")
    reuse = archive_arguments(root, artifact)
    partition = ["--partition", f"hash:{shard}/{SHARDS}"]
    (target / "debug").mkdir(parents=True)
    for name in HELPERS:
        path = target / "debug" / name
        shutil.copyfile(artifact / name, path)
        path.chmod(0o755)
        os.environ[f"CARGO_BIN_EXE_{name}"] = str(path)
        os.environ[f"CARGO_BIN_EXE_{name.replace('-', '_')}"] = str(path)
    listed = capture(
        root,
        out / "inventory.json",
        ["cargo", "nextest", "list", *reuse, *partition, "--message-format", "json"],
    )
    for name in HELPERS:
        require(
            digest(target / "debug" / name) == digest(artifact / name),
            "extracted runtime helper differs",
        )
    packages = load(artifact / "plan.json")["packages"]
    all_tests, selected, ignored = inventory(listed, packages, partition=True)
    full_all, full_selected, full_ignored = inventory(
        load(artifact / "inventory.json"), packages
    )
    require(
        all_tests == full_all and ignored == full_ignored and selected <= full_selected,
        "replay inventory changed",
    )
    junit = out / "junit.xml"
    reporting = out / "reporting.toml"
    reporting.write_text(
        "[profile.local.junit]\npath = " + json.dumps(str(junit)) + "\n"
    )
    recorded(
        root,
        out,
        "test-command",
        [
            "just",
            "test",
            *reuse,
            *partition,
            "--test-threads",
            "2",
            "--tool-config-file",
            f"hepta-scoped:{reporting}",
        ],
        3600,
        minimum=len(selected),
    )
    retried = junit_passes(junit, selected)
    for name in HELPERS:
        require(
            digest(target / "debug" / name) == digest(artifact / name),
            "runtime helper changed",
        )
    require(identity(root) == manifest["identity"], "tests changed source identity")
    save(
        out / "result.json",
        {
            "status": "passed",
            "shard": shard,
            "manifest_sha256": digest(artifact / "manifest.json"),
            "selected": sorted(selected),
            "junit_sha256": digest(junit),
            "inventory_sha256": digest(out / "inventory.json"),
            "record_sha256": digest(out / "test-command.json"),
            "retried": retried,
            "ignored_not_qualified": len(ignored),
            "partition_excluded": len(full_selected - selected),
            "missing": 0,
        },
    )


def summarize(out, build, shards, needs):
    out.mkdir(parents=True, exist_ok=False)
    require(
        set(needs) == {"archive", "replay"}
        and all(n["result"] == "success" for n in needs.values()),
        "a required job did not succeed",
    )
    manifest = load(build / "manifest.json")
    require(manifest["status"] == "built", "archive stage missing")
    bound = manifest["identity"]
    require(
        (bound["source_sha"], bound["source_tree"], bound["base_sha"])
        == (SOURCE, TREE, BASE),
        "wrong frozen product",
    )
    require(
        bound["workflow_sha"] == os.environ["WORKFLOW_SHA"]
        and bound["qualification_helper_sha256"] == digest(Path(__file__).resolve())
        and bound["run_id"] == os.environ["GITHUB_RUN_ID"]
        and bound["run_attempt"] == os.environ["GITHUB_RUN_ATTEMPT"],
        "stale/foreign qualification evidence",
    )
    for name in ("identity.json", "plan.json", "inventory.json"):
        require(
            digest(build / name) == manifest["files"][name]["sha256"],
            "build inputs changed",
        )
    require(
        set(manifest["records"])
        == {"plan-command.json", "archive-command.json", "helper-command.json"},
        "missing build stage",
    )
    for name, expected in manifest["records"].items():
        record = load(build / name)
        require(
            digest(build / name) == expected
            and record["status"] == "passed"
            and record["exit_code"] == 0
            and record["tested_sha"] == SOURCE
            and record["before"] == record["after"]
            and record["before"]["dirty"] is False,
            "build record missing/failed",
        )
    packages = load(build / "plan.json")["packages"]
    require(len(packages) == len(set(packages)) == 124, "incomplete package scope")
    all_tests, expected, ignored = inventory(load(build / "inventory.json"), packages)
    require(
        (manifest["all_tests"], manifest["runnable_tests"], manifest["ignored_tests"])
        == (len(all_tests), len(expected), len(ignored)),
        "archive inventory counts differ",
    )
    observed, retried = set(), []
    require(
        {p.name for p in shards.iterdir()}
        == {f"shard-{i}" for i in range(1, SHARDS + 1)},
        "missing/extra shards",
    )
    for i in range(1, SHARDS + 1):
        directory = shards / f"shard-{i}"
        result = load(directory / "result.json")
        require(
            result["status"] == "passed"
            and result["shard"] == i
            and result["manifest_sha256"] == digest(build / "manifest.json"),
            "shard identity differs",
        )
        for name, key in (
            ("junit.xml", "junit_sha256"),
            ("inventory.json", "inventory_sha256"),
            ("test-command.json", "record_sha256"),
        ):
            require(digest(directory / name) == result[key], "shard evidence changed")
        shard_all, selected, shard_ignored = inventory(
            load(directory / "inventory.json"), packages, partition=True
        )
        require(
            shard_all == all_tests
            and shard_ignored == ignored
            and not observed & selected,
            "overlap/inventory mismatch",
        )
        require(
            result["ignored_not_qualified"] == len(ignored)
            and result["missing"] == 0
            and result["partition_excluded"] == len(expected - selected),
            "shard accounting changed",
        )
        require(
            sorted(selected) == [tuple(x) for x in result["selected"]],
            "shard result differs",
        )
        attempts = junit_passes(directory / "junit.xml", selected)
        require(
            attempts == [tuple(x) for x in result["retried"]],
            "retry accounting changed",
        )
        retried.extend(attempts)
        record = load(directory / "test-command.json")
        require(
            record["status"] == "passed"
            and record["exit_code"] == 0
            and record["tested_sha"] == SOURCE
            and record["minimum_tests"]
            == record["observed_passed_tests"]
            == len(selected)
            and record["observed_failed_tests"] == 0
            and not record["timed_out"]
            and not record["output_limit_exceeded"]
            and record["after"] == record["before"]
            and record["before"]["commit"] == SOURCE
            and record["before"]["tree"] == TREE
            and record["before"]["dirty"] is False,
            "native test record failed",
        )
        observed |= selected
    require(
        observed == expected,
        "shard union does not equal complete runnable test inventory",
    )
    save(
        out / "summary.json",
        {
            "status": "passed",
            "source_sha": SOURCE,
            "source_tree": TREE,
            "manifest_sha256": digest(build / "manifest.json"),
            "packages": len(packages),
            "runnable_passed": len(observed),
            "ignored_not_qualified": len(ignored),
            "ignored_tests": sorted(ignored),
            "retried_tests": sorted(retried),
            "missing_tests": 0,
            "shards": SHARDS,
            "product_qualified": False,
            "replaces_required_gate": False,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "archive", "replay", "summarize"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--shard", type=int)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--shards", type=Path)
    args = parser.parse_args()
    if args.source:
        source = args.source.resolve(strict=True)
        require(
            not args.output.resolve().is_relative_to(source),
            "evidence must be outside frozen source",
        )
        if args.artifact:
            require(
                not args.artifact.resolve().is_relative_to(source),
                "artifacts must be outside frozen source",
            )
    try:
        if args.action == "summarize":
            summarize(
                args.output, args.build, args.shards, json.loads(os.environ["NEEDS"])
            )
        else:
            root = args.source.resolve(strict=True)
            os.environ.update(
                SOURCE_SHA=SOURCE,
                TESTED_SHA=SOURCE,
                BASE_SHA=BASE,
                HEPTA_CI_LANE="source-head",
                NEXTEST_PROFILE="local",
                RUST_MIN_STACK="8388608",
                CODEX_REPO_ROOT=str(root),
                CARGO_TARGET_DIR=str(
                    Path(os.environ["RUNNER_TEMP"]) / "hepta-scoped-4223/target"
                ),
            )
            if args.action == "prepare":
                prepare(root, args.output)
            elif args.action == "archive":
                archive(root, args.output, args.artifact)
            else:
                replay(root, args.output, args.artifact, args.shard)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ET.ParseError,
        subprocess.SubprocessError,
    ) as error:
        args.output.mkdir(parents=True, exist_ok=True)
        save(
            args.output / "failure.json",
            {"status": "failed", "stage": args.action, "error": str(error)},
        )
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()

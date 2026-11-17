"""Record whole Core integration and worker-host gates without adding process deadlines."""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET


BASE = "de977dbce164848f7b7175e423c5c8f95729e430"
SOURCE = "30c68cf4a28199d84fabaf64ba289234fc4ec31b"
SOURCE_TREE = "cf5b84888a74a7e2314b561000bbd40024ff5103"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
REF = "refs/heads/integration/hepta-rust-validation-20261117-59d82"
CI_PATHS = {
    ".github/workflows/hepta-guardian-microbatch-validation.yml",
    ".github/scripts/validate_guardian_microbatch.py",
}
REVIEWED_TEST_BLOBS = {
    "codex-rs/core/tests/suite/network_approval.rs": "6abf7adb41876d4895b20c00892192ff4307bb20",
    "codex-rs/hepta-infer-worker-host/src/neuron_microbatch_tests.rs": "016296eb639027997cb2d1f9ac4d06e18a455317",
}
HOST_CASES = (
    "neuron_microbatch::tests::planner_accepts_two_requests_with_identical_snapshots",
    "neuron_microbatch::tests::planner_rejects_one_unit_change_in_second_snapshot_feature",
)
GUARDIAN_CASE = "suite::network_approval::timed_out_guardian_network_review_uses_timeout_outcome_without_user_fallback"
CORE_TARGET = "//codex-rs/core:core-all-test"
CORE_SHARDS = 16
MAX_LOG_BYTES = 64 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]
CWD = ROOT / "codex-rs"


def now():
    return datetime.now(timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(
        ["git", "-c", "protocol.allow=never", *args],
        cwd=ROOT,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"},
    )


def save(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    if path.suffix == ".gz":
        data = gzip.compress(data, mtime=0)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return {
        "path": path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def file_identity(path):
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode):
        data = os.fsencode(os.readlink(path))
        return {
            "mode": "120000",
            "bytes": len(data),
            "blob": hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data
            ).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"not a tracked regular file or link: {path}")
    sha = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            sha.update(chunk)
            blob.update(chunk)
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if total != before.st_size or any(
        getattr(before, f) != getattr(after, f) for f in fields
    ):
        raise ValueError(f"file changed while being recorded: {path}")
    return {
        "mode": "100755" if before.st_mode & 0o111 else "100644",
        "bytes": total,
        "blob": blob.hexdigest(),
        "sha256": sha.hexdigest(),
    }


def snapshot(output, name):
    rows = []
    for raw in git("ls-files", "--stage", "-z").split(b"\0"):
        if not raw:
            continue
        metadata, path_raw = raw.split(b"\t", 1)
        mode, blob, stage = metadata.decode().split()
        path = os.fsdecode(path_raw)
        row = {"path": path, "indexMode": mode, "indexBlob": blob, "stage": stage}
        try:
            if mode == "160000":
                raise ValueError("submodule content is outside this file manifest")
            row.update(file_identity(ROOT / path))
        except (OSError, ValueError) as error:
            row["readError"] = str(error)
        rows.append(row)
    for raw in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if raw:
            path = os.fsdecode(raw)
            row = {
                "path": path,
                "indexMode": None,
                "indexBlob": None,
                "stage": "untracked",
            }
            try:
                row.update(file_identity(ROOT / path))
            except (OSError, ValueError) as error:
                row["readError"] = str(error)
            rows.append(row)
    state = {
        "head": git("rev-parse", "HEAD").decode().strip(),
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "status": git(
            "status", "--porcelain=v1", "--untracked-files=all", "-z"
        ).decode(),
        "rows": rows,
    }
    receipt = save(output / f"{name}.json.gz", state)
    receipt["trackedFiles"] = sum(row["stage"] != "untracked" for row in rows)
    receipt["untrackedFiles"] = sum(row["stage"] == "untracked" for row in rows)
    return state, receipt


def read_bounded(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"record input exceeds {limit} bytes: {path}")
    return data


def require_absent_junit(path):
    if os.path.lexists(path):
        raise ValueError(f"JUnit report already exists before the test command: {path}")
    return {"path": str(path), "absent": True, "notBeforeNs": time.time_ns()}


def read_fresh_junit(path, not_before_ns):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("JUnit report is not a regular file")
    if before.st_size > MAX_LOG_BYTES or before.st_mtime_ns < not_before_ns:
        raise ValueError("JUnit report exceeds the limit or predates this test command")
    data = read_bounded(path, MAX_LOG_BYTES)
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise ValueError("JUnit report changed during collection")
    if len(data) != after.st_size:
        raise ValueError("JUnit report length differs from its metadata")
    return data, {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mtimeNs": after.st_mtime_ns,
        "notBeforeNs": not_before_ns,
    }


def preflight(output):
    raw = read_bounded(Path(os.environ["GITHUB_EVENT_PATH"]), 2 * 1024 * 1024)
    event = json.loads(raw)
    head = os.environ["GITHUB_SHA"]
    if re.fullmatch(r"[0-9a-f]{40}", head) is None or head == "0" * 40:
        raise ValueError("invalid push SHA")
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("GITHUB_REF") != REF
        or not isinstance(event, dict)
        or not isinstance(event.get("repository"), dict)
        or event.get("repository", {}).get("full_name") != REPOSITORY
        or event.get("ref") != REF
        or event.get("after") != head
        or event.get("deleted") is not False
    ):
        raise ValueError("event does not identify the dedicated validation push")
    if git("rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("checkout differs from the push commit")
    if git("rev-parse", f"{SOURCE}^{{tree}}").decode().strip() != SOURCE_TREE:
        raise ValueError("reviewed source tree differs")
    git("merge-base", "--is-ancestor", SOURCE, "HEAD")
    changed = {
        os.fsdecode(p)
        for p in git("diff", "--name-only", "--no-renames", "-z", SOURCE, "HEAD").split(
            b"\0"
        )
        if p
    }
    if changed != CI_PATHS:
        raise ValueError("candidate changes more than the two validation files")
    for path, expected in REVIEWED_TEST_BLOBS.items():
        if git("rev-parse", f"HEAD:{path}").decode().strip() != expected:
            raise ValueError(f"reviewed test postimage differs: {path}")
    before, manifest = snapshot(output, "source-before")
    if before["status"] or any(
        row.get("blob") != row["indexBlob"]
        or row.get("mode") != row["indexMode"]
        or row["stage"] != "0"
        for row in before["rows"]
    ):
        raise ValueError("initial checkout is not the exact clean tracked source")
    forbidden = sorted(
        key
        for key in os.environ
        if key.startswith(("NEXTEST_", "CARGO_PROFILE_"))
        or key
        in {
            "RUST_TEST_THREADS",
            "RUST_MIN_STACK",
            "RUSTFLAGS",
            "CARGO_ENCODED_RUSTFLAGS",
        }
    )
    if forbidden:
        raise ValueError(f"unexpected inherited test/build overrides: {forbidden}")
    target = Path(os.environ["CARGO_TARGET_DIR"])
    if (
        not target.is_absolute()
        or target.resolve().is_relative_to(ROOT)
        or target.exists()
    ):
        raise ValueError("Cargo target must be a new directory outside the checkout")
    tools = []
    for argv, expected in (
        (["rustc", "-Vv"], r"(?m)^release: 1\.96\.0$"),
        (["cargo", "--version"], r"^cargo 1\.96\.0(?:\s|$)"),
        (["rustfmt", "--version"], r"^rustfmt "),
        (["cargo", "clippy", "--version"], r"^clippy 0\.1\.96(?:\s|$)"),
        (["just", "--version"], r"^just 1\.51\.0(?:\s|$)"),
        (["cargo", "nextest", "--version"], r"^cargo-nextest 0\.9\.103(?:\s|$)"),
        (["uv", "--version"], r"^uv 0\.11\.3(?:\s|$)"),
        ([sys.executable, "--version"], r"^Python 3\.12\.14(?:\s|$)"),
        (["git", "--version"], r"^git version "),
    ):
        result = subprocess.run(argv, cwd=CWD, capture_output=True, check=False)
        text = result.stdout.decode(errors="replace") + result.stderr.decode(
            errors="replace"
        )
        tools.append(
            {
                "argv": argv,
                "cwd": str(CWD),
                "exitCode": result.returncode,
                "output": text,
            }
        )
        if result.returncode or re.search(expected, text) is None:
            save(output / "tools.json", tools)
            raise ValueError(f"tool version mismatch: {argv}")
    save(output / "tools.json", tools)
    return before, manifest, hashlib.sha256(raw).hexdigest()


def command(output, number, argv, cwd):
    path = output / f"command-{number}.json"
    # Only explicitly named non-secret process controls are serialized. Runtime
    # artifact credentials and all unrelated environment values are excluded.
    names = {
        "PATH",
        "HOME",
        "TMPDIR",
        "CI",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "CARGO_BUILD_JOBS",
        "CODEX_BAZEL_LINUX_TARGET_PLATFORM",
        "CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR",
        "BAZEL_OUTPUT_BASE",
        "CARGO_INCREMENTAL",
        "CARGO_TARGET_DIR",
        "RUST_BACKTRACE",
        "RUSTUP_TOOLCHAIN",
        "UV_PROJECT_ENVIRONMENT",
        "GITHUB_SHA",
        "GITHUB_REF",
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_JOB",
        "RUNNER_OS",
        "RUNNER_ARCH",
    }
    record = {
        "status": "running",
        "startedAt": now(),
        "argv": argv,
        "cwd": str(cwd),
        "environment": {k: os.environ.get(k) for k in sorted(names)},
        "testRecipeEnvironment": {
            "RUST_MIN_STACK": "8388608",
            "NEXTEST_PROFILE": "local",
        }
        if argv[:2] == ["just", "test"]
        else {},
        "logLimitBytes": MAX_LOG_BYTES,
    }
    save(path, record)
    started = time.monotonic()
    process = subprocess.Popen(
        argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    record["pid"] = process.pid
    save(path, record)
    total = kept = 0
    all_sha = hashlib.sha256()
    kept_sha = hashlib.sha256()
    with (output / f"command-{number}.log").open("xb") as stream:
        while chunk := process.stdout.read(65536):
            total += len(chunk)
            all_sha.update(chunk)
            part = chunk[: max(0, MAX_LOG_BYTES - kept)]
            stream.write(part)
            kept += len(part)
            kept_sha.update(part)
            sys.stdout.buffer.write(part)
            sys.stdout.buffer.flush()
        stream.flush()
        os.fsync(stream.fileno())
    # Natural completion only. EOF, a pipe error, or a platform interruption
    # cannot produce a passing receipt while this direct child is still running.
    returncode = process.wait()
    process.stdout.close()
    record.update(
        {
            "status": "completed",
            "exitCode": returncode,
            "finishedAt": now(),
            "elapsedSeconds": time.monotonic() - started,
            "logBytes": kept,
            "logSha256": kept_sha.hexdigest(),
            "observedOutputBytes": total,
            "observedOutputSha256": all_sha.hexdigest(),
            "logComplete": total == kept,
        }
    )
    save(path, record)
    return record


def commands_for(mode):
    commands = [
        (["just", "fmt"], CWD, "format"),
        (["just", "fmt", "--base", BASE], CWD, "format-base"),
        (["just", "fmt", "--base", BASE, "--check"], CWD, "format-check"),
    ]
    if mode == "host":
        commands.extend(
            [
                (
                    [
                        "just",
                        "fix",
                        "--locked",
                        "-p",
                        "codex-core",
                        "-p",
                        "codex-hepta-infer-worker-host",
                    ],
                    CWD,
                    "scoped-fix",
                ),
                (
                    ["just", "test", "--locked", "-p", "codex-hepta-infer-worker-host"],
                    CWD,
                    "host-test",
                ),
            ]
        )
    else:
        commands.append(
            (
                [
                    "./.github/scripts/run-bazel-ci.sh",
                    "--print-failed-action-summary",
                    "--print-failed-test-logs",
                    "--",
                    "test",
                    "--strategy=TestRunner=local",
                    "--test_tag_filters=-argument-comment-lint",
                    "--test_verbose_timeout_warnings",
                    "--nocache_test_results",
                    f"--build_metadata=COMMIT_SHA={os.environ['GITHUB_SHA']}",
                    "--build_metadata=TAG_job=native-core-integration-tests",
                    "--",
                    CORE_TARGET,
                ],
                ROOT,
                "core-test",
            )
        )
    return commands


def junit_cases(data):
    return [
        {
            "name": case.get("name"),
            "classname": case.get("classname"),
            "time": case.get("time"),
            "outcomes": [
                item.tag for item in case if item.tag in {"failure", "error", "skipped"}
            ],
        }
        for case in ET.fromstring(data).iter("testcase")
    ]


def collect_host(output, report, started_ns):
    data, identity = read_fresh_junit(report, started_ns)
    (output / "junit.xml").write_bytes(data)
    cases = junit_cases(data)
    save(output / "test-cases.json.gz", cases)
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for case in cases:
        if any(value in {"failure", "error"} for value in case["outcomes"]):
            counts["failed"] += 1
        elif "skipped" in case["outcomes"]:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    selected = {
        name: [case for case in cases if case["name"] == name] for name in HOST_CASES
    }
    result = {"report": identity, "counts": counts, "requiredCases": selected}
    result["passed"] = (
        counts["passed"] > 0
        and counts["failed"] == 0
        and all(
            len(rows) == 1 and not rows[0]["outcomes"] for rows in selected.values()
        )
    )
    save(output / "host-test-evidence.json", result)
    return result


def collect_core(output, started_ns):
    # Reuse the existing checked regular-file copier and complete attempt
    # discovery. The wrapper separately retains observed failure/flaky evidence.
    helper = runpy.run_path(str(ROOT / ".github/scripts/collect_bazel_test_logs.py"))
    evidence = output / "core-all-materialized-attempts"
    evidence.mkdir()
    result = {"target": CORE_TARGET, "attempts": [], "errors": [], "passed": False}
    try:
        root = (ROOT / "bazel-testlogs").resolve(strict=True)
        output_base = Path(os.environ["BAZEL_OUTPUT_BASE"]).resolve(strict=True)
        if not root.is_dir() or not root.is_relative_to(output_base):
            raise ValueError("Bazel testlogs are outside the configured output base")
        directory = root / "codex-rs/core/core-all-test"
        paths = set()
        helper["discover_attempts"](directory, root, paths, result["errors"])
        if not paths:
            raise ValueError(
                "the complete Core target has no materialized attempt logs"
            )
        terminal = []
        for path in sorted(paths):
            relative = path.relative_to(root)
            row = {"relativeLogPath": relative.as_posix()}
            for role, source in (("log", path), ("junit", path.with_suffix(".xml"))):
                checked, relative_file = helper["checked_path"](source, root)
                destination = evidence / relative_file
                destination.parent.mkdir(parents=True, exist_ok=True)
                identity = helper["copy_file"](checked, destination)
                identity["artifact"] = destination.relative_to(output).as_posix()
                row[role] = identity
                if identity["status"] != "copied":
                    result["errors"].append({"source": str(source), "error": identity})
            result["attempts"].append(row)
            if path.name == "test.log" and "test_attempts" not in relative.parts:
                terminal.append((path, row))
        result["terminalShards"] = []
        guardian_matches = []
        for path, row in terminal:
            parts = path.relative_to(directory).parts
            shard = [re.fullmatch(r"shard_([1-9][0-9]*)_of_16", part) for part in parts]
            shard = [int(match.group(1)) for match in shard if match]
            if len(shard) != 1:
                raise ValueError(
                    "terminal Core evidence does not identify one original shard"
                )
            data, identity = read_fresh_junit(path.with_suffix(".xml"), started_ns)
            if identity["sha256"] != row["junit"].get("sha256"):
                raise ValueError("Core XML changed between copy and census")
            xml_cases = junit_cases(data)
            log = evidence / row["relativeLogPath"]
            raw = read_bounded(log, MAX_LOG_BYTES)
            clean = helper["ANSI"].sub("", raw.decode(errors="replace"))
            summaries = re.findall(
                r"(?m)^test result: (ok|FAILED)\. ([0-9]+) passed; ([0-9]+) failed; ([0-9]+) ignored; ([0-9]+) measured; ([0-9]+) filtered out; finished in ([0-9.]+)s\s*$",
                clean,
            )
            if not summaries:
                raise ValueError("terminal Core log lacks the original libtest census")
            summary = summaries[-1]
            hits = re.findall(
                r"(?m)^test " + re.escape(GUARDIAN_CASE) + r" \.\.\. ok\s*$", clean
            )
            guardian_matches.extend({"shard": shard[0], "line": hit} for hit in hits)
            result["terminalShards"].append(
                {
                    "shard": shard[0],
                    "relativeLogPath": row["relativeLogPath"],
                    "libtestSummary": {
                        "status": summary[0],
                        "passed": int(summary[1]),
                        "failed": int(summary[2]),
                        "ignored": int(summary[3]),
                        "measured": int(summary[4]),
                        "filteredOut": int(summary[5]),
                        "elapsedSeconds": float(summary[6]),
                    },
                    "junitCases": xml_cases,
                }
            )
        result["guardianHarnessMatches"] = guardian_matches
        result["passed"] = (
            not result["errors"]
            and sorted(row["shard"] for row in result["terminalShards"])
            == list(range(1, CORE_SHARDS + 1))
            and len(guardian_matches) == 1
            and all(
                row["libtestSummary"]["status"] == "ok"
                and row["libtestSummary"]["failed"] == 0
                and row["junitCases"]
                and not any(
                    "failure" in case["outcomes"] or "error" in case["outcomes"]
                    for case in row["junitCases"]
                )
                for row in result["terminalShards"]
            )
        )
    except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
        result["errors"].append({"error": str(error)})
    save(output / "core-test-evidence.json", result)
    return result


def preserve_source_change(output, before, after, receipt):
    patch = git("diff", "--binary", "--no-ext-diff", "HEAD", "--")
    (output / "source-change.patch").write_bytes(patch)
    prior = {row["path"]: row for row in before["rows"]}
    changed = [row for row in after["rows"] if row != prior.get(row["path"])]
    with tarfile.open(output / "changed-files.tar.gz", "w:gz") as archive:
        for row in changed:
            path = ROOT / row["path"]
            if path.is_file() or path.is_symlink():
                archive.add(path, arcname=row["path"], recursive=False)
    save(
        output / "source-change.json",
        {
            "patchSha256": hashlib.sha256(patch).hexdigest(),
            "patchBytes": len(patch),
            "changedPaths": changed,
            "changedFilesArchive": file_identity(output / "changed-files.tar.gz"),
            "status": after["status"],
            "after": receipt,
        },
    )


def validate(mode):
    output = Path(os.environ["HEPTA_VALIDATION_OUTPUT"])
    if not output.is_absolute() or output.resolve().is_relative_to(ROOT):
        raise ValueError("records must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "running",
        "startedAt": now(),
        "mode": mode,
        "sourceAnchor": SOURCE,
        "sourceTree": SOURCE_TREE,
        "formatBase": BASE,
        "commands": [],
        "originalCommandExitCode": None,
    }
    save(output / "result.json", result)
    try:
        before, receipt, event_sha = preflight(output)
        result.update(
            {
                "sourceBefore": receipt,
                "head": before["head"],
                "tree": before["tree"],
                "eventSha256": event_sha,
            }
        )
        platform = os.environ.get("CODEX_BAZEL_LINUX_TARGET_PLATFORM", "")
        expected_platform = (
            "@rules_rs//rs/platforms:x86_64-unknown-linux-musl"
            if mode == "core-musl"
            else ""
        )
        if platform != expected_platform or os.environ.get("RUNNER_OS") != "Linux":
            raise ValueError(
                "validation lane differs from the original Linux target platform"
            )
        if mode != "host":
            logs = output / "bazel-execution-logs"
            if os.environ.get("CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR") != str(logs):
                raise ValueError(
                    "Bazel evidence output differs from the job-owned directory"
                )
            logs.mkdir()
        save(output / "result.json", result)
        report = CWD / "target" / "nextest" / "local" / "junit.xml"
        for number, (argv, cwd, role) in enumerate(commands_for(mode), 1):
            started_ns = time.time_ns()
            if role == "host-test":
                result["junitBeforeTest"] = require_absent_junit(report)
                started_ns = result["junitBeforeTest"]["notBeforeNs"]
            save(output / "result.json", result)
            execution = command(output, number, argv, cwd)
            execution["role"] = role
            result["commands"].append(execution)
            if execution["exitCode"]:
                result["originalCommandExitCode"] = execution["exitCode"]
            # Preserve fresh test artifacts even when the original test fails.
            if role in {"host-test", "core-test"}:
                try:
                    evidence = (
                        collect_host(output, report, started_ns)
                        if role == "host-test"
                        else collect_core(output, started_ns)
                    )
                    result["testEvidence"] = evidence
                except (OSError, ValueError, ET.ParseError) as error:
                    result["testEvidence"] = {"passed": False, "error": str(error)}
            after, receipt = snapshot(output, f"source-after-{number}")
            execution.update(sourceAfter=receipt, sourceUnchanged=after == before)
            save(output / "result.json", result)
            if after != before:
                preserve_source_change(output, before, after, receipt)
                raise ValueError("source changed; later gates were not dispatched")
            if execution["exitCode"] or not execution["logComplete"]:
                raise ValueError("command failed or complete output was not retained")
            if (
                role in {"host-test", "core-test"}
                and not result["testEvidence"]["passed"]
            ):
                raise ValueError(
                    "whole-target evidence or required regression census is incomplete or failed"
                )
        final, receipt = snapshot(output, "source-final")
        result["sourceFinal"] = receipt
        if (
            final != before
            or hashlib.sha256(
                read_bounded(Path(os.environ["GITHUB_EVENT_PATH"]), 2 * 1024 * 1024)
            ).hexdigest()
            != event_sha
        ):
            raise ValueError("final source or event changed during result collection")
        result["status"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
        result.update(status="failed", error=str(error))
    except KeyboardInterrupt:
        result.update(
            status="interrupted",
            childState="unknown; no signal was sent by this runner",
        )
    finally:
        try:
            result["unresolvedCommandRecords"] = [
                path.name
                for path in sorted(output.glob("command-*.json"))
                if json.loads(path.read_text()).get("status") == "running"
            ]
            if result["unresolvedCommandRecords"]:
                result.update(
                    status="incomplete",
                    childState="natural completion not observed; no signal was sent by this runner",
                )
            result["finishedAt"] = now()
            save(output / "result.json", result)
            inventory = [
                {"path": path.relative_to(output).as_posix(), **file_identity(path)}
                for path in sorted(output.rglob("*"))
                if path.is_file() or path.is_symlink()
            ]
            save(
                output / "artifact-inventory.json",
                {
                    "schemaVersion": 1,
                    "scope": "all saved files except this inventory",
                    "files": inventory,
                },
            )
        except (OSError, ValueError) as error:
            # A final evidence write must not replace an already observed
            # nonzero command result or allow an otherwise successful run to
            # pass without its inventory. Preserve what the filesystem permits.
            if result["status"] not in {"interrupted", "incomplete"}:
                result["status"] = "failed"
            result["artifactFinalizationError"] = f"{type(error).__name__}: {error}"
            for name, value in (
                (
                    "artifact-finalization-error.json",
                    {
                        "status": result["status"],
                        "originalCommandExitCode": result["originalCommandExitCode"],
                        "error": result["artifactFinalizationError"],
                    },
                ),
                ("result.json", result),
            ):
                try:
                    save(output / name, value)
                except (OSError, ValueError):
                    pass
    if result["status"] == "passed":
        return 0
    original = result["originalCommandExitCode"]
    return original if isinstance(original, int) and 0 < original < 256 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", required=True, choices=("host", "core-gnu", "core-musl")
    )
    args = parser.parse_args()
    sys.exit(validate(args.mode))

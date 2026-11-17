"""Record the original six cognitive package gates; only the platform sets a job deadline."""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET


BASE = "464ebe0c5e1b456dff7abbd897e302dd7e1d9034"
SOURCE = "26b4e510ef113aa4a141f668d536711b4188a40d"
SOURCE_TREE = "7f08a6f8babda37c20a4af402589d96563f86d5a"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
REF = "refs/heads/integration/hepta-rust-validation-20261117-59d82"
CI_PATHS = {
    ".github/workflows/hepta-cognitive-package-validation.yml",
    ".github/scripts/validate_cognitive_packages.py",
}
PACKAGES = [
    "-p",
    "codex-hepta-cognitive-types",
    "-p",
    "codex-hepta-cognitive-store",
    "-p",
    "codex-hepta-cognitive-read",
    "-p",
    "codex-hepta-memory-retrieval",
    "-p",
    "codex-hepta-compact-engine",
    "-p",
    "codex-hepta-intelligence",
]
COMMANDS = [
    ["just", "fmt"],
    ["just", "fmt", "--base", BASE],
    ["just", "fmt", "--base", BASE, "--check"],
    ["just", "fix", "--locked", *PACKAGES],
    ["just", "test", "--locked", *PACKAGES],
]
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


def command(output, number, argv):
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
        "cwd": str(CWD),
        "environment": {k: os.environ.get(k) for k in sorted(names)},
        "testRecipeEnvironment": {
            "RUST_MIN_STACK": "8388608",
            "NEXTEST_PROFILE": "local",
        }
        if argv[1] == "test"
        else {},
        "logLimitBytes": MAX_LOG_BYTES,
    }
    save(path, record)
    started = time.monotonic()
    process = subprocess.Popen(
        argv, cwd=CWD, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
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


def validate():
    output = Path(os.environ["HEPTA_VALIDATION_OUTPUT"])
    if not output.is_absolute() or output.resolve().is_relative_to(ROOT):
        raise ValueError("records must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "running",
        "startedAt": now(),
        "sourceAnchor": SOURCE,
        "formatBase": BASE,
        "commands": [],
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
        save(output / "result.json", result)
        # nextest 0.9.103 stores reports relative to the workspace root.
        report = CWD / "target" / "nextest" / "local" / "junit.xml"
        for number, argv in enumerate(COMMANDS, 1):
            if argv[:2] == ["just", "test"]:
                result["junitBeforeTest"] = require_absent_junit(report)
                save(output / "result.json", result)
            execution = command(output, number, argv)
            if argv[:2] == ["just", "test"]:
                try:
                    data, junit_record = read_fresh_junit(
                        report, result["junitBeforeTest"]["notBeforeNs"]
                    )
                    (output / "junit.xml").write_bytes(data)
                    execution["junitAfterTest"] = {
                        "status": "captured",
                        **junit_record,
                    }
                except (OSError, ValueError) as error:
                    execution["junitAfterTest"] = {
                        "status": "not captured",
                        "error": str(error),
                    }
                save(output / "junit-after-test.json", execution["junitAfterTest"])
            after, receipt = snapshot(output, f"source-after-{number}")
            execution["sourceAfter"] = receipt
            execution["sourceUnchanged"] = after == before
            result["commands"].append(execution)
            if after != before:
                patch = git("diff", "--binary", "--no-ext-diff", "HEAD", "--")
                (output / "source-change.patch").write_bytes(patch)
                prior = {row["path"]: row for row in before["rows"]}
                changed = [
                    row for row in after["rows"] if row != prior.get(row["path"])
                ]
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
                        "patchScope": "tracked HEAD difference; changed-files.tar.gz also contains new untracked files",
                        "changedPaths": changed,
                        "changedFilesArchive": {
                            "path": "changed-files.tar.gz",
                            **file_identity(output / "changed-files.tar.gz"),
                        },
                        "status": after["status"],
                        "before": result["sourceBefore"],
                        "after": receipt,
                    },
                )
                raise ValueError("source changed; later gates were not dispatched")
            if execution["exitCode"] or not execution["logComplete"]:
                raise ValueError("command failed or complete output was not retained")
            save(output / "result.json", result)
        data, result["junitReport"] = read_fresh_junit(
            report, result["junitBeforeTest"]["notBeforeNs"]
        )
        (output / "junit.xml").write_bytes(data)
        save(output / "result.json", result)
        root = ET.fromstring(data)
        cases = [
            {
                "name": c.get("name"),
                "classname": c.get("classname"),
                "time": c.get("time"),
                "outcomes": [
                    e.tag for e in c if e.tag in {"failure", "error", "skipped"}
                ],
            }
            for c in root.iter("testcase")
        ]
        save(output / "test-cases.json", cases)
        counts = {"passed": 0, "failed": 0, "skipped": 0}
        for case in cases:
            if any(outcome in {"failure", "error"} for outcome in case["outcomes"]):
                counts["failed"] += 1
            elif "skipped" in case["outcomes"]:
                counts["skipped"] += 1
            else:
                counts["passed"] += 1
        if counts["failed"] or not counts["passed"]:
            raise ValueError(
                "the full-package report has failures or no executed passing cases"
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
        result.update(
            {
                "status": "passed",
                "junitSha256": hashlib.sha256(data).hexdigest(),
                "reportedCases": len(cases),
                "reportedCounts": counts,
            }
        )
    except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
        result.update({"status": "failed", "error": str(error)})
    except KeyboardInterrupt:
        result.update(
            {
                "status": "interrupted",
                "childState": "unknown; no signal was sent by this runner",
            }
        )
    finally:
        result["unresolvedCommandRecords"] = [
            path.name
            for path in sorted(output.glob("command-*.json"))
            if json.loads(path.read_text()).get("status") == "running"
        ]
        if result["unresolvedCommandRecords"]:
            result.update(
                {
                    "status": "incomplete",
                    "childState": "natural completion not observed; no signal was sent by this runner",
                }
            )
        result["finishedAt"] = now()
        save(output / "result.json", result)
    return 0 if result["status"] == "passed" else 1


def export_tools():
    """Archive named public installation paths, never tool homes or caches."""
    output = Path(os.environ["HEPTA_PUBLIC_TOOL_OUTPUT"])
    if not output.is_absolute() or output.resolve().is_relative_to(ROOT):
        raise ValueError("public tool output must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    sysroot = Path(
        subprocess.check_output(
            ["rustup", "run", "1.96.0", "rustc", "--print", "sysroot"],
            cwd=CWD,
            text=True,
        ).strip()
    ).resolve()
    entries = []
    with tarfile.open(output / "public-tools.tar.gz", "w:gz") as archive:
        for name in ("bin", "lib", "libexec"):
            base = sysroot / name
            if not base.exists():
                entries.append({"path": f"rust-sysroot/{name}", "absent": True})
                continue
            for path in [base, *sorted(base.rglob("*"))]:
                relative = Path("rust-sysroot") / path.relative_to(sysroot)
                if not path.resolve().is_relative_to(sysroot):
                    raise ValueError("public sysroot link escapes its installation")
                if path.is_dir() and not path.is_symlink():
                    continue
                entries.append({"path": str(relative), **file_identity(path)})
                archive.add(path, arcname=str(relative), recursive=False)
        for name in ("just", "cargo-nextest"):
            path = Path(shutil.which(name)).resolve()
            relative = f"tools/{name}"
            entries.append({"path": relative, **file_identity(path)})
            archive.add(path, arcname=relative, recursive=False)
    versions = []
    for argv in (
        ["rustup", "run", "1.96.0", "rustc", "-Vv"],
        ["just", "--version"],
        ["cargo", "nextest", "--version"],
    ):
        result = subprocess.run(argv, cwd=CWD, capture_output=True, check=False)
        versions.append(
            {
                "argv": argv,
                "cwd": str(CWD),
                "exitCode": result.returncode,
                "stdout": result.stdout.decode(errors="replace"),
                "stderr": result.stderr.decode(errors="replace"),
            }
        )
        if result.returncode:
            raise ValueError(f"public tool version unavailable: {argv}")
    save(
        output / "public-files.json.gz",
        {
            "head": os.environ.get("GITHUB_SHA"),
            "sysroot": str(sysroot),
            "files": entries,
            "versions": versions,
            "archive": file_identity(output / "public-tools.tar.gz"),
        },
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-tools", action="store_true")
    args = parser.parse_args()
    sys.exit(export_tools() if args.export_tools else validate())

"""Recheck docs, formatting, and frozen identities without running unit tests."""

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import traceback
import zipfile


ROOT = Path(__file__).resolve().parents[2]
FORMAT_BASE = "332d8156d081e22405450dd607023689f68f03e1"
REQUEST = "qualification/memory-cell-v5-ci/VERIFY_REQUEST.json"
HELPER = "qualification/memory-cell-v5-ci/recheck.py"
NEW_SOURCES = (HELPER, "qualification/memory-cell-v5-ci/collect_log.py")
PRIOR_SOURCES = (
    "scripts/hepta-docs.py",
    "scripts/test_hepta_workflow_references.py",
    "qualification/memory-cell-v5-ci/verify.py",
    "qualification/memory-cell-v5-ci/probe_dependency.py",
)
SOURCES = (*PRIOR_SOURCES, *NEW_SOURCES)
PRIOR_TEST_ARGUMENTS = (
    ["-B", "scripts/test_hepta_workflow_references.py", "-v"],
    [
        "-B",
        "-m",
        "unittest",
        "test_hepta_cleanup_consumers.CleanupConsumerTests.test_exact_workflow_reference_must_exist",
        "test_hepta_cleanup_consumers.CleanupConsumerTests.test_exact_workflow_reference_accepts_existing_file",
        "-v",
    ],
)


def byte_identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def identity(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    return byte_identity(path.read_bytes())


def syntax(path):
    value = ast.dump(ast.parse(path.read_bytes()), include_attributes=False)
    return hashlib.sha256(value.encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def frozen_snapshot():
    base = ROOT / "qualification/memory-cell-v5"
    require(base.is_dir() and not base.is_symlink(), "V5 directory is missing or linked")
    files = {}
    for path in sorted(base.rglob("*")):
        require(not path.is_symlink(), f"Linked V5 entry: {path}")
        if path.is_file():
            files[path.relative_to(base).as_posix()] = identity(path)
    require(bool(files), "V5 inventory is empty")
    return files


def inventory_identity(files):
    raw = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"files": len(files), "canonical_sha256": hashlib.sha256(raw).hexdigest()}


def tracked_changes():
    return subprocess.check_output(
        ["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True
    ).splitlines()


def load_prior(report):
    request = json.loads((ROOT / REQUEST).read_bytes())
    require(request["request"] == 2, "Expected phase 2 request")
    require(request["baseline_commit"] == FORMAT_BASE, "Unexpected format baseline")
    require(request["preserve_every_v5_file"] is True, "V5 preservation is required")
    require(
        request["unit_tests_already_run_before_format"] is True,
        "Prior tests must be declared; this recheck never runs them",
    )
    binding = request["prior_verification"]
    archive_path = Path(binding["archive"])
    require(
        not archive_path.is_absolute() and ".." not in archive_path.parts,
        "Prior archive must be inside the repository",
    )
    archive_path = ROOT / archive_path
    require(archive_path.resolve().is_relative_to(ROOT), "Prior archive escapes root")
    archive_identity = identity(archive_path)
    require(
        archive_identity["sha256"] == binding["archive_sha256"],
        "Prior artifact archive hash mismatch",
    )
    with zipfile.ZipFile(io.BytesIO(archive_path.read_bytes())) as archive:
        require(
            archive.namelist().count(binding["member"]) == 1,
            "Prior receipt member must occur exactly once",
        )
        raw = archive.read(binding["member"])
    prior = json.loads(raw)
    report["request"] = {"path": REQUEST, **identity(ROOT / REQUEST)}
    report["prior_verification"] = {
        **binding,
        "archive_identity": archive_identity,
        "receipt_identity": byte_identity(raw),
        "prior_overall_passed": prior["passed"],
    }
    require(
        prior["schema"] == "hepta.memory.v5.ci-fix-verification.v1"
        and prior["commit"] == binding["commit"],
        "Prior verification identity mismatch",
    )
    require(
        all(
            prior[name] is True
            for name in (
                "all_ast_equal",
                "all_v5_files_unchanged",
                "changes_limited_to_formatter_sources",
                "tests_before_format_only",
            )
        ),
        "Prior tests and formatter preservation were not verified",
    )
    require(
        set(prior["after"]) == set(PRIOR_SOURCES)
        and set(prior["ast_sha256"]) == set(PRIOR_SOURCES),
        "Unexpected prior formatter source inventory",
    )
    tests = prior["commands"][:2]
    require(
        len(tests) == 2
        and all(
            row["command"][1:] == expected and row["exit_code"] == 0
            for row, expected in zip(tests, PRIOR_TEST_ARGUMENTS)
        ),
        "The two prior unit-test commands must have succeeded",
    )
    report["reused_test_results"] = [
        {key: row[key] for key in ("command", "exit_code", "wall_seconds")}
        for row in tests
    ]
    return prior


def run_command(command, directory, output, index):
    started = time.perf_counter()
    process = subprocess.run(command, cwd=directory, capture_output=True)
    record = {
        "command": command,
        "cwd": directory.relative_to(ROOT).as_posix(),
        "exit_code": process.returncode,
        "wall_seconds": time.perf_counter() - started,
    }
    for stream in ("stdout", "stderr"):
        raw = getattr(process, stream)
        name = f"command-{index:02d}.{stream}.txt"
        (output / name).write_bytes(raw)
        record[stream] = {"artifact_member": name, **byte_identity(raw)}
    return record


def recheck(report, output):
    current_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    require(current_commit == report["commit"], "Checkout differs from GITHUB_SHA")
    require(not tracked_changes(), "Checkout contains tracked modifications")
    prior = load_prior(report)
    before = {name: identity(ROOT / name) for name in SOURCES}
    trees = {name: syntax(ROOT / name) for name in SOURCES}
    frozen = frozen_snapshot()
    report["before"] = before
    report["ast_sha256_before"] = trees
    report["v5_inventory_before"] = inventory_identity(frozen)
    report["prior_v5_inventory"] = inventory_identity(prior["all_v5_files_before"])
    report["prior_source_bytes_and_ast_match_before"] = all(
        before[name] == prior["after"][name]
        and trees[name] == prior["ast_sha256"][name]
        for name in PRIOR_SOURCES
    )
    report["all_v5_files_match_prior_before"] = frozen == prior["all_v5_files_before"]
    require(
        report["prior_source_bytes_and_ast_match_before"]
        and report["all_v5_files_match_prior_before"],
        "Checkout differs from prior verified source or V5 inventory",
    )
    ruff = ["uv", "run", "--frozen", "--project", "scripts", "ruff"]
    commands = [
        (
            [sys.executable, "-B", "scripts/hepta-docs.py", "verify", "--profile", "development"],
            ROOT,
        ),
        (["just", "fmt", "--base", FORMAT_BASE], ROOT / "codex-rs"),
        ([*ruff, "format", *NEW_SOURCES], ROOT),
        ([*ruff, "format", "--check", *SOURCES], ROOT),
        ([*ruff, "check", *SOURCES], ROOT),
    ]
    for index, (command, directory) in enumerate(commands, 1):
        report["commands"].append(run_command(command, directory, output, index))
    after = {name: identity(ROOT / name) for name in SOURCES}
    after_trees = {name: syntax(ROOT / name) for name in SOURCES}
    after_frozen = frozen_snapshot()
    changed = tracked_changes()
    report.update(
        {
            "after": after,
            "ast_sha256_after": after_trees,
            "all_ast_equal": trees == after_trees,
            "prior_source_bytes_and_ast_match_after": all(
                after[name] == prior["after"][name]
                and after_trees[name] == prior["ast_sha256"][name]
                for name in PRIOR_SOURCES
            ),
            "v5_inventory_after": inventory_identity(after_frozen),
            "all_v5_files_unchanged": after_frozen == frozen,
            "all_v5_files_match_prior_after": after_frozen == prior["all_v5_files_before"],
            "changed_paths": changed,
            "changes_limited_to_new_helper_formatter": set(changed) <= set(NEW_SOURCES),
        }
    )
    report["passed"] = all(
        report[name]
        for name in (
            "all_ast_equal",
            "prior_source_bytes_and_ast_match_after",
            "all_v5_files_unchanged",
            "all_v5_files_match_prior_after",
            "changes_limited_to_new_helper_formatter",
        )
    ) and all(row["exit_code"] == 0 for row in report["commands"])
    with tarfile.open(output / "formatted-ci-source.tar.gz", "w:gz") as archive:
        for name in SOURCES:
            archive.add(ROOT / name, arcname=name, recursive=False)


def main():
    output = ROOT / "memory-ci-output"
    output.mkdir(exist_ok=False)
    report = {
        "schema": "hepta.memory.v5.ci-fix-recheck.v1",
        "commit": os.environ.get("GITHUB_SHA"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "unit_tests_executed": False,
        "commands": [],
        "passed": False,
    }
    try:
        recheck(report, output)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        (output / "error.txt").write_text(traceback.format_exc())
    (output / "RECHECK.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("commit", "passed", "unit_tests_executed")}))
    if "error" in report:
        print(report["error"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

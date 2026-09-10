#!/usr/bin/env python3
"""Build a clean single-parent Hepta candidate from the latest reviewed owner deltas.

This executor is intentionally hosted only on an ops branch.  The published
candidate starts from the exact r12 tree, overlays only final files from the
current Lane B, E and G owner candidates, removes recovery/materialization
carriers, regenerates shared projections, runs repository-controlled gates,
and republishes the resulting tree as one direct child of the review anchor.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path.cwd()
R12_SHA = "9a71e0bf02e7c538c725f0aaeffa6f1404546aa2"
LANE_B_SHA = "fc5d69029ab896a8d81847282415884964dded2e"
LANE_E_SHA = "42b24ed1a5ff0daedd2593b98d439af322b8045c"
LANE_G_SHA = "54629ac932b1ccad8417d6a98c013400850800af"
REVIEW_ANCHOR = "05981ed1adfb931a87a47b0606f1cedaa69f123b"
TARGET_BRANCH = "candidate/hepta-all-gap-closure-final-20260910"

# Exact final Lane B owner files.  Candidate-subject workflow/manifest files
# are excluded because their identity is the isolated Lane B PR head, not the
# composed repository candidate.
LANE_B_FILES = (
    "apps/hepta-browser/src/runtime.js",
    "apps/hepta-browser/test/runtime.test.js",
    "apps/hepta-control-ui/src/runtime-client.js",
    "apps/hepta-control-ui/test/runtime-client.test.js",
    "apps/hepta-native/src/shell-runtime.js",
    "apps/hepta-native/test/shell-runtime.test.js",
    "codex-rs/hepta-automation/Cargo.toml",
    "codex-rs/hepta-automation/src/bin/hepta-taskflow-runtime.rs",
    "codex-rs/hepta-fleet/src/bin/hepta-fleet-leased.rs",
    "codex-rs/hepta-infer-core/src/bin/hepta-infer-control.rs",
    "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs",
    "codex-rs/hepta-matrixd/src/bin/hepta-matrix-send-observer.rs",
    "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json",
)

LANE_E_FILES = (
    "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md",
    "codex-rs/hepta-intelligence-eval/src/closure.rs",
    "codex-rs/hepta-intelligence-eval/src/closure_tests.rs",
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "codex-rs/hepta-intelligence-eval/tests/operator_claim.rs",
    "codex-rs/hepta-shadow-qualification/src/lane_e_closure_tests.rs",
    "docs/lane-e/END_TO_END_LEARNING_SEQUENCE.md",
    "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json",
    "qualification/lane-e/TEST_TRACEABILITY.json",
    "qualification/module-execution-dossiers/DETAILS.json",
    "qualification/module-execution-dossiers/detail/learning.eval.md",
    "scripts/hepta-lane-e-closure.py",
)

# Latest Lane G closure plus repository-wide compatibility fixes that were
# qualified with it.  Self-materializing/source-export workflows and Cargo.lock
# are deliberately excluded; the lock is regenerated from the composed tree.
LANE_G_FILES = (
    ".github/actions/setup-bazel-ci/action.yml",
    ".github/scripts/run-bazel-ci.sh",
    ".github/scripts/test_run_bazel_ci.py",
    ".github/workflows/hepta-development-docs.yml",
    ".github/workflows/hepta-lane-g-engineering.yml",
    ".github/workflows/hepta-objective-admission.yml",
    "codex-rs/app-server/src/hepta_local_lifecycle.rs",
    "codex-rs/app-server/src/message_processor.rs",
    "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
    "codex-rs/app-server/src/request_processors/mcp_event_stream.rs",
    "codex-rs/app-server/src/request_processors/thread_delete.rs",
    "codex-rs/core/src/agent/control/execution.rs",
    "codex-rs/core/src/agent/control/residency.rs",
    "codex-rs/core/src/client.rs",
    "codex-rs/core/src/codex_thread.rs",
    "codex-rs/core/src/session/inject.rs",
    "codex-rs/core/src/session/mod.rs",
    "codex-rs/core/src/session/session.rs",
    "codex-rs/core/src/session/turn.rs",
    "codex-rs/core/src/session/turn_input.rs",
    "codex-rs/core/src/session/turn_suspension.rs",
    "codex-rs/core/src/tasks/mod.rs",
    "codex-rs/core/src/tools/registry.rs",
    "codex-rs/ext/hepta-memory/src/extension.rs",
    "codex-rs/ext/hepta-memory/src/local_replay.rs",
    "codex-rs/ext/hepta-memory/src/local_runtime.rs",
    "codex-rs/ext/hepta-memory/src/local_turn_writer.rs",
    "codex-rs/ext/hepta-memory/src/local_witness.rs",
    "codex-rs/ext/queue/src/service.rs",
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "codex-rs/hepta-agentd/examples/h4_persistent_writer.rs",
    "codex-rs/hepta-agentd/src/app_runtime.rs",
    "codex-rs/hepta-agentd/src/control.rs",
    "codex-rs/hepta-agentd/src/error.rs",
    "codex-rs/hepta-contracts/Cargo.toml",
    "codex-rs/hepta-contracts/src/callers_manifest_tests.rs",
    "codex-rs/hepta-intelligence/Cargo.toml",
    "codex-rs/hepta-intelligence/src/lib.rs",
    "codex-rs/hepta-intelligence/src/vertical.rs",
    "codex-rs/hepta-intelligence/src/vertical_tests.rs",
    "codex-rs/hepta-learning-ledger/Cargo.toml",
    "codex-rs/hepta-learning-ledger/src/lib.rs",
    "codex-rs/hepta-learning-ledger/src/shadow.rs",
    "codex-rs/hepta-learning-ledger/src/shadow_tests.rs",
    "codex-rs/hepta-objective/src/lib.rs",
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "codex-rs/hepta-objective/src/objective_admission_tests.rs",
    "codex-rs/hepta-runtime/src/organs.rs",
    "codex-rs/hepta-supervisor/src/main.rs",
    "codex-rs/hepta-supervisor/src/signed_intent.rs",
    "codex-rs/hepta-supervisor/src/supervisor.rs",
    "codex-rs/http-client/src/tls_backend_fallback.rs",
    "codex-rs/windows-sandbox-rs/src/unified_exec/backend_selection_tests.rs",
    "codex-rs/windows-sandbox-rs/src/unified_exec/mod.rs",
    "docs/modules/control.engineering/IMPLEMENTATION_BINDING.md",
    "qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json",
    "qualification/module-execution-dossiers/NATIVE_BINDINGS.json",
    "qualification/module-execution-dossiers/test_implementation_contracts.py",
    "tools/hepta-engineering-control/README.md",
    "tools/hepta-engineering-control/control_engineering_v2/COMPONENTS.json",
    "tools/hepta-engineering-control/control_engineering_v2/EXTERNAL_GATES.json",
    "tools/hepta-engineering-control/control_engineering_v2/FAILURE_CODES.json",
    "tools/hepta-engineering-control/control_engineering_v2/HARDENING.json",
    "tools/hepta-engineering-control/control_engineering_v2/HARDENING.md",
    "tools/hepta-engineering-control/control_engineering_v2/HARDENING_FAILURE_CODES.json",
    "tools/hepta-engineering-control/control_engineering_v2/IMPLEMENTATION.md",
    "tools/hepta-engineering-control/control_engineering_v2/MATURITY.json",
    "tools/hepta-engineering-control/control_engineering_v2/README.md",
    "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
    "tools/hepta-engineering-control/control_engineering_v2/TRACEABILITY.json",
    "tools/hepta-engineering-control/control_engineering_v2/__init__.py",
    "tools/hepta-engineering-control/control_engineering_v2/__main__.py",
    "tools/hepta-engineering-control/control_engineering_v2/assimilation.py",
    "tools/hepta-engineering-control/control_engineering_v2/candidate.py",
    "tools/hepta-engineering-control/control_engineering_v2/closure.py",
    "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
    "tools/hepta-engineering-control/control_engineering_v2/evidence.py",
    "tools/hepta-engineering-control/control_engineering_v2/facade.py",
    "tools/hepta-engineering-control/control_engineering_v2/hardening.py",
    "tools/hepta-engineering-control/control_engineering_v2/py.typed",
    "tools/hepta-engineering-control/control_engineering_v2/seal.py",
    "tools/hepta-engineering-control/lane_g_hardening_validate.py",
    "tools/hepta-engineering-control/lane_g_validate.py",
    "tools/hepta-engineering-control/pyproject.toml",
    "tools/hepta-engineering-control/test_control_engineering_v2.py",
    "tools/hepta-engineering-control/test_lane_g_closure.py",
    "tools/hepta-engineering-control/test_lane_g_hardening.py",
    "tools/hepta-engineering-control/test_lane_g_seal.py",
)

TRANSIENT_PATHS = (
    ".lane-f-bootstrap",
    ".lane-f-final",
    ".lane-f-min",
    ".lane-f-recovery",
    ".github/workflows/lane-f-bootstrap.yml",
    ".github/workflows/lane-f-context-export-20260910.yml",
    ".github/workflows/lane-f-finalize-20260910.yml",
    ".github/workflows/lane-f-finalize-v2-20260910.yml",
    ".github/workflows/lane-f-finalize-v3-20260910.yml",
    ".github/workflows/lane-f-object-provenance-20260910.yml",
    ".github/workflows/lane-f-payload-salvage-20260910.yml",
    ".github/workflows/lane-f-recovered-source-qualification-20260910.yml",
    ".github/workflows/lane-f-resume-20260910.yml",
    ".github/workflows/lane-f-resume.yml",
    ".github/workflows/hepta-gap-agentd-process.yml",
    ".github/workflows/hepta-gap-source-export.yml",
    ".github/workflows/hepta-objective-admission-autofix.yml",
    ".github/workflows/hepta-lane-d-compile-repair.yml",
    ".github/workflows/hepta-diagnostic-source-export.yml",
    "qualification/lane-b/LANE_B_CANDIDATE_MANIFEST.json",
    "scripts/hepta-lane-b-candidate.py",
)

GENERATOR_COMMANDS = (
    ("python3", "scripts/hepta-readiness.py", "generate-status"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "generate-status"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status"),
    ("python3", "scripts/hepta-cns.py", "generate-status"),
    ("python3", "scripts/hepta-docs.py", "generate-status"),
)

REPOSITORY_COMMANDS = (
    ("python3", "scripts/hepta-readiness.py", "self-test"),
    ("python3", "scripts/hepta-readiness.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-readiness.py", "verify"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "self-test"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "verify"),
    ("python3", "scripts/hepta-technical-closure.py", "self-test"),
    ("python3", "scripts/hepta-technical-closure.py", "verify"),
    ("python3", "qualification/module-execution-dossiers/implementation_contracts.py", "self-test"),
    ("python3", "qualification/module-execution-dossiers/implementation_contracts.py", "verify-repository"),
    ("python3", "scripts/hepta-module-docs.py", "self-test"),
    ("python3", "scripts/hepta-module-docs.py", "verify"),
    ("python3", "scripts/hepta-algorithm-docs.py", "self-test"),
    ("python3", "scripts/hepta-algorithm-docs.py", "verify-sources"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-algorithm-docs.py", "verify"),
    ("python3", "scripts/hepta-cns.py", "self-test"),
    ("python3", "scripts/hepta-cns.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-cns.py", "verify"),
    ("python3", "scripts/hepta-hnmf.py", "self-test"),
    ("python3", "scripts/hepta-hnmf.py", "verify"),
    ("python3", "scripts/hepta-docs.py", "self-test"),
    ("python3", "scripts/hepta-docs.py", "verify"),
)


def run(argv: Sequence[str], *, check: bool = True, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    print("+", shlex.join(argv), flush=True)
    completed = subprocess.run(argv, cwd=cwd, text=True, check=False)
    if check and completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {shlex.join(argv)}")
    return completed


def output(argv: Sequence[str], *, cwd: Path = ROOT) -> str:
    print("+", shlex.join(argv), flush=True)
    completed = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(completed.stdout, end="", flush=True)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {shlex.join(argv)}")
    return completed.stdout.strip()


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(("git", *args), check=check)


def git_output(*args: str) -> str:
    return output(("git", *args))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_object(commit: str) -> None:
    actual = git_output("rev-parse", "--verify", f"{commit}^{{commit}}")
    if actual != commit:
        raise RuntimeError(f"commit identity mismatch: expected={commit} actual={actual}")


def assert_remote_tip(branch: str, expected: str) -> None:
    actual = git_output("rev-parse", f"origin/{branch}^{{commit}}")
    if actual != expected:
        raise RuntimeError(
            f"source branch moved: branch={branch} expected={expected} actual={actual}"
        )


def restore_exact(commit: str, paths: Iterable[str]) -> None:
    for path in paths:
        exists = subprocess.run(
            ("git", "cat-file", "-e", f"{commit}:{path}"),
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
        if exists:
            git("checkout", commit, "--", path)
        else:
            git("rm", "-rf", "--ignore-unmatch", "--", path)


def remove_transients() -> list[str]:
    removed: list[str] = []
    for path in TRANSIENT_PATHS:
        candidate = ROOT / path
        if candidate.exists() or candidate.is_symlink():
            git("rm", "-rf", "--ignore-unmatch", "--", path)
            removed.append(path)
    return removed


def refresh_details() -> list[str]:
    path = ROOT / "qualification/module-execution-dossiers/DETAILS.json"
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("DETAILS.json rows must be a list")
    updated: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("DETAILS.json row must be an object")
        relative = row.get("path")
        module = row.get("module")
        if not isinstance(relative, str) or not relative:
            raise RuntimeError(f"invalid detailed-design path for {module}")
        source = ROOT / relative
        if not source.is_file():
            raise RuntimeError(f"missing detailed-design file for {module}: {relative}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if row.get("sha256") != digest:
            row["sha256"] = digest
            updated.append(str(module))
    if updated:
        write_json(path, value)
    return updated


def rebind_native_indexes() -> dict[str, int]:
    rebound = 0
    checked = 0
    for path in sorted((ROOT / "qualification/module-execution-dossiers").glob("NATIVE_BINDINGS*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value.get("observations")
        if not isinstance(rows, list):
            raise RuntimeError(f"{path} observations must be a list")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError(f"{path} observation must be an object")
            relative = row.get("path")
            exports = row.get("exports")
            if not isinstance(relative, str) or not isinstance(exports, list):
                raise RuntimeError(f"invalid native row in {path}: {row!r}")
            source = ROOT / relative
            if not source.is_file():
                raise RuntimeError(f"native source missing: {relative}")
            text = source.read_text(encoding="utf-8", errors="strict")
            missing = [name for name in exports if not isinstance(name, str) or not name or name not in text]
            if missing:
                raise RuntimeError(f"native exports missing from {relative}: {missing}")
            digest = git_output("hash-object", "--", relative)
            checked += 1
            if row.get("blobSha") != digest:
                row["blobSha"] = digest
                rebound += 1
        coverage = value.get("moduleCoverage")
        if path.name == "NATIVE_BINDINGS.json" and (coverage != 40 or len(rows) != 40):
            raise RuntimeError(
                f"main native index coverage mismatch: coverage={coverage} rows={len(rows)}"
            )
        value["sourceSnapshot"] = R12_SHA
        write_json(path, value)
    return {"checked": checked, "rebound": rebound}


def run_generators() -> None:
    for command in GENERATOR_COMMANDS:
        if (ROOT / command[1]).is_file():
            run(command)


def run_repository_gates(head: str) -> None:
    run(("python3", "scripts/hepta-repository-integrity.py", "self-test"))
    run(
        (
            "python3",
            "scripts/hepta-repository-integrity.py",
            "verify",
            "--base",
            REVIEW_ANCHOR,
            "--head",
            head,
            "--output",
            "qualification/convergence/REPOSITORY_INTEGRITY_R13.json",
        )
    )
    for command in REPOSITORY_COMMANDS:
        if (ROOT / command[1]).is_file():
            run(command)


def run_lane_g_gates() -> None:
    directory = ROOT / "tools/hepta-engineering-control"
    run(("python3", "-m", "compileall", "-q", "control_engineering_v2"), cwd=directory)
    run(("python3", "lane_g_validate.py"), cwd=directory)
    if (directory / "lane_g_hardening_validate.py").is_file():
        run(("python3", "lane_g_hardening_validate.py"), cwd=directory)
    tests = [
        name
        for name in (
            "test_hepta_engineering_control.py",
            "test_integration_identity.py",
            "test_control_engineering_v2.py",
            "test_lane_g_closure.py",
            "test_lane_g_hardening.py",
            "test_lane_g_seal.py",
        )
        if (directory / name).is_file()
    ]
    run(("python3", "-m", "unittest", "-v", *tests), cwd=directory)


def run_owner_gates() -> None:
    # Lane B composed-candidate truth verifier and UI/runtime suites.
    run(("python3", "scripts/hepta-lane-b-truth.py", "self-test"))
    run(("python3", "-m", "unittest", "scripts/test_hepta_lane_b_truth.py"))
    run(("python3", "scripts/hepta-lane-b-truth.py", "verify"))
    run(("python3", "scripts/hepta-lane-b-docs.py"))
    run(("node", "--test", "apps/hepta-browser/test/runtime.test.js"))
    run(("node", "--test", "apps/hepta-control-ui/test/runtime-client.test.js"))
    run(("node", "--test", "apps/hepta-native/test/shell-runtime.test.js"))

    # Lane E closed-world semantic verifier.
    run(("python3", "scripts/hepta-lane-e-closure.py", "self-test"))
    run(("python3", "scripts/hepta-lane-e-closure.py", "verify"))

    run_lane_g_gates()


def run_rust_smoke() -> None:
    packages = (
        "codex-hepta-fleet",
        "codex-hepta-infer-core",
        "codex-hepta-infer-worker-host",
        "codex-hepta-automation",
        "codex-hepta-matrixd",
        "codex-hepta-intelligence-eval",
        "codex-hepta-shadow-qualification",
        "codex-hepta-intelligence",
        "codex-hepta-learning-ledger",
        "codex-hepta-objective",
        "codex-hepta-runtime",
        "codex-hepta-supervisor",
    )
    selectors: list[str] = []
    for package in packages:
        selectors.extend(("-p", package))
    run(
        (
            "cargo",
            "check",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            *selectors,
            "--all-targets",
        )
    )


def publish_single_parent(tree: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Hepta r13 Convergence",
            "GIT_AUTHOR_EMAIL": "hepta-r13-convergence@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "Hepta r13 Convergence",
            "GIT_COMMITTER_EMAIL": "hepta-r13-convergence@users.noreply.github.com",
            "GIT_AUTHOR_DATE": "2026-09-10T12:00:00Z",
            "GIT_COMMITTER_DATE": "2026-09-10T12:00:00Z",
        }
    )
    message = (
        "fix(hepta): publish latest-owner repository gap closure r13\n\n"
        "Exact tree qualified from r12 plus pinned Lane B/E/G owner deltas.\n"
        "Recovery/materialization carriers are absent. External authority gates remain open.\n"
    )
    completed = subprocess.run(
        ("git", "commit-tree", tree, "-p", REVIEW_ANCHOR),
        cwd=ROOT,
        input=message,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    print(completed.stdout, end="", flush=True)
    if completed.returncode:
        raise RuntimeError("git commit-tree failed")
    commit = completed.stdout.strip()
    if git_output("rev-parse", f"{commit}^{{tree}}") != tree:
        raise RuntimeError("single-parent tree identity mismatch")
    if git_output("rev-parse", f"{commit}^1") != REVIEW_ANCHOR:
        raise RuntimeError("single-parent review-anchor identity mismatch")
    git("push", "--force-with-lease", "origin", f"{commit}:refs/heads/{TARGET_BRANCH}")
    return commit


def create_or_update_pr(commit: str, tree: str) -> None:
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required to publish the candidate PR")
    existing = output(
        (
            "gh",
            "pr",
            "list",
            "--repo",
            os.environ["GITHUB_REPOSITORY"],
            "--state",
            "open",
            "--head",
            TARGET_BRANCH,
            "--base",
            "ops/hepta-final-convergence-review-anchor-20260909",
            "--json",
            "number",
            "--jq",
            ".[0].number // empty",
        )
    )
    body = ROOT / ".git" / "hepta-r13-pr.md"
    body.write_text(
        "\n".join(
            (
                "## Exact candidate",
                "",
                f"- head commit: `{commit}`",
                f"- tree: `{tree}`",
                f"- only parent: `{REVIEW_ANCHOR}`",
                f"- r12 source: `{R12_SHA}`",
                f"- Lane B source: `{LANE_B_SHA}`",
                f"- Lane E source: `{LANE_E_SHA}`",
                f"- Lane G source: `{LANE_G_SHA}`",
                "",
                "## Repository-controlled closure",
                "",
                "The tree overlays only the final owner files, regenerates shared projections and lock state, removes all known recovery/materialization carriers, and passes the in-run repository integrity, documentation, owner and Rust smoke gates before publication.",
                "",
                "## Authority ceiling",
                "",
                "This PR does not self-issue independent semantic acceptance, real model/runtime identity, future-window efficacy, target-host/hardware qualification, operator acceptance, production canary, selection, signing, promotion or release authority.",
                "",
            )
        ),
        encoding="utf-8",
    )
    if existing:
        run(
            (
                "gh",
                "pr",
                "edit",
                existing,
                "--repo",
                os.environ["GITHUB_REPOSITORY"],
                "--title",
                "fix(hepta): latest-owner repository gap closure r13",
                "--body-file",
                str(body),
            )
        )
    else:
        run(
            (
                "gh",
                "pr",
                "create",
                "--repo",
                os.environ["GITHUB_REPOSITORY"],
                "--base",
                "ops/hepta-final-convergence-review-anchor-20260909",
                "--head",
                TARGET_BRANCH,
                "--title",
                "fix(hepta): latest-owner repository gap closure r13",
                "--body-file",
                str(body),
            )
        )


def main() -> int:
    git("config", "user.name", "Hepta r13 Convergence")
    git("config", "user.email", "hepta-r13-convergence@users.noreply.github.com")
    git("fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")

    for commit in (R12_SHA, LANE_B_SHA, LANE_E_SHA, LANE_G_SHA, REVIEW_ANCHOR):
        assert_object(commit)
    assert_remote_tip("integration/hepta-all-gap-closure-20260910-r12", R12_SHA)
    assert_remote_tip("codex/hepta-lane-b-full-closure-20260910", LANE_B_SHA)
    assert_remote_tip("codex/hepta-lane-e-semantic-holdout-closure-r4-20260910", LANE_E_SHA)
    assert_remote_tip("codex/lane-g-real-full-closure-v2-20260910", LANE_G_SHA)

    git("checkout", "--detach", R12_SHA)
    git("checkout", "-B", "hepta-r13-materialized")
    restore_exact(LANE_B_SHA, LANE_B_FILES)
    restore_exact(LANE_E_SHA, LANE_E_FILES)
    restore_exact(LANE_G_SHA, LANE_G_FILES)
    removed = remove_transients()

    provenance = {
        "schema": "hepta.final-candidate-r13.v1",
        "reviewAnchor": REVIEW_ANCHOR,
        "r12Source": R12_SHA,
        "ownerSources": {
            "laneB": LANE_B_SHA,
            "laneE": LANE_E_SHA,
            "laneF": "preserved-r12-qualified-tree",
            "laneG": LANE_G_SHA,
        },
        "overlayFileCounts": {
            "laneB": len(LANE_B_FILES),
            "laneE": len(LANE_E_FILES),
            "laneG": len(LANE_G_FILES),
        },
        "removedTransientPaths": removed,
        "repositoryControlledCandidate": True,
        "externalAuthorityGatesRetained": True,
        "authorityGranted": False,
        "productionActivation": False,
        "selection": False,
        "promotion": False,
        "release": False,
    }
    write_json(ROOT / "qualification/convergence/FINAL_CANDIDATE_R13.json", provenance)

    # Regenerate dependency and formatted source state from the composed tree.
    run(("cargo", "metadata", "--manifest-path", "codex-rs/Cargo.toml", "--format-version", "1"))
    run(("cargo", "metadata", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "--format-version", "1"))
    run(("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"))
    detail_updates = refresh_details()
    native_receipt = rebind_native_indexes()
    run_generators()
    # Generators may update design documents; bind indexes once more.
    detail_updates.extend(refresh_details())
    native_receipt = rebind_native_indexes()
    provenance["updatedDetailedDesignModules"] = sorted(set(detail_updates))
    provenance["nativeBindingReceipt"] = native_receipt
    write_json(ROOT / "qualification/convergence/FINAL_CANDIDATE_R13.json", provenance)

    git("add", "-A")
    git("diff", "--cached", "--check")
    git("commit", "--signoff", "-m", "chore(hepta): materialize latest-owner r13 tree")
    materialized = git_output("rev-parse", "HEAD")

    run_repository_gates(materialized)
    run_owner_gates()
    run_rust_smoke()
    run(("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all", "--", "--check"))
    git("diff", "--check")
    if git_output("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("qualification mutated the tracked materialized tree")

    tree = git_output("rev-parse", "HEAD^{tree}")
    final_commit = publish_single_parent(tree)
    create_or_update_pr(final_commit, tree)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_R13_MATERIALIZED_AND_PUBLISHED",
                "materializedCommit": materialized,
                "candidateCommit": final_commit,
                "candidateTree": tree,
                "targetBranch": TARGET_BRANCH,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_R13_CONVERGENCE_ERROR: {error}", file=sys.stderr)
        raise

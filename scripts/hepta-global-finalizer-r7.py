#!/usr/bin/env python3
"""Parallel, fail-closed final convergence for all canonical Hepta packages.

Subcommands:

* ``prepare`` builds one exact integration candidate from the newest named lane
  closures, performs deterministic mechanical repairs, and emits a package
  shard matrix.
* ``repository-gate`` runs the repository closed-world/document/native-source
  gates against the exact candidate source commit.
* ``package-gate`` runs tests and strict Clippy for one package shard.
* ``finalize`` binds all receipts to the qualified source commit and writes a
  receipt-only commit.  It never grants independent review, production,
  selection, promotion, release, model/provider, or writer authority.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import tomllib
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path.cwd()
TARGET_BRANCH = os.environ.get(
    "HEPTA_FINAL_TARGET",
    "integration/hepta-all-gap-closure-20260910-r7",
)
BASE_CANDIDATES = (
    "origin/ops/hepta-final-convergence-review-anchor-20260909",
    "origin/codex/hepta-native-source-closed-world-20260909",
    "origin/integration/vnext-main-20260811",
)
LANE_ORDER = ("A", "B", "C", "D", "E", "F", "G")
LANE_PREFERENCES: dict[str, tuple[str, ...]] = {
    "A": (
        "codex/lane-a-gap-closure-20260910",
        "codex/hepta-lane-a-gap-closure-20260910",
    ),
    "B": (
        "codex/hepta-lane-b-gap-closure-20260910",
        "codex/lane-b-gap-closure-20260910",
    ),
    "C": (
        "codex/lane-c-full-gap-closure-20260910",
        "codex/hepta-lane-c-gap-closure-20260910",
    ),
    "D": (
        "codex/hepta-lane-d-gap-closure-20260910",
        "codex/lane-d-gap-closure-20260910",
    ),
    "E": (
        "codex/hepta-lane-e-gap-closure-20260910",
        "codex/lane-e-gap-closure-20260910",
    ),
    "F": (
        "codex/lane-f-gap-closure-20260910",
        "codex/hepta-lane-f-gap-closure-20260910",
    ),
    "G": (
        "codex/hepta-lane-g-gap-closure-20260910",
        "codex/lane-g-gap-closure-20260910",
    ),
}
GENERATED_CONFLICTS = (
    re.compile(r"^codex-rs/Cargo\.lock$"),
    re.compile(r"^docs/(?:STATUS\.md|CURRENT\.json)$"),
    re.compile(r"^docs/.*/STATUS(?:\.md|\.json)$"),
    re.compile(
        r"^qualification/module-execution-dossiers/"
        r"(?:NATIVE_BINDINGS|IMPLEMENTATION_COMPLETION)\.json$"
    ),
)
OUT_ROOT = ROOT / "qualification" / "global-gap-closure-final-r7"
PREPARE_RECEIPT = OUT_ROOT / "PREPARE.json"
REPOSITORY_RECEIPT = OUT_ROOT / "REPOSITORY_GATE.json"
FINAL_STATUS = OUT_ROOT / "STATUS.json"

GENERATORS: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/hepta-readiness.py", "generate-status"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "generate-status"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status"),
    ("python3", "scripts/hepta-cns.py", "generate-status"),
    ("python3", "scripts/hepta-docs.py", "generate-status"),
)
REPOSITORY_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/hepta-readiness.py", "self-test"),
    ("python3", "scripts/hepta-readiness.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-readiness.py", "verify"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "self-test"),
    (
        "python3",
        "scripts/hepta-implementation-dossiers.py",
        "generate-status",
        "--check",
    ),
    ("python3", "scripts/hepta-implementation-dossiers.py", "verify"),
    ("python3", "scripts/hepta-technical-closure.py", "self-test"),
    ("python3", "scripts/hepta-technical-closure.py", "verify"),
    (
        "python3",
        "qualification/module-execution-dossiers/implementation_contracts.py",
        "self-test",
    ),
    (
        "python3",
        "qualification/module-execution-dossiers/implementation_contracts.py",
        "verify-repository",
    ),
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


@dataclass
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    seconds: float
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def receipt(self, *, tail_lines: int = 80) -> dict[str, Any]:
        encoded = self.output.encode("utf-8", errors="replace")
        return {
            "command": list(self.argv),
            "returnCode": self.returncode,
            "durationSeconds": round(self.seconds, 3),
            "outputSha256": hashlib.sha256(encoded).hexdigest(),
            "tail": self.output.splitlines()[-tail_lines:],
        }


def run(
    argv: Iterable[str],
    *,
    timeout: int = 3600,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> CommandResult:
    args = tuple(argv)
    print("+", shlex.join(args), flush=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        result = CommandResult(
            args,
            completed.returncode,
            time.monotonic() - started,
            completed.stdout,
        )
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + "\nTIMEOUT\n"
        result = CommandResult(args, 124, time.monotonic() - started, output)
    print(result.output[-12000:], flush=True)
    if check and not result.passed:
        raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(args)}")
    return result


def git(*args: str, check: bool = True, timeout: int = 1200) -> CommandResult:
    return run(("git", *args), check=check, timeout=timeout)


def git_text(*args: str) -> str:
    return git(*args).output.strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_json_object(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("command output did not contain a JSON object")


def set_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")
    print(f"OUTPUT {name}={value}")


def repository_remote_branches() -> dict[str, int]:
    result = git(
        "for-each-ref",
        "--format=%(refname:short)|%(committerdate:unix)",
        "refs/remotes/origin",
    )
    branches: dict[str, int] = {}
    for line in result.output.splitlines():
        if not line.startswith("origin/") or "|" not in line:
            continue
        ref, raw_timestamp = line.rsplit("|", 1)
        branch = ref.removeprefix("origin/")
        if branch == "HEAD":
            continue
        try:
            branches[branch] = int(raw_timestamp)
        except ValueError:
            continue
    return branches


def resolve_base() -> tuple[str, str]:
    override = os.environ.get("HEPTA_CONVERGENCE_BASE")
    candidates = (override,) + BASE_CANDIDATES if override else BASE_CANDIDATES
    for ref in candidates:
        probe = git("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        if probe.passed:
            return ref, probe.output.strip()
    raise RuntimeError("no admissible exact convergence base exists")


def select_lane_branches(branches: dict[str, int]) -> dict[str, str | None]:
    selected: dict[str, str | None] = {}
    for lane in LANE_ORDER:
        selected[lane] = next(
            (branch for branch in LANE_PREFERENCES[lane] if branch in branches),
            None,
        )
        if selected[lane] is not None:
            continue
        marker = f"lane-{lane.lower()}"
        candidates = [
            branch
            for branch in branches
            if marker in branch.lower()
            and "20260910" in branch
            and ("gap" in branch.lower() or "closure" in branch.lower())
            and "global-gap-closure" not in branch.lower()
            and "all-gap-closure" not in branch.lower()
        ]
        if candidates:
            selected[lane] = max(candidates, key=lambda branch: branches[branch])
    return selected


def generated_conflicts_only(paths: Sequence[str]) -> bool:
    return bool(paths) and all(
        any(pattern.match(path) for pattern in GENERATED_CONFLICTS) for path in paths
    )


LANE_B_PRIOR_LANE_A_CONFLICTS = frozenset(
    {
        ".github/workflows/lane-a-foundation.yml",
        "codex-rs/hepta-authbus/src/lib.rs",
        "codex-rs/hepta-authbus/src/lib_tests.rs",
        "codex-rs/hepta-operations/src/ledger.rs",
        "codex-rs/hepta-operations/src/ledger_tests.rs",
        "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json",
        "docs/lane-a-foundation/README.md",
        "docs/lane-a-foundation/STATUS_MODEL.md",
        "docs/lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.authority/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.operations/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/platform.wire/WIRE_V1.md",
        "docs/lane-a-foundation/secrets.heptabao/CURRENT_IMPLEMENTATION.md",
        "qualification/module-execution-dossiers/NATIVE_BINDINGS.json",
        "qualification/module-execution-dossiers/test_implementation_contracts.py",
        "qualification/module-execution-dossiers/test_lane_a_foundation.py",
        "scripts/verify_lane_a_foundation.py",
    }
)

LANE_C_SPLIT_TEST_HARNESS_CONFLICT = (
    "qualification/module-execution-dossiers/test_implementation_contracts.py"
)

LANE_D_PRIOR_OWNER_CONFLICTS = frozenset(
    {
        ".github/workflows/lane-a-foundation.yml",
        "codex-rs/hepta-authbus/src/lib.rs",
        "codex-rs/hepta-authbus/src/lib_tests.rs",
        "codex-rs/hepta-cognitive-read/src/authoritative_tests.rs",
        "codex-rs/hepta-cognitive-store/src/v2.rs",
        "codex-rs/hepta-cognitive-store/src/v2_tests.rs",
        "codex-rs/hepta-cognitive-types/src/lane_c.rs",
        "codex-rs/hepta-compact-engine/src/qualified.rs",
        "codex-rs/hepta-compact-engine/src/qualified_tests.rs",
        "codex-rs/hepta-context-compiler/src/v2.rs",
        "codex-rs/hepta-context-compiler/src/v2_tests.rs",
        "codex-rs/hepta-kg/src/generation.rs",
        "codex-rs/hepta-kg/src/generation_tests.rs",
        "codex-rs/hepta-memory-federation/src/v2.rs",
        "codex-rs/hepta-memory-federation/src/v2_tests.rs",
        "codex-rs/hepta-memory-retrieval/src/generation_bound.rs",
        "codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs",
        "codex-rs/hepta-operations/src/ledger.rs",
        "codex-rs/hepta-operations/src/ledger_tests.rs",
        "codex-rs/hepta-prompt-registry/src/v2.rs",
        "codex-rs/hepta-prompt-registry/src/v2_tests.rs",
        "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json",
        "docs/lane-a-foundation/README.md",
        "docs/lane-a-foundation/STATUS_MODEL.md",
        "docs/lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.authority/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.operations/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/platform.wire/WIRE_V1.md",
        "docs/lane-a-foundation/secrets.heptabao/CURRENT_IMPLEMENTATION.md",
        "qualification/module-execution-dossiers/NATIVE_BINDINGS.json",
        "qualification/module-execution-dossiers/test_implementation_contracts.py",
        "qualification/module-execution-dossiers/test_lane_a_foundation.py",
        "scripts/verify_lane_a_foundation.py",
    }
)


LANE_F_OWNER_CONFLICTS = frozenset(
    {
        ".github/workflows/hepta-lane-f-shadow-qualification.yml",
        ".github/workflows/lane-f-bootstrap.yml",
        "qualification/lane-f-shadow/src/lib.rs",
    }
)

LANE_G_PRIOR_OWNER_CONFLICTS = frozenset(
    {
        "qualification/module-execution-dossiers/NATIVE_BINDINGS.json",
        "qualification/module-execution-dossiers/test_implementation_contracts.py",
    }
)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
    before = git_text("rev-parse", "HEAD")
    message = (
        f"merge(lane-{lane.lower()}): converge {branch}\n\n"
        "Signed-off-by: OpenAI Codex <noreply@openai.com>"
    )
    result = git(
        "merge",
        "--no-ff",
        "--no-edit",
        "-m",
        message,
        f"origin/{branch}",
        check=False,
        timeout=1800,
    )
    conflicts: list[str] = []
    auto_resolved = False
    lane_owner_conflict = False
    prior_lane_owner_conflict = False
    split_test_harness_conflict = False
    lane_d_prior_owner_conflict = False
    lane_f_owner_conflict = False
    lane_g_prior_owner_conflict = False
    if not result.passed:
        conflicts = [
            line.strip()
            for line in git(
                "diff", "--name-only", "--diff-filter=U", check=False
            ).output.splitlines()
            if line.strip()
        ]
        lane_owner_conflict = lane == "E" and conflicts == ["docs/lane-e/README.md"]
        prior_lane_owner_conflict = (
            lane == "B"
            and len(conflicts) == len(LANE_B_PRIOR_LANE_A_CONFLICTS)
            and frozenset(conflicts) == LANE_B_PRIOR_LANE_A_CONFLICTS
        )
        split_test_harness_conflict = lane == "C" and conflicts == [
            LANE_C_SPLIT_TEST_HARNESS_CONFLICT
        ]
        lane_d_prior_owner_conflict = (
            lane == "D"
            and len(conflicts) == len(LANE_D_PRIOR_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_D_PRIOR_OWNER_CONFLICTS
        )
        lane_f_owner_conflict = (
            lane == "F"
            and len(conflicts) == len(LANE_F_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_F_OWNER_CONFLICTS
        )
        lane_g_prior_owner_conflict = (
            lane == "G"
            and len(conflicts) == len(LANE_G_PRIOR_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_G_PRIOR_OWNER_CONFLICTS
        )
        if (
            not generated_conflicts_only(conflicts)
            and not lane_owner_conflict
            and not prior_lane_owner_conflict
            and not split_test_harness_conflict
            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
            and not lane_g_prior_owner_conflict
        ):
            git("merge", "--abort", check=False)
            return {
                "lane": lane,
                "branch": branch,
                "merged": False,
                "before": before,
                "conflicts": conflicts,
                "outputTail": result.output.splitlines()[-100:],
            }
        checkout_side = (
            "--theirs"
            if lane_owner_conflict or lane_f_owner_conflict
            else "--ours"
        )
        for path in conflicts:
            if (
                lane_f_owner_conflict
                and path == ".github/workflows/lane-f-bootstrap.yml"
            ):
                git("rm", "--", path)
                continue
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
        if lane_owner_conflict:
            resolution_class = "lane-E owner documentation"
        elif prior_lane_owner_conflict:
            resolution_class = "prior lane-A owner paths retained during lane-B merge"
        elif split_test_harness_conflict:
            resolution_class = "split implementation-contract test harness"
        elif lane_d_prior_owner_conflict:
            resolution_class = "prior Lane A/C owner paths retained during Lane D merge"
        elif lane_f_owner_conflict:
            resolution_class = "Lane F owner shadow qualification paths"
        elif lane_g_prior_owner_conflict:
            resolution_class = "prior cumulative owner metadata retained during Lane G merge"
        else:
            resolution_class = "generated convergence metadata"
        git(
            "commit",
            "--signoff",
            "-m",
            f"merge(lane-{lane.lower()}): resolve {resolution_class}",
        )
        auto_resolved = True
    return {
        "lane": lane,
        "branch": branch,
        "merged": True,
        "before": before,
        "after": git_text("rev-parse", "HEAD"),
        "autoResolvedGeneratedOnly": (
            auto_resolved
            and not lane_owner_conflict
            and not prior_lane_owner_conflict
            and not split_test_harness_conflict
            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
            and not lane_g_prior_owner_conflict
        ),
        "autoResolvedLaneOwnerOnly": lane_owner_conflict,
        "autoResolvedPriorLaneOwnerOnly": prior_lane_owner_conflict,
        "autoResolvedSplitTestHarnessOnly": split_test_harness_conflict,
        "autoResolvedLaneDPriorOwnerOnly": lane_d_prior_owner_conflict,
        "autoResolvedLaneFOwnerOnly": lane_f_owner_conflict,
        "autoResolvedLaneGPriorOwnerOnly": lane_g_prior_owner_conflict,
        "conflicts": conflicts,
    }


def repair_lane_g_shared_artifacts(
    selected: dict[str, str | None],
) -> dict[str, Any]:
    """Aggregate exact native rows by primary lane and regenerate Lane G."""

    relative_path = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    native_path = ROOT / relative_path
    profiles = read_json(
        ROOT
        / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    )
    profile_rows = profiles.get("modules")
    if not isinstance(profile_rows, list):
        raise RuntimeError("implementation profiles modules must be a list")
    canonical_modules = [row.get("module") for row in profile_rows]
    if len(canonical_modules) != 40 or len(set(canonical_modules)) != 40:
        raise RuntimeError("implementation profiles must contain 40 unique modules")
    module_lanes = {row.get("module"): row.get("lane") for row in profile_rows}
    invalid_lanes = sorted(
        f"{module}:{lane}"
        for module, lane in module_lanes.items()
        if lane not in LANE_ORDER
    )
    if invalid_lanes:
        raise RuntimeError(
            "implementation profiles contain invalid lane bindings: "
            + ", ".join(invalid_lanes)
        )

    seed_ref = "origin/codex/hepta-native-source-closed-world-20260909"
    seed_commit = git_text("rev-parse", f"{seed_ref}^{{commit}}")
    seed_result = git("show", f"{seed_ref}:{relative_path}", check=False)
    if not seed_result.passed:
        raise RuntimeError(
            "cannot read immutable 40-module native seed: "
            + "\n".join(seed_result.output.splitlines()[-20:])
        )
    try:
        seed_document = json.loads(seed_result.output)
    except json.JSONDecodeError as error:
        raise RuntimeError("40-module native seed is invalid JSON") from error
    seed_rows = seed_document.get("observations")
    if not isinstance(seed_rows, list):
        raise RuntimeError("40-module native seed observations must be a list")
    seed_modules = [
        row.get("module") if isinstance(row, dict) else None for row in seed_rows
    ]
    if (
        len(seed_rows) != 40
        or len(set(seed_modules)) != 40
        or set(seed_modules) != set(canonical_modules)
    ):
        raise RuntimeError("40-module native seed does not match canonical modules")

    aggregated: dict[str, dict[str, Any]] = {
        row["module"]: dict(row) for row in seed_rows
    }
    row_sources: dict[str, dict[str, str]] = {
        module: {"source": "seed", "ref": seed_ref, "commit": seed_commit}
        for module in canonical_modules
    }
    lane_receipts: list[dict[str, Any]] = []
    for lane in LANE_ORDER:
        branch = selected.get(lane)
        if not branch:
            raise RuntimeError(f"selected lane {lane} branch is missing")
        lane_ref = f"origin/{branch}"
        lane_commit = git_text("rev-parse", f"{lane_ref}^{{commit}}")
        lane_result = git("show", f"{lane_ref}:{relative_path}", check=False)
        if not lane_result.passed:
            lane_receipts.append(
                {
                    "lane": lane,
                    "branch": branch,
                    "commit": lane_commit,
                    "indexPresent": False,
                    "ownedRows": [],
                }
            )
            continue
        try:
            lane_document = json.loads(lane_result.output)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"selected lane {lane} native index is invalid JSON"
            ) from error
        lane_rows = lane_document.get("observations")
        if not isinstance(lane_rows, list):
            raise RuntimeError(
                f"selected lane {lane} native observations must be a list"
            )
        lane_modules = [
            row.get("module") if isinstance(row, dict) else None for row in lane_rows
        ]
        duplicates = sorted(
            str(module)
            for module in set(lane_modules)
            if lane_modules.count(module) > 1
        )
        unknown = sorted(
            str(module) for module in lane_modules if module not in module_lanes
        )
        if duplicates or unknown:
            raise RuntimeError(
                f"selected lane {lane} native index invalid: "
                f"duplicates={duplicates} unknown={unknown}"
            )
        owned_rows: list[str] = []
        for row in lane_rows:
            module = row["module"]
            if module_lanes[module] != lane:
                continue
            aggregated[module] = dict(row)
            row_sources[module] = {
                "source": "primary_lane",
                "ref": lane_ref,
                "commit": lane_commit,
            }
            owned_rows.append(module)
        lane_receipts.append(
            {
                "lane": lane,
                "branch": branch,
                "commit": lane_commit,
                "indexPresent": True,
                "indexObservationCount": len(lane_rows),
                "ownedRows": sorted(owned_rows),
            }
        )

    lane_g_branch = selected.get("G")
    if not lane_g_branch:
        raise RuntimeError("Lane G source branch is required")
    source_path = (
        "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
    )
    source_text = git_text(
        "show", f"origin/{lane_g_branch}:{source_path}"
    )
    merged_source = ROOT / source_path
    if not merged_source.is_file():
        raise RuntimeError(
            f"Lane G control.engineering source is missing after merge: {source_path}"
        )
    merged_text = merged_source.read_text(encoding="utf-8")
    expected_text = source_text + ("" if source_text.endswith("\n") else "\n")
    if merged_text != expected_text:
        raise RuntimeError("merged Lane G public surface differs from exact lane source")
    try:
        source_tree = ast.parse(source_text, filename=source_path)
    except SyntaxError as error:
        raise RuntimeError("selected Lane G public surface is invalid Python") from error
    exports = sorted(
        {
            alias.asname or alias.name
            for node in source_tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if not (alias.asname or alias.name).startswith("_")
        }
    )
    required_exports = {
        "EngineeringStore",
        "WorkEnvelope",
        "WorkPackage",
        "Candidate",
        "SandboxReceipt",
        "EvidenceDecision",
        "AssimilationProposal",
        "issue_work_envelope",
        "schedule_ready_packages",
        "generate_candidate",
        "execute_candidate_sandbox",
        "verify_integration_evidence",
        "request_independent_review",
        "record_integration_decision",
        "publish_audit_projection",
        "prepare_assimilation_candidate",
    }
    missing_required = sorted(required_exports - set(exports))
    if missing_required:
        raise RuntimeError(
            "selected Lane G public surface lacks required exports: "
            + ", ".join(missing_required)
        )
    lane_g_commit = git_text(
        "rev-parse", f"origin/{lane_g_branch}^{{commit}}"
    )
    aggregated["control.engineering"] = {
        "module": "control.engineering",
        "path": source_path,
        "blobSha": git_text(
            "rev-parse", f"origin/{lane_g_branch}:{source_path}"
        ),
        "exports": exports,
    }
    row_sources["control.engineering"] = {
        "source": "exact_lane_g_public_surface",
        "ref": f"origin/{lane_g_branch}",
        "commit": lane_g_commit,
    }

    observations = [aggregated[module] for module in canonical_modules]
    for row in observations:
        module = row.get("module")
        source = row.get("path")
        row_exports = row.get("exports")
        if (
            module not in module_lanes
            or not isinstance(source, str)
            or not source
            or not isinstance(row_exports, list)
            or not row_exports
            or any(not isinstance(value, str) or not value for value in row_exports)
        ):
            raise RuntimeError(f"invalid aggregated native row for {module}")

    output_document = dict(seed_document)
    output_document["sourceSnapshot"] = git_text("rev-parse", "HEAD")
    output_document["moduleCoverage"] = 40
    output_document["consumerCallsitesProved"] = False
    output_document["productExecutionProved"] = False
    output_document["observations"] = observations
    write_json(native_path, output_document)

    harness_path = (
        ROOT / "qualification/module-execution-dossiers/test_implementation_contracts.py"
    )
    harness = harness_path.read_text(encoding="utf-8")
    test_surfaces = [harness]
    for name in (
        "implementation_contract_tests_core.py",
        "implementation_contract_tests_native.py",
        "implementation_contract_tests_system.py",
    ):
        candidate = harness_path.with_name(name)
        if candidate.is_file():
            test_surfaces.append(candidate.read_text(encoding="utf-8"))
    if "class NativeBindingCoverageTests" not in "\n".join(test_surfaces):
        raise RuntimeError("cumulative native-binding coverage tests are missing")
    if "from implementation_contract_tests_core import *" in harness:
        core_path = harness_path.with_name("implementation_contract_tests_core.py")
        if not core_path.is_file():
            raise RuntimeError("split implementation-contract core tests are missing")

    fallback_modules = sorted(
        module
        for module, source in row_sources.items()
        if source["source"] == "seed"
    )
    return {
        "seedRef": seed_ref,
        "seedCommit": seed_commit,
        "laneReceipts": lane_receipts,
        "fallbackModules": fallback_modules,
        "rowSources": row_sources,
        "laneGBranch": lane_g_branch,
        "laneGCommit": lane_g_commit,
        "laneGSourcePath": source_path,
        "laneGExports": exports,
        "moduleCoverage": len(observations),
        "changed": [relative_path],
        "count": 1,
    }


def repair_argument_comment_blockers() -> dict[str, Any]:
    repairs = (
        (
            Path("codex-rs/http-client/src/tls_backend_fallback.rs"),
            "walk_error_chain(error, 0, &mut |error| {",
            "walk_error_chain(error, /*depth*/ 0, &mut |error| {",
            2,
        ),
        (
            Path("codex-rs/hepta-runtime/src/organs.rs"),
            "Generation::new(1)?",
            "Generation::new(/*value*/ 1)?",
            1,
        ),
    )
    changed: list[str] = []
    for path, old, new, expected_count in repairs:
        source = path.read_text(encoding="utf-8")
        old_count = source.count(old)
        new_count = source.count(new)
        if old_count == expected_count and new_count == 0:
            path.write_text(source.replace(old, new), encoding="utf-8")
            changed.append(path.as_posix())
            continue
        if old_count == 0 and new_count == expected_count:
            continue
        raise RuntimeError(
            f"argument-comment repair drift for {path}: "
            f"old={old_count} new={new_count} expected={expected_count}"
        )
    return {"changed": changed, "count": len(changed)}


def run_generators() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for command in GENERATORS:
        if not (ROOT / command[1]).is_file():
            receipts.append({"command": list(command), "skipped": "missing executable"})
            continue
        receipts.append(run(command, timeout=1800).receipt())
    return receipts


def repair_native_bindings() -> dict[str, Any]:
    path = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    if not path.is_file():
        return {"present": False, "valid": False, "updated": 0}
    document = read_json(path)
    observations = document.get("observations", [])
    updated = 0
    failures: list[dict[str, Any]] = []
    for row in observations:
        source = row.get("path")
        exports = row.get("exports")
        if not isinstance(source, str) or not isinstance(exports, list):
            failures.append({"path": source, "reason": "invalid observation shape"})
            continue
        source_path = ROOT / source
        if not source_path.is_file():
            failures.append({"path": source, "reason": "source missing"})
            continue
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        missing_exports = [
            value
            for value in exports
            if not isinstance(value, str) or value not in source_text
        ]
        if missing_exports:
            failures.append(
                {"path": source, "reason": "export missing", "exports": missing_exports}
            )
        actual = git_text("hash-object", "--", source)
        if row.get("blobSha") != actual:
            row["blobSha"] = actual
            updated += 1
    if updated:
        write_json(path, document)
    module_coverage = document.get("moduleCoverage")
    return {
        "present": True,
        "moduleCoverage": module_coverage,
        "observationCount": len(observations),
        "updated": updated,
        "failures": failures,
        "valid": module_coverage == 40 and len(observations) == 40 and not failures,
    }


def cargo_metadata(*, locked: bool) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    command = [
        "cargo",
        "metadata",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "--format-version",
        "1",
    ]
    if locked:
        command.append("--locked")
    result = run(command, timeout=2400)
    receipt = result.receipt()
    if not result.passed:
        return None, receipt
    try:
        return parse_json_object(result.output), receipt
    except ValueError:
        return None, receipt


def normalize_lockfile() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metadata, first = cargo_metadata(locked=True)
    receipts = [first]
    if metadata is not None:
        return metadata, receipts
    metadata, unlocked = cargo_metadata(locked=False)
    receipts.append(unlocked)
    if metadata is None:
        return None, receipts
    metadata, locked_again = cargo_metadata(locked=True)
    receipts.append(locked_again)
    return metadata, receipts


def workspace_package_map(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workspace = set(metadata.get("workspace_members", []))
    return {
        row["name"]: row
        for row in metadata.get("packages", [])
        if row.get("id") in workspace
    }


def dependency_names(section: Any, context: str) -> set[str]:
    if section is None:
        return set()
    if not isinstance(section, dict):
        raise RuntimeError(f"{context} must be a TOML table")
    names: set[str] = set()
    for declared_name, declaration in section.items():
        names.add(declared_name)
        if isinstance(declaration, dict):
            package_name = declaration.get("package")
            if package_name is not None:
                if not isinstance(package_name, str) or not package_name:
                    raise RuntimeError(
                        f"{context}.{declared_name}.package must be a non-empty string"
                    )
                names.add(package_name)
    return names


DEPENDENCY_KINDS = (
    "dependencies",
    "dev-dependencies",
    "build-dependencies",
)


def dependency_declarations(text: str) -> dict[str, set[str]]:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(f"cannot inspect invalid Cargo manifest: {error}") from error

    declared = {
        kind: dependency_names(document.get(kind), kind) for kind in DEPENDENCY_KINDS
    }
    targets = document.get("target")
    if targets is None:
        return declared
    if not isinstance(targets, dict):
        raise RuntimeError("target must be a TOML table")
    for target_name, target in targets.items():
        if not isinstance(target, dict):
            raise RuntimeError(f"target.{target_name} must be a TOML table")
        for kind in DEPENDENCY_KINDS:
            declared[kind].update(
                dependency_names(target.get(kind), f"target.{target_name}.{kind}")
            )
    return declared


def dependency_sections(text: str) -> set[str]:
    declared = dependency_declarations(text)
    return set().union(*(declared[kind] for kind in DEPENDENCY_KINDS))


def satisfying_dependency_kinds(kind: str) -> tuple[str, ...]:
    if kind == "dependencies":
        return ("dependencies",)
    if kind == "dev-dependencies":
        return ("dependencies", "dev-dependencies")
    if kind == "build-dependencies":
        return ("build-dependencies",)
    raise RuntimeError(f"unsupported dependency kind: {kind}")


def dependency_is_declared(
    declarations: dict[str, set[str]], dependency: str, kind: str
) -> bool:
    return any(
        dependency in declarations[declared_kind]
        for declared_kind in satisfying_dependency_kinds(kind)
    )


def add_dependency(
    manifest: Path,
    dependency: str,
    dependency_path: Path,
    kind: str = "dependencies",
) -> bool:
    if kind not in DEPENDENCY_KINDS:
        raise RuntimeError(f"unsupported dependency kind: {kind}")
    text = manifest.read_text(encoding="utf-8")
    declarations = dependency_declarations(text)
    if dependency_is_declared(declarations, dependency, kind):
        return False
    try:
        relative = dependency_path.relative_to(manifest.parent).as_posix()
    except ValueError:
        relative = os.path.relpath(dependency_path, manifest.parent).replace(
            os.sep, "/"
        )
    line = f'{dependency} = {{ path = "{relative}" }}\n'
    marker = f"[{kind}]\n"
    if marker in text:
        text = text.replace(marker, marker + line, 1)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n[{kind}]\n{line}"
    manifest.write_text(text, encoding="utf-8")
    return True


def _blank_rust_character(character: str) -> str:
    return "\n" if character == "\n" else " "


def rust_code_only(text: str) -> str:
    """Return Rust code with comments and literal bodies replaced by whitespace."""

    output: list[str] = []
    index = 0
    block_depth = 0
    length = len(text)
    while index < length:
        if block_depth:
            if text.startswith("/*", index):
                output.extend((" ", " "))
                index += 2
                block_depth += 1
                continue
            if text.startswith("*/", index):
                output.extend((" ", " "))
                index += 2
                block_depth -= 1
                continue
            output.append(_blank_rust_character(text[index]))
            index += 1
            continue

        if text.startswith("//", index):
            output.extend((" ", " "))
            index += 2
            while index < length and text[index] != "\n":
                output.append(" ")
                index += 1
            continue
        if text.startswith("/*", index):
            output.extend((" ", " "))
            index += 2
            block_depth = 1
            continue

        if text[index] == "r":
            cursor = index + 1
            while cursor < length and text[cursor] == "#":
                cursor += 1
            if cursor < length and text[cursor] == '"':
                hashes = cursor - index - 1
                terminator = '"' + ("#" * hashes)
                body_end = text.find(terminator, cursor + 1)
                final = length if body_end < 0 else body_end + len(terminator)
                while index < final:
                    output.append(_blank_rust_character(text[index]))
                    index += 1
                continue

        if text[index] == '"':
            output.append(" ")
            index += 1
            escaped = False
            while index < length:
                character = text[index]
                output.append(_blank_rust_character(character))
                index += 1
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    break
            continue

        if text[index] == "'":
            char_end: int | None = None
            if index + 2 < length and text[index + 2] == "'":
                char_end = index + 3
            elif index + 2 < length and text[index + 1] == "\\":
                cursor = index + 2
                while cursor < length and text[cursor] != "\n":
                    if text[cursor] == "'" and text[cursor - 1] != "\\":
                        char_end = cursor + 1
                        break
                    cursor += 1
            if char_end is not None:
                while index < char_end:
                    output.append(_blank_rust_character(text[index]))
                    index += 1
                continue

        output.append(text[index])
        index += 1

    if block_depth:
        raise RuntimeError("unterminated nested Rust block comment during dependency scan")
    return "".join(output)


def source_dependency_kind(package_root: Path, source: Path) -> str:
    relative = source.relative_to(package_root)
    if relative == Path("build.rs"):
        return "build-dependencies"
    if not relative.parts:
        return "dependencies"
    first = relative.parts[0].lower()
    if first in {"tests", "benches", "examples"}:
        return "dev-dependencies"
    if first == "src":
        filename = relative.name.lower()
        parent_parts = {part.lower() for part in relative.parts[1:-1]}
        if (
            filename in {"test.rs", "tests.rs", "test_support.rs"}
            or filename.endswith("_test.rs")
            or filename.endswith("_tests.rs")
            or filename.endswith("_test_support.rs")
            or parent_parts.intersection({"test", "tests"})
        ):
            return "dev-dependencies"
    return "dependencies"


def imported_workspace_crates_by_kind(
    package_root: Path,
) -> dict[str, set[str]]:
    imported = {kind: set() for kind in DEPENDENCY_KINDS}
    pattern = re.compile(r"\b(?:use|extern\s+crate)\s+(?:::)?(codex_[A-Za-z0-9_]+)")
    path_pattern = re.compile(r"\b(codex_[A-Za-z0-9_]+)\s*::")
    sources: set[Path] = set()
    build_script = package_root / "build.rs"
    if build_script.is_file():
        sources.add(build_script)
    for subdir in ("src", "tests", "benches", "examples"):
        source_root = package_root / subdir
        if source_root.exists():
            sources.update(source_root.rglob("*.rs"))
    for source in sorted(sources):
        code = rust_code_only(source.read_text(encoding="utf-8", errors="replace"))
        kind = source_dependency_kind(package_root, source)
        imported[kind].update(pattern.findall(code))
        imported[kind].update(path_pattern.findall(code))
    imported["dev-dependencies"].difference_update(imported["dependencies"])
    return imported


def workspace_dependency_graph(metadata: dict[str, Any]) -> dict[str, set[str]]:
    packages = workspace_package_map(metadata)
    workspace_ids = {row["id"]: name for name, row in packages.items()}
    graph = {name: set() for name in packages}
    resolve = metadata.get("resolve")
    if not isinstance(resolve, dict) or not isinstance(resolve.get("nodes"), list):
        raise RuntimeError("cargo metadata resolve graph is missing")
    for node in resolve["nodes"]:
        if not isinstance(node, dict):
            raise RuntimeError("cargo metadata resolve node must be an object")
        source = workspace_ids.get(node.get("id"))
        if source is None:
            continue
        dependencies = node.get("deps", [])
        if not isinstance(dependencies, list):
            raise RuntimeError(f"cargo metadata deps for {source} must be a list")
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise RuntimeError(f"cargo metadata dependency for {source} must be an object")
            target = workspace_ids.get(dependency.get("pkg"))
            if target is None:
                continue
            kinds = dependency.get("dep_kinds", [])
            if not isinstance(kinds, list):
                raise RuntimeError(
                    f"cargo metadata dep_kinds for {source}->{target} must be a list"
                )
            if not kinds or any(
                not isinstance(kind, dict) or kind.get("kind") != "dev"
                for kind in kinds
            ):
                graph[source].add(target)
    return graph


def dependency_cycle_path(
    graph: dict[str, set[str]], package: str, dependency: str
) -> list[str] | None:
    if package == dependency:
        return [package, package]
    queue: deque[tuple[str, list[str]]] = deque([(dependency, [dependency])])
    visited: set[str] = set()
    while queue:
        current, path = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if current == package:
            return [package, *path]
        for following in sorted(graph.get(current, set())):
            if following not in visited:
                queue.append((following, [*path, following]))
    return None


def repair_missing_local_dependencies(metadata: dict[str, Any]) -> dict[str, Any]:
    packages = workspace_package_map(metadata)
    crate_to_package = {
        package_name.replace("-", "_"): (
            package_name,
            Path(row["manifest_path"]).parent,
        )
        for package_name, row in packages.items()
    }
    graph = workspace_dependency_graph(metadata)
    added: list[dict[str, str]] = []
    skipped_cycles: list[dict[str, Any]] = []
    for package_name, row in sorted(packages.items()):
        manifest = Path(row["manifest_path"])
        package_root = manifest.parent
        declarations = dependency_declarations(manifest.read_text(encoding="utf-8"))
        imports = imported_workspace_crates_by_kind(package_root)
        for kind in DEPENDENCY_KINDS:
            for crate_name in sorted(imports[kind]):
                target = crate_to_package.get(crate_name)
                if target is None:
                    continue
                dependency_name, dependency_path = target
                if dependency_name == package_name or dependency_is_declared(
                    declarations, dependency_name, kind
                ):
                    continue
                if kind in {"dependencies", "build-dependencies"}:
                    cycle = dependency_cycle_path(graph, package_name, dependency_name)
                    if cycle is not None:
                        skipped_cycles.append(
                            {
                                "package": package_name,
                                "dependency": dependency_name,
                                "kind": kind,
                                "manifest": manifest.relative_to(ROOT).as_posix(),
                                "cyclePath": cycle,
                            }
                        )
                        continue
                if add_dependency(manifest, dependency_name, dependency_path, kind):
                    declarations[kind].add(dependency_name)
                    if kind in {"dependencies", "build-dependencies"}:
                        graph[package_name].add(dependency_name)
                    added.append(
                        {
                            "package": package_name,
                            "dependency": dependency_name,
                            "kind": kind,
                            "manifest": manifest.relative_to(ROOT).as_posix(),
                        }
                    )
    return {
        "added": added,
        "count": len(added),
        "skippedCycles": skipped_cycles,
        "skippedCycleCount": len(skipped_cycles),
    }


def canonical_hepta_packages(metadata: dict[str, Any]) -> list[str]:
    packages = workspace_package_map(metadata)
    selected = sorted(name for name in packages if name.startswith("codex-hepta-"))
    if len(selected) < 40:
        raise RuntimeError(
            f"canonical Hepta package set is unexpectedly small: {len(selected)}"
        )
    return selected


def run_prepare_compile_checks(packages: Sequence[str]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for package in packages:
        result = run(
            (
                "cargo",
                "check",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                "-p",
                package,
                "--all-targets",
            ),
            timeout=5400,
        )
        receipts.append({"package": package, **result.receipt()})
    return receipts


def commit_if_dirty(message: str) -> str:
    if not git("status", "--porcelain", check=False).output.strip():
        return git_text("rev-parse", "HEAD")
    git("add", "-A")
    git("commit", "--signoff", "-m", message)
    return git_text("rev-parse", "HEAD")


def shard_matrix(packages: Sequence[str], shard_count: int) -> dict[str, Any]:
    count = max(1, min(shard_count, len(packages)))
    shards: list[list[str]] = [[] for _ in range(count)]
    for index, package in enumerate(packages):
        shards[index % count].append(package)
    return {
        "include": [
            {
                "shard": index,
                "packages_json": json.dumps(values, separators=(",", ":")),
                "package_count": len(values),
            }
            for index, values in enumerate(shards)
        ]
    }


def command_receipts_pass(receipts: Iterable[dict[str, Any]]) -> bool:
    return all(
        "skipped" in receipt or receipt.get("returnCode") == 0 for receipt in receipts
    )


def prepare(args: argparse.Namespace) -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    git("config", "user.name", "Hepta Parallel Finalizer")
    git("config", "user.email", "noreply@openai.com")
    git(
        "fetch",
        "--prune",
        "origin",
        "+refs/heads/*:refs/remotes/origin/*",
        timeout=1800,
    )
    base_ref, base_commit = resolve_base()
    branches = repository_remote_branches()
    selected = select_lane_branches(branches)
    if not any(selected.values()):
        raise RuntimeError("no current 2026-09-10 lane candidate was discovered")

    git("checkout", "-B", TARGET_BRANCH, base_ref)
    merge_receipts: list[dict[str, Any]] = []
    for lane in LANE_ORDER:
        branch = selected[lane]
        if branch is None:
            merge_receipts.append(
                {"lane": lane, "branch": None, "status": "no_current_candidate"}
            )
            continue
        receipt = merge_lane(lane, branch)
        merge_receipts.append(receipt)
        if not receipt.get("merged"):
            write_json(
                PREPARE_RECEIPT,
                {
                    "schemaVersion": 1,
                    "baseRef": base_ref,
                    "baseCommit": base_commit,
                    "targetBranch": TARGET_BRANCH,
                    "selectedLaneBranches": selected,
                    "mergeReceipts": merge_receipts,
                    "prepared": False,
                    "authorityGranted": False,
                },
            )
            commit_if_dirty("ops: record fail-closed r7 source convergence conflict")
            git(
                "push",
                "--force-with-lease",
                "origin",
                f"HEAD:refs/heads/{TARGET_BRANCH}",
            )
            return 2

    argument_comment_repair = repair_argument_comment_blockers()
    generator_receipts = run_generators()
    lane_g_artifact_repair = repair_lane_g_shared_artifacts(selected)
    native_before = repair_native_bindings()
    metadata, lock_receipts = normalize_lockfile()
    if metadata is None:
        raise RuntimeError("workspace metadata could not be normalized")
    dependency_repair = repair_missing_local_dependencies(metadata)
    if dependency_repair["count"]:
        metadata, extra_lock_receipts = normalize_lockfile()
        lock_receipts.extend(extra_lock_receipts)
        if metadata is None:
            raise RuntimeError("workspace metadata failed after dependency repair")
    packages = canonical_hepta_packages(metadata)
    compile_receipts = run_prepare_compile_checks(packages)
    format_result = run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=2400,
    )
    native_after_format = repair_native_bindings()
    source_commit = commit_if_dirty(
        "chore: materialize parallel all-Hepta convergence r7"
    )
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET_BRANCH}")

    matrix = shard_matrix(packages, args.shards)
    prepared = (
        command_receipts_pass(generator_receipts)
        and command_receipts_pass(lock_receipts)
        and command_receipts_pass(compile_receipts)
        and format_result.passed
        and native_after_format.get("valid") is True
    )
    prepare_receipt = {
        "schemaVersion": 1,
        "runId": os.environ.get("GITHUB_RUN_ID", "local"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "baseRef": base_ref,
        "baseCommit": base_commit,
        "targetBranch": TARGET_BRANCH,
        "sourceCommit": source_commit,
        "selectedLaneBranches": selected,
        "mergeReceipts": merge_receipts,
        "argumentCommentRepair": argument_comment_repair,
        "generatorReceipts": generator_receipts,
        "laneGArtifactRepair": lane_g_artifact_repair,
        "nativeBindingBefore": native_before,
        "nativeBindingAfterFormat": native_after_format,
        "lockReceipts": lock_receipts,
        "dependencyRepair": dependency_repair,
        "compileReceipts": compile_receipts,
        "formatReceipt": format_result.receipt(),
        "canonicalHeptaPackageCount": len(packages),
        "canonicalHeptaPackages": packages,
        "matrix": matrix,
        "prepared": prepared,
        "authorityGranted": False,
    }
    write_json(PREPARE_RECEIPT, prepare_receipt)
    # Keep the tested source SHA stable. PREPARE.json is uploaded as an artifact;
    # it is intentionally not committed until the receipt-only finalize step.
    set_output("candidate_sha", source_commit)
    set_output("candidate_branch", TARGET_BRANCH)
    set_output("matrix", json.dumps(matrix, separators=(",", ":")))
    set_output("package_count", str(len(packages)))
    set_output("prepared", "true" if prepared else "false")
    return 0 if prepared else 3


def assert_exact_source(expected_sha: str) -> None:
    actual = git_text("rev-parse", "HEAD")
    if actual != expected_sha:
        raise RuntimeError(
            f"source identity mismatch: expected={expected_sha} actual={actual}"
        )
    if git("status", "--porcelain", check=False).output.strip():
        raise RuntimeError("qualification checkout is not clean")


def repository_gate(args: argparse.Namespace) -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    assert_exact_source(args.expected_sha)
    receipts: list[dict[str, Any]] = []
    for command in REPOSITORY_COMMANDS:
        if not (ROOT / command[1]).is_file():
            receipts.append({"command": list(command), "skipped": "missing executable"})
            continue
        receipts.append(run(command, timeout=2400).receipt())
    receipts.append(
        run(
            (
                "cargo",
                "fmt",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--all",
                "--",
                "--check",
            ),
            timeout=2400,
        ).receipt()
    )
    native = repair_native_bindings()
    clean_after_native_check = not git(
        "status", "--porcelain", check=False
    ).output.strip()
    diff_check = git("diff", "--check", check=False).receipt()
    passed = (
        command_receipts_pass(receipts)
        and native.get("valid") is True
        and native.get("updated") == 0
        and clean_after_native_check
        and diff_check.get("returnCode") == 0
    )
    receipt = {
        "schemaVersion": 1,
        "sourceCommit": args.expected_sha,
        "receipts": receipts,
        "nativeBinding": native,
        "cleanAfterNativeCheck": clean_after_native_check,
        "diffCheck": diff_check,
        "passed": passed,
        "authorityGranted": False,
    }
    write_json(REPOSITORY_RECEIPT, receipt)
    return 0 if passed else 3


def package_gate(args: argparse.Namespace) -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    assert_exact_source(args.expected_sha)
    packages = json.loads(args.packages_json)
    if not isinstance(packages, list) or not all(
        isinstance(value, str) for value in packages
    ):
        raise ValueError("packages-json must be a JSON string array")
    receipts: list[dict[str, Any]] = []
    for package in packages:
        test = run(
            (
                "cargo",
                "test",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                "-p",
                package,
                "--all-targets",
            ),
            timeout=7200,
        )
        receipts.append({"package": package, "gate": "test", **test.receipt()})
        lint = run(
            (
                "cargo",
                "clippy",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                "-p",
                package,
                "--all-targets",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ),
            timeout=7200,
        )
        receipts.append({"package": package, "gate": "clippy", **lint.receipt()})
    passed = command_receipts_pass(receipts)
    receipt = {
        "schemaVersion": 1,
        "sourceCommit": args.expected_sha,
        "shard": args.shard,
        "packages": packages,
        "receipts": receipts,
        "passed": passed,
        "authorityGranted": False,
    }
    write_json(OUT_ROOT / f"PACKAGE_GATE_{args.shard}.json", receipt)
    return 0 if passed else 3


def load_artifact_receipts(
    artifact_root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    receipts: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in artifact_root.rglob("*.json"):
        if path.name not in {
            "PREPARE.json",
            "REPOSITORY_GATE.json",
        } and not path.name.startswith("PACKAGE_GATE_"):
            continue
        try:
            value = read_json(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path}: {error}")
            continue
        if isinstance(value, dict):
            value["artifactPath"] = path.relative_to(artifact_root).as_posix()
            receipts.append(value)
    return receipts, errors


def external_gates() -> list[dict[str, Any]]:
    return [
        {
            "id": f"RDY-EXT-{index:03d}",
            "status": "external_open",
            "selfCertificationAllowed": False,
        }
        for index in range(1, 10)
    ]


def finalize(args: argparse.Namespace) -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    git("config", "user.name", "Hepta Parallel Finalizer")
    git("config", "user.email", "noreply@openai.com")
    actual = git_text("rev-parse", "HEAD")
    if actual != args.expected_sha:
        raise RuntimeError(
            f"finalize checkout must begin at qualified source: expected={args.expected_sha} actual={actual}"
        )
    artifact_root = Path(args.artifact_root)
    receipts, artifact_errors = load_artifact_receipts(artifact_root)
    prepare_receipts = [value for value in receipts if value.get("matrix") is not None]
    repository_receipts = [
        value for value in receipts if "nativeBinding" in value and "receipts" in value
    ]
    package_receipts = [
        value for value in receipts if "shard" in value and "packages" in value
    ]
    source_mismatches = [
        value.get("artifactPath", "unknown")
        for value in receipts
        if value.get("sourceCommit") not in {None, args.expected_sha}
    ]
    expected_shards = args.expected_shards
    package_coverage = sorted(
        {
            package
            for value in package_receipts
            for package in value.get("packages", [])
            if isinstance(package, str)
        }
    )
    prepare_package_set = sorted(
        {
            package
            for value in prepare_receipts
            for package in value.get("canonicalHeptaPackages", [])
            if isinstance(package, str)
        }
    )
    internal_passed = (
        args.prepare_result == "success"
        and args.repository_result == "success"
        and args.package_result == "success"
        and len(prepare_receipts) == 1
        and len(repository_receipts) == 1
        and len(package_receipts) == expected_shards
        and not artifact_errors
        and not source_mismatches
        and prepare_receipts[0].get("prepared") is True
        and repository_receipts[0].get("passed") is True
        and all(value.get("passed") is True for value in package_receipts)
        and package_coverage == prepare_package_set
        and len(package_coverage) >= 40
    )
    gates = external_gates()
    status = {
        "schemaVersion": 1,
        "runId": os.environ.get("GITHUB_RUN_ID", "local"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "targetBranch": TARGET_BRANCH,
        "qualifiedSourceCommit": args.expected_sha,
        "prepareJobResult": args.prepare_result,
        "repositoryJobResult": args.repository_result,
        "packageJobResult": args.package_result,
        "expectedShards": expected_shards,
        "observedPackageShards": len(package_receipts),
        "canonicalHeptaPackageCount": len(package_coverage),
        "canonicalHeptaPackages": package_coverage,
        "artifactErrors": artifact_errors,
        "sourceMismatches": source_mismatches,
        "repositoryInternalValidationPassed": internal_passed,
        "repositoryInternalGapsClosed": internal_passed,
        "externalAuthorityGates": gates,
        "externalAuthorityGatesRetained": True,
        "allGapsClosed": False,
        "authorityGranted": False,
        "productionActivation": False,
        "modelInvocationAuthority": False,
        "providerDispatchAuthority": False,
        "productionWriterAuthorityAdded": False,
        "selection": False,
        "promotion": False,
        "release": False,
    }
    write_json(FINAL_STATUS, status)
    write_json(
        OUT_ROOT / "EXTERNAL_GATE_HANDOFF.json",
        {
            "schemaVersion": 1,
            "qualifiedSourceCommit": args.expected_sha,
            "selfCertificationAllowed": False,
            "authorityGranted": False,
            "gates": gates,
        },
    )
    for value in receipts:
        path_name = Path(value.get("artifactPath", "receipt.json")).name
        write_json(OUT_ROOT / "receipts" / path_name, value)
    failed_commands: list[dict[str, Any]] = []
    for value in receipts:
        for receipt in value.get("receipts", []):
            if isinstance(receipt, dict) and receipt.get("returnCode") not in {None, 0}:
                failed_commands.append(receipt)
    lines = [
        "# Hepta parallel all-package convergence r7",
        "",
        f"- qualified source: `{args.expected_sha}`",
        f"- target branch: `{TARGET_BRANCH}`",
        f"- canonical Hepta packages covered: `{len(package_coverage)}`",
        f"- package shards: `{len(package_receipts)}/{expected_shards}`",
        f"- repository-internal validation: `{'PASS' if internal_passed else 'BLOCKED'}`",
        "- external independent-authority gates: `9 retained open`",
        "- self-issued production/model/provider/writer/selection/promotion/release authority: `false`",
        "",
        "## Remaining repository-internal failures",
        "",
    ]
    if failed_commands:
        for receipt in failed_commands:
            lines.append(
                f"- `{shlex.join(receipt.get('command', []))}` returned "
                f"`{receipt.get('returnCode')}`; output sha256 "
                f"`{receipt.get('outputSha256')}`."
            )
    elif internal_passed:
        lines.append(
            "- none detected by exact-source, closed-world, document, format, test and lint gates"
        )
    else:
        lines.extend(
            [
                f"- prepare job: `{args.prepare_result}`",
                f"- repository job: `{args.repository_result}`",
                f"- package matrix job: `{args.package_result}`",
                f"- artifact errors: `{len(artifact_errors)}`",
                f"- source mismatches: `{len(source_mismatches)}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Non-self-certifiable handoff",
            "",
            "Independent semantic review, real runtime/model identity, future-time validity, "
            "target-host or hardware qualification, remote-owner consent, operator acceptance, "
            "production canary, selection/promotion, and release authorization remain explicit "
            "external gates. This receipt-only commit does not satisfy them.",
            "",
        ]
    )
    (OUT_ROOT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    receipt_commit = commit_if_dirty(
        "docs: bind parallel all-Hepta r7 qualification receipts"
    )
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET_BRANCH}")
    set_output("receipt_commit", receipt_commit)
    set_output("internal_passed", "true" if internal_passed else "false")
    return 0 if internal_passed else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--shards", type=int, default=8)
    prepare_parser.set_defaults(function=prepare)

    repository_parser = subparsers.add_parser("repository-gate")
    repository_parser.add_argument("--expected-sha", required=True)
    repository_parser.set_defaults(function=repository_gate)

    package_parser = subparsers.add_parser("package-gate")
    package_parser.add_argument("--expected-sha", required=True)
    package_parser.add_argument("--shard", type=int, required=True)
    package_parser.add_argument("--packages-json", required=True)
    package_parser.set_defaults(function=package_gate)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--expected-sha", required=True)
    finalize_parser.add_argument("--artifact-root", required=True)
    finalize_parser.add_argument("--expected-shards", type=int, required=True)
    finalize_parser.add_argument("--prepare-result", required=True)
    finalize_parser.add_argument("--repository-result", required=True)
    finalize_parser.add_argument("--package-result", required=True)
    finalize_parser.set_defaults(function=finalize)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_GLOBAL_FINALIZER_R7_ERROR: {error}", file=sys.stderr)
        raise

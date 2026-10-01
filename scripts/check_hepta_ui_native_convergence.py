#!/usr/bin/env python3
"""Fail-closed structural qualification for the immutable ui.native candidate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")

FORBIDDEN_WORKFLOWS = {
    "hepta-ui-native-acceptance-proposal.yml",
    "hepta-ui-native-current-source.yml",
    "hepta-ui-native-fix-materializer.yml",
    "hepta-ui-native-integrate-20260928.yml",
    "hepta-ui-native-operational-materialize.yml",
    "hepta-ui-native-projections.yml",
    "hepta-ui-native-qualified-integration.yml",
    "hepta-ui-native-remediation-format.yml",
    "hepta-ui-native-remediation.yml",
    "hepta-ui-native-slim-materializer.yml",
    "hepta-ui-native-source-integrity.yml",
    "ui-native-direct-apply-once.yml",
    "ui-native-remediation-apply-once.yml",
    "ui-native-source-export-pr.yml",
    "ui-native-wal-index-apply-once.yml",
    "ui-native-wal-index-export-pr.yml",
}
ALLOWED_WORKFLOW = "ui-native-qualification.yml"

STATE_FILES = (
    "apps/hepta-native/CURRENT_SOURCE.json",
    "apps/hepta-native/CANDIDATE.json",
    "apps/hepta-native/STORAGE_BUDGETS.json",
    "docs/modules/ui.native/CURRENT_SOURCE.json",
    "docs/modules/ui.native/CURRENT_DELIVERY.json",
    "docs/modules/ui.native/IMPLEMENTATION_MAP.json",
    "docs/modules/ui.native/QUALIFICATION_MANIFEST.json",
)

IMPLEMENTATION_PATHS = (
    "apps/hepta-native/src",
    "apps/hepta-native/tests",
    "apps/hepta-native/Cargo.toml",
    "apps/hepta-native/Cargo.lock",
    "apps/hepta-native/build.rs",
    "apps/hepta-native/rust-toolchain.toml",
    "apps/hepta-native/portal",
    "apps/hepta-native/packaging",
    "apps/hepta-native/tools/package_unsigned.py",
    "apps/hepta-native/tools/archive_safety.py",
    "codex-rs/hepta-native-gateway",
    "codex-rs/hepta-private-state",
    "codex-rs/keyring-store",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/hepta-contracts",
    ".cargo",
    "codex-rs/.cargo",
    "apps/hepta-native/.cargo",
)
QUALIFIED_MANIFESTS = (
    "apps/hepta-native/Cargo.toml",
    "codex-rs/hepta-native-gateway/Cargo.toml",
    "codex-rs/hepta-contracts/Cargo.toml",
    "codex-rs/hepta-private-state/Cargo.toml",
    "codex-rs/utils/private-state/Cargo.toml",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_json(path: str) -> dict[str, Any]:
    value = json.loads(_read(path))
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def _walk(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="strict"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_success(*args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _cargo_manifest(path: Path) -> dict[str, Any]:
    _require(
        path.is_file() and not path.is_symlink(),
        f"unsafe or missing Cargo manifest: {path}",
    )
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _repository_path(path: Path) -> str:
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise RuntimeError(
            f"local Cargo dependency escapes the repository: {path}"
        ) from error
    _require(
        not any(
            parent.is_symlink()
            for parent in (path, *path.parents)
            if parent.is_relative_to(ROOT)
        ),
        f"local Cargo dependency uses a symlink: {path}",
    )
    return relative.as_posix()


def _workspace_manifest(path: Path, manifest: dict[str, Any]) -> Path | None:
    if "workspace" in manifest:
        return path
    explicit = manifest.get("package", {}).get("workspace")
    if explicit is not None:
        _require(isinstance(explicit, str), "Cargo package.workspace must be a path")
        workspace = path.parent / explicit / "Cargo.toml"
        _require(
            "workspace" in _cargo_manifest(workspace),
            "explicit Cargo workspace is missing",
        )
        _repository_path(workspace)
        return workspace
    for parent in path.parent.parents:
        try:
            parent.relative_to(ROOT)
        except ValueError:
            break
        candidate = parent / "Cargo.toml"
        if candidate.is_file() and "workspace" in _cargo_manifest(candidate):
            return candidate
    return None


def local_cargo_dependency_paths() -> tuple[str, ...]:
    """Resolve local paths for the exact app and owner Cargo subjects.

    Dev dependencies enter only for packages tested with --all-targets. Every
    target's normal/build dependencies and optional dependencies are included,
    because qualification uses all features and all three operating systems.
    """
    seeds = {
        ROOT / relative
        for relative in QUALIFIED_MANIFESTS
        if (ROOT / relative).is_file()
    }
    queue = [(path, True) for path in seeds]
    visited: dict[Path, bool] = {}
    paths: set[str] = set()
    while queue:
        path, include_dev = queue.pop()
        _repository_path(path)
        path = path.resolve(strict=True)
        if path in visited and (visited[path] or not include_dev):
            continue
        visited[path] = include_dev
        paths.add(_repository_path(path.parent))
        manifest = _cargo_manifest(path)
        workspace_path = _workspace_manifest(path, manifest)
        workspace = (
            _cargo_manifest(workspace_path) if workspace_path is not None else {}
        )
        if workspace_path is not None:
            paths.add(_repository_path(workspace_path))
        sections = ("dependencies", "build-dependencies") + (
            ("dev-dependencies",) if include_dev else ()
        )
        for table in [manifest, *manifest.get("target", {}).values()]:
            for section in sections:
                for name, specification in table.get(section, {}).items():
                    if not isinstance(specification, dict):
                        continue
                    base = path.parent
                    if specification.get("workspace") is True:
                        _require(
                            workspace_path is not None,
                            f"{path}: dependency {name} has no workspace",
                        )
                        inherited = (
                            workspace.get("workspace", {})
                            .get("dependencies", {})
                            .get(name)
                        )
                        _require(
                            inherited is not None,
                            f"{path}: workspace dependency {name} is missing",
                        )
                        specification = inherited
                        base = workspace_path.parent
                    if isinstance(specification, dict) and "path" in specification:
                        dependency = base / specification["path"]
                        _repository_path(dependency)
                        queue.append(
                            (
                                dependency / "Cargo.toml",
                                dependency / "Cargo.toml" in seeds,
                            )
                        )
        # Local registry/git overrides may influence any qualified root. Freeze
        # every declared local override, even when it currently resolves unused.
        for owner_path, owner in ((path, manifest), (workspace_path, workspace)):
            if owner_path is None:
                continue
            for override in [
                *owner.get("patch", {}).values(),
                owner.get("replace", {}),
            ]:
                for specification in override.values():
                    if isinstance(specification, dict) and "path" in specification:
                        dependency = owner_path.parent / specification["path"]
                        _repository_path(dependency)
                        queue.append((dependency / "Cargo.toml", False))
    return tuple(sorted(paths))


def implementation_paths() -> tuple[str, ...]:
    # The standalone app permits evidence/navigation continuations beside its
    # product source, so retain its explicit operational paths above.
    dependencies = set(local_cargo_dependency_paths()) - {"apps/hepta-native"}
    return tuple(sorted(set(IMPLEMENTATION_PATHS) | dependencies))


def check_dependency_workflow_filters(workflow: str) -> None:
    _require("    paths:\n" in workflow, "qualification path filters are missing")
    filters = workflow.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
    patterns = {
        line.strip().removeprefix("- ").strip("\"'")
        for line in filters.splitlines()
        if line.strip().startswith("- ")
    }
    dependencies = (
        *local_cargo_dependency_paths(),
        "tools/ui-native-projections",
        ".cargo",
        "codex-rs/.cargo",
    )
    for path in dependencies:
        expected = path if path.endswith("Cargo.toml") else f"{path}/**"
        parent_patterns = {
            f"{parent.as_posix()}/**"
            for parent in Path(path).parents
            if parent.as_posix() != "."
        }
        _require(
            expected in patterns
            or bool(parent_patterns & patterns)
            or "**" in patterns,
            f"qualification workflow does not trigger for dependency {path}",
        )


def check_frozen_implementation(implementation: str) -> None:
    paths = implementation_paths()
    _require(
        _git_success("diff", "--quiet", implementation, "HEAD", "--", *paths),
        "metadata continuation changes product implementation after the frozen source",
    )
    _require(
        _git_success("diff", "--quiet", "HEAD", "--", *paths),
        "product implementation has staged or working-tree drift",
    )
    untracked = _git_value("ls-files", "--others", "--exclude-standard", "--", *paths)
    _require(untracked == "", "product implementation has untracked source files")
    check_frozen_storage_budgets(implementation)


def check_job_environment_contexts(workflow: str) -> None:
    """Check job env expressions before GitHub schedules a runner.

    This workflow uses two-space mapping indentation. Runner, step and env
    contexts are available inside steps, but not in job-level env values.
    """
    allowed = {"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"}
    in_jobs = False
    job = None
    environment: list[str] = []
    in_environment = False

    def validate() -> None:
        pattern = r"\$\{\{((?:'(?:[^']|'')*'|[^'}]|\}(?!\}))*?)\}\}"
        for match in re.finditer(pattern, "\n".join(environment), re.DOTALL):
            # Expressions use single-quoted string literals, with doubled
            # quotes for escaping. Text in a literal names no context.
            expression = re.sub(r"'(?:[^']|'')*'", "", match.group(1))
            for token in re.finditer(r"[A-Za-z_][A-Za-z0-9_-]*", expression):
                before = expression[: token.start()].rstrip()
                after = expression[token.end() :].lstrip()
                name = token.group().lower()
                if (
                    before.endswith(".")
                    or after.startswith("(")
                    or name in {"true", "false", "null"}
                ):
                    continue
                _require(
                    name in allowed,
                    f"job {job} env uses unavailable context {token.group()!r}",
                )

    for line in workflow.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indentation = len(line) - len(stripped)
        if in_environment and indentation <= 4:
            validate()
            environment = []
            in_environment = False
        if indentation == 0:
            # A trailing YAML comment or whitespace does not change this
            # block mapping header. Quoted inline scalar values are not headers.
            in_jobs = re.fullmatch(r"jobs:(?:[ \t]+(?:#.*)?)?", stripped) is not None
            job = None
        elif in_jobs and indentation == 2:
            job = stripped.split(":", 1)[0]
        elif (
            in_jobs
            and job is not None
            and indentation == 4
            and stripped.startswith("env:")
        ):
            in_environment = True
            environment.append(stripped[4:])
        elif in_environment:
            environment.append(stripped)
    if in_environment:
        validate()


def check_frozen_storage_budgets(implementation: str) -> None:
    # This JSON is embedded by include_str! in the qualification executable.
    # Only the two source-navigation anchors may continue after its source freeze.
    relative = "apps/hepta-native/STORAGE_BUDGETS.json"
    path = ROOT / relative
    frozen_exists = _git_success("cat-file", "-e", f"{implementation}:{relative}")
    if not frozen_exists and not path.exists():
        return  # Small isolated source fixtures need not define storage budgets.
    _require(
        frozen_exists and path.is_file() and not path.is_symlink(),
        "storage budget contract is missing from the frozen or current source",
    )
    frozen = json.loads(_git_value("show", f"{implementation}:{relative}") or "null")
    current = _load_json(relative)
    _require(
        isinstance(frozen, dict), "frozen storage budget contract is not an object"
    )
    navigation = {"implementationSourceSha", "implementationSourceTree"}
    _require(
        {key: value for key, value in frozen.items() if key not in navigation}
        == {key: value for key, value in current.items() if key not in navigation},
        "storage budget contract changed after the frozen source",
    )


def check_repository() -> dict[str, Any]:
    workflows = ROOT / ".github" / "workflows"
    for name in FORBIDDEN_WORKFLOWS:
        _require(
            not (workflows / name).exists(), f"retired writer workflow remains: {name}"
        )

    ui_native_workflows = sorted(
        path.name for path in workflows.glob("*ui-native*.yml")
    )
    _require(
        ui_native_workflows == [ALLOWED_WORKFLOW],
        f"unexpected ui.native workflow set: {ui_native_workflows}",
    )
    workflow = _read(f".github/workflows/{ALLOWED_WORKFLOW}")
    check_job_environment_contexts(workflow)
    check_dependency_workflow_filters(workflow)
    for forbidden in ("contents: write", "git push", "git commit", "git apply"):
        _require(
            forbidden not in workflow, f"qualification workflow contains {forbidden!r}"
        )
    _require(
        "persist-credentials: false" in workflow, "checkout credentials are persisted"
    )
    _require(
        "cancel-in-progress: false" in workflow, "exact-source run may be cancelled"
    )
    _require("exact head" in workflow, "exact-head platform subjects are missing")
    _require(
        "ordered-parent merge" in workflow, "ordered-parent merge subjects are missing"
    )

    ci_root = ROOT / ".ci"
    if ci_root.exists():
        capsules = sorted(
            str(path.relative_to(ROOT)) for path in ci_root.glob("ui-native*")
        )
        _require(not capsules, f"ui.native patch capsules remain: {capsules}")

    journal = _read("apps/hepta-native/src/journal.rs")
    storage = _read("apps/hepta-native/src/journal_storage.rs")
    retirement = _read("apps/hepta-native/src/retirement.rs")
    platform = _read("apps/hepta-native/src/platform.rs")

    source_contracts = {
        "journal-v7": 'const JOURNAL_SCHEMA_V7: &str = "hepta.native-operation-journal.v7";',
        "wal-v1": 'const WAL_SCHEMA: &str = "hepta.native-operation-wal.v1";',
        "active-index": "operation_index: HashMap<OperationKey, usize>",
        "wal-magic": 'const WAL_MAGIC: &[u8; 8] = b"HPTNWAL1";',
        "retirement-v3": 'const HEAD_SCHEMA: &str = "hepta.native-retirement.v3";',
        "retirement-index-v1": 'const INDEX_SCHEMA: &str = "hepta.native-retirement-index.v1";',
        "retirement-bucket-v1": 'const BUCKET_SCHEMA: &str = "hepta.native-retirement-index-bucket.v1";',
    }
    joined = "\n".join((journal, storage, retirement))
    for name, token in source_contracts.items():
        _require(token in joined, f"missing source contract {name}: {token}")

    budgets = _load_json("apps/hepta-native/STORAGE_BUDGETS.json")
    structural = budgets.get("structural")
    _require(isinstance(structural, dict), "storage structural budgets are missing")
    _require(
        budgets.get("status") == "provisional-unqualified",
        "budgets claim qualification",
    )
    _require(
        budgets.get("measurements") is None, "unreviewed measurements are embedded"
    )
    exact_constants = {
        "maxActiveRecords": "const MAX_OPERATION_RECORDS: usize = 4096;",
        "maxSnapshotBytes": "const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;",
        "maxWalBytes": "const MAX_WAL_BYTES: u64 = 4 * 1024 * 1024;",
        "maxWalFrameBytes": "const MAX_WAL_FRAME_BYTES: u64 = 128 * 1024;",
        "checkpointWalEntries": "const WAL_CHECKPOINT_ENTRIES: usize = 128;",
        "retirementSegmentEntries": "const SEGMENT_ENTRIES: usize = 1024;",
        "retirementSegmentBytes": "const SEGMENT_BYTES: u64 = 512 * 1024;",
        "retirementRecordBytes": "const RECORD_BYTES: u64 = 32 * 1024;",
        "retirementIndexBucketEntries": "const MAX_INDEX_BUCKET_ENTRIES: usize = 65_536;",
        "retirementIndexCacheEntries": "const MAX_INDEX_CACHE_ENTRIES: usize = 65_536;",
    }
    for key, token in exact_constants.items():
        _require(key in structural, f"storage budget {key} is missing")
        _require(token in joined, f"source constant for {key} drifted")

    _require(
        'Command::new("/usr/bin/osascript")' in platform,
        "macOS launcher is not absolute",
    )
    _require(
        'Command::new("/usr/bin/notify-send")' in platform,
        "Linux launcher is not absolute",
    )
    _require(
        'Command::new("osascript")' not in platform, "PATH-resolved osascript remains"
    )
    _require(
        'Command::new("notify-send")' not in platform,
        "PATH-resolved notify-send remains",
    )
    _require("command.env_clear();" in platform, "launcher environment is not cleared")

    anchors: dict[str, str] = {}
    trees: dict[str, str] = {}
    for relative in STATE_FILES:
        state = _load_json(relative)
        anchor = state.get("implementationSourceSha")
        tree = state.get("implementationSourceTree")
        _require(
            isinstance(anchor, str) and SHA1_RE.fullmatch(anchor) is not None,
            f"{relative} lacks a valid implementationSourceSha",
        )
        _require(
            isinstance(tree, str) and SHA1_RE.fullmatch(tree) is not None,
            f"{relative} lacks a valid implementationSourceTree",
        )
        anchors[relative] = anchor
        trees[relative] = tree
        for key, value in _walk(state):
            if key in {
                "productionQualified",
                "deploymentQualified",
                "releaseAuthorized",
            }:
                _require(value is False, f"{relative} falsely sets {key}={value!r}")

    unique_anchors = sorted(set(anchors.values()))
    unique_trees = sorted(set(trees.values()))
    _require(len(unique_anchors) == 1, f"state anchors disagree: {anchors}")
    _require(len(unique_trees) == 1, f"state trees disagree: {trees}")
    implementation = unique_anchors[0]
    implementation_tree = unique_trees[0]
    _require(
        _git_success("cat-file", "-e", f"{implementation}^{{commit}}"),
        "implementation source commit is unavailable",
    )
    _require(
        _git_value("rev-parse", f"{implementation}^{{tree}}") == implementation_tree,
        "implementation source tree does not match its commit",
    )
    check_frozen_implementation(implementation)

    head = _git_value("rev-parse", "HEAD")
    tree = _git_value("rev-parse", "HEAD^{tree}")
    parents = (_git_value("show", "-s", "--format=%P", "HEAD") or "").split()
    return {
        "schema": "hepta.ui-native-source-evidence.v1",
        "status": "structural-pass",
        "implementationSourceSha": implementation,
        "implementationSourceTree": implementation_tree,
        "repositoryHead": head,
        "repositoryTree": tree,
        "orderedParents": parents,
        "workflow": ALLOWED_WORKFLOW,
        "retiredWorkflowCount": len(FORBIDDEN_WORKFLOWS),
        "sourceContracts": sorted(source_contracts),
        "localCargoDependencyPaths": list(local_cargo_dependency_paths()),
        "limitations": [
            "structural evidence is not physical-platform acceptance",
            "performance budgets remain unqualified until measured artifacts are attached",
            "release flags remain false pending independent review",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit", type=Path)
    args = parser.parse_args()
    evidence = check_repository()
    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.emit is not None:
        args.emit.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

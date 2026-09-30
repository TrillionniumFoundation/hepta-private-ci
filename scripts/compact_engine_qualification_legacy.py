#!/usr/bin/env python3
"""Closed-world qualification helpers for compact.engine.

This module deliberately separates three facts:

* source navigation: every mapped implementation/test path is real and every
  Rust test source is reachable from a crate test root;
* one-run pre-merge readiness: all required lanes belong to one source SHA,
  workflow run and attempt;
* production qualification: remains false until a final merge SHA and an
  explicit post-merge success receipt are supplied.

The emitted readiness manifest is fail-closed. Missing, queued, skipped,
cancelled, stale or cross-attempt evidence can never be promoted by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

MAP_PATH = Path("docs/modules/compact.engine/IMPLEMENTATION_MAP.json")
CRATE_ROOT = Path("codex-rs/hepta-compact-engine")
AGENTD_HOST = Path("codex-rs/hepta-agentd/src/compaction_checkpoint_host.rs")

MIGRATION_INPUTS = (
    CRATE_ROOT / "src/compaction_schema.sql",
    CRATE_ROOT / "src/compaction_schema_hardening.sql",
    CRATE_ROOT / "src/durable.rs",
    CRATE_ROOT / "src/mutation_guard.rs",
    CRATE_ROOT / "src/recovery.rs",
)

DOCUMENTATION_INPUTS = (
    Path("docs/modules/compact.engine/TECHNICAL.md"),
    Path("docs/modules/compact.engine/RECOVERY_PROTOCOL_V2.md"),
    Path("docs/modules/compact.engine/REMEDIATION_20260928.md"),
    Path("qualification/module-execution-dossiers/detail/compact.engine.md"),
)

QUALIFICATION_PROFILE_INPUTS = (
    Path(".github/workflows/compact-engine-qualification.yml"),
    Path(".github/workflows/compact-engine-capacity.yml"),
    Path("scripts/compact_engine_qualification.py"),
    Path("scripts/test_compact_engine_qualification.py"),
)

REQUIRED_LANES = (
    "source_snapshot",
    "exact_head",
    "synthetic_merge",
    "capacity",
)

_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_EXTERNAL_MOD_RE = re.compile(
    r"(?ms)(?P<attrs>(?:\s*#\s*\[[^\]]+\]\s*)*)"
    r"(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;"
)
_PATH_ATTR_RE = re.compile(r"#\s*\[\s*path\s*=\s*\"([^\"]+)\"\s*\]")


class QualificationError(ValueError):
    """A fail-closed qualification input error."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    try:
        completed = subprocess.run(
            ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise QualificationError(f"git {' '.join(args)} failed: {detail}") from exc
    return completed.stdout.strip()


def checked_repo_path(root: Path, relative: str | Path) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"non-canonical repository path: {relative}")
    resolved_root = root.resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise QualificationError(f"repository path escapes root: {relative}") from exc
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise QualificationError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def combined_hash(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    normalized = sorted({Path(path).as_posix() for path in paths})
    if not normalized:
        raise QualificationError("combined hash input set is empty")
    for relative in normalized:
        path = checked_repo_path(root, relative)
        if not path.is_file():
            raise QualificationError(f"hash input is missing or not a file: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def directory_hash(directory: Path) -> str:
    if not directory.is_dir():
        raise QualificationError(f"artifact directory is missing: {directory}")
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise QualificationError(f"artifact directory is empty: {directory}")
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(directory).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _module_base(source: Path) -> Path:
    if source.name in {"lib.rs", "main.rs", "mod.rs"}:
        return source.parent
    return source.parent / source.stem


def rust_test_graph(root: Path, crate_root: Path = CRATE_ROOT) -> set[str]:
    crate = checked_repo_path(root, crate_root)
    roots = [crate / "src/lib.rs"]
    tests_dir = crate / "tests"
    if tests_dir.is_dir():
        roots.extend(sorted(tests_dir.glob("*.rs")))
    queue = [path for path in roots if path.is_file()]
    reachable: set[Path] = set()
    while queue:
        source = queue.pop()
        source = source.resolve()
        if source in reachable:
            continue
        reachable.add(source)
        text = source.read_text(encoding="utf-8")
        for match in _EXTERNAL_MOD_RE.finditer(text):
            attrs = match.group("attrs") or ""
            name = match.group("name")
            path_match = _PATH_ATTR_RE.search(attrs)
            if path_match:
                candidates = [source.parent / path_match.group(1)]
            else:
                base = _module_base(source)
                candidates = [base / f"{name}.rs", base / name / "mod.rs"]
            existing = [candidate.resolve() for candidate in candidates if candidate.is_file()]
            if len(existing) > 1:
                raise QualificationError(
                    f"ambiguous Rust module {name} declared by {source.relative_to(root)}"
                )
            queue.extend(existing)
    return {path.relative_to(root.resolve()).as_posix() for path in reachable}


def _symbol_leaf(symbol: str) -> str:
    leaf = symbol.rsplit("::", 1)[-1]
    leaf = leaf.split("<", 1)[0]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", leaf):
        raise QualificationError(f"unsupported native symbol identity: {symbol}")
    return leaf


def _require_symbol(path: Path, symbol: str) -> None:
    text = path.read_text(encoding="utf-8")
    leaf = _symbol_leaf(symbol)
    if "::" in symbol:
        pattern = rf"\bfn\s+{re.escape(leaf)}\s*\("
    else:
        pattern = (
            rf"\b(?:fn|struct|enum|trait|type|const|static)\s+"
            rf"{re.escape(leaf)}\b"
        )
    if re.search(pattern, text) is None:
        raise QualificationError(f"native symbol {symbol} is absent from {path}")


def verify_implementation_map(root: Path, output: Path | None = None) -> dict[str, Any]:
    map_path = checked_repo_path(root, MAP_PATH)
    row = load_json(map_path)
    if row.get("schema") != "hepta.module-implementation-map.v3":
        raise QualificationError("compact.engine implementation map has the wrong schema")
    if row.get("module") != "compact.engine":
        raise QualificationError("implementation map does not describe compact.engine")
    operations = row.get("operations")
    if not isinstance(operations, list) or not operations:
        raise QualificationError("implementation map operations must be non-empty")

    reachable = rust_test_graph(root)
    mapped_tests: set[str] = set()
    mapped_sources: set[str] = set()
    symbols: list[str] = []

    for operation in operations:
        if not isinstance(operation, dict):
            raise QualificationError("implementation map operation must be an object")
        source_value = operation.get("sourcePath")
        symbol = operation.get("nativeSymbol")
        if not isinstance(source_value, str) or not source_value:
            raise QualificationError("every compact.engine operation needs sourcePath")
        if not isinstance(symbol, str) or not symbol:
            raise QualificationError("every compact.engine operation needs nativeSymbol")
        source = checked_repo_path(root, source_value)
        if not source.is_file():
            raise QualificationError(f"mapped source path is missing: {source_value}")
        if operation.get("sourcePathExists") is False:
            raise QualificationError(f"mapped source is present but sourcePathExists=false: {source_value}")
        _require_symbol(source, symbol)
        mapped_sources.add(Path(source_value).as_posix())
        symbols.append(symbol)

        tests = operation.get("tests", [])
        if not isinstance(tests, list):
            raise QualificationError(f"tests must be a list for {operation.get('operation')}")
        for raw_test in tests:
            if not isinstance(raw_test, str) or not raw_test:
                raise QualificationError("test evidence must be a non-empty path string")
            test_path_value = raw_test
            test_symbol: str | None = None
            marker = ".rs::"
            if marker in raw_test:
                prefix, test_symbol = raw_test.split(marker, 1)
                test_path_value = prefix + ".rs"
            test_path = checked_repo_path(root, test_path_value)
            if not test_path.is_file():
                raise QualificationError(f"mapped test evidence is missing: {test_path_value}")
            normalized = Path(test_path_value).as_posix()
            if normalized.endswith(".rs") and normalized.startswith(CRATE_ROOT.as_posix() + "/"):
                if normalized not in reachable:
                    raise QualificationError(
                        f"Rust test source is not reachable from the crate test graph: {normalized}"
                    )
                mapped_tests.add(normalized)
            if test_symbol is not None:
                leaf = test_symbol.rsplit("::", 1)[-1]
                text = test_path.read_text(encoding="utf-8")
                if re.search(rf"\bfn\s+{re.escape(leaf)}\s*\(", text) is None:
                    raise QualificationError(
                        f"mapped Rust test identity is absent: {raw_test}"
                    )

        delegates = operation.get("delegatedCallees", [])
        if not isinstance(delegates, list):
            raise QualificationError("delegatedCallees must be a list")
        for delegate in delegates:
            if not isinstance(delegate, str) or not delegate:
                raise QualificationError("delegated callee must be a non-empty string")
            if "/" in delegate or delegate.endswith(".rs"):
                delegate_path = checked_repo_path(root, delegate)
                if not delegate_path.exists():
                    raise QualificationError(f"mapped delegated source is missing: {delegate}")

    orphan_test_sources = sorted(
        path.relative_to(root.resolve()).as_posix()
        for path in checked_repo_path(root, CRATE_ROOT / "src").glob("*_tests.rs")
        if path.resolve().relative_to(root.resolve()).as_posix() not in reachable
    )
    if orphan_test_sources:
        raise QualificationError(
            "crate contains unreachable Rust test sources: " + ", ".join(orphan_test_sources)
        )

    report = {
        "schema": "hepta.compact-engine-implementation-map-verification.v1",
        "module": "compact.engine",
        "implementation_map": MAP_PATH.as_posix(),
        "mapped_source_count": len(mapped_sources),
        "mapped_test_source_count": len(mapped_tests),
        "reachable_rust_source_count": len(reachable),
        "mapped_symbols": sorted(symbols),
        "mapped_sources": sorted(mapped_sources),
        "mapped_test_sources": sorted(mapped_tests),
        "orphan_test_sources": [],
        "verified": True,
    }
    if output is not None:
        dump_json(output, report)
    return report


@dataclass(frozen=True)
class LaneEvidence:
    name: str
    result: str
    artifact_name: str | None
    identity: dict[str, Any] | None
    success_marker: bool
    artifact_hash: str | None
    errors: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        return self.result == "success" and self.success_marker and not self.errors

    def as_json(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "artifact_name": self.artifact_name,
            "success_marker": self.success_marker,
            "artifact_hash": self.artifact_hash,
            "identity": self.identity,
            "errors": list(self.errors),
            "succeeded": self.succeeded,
        }


def _one_artifact(artifacts: Path, prefix: str) -> tuple[str | None, Path | None, list[str]]:
    matches = sorted(
        path for path in artifacts.iterdir() if path.is_dir() and path.name.startswith(prefix)
    ) if artifacts.is_dir() else []
    if len(matches) != 1:
        return None, None, [f"expected exactly one {prefix} artifact, found {len(matches)}"]
    return matches[0].name, matches[0], []


def _load_lane(
    artifacts: Path,
    *,
    name: str,
    prefix: str,
    result: str,
    source_sha: str,
    run_id: str,
    attempt_id: str,
) -> LaneEvidence:
    artifact_name, directory, errors = _one_artifact(artifacts, prefix)
    identity: dict[str, Any] | None = None
    success = False
    artifact_digest: str | None = None
    if directory is not None:
        try:
            artifact_digest = directory_hash(directory)
        except QualificationError as exc:
            errors.append(str(exc))
        identity_path = directory / "identity.json"
        if not identity_path.is_file():
            errors.append(f"{name} artifact has no identity.json")
        else:
            try:
                identity = load_json(identity_path)
            except QualificationError as exc:
                errors.append(str(exc))
        success_path = directory / "success.json"
        if not success_path.is_file():
            errors.append(f"{name} artifact has no success marker")
        else:
            try:
                success_row = load_json(success_path)
            except QualificationError as exc:
                errors.append(str(exc))
            else:
                success = success_row.get("success") is True
                if not success:
                    errors.append(f"{name} success marker is not true")
    if identity is not None:
        expected = {
            "lane": name,
            "source_head_sha": source_sha,
            "frozen_source_sha": source_sha,
            "workflow_run_id": run_id,
            "attempt_id": attempt_id,
        }
        for field, value in expected.items():
            if str(identity.get(field, "")) != value:
                errors.append(
                    f"{name} {field} mismatch: {identity.get(field)!r} != {value!r}"
                )
    if result not in {"success", "failure", "cancelled", "skipped"}:
        errors.append(f"{name} has non-terminal result {result!r}")
    return LaneEvidence(
        name=name,
        result=result,
        artifact_name=artifact_name,
        identity=identity,
        success_marker=success,
        artifact_hash=artifact_digest,
        errors=tuple(errors),
    )


def _validate_sha(name: str, value: str, errors: list[str], *, optional: bool = False) -> str | None:
    if not value:
        if not optional:
            errors.append(f"{name} is missing")
        return None
    if _SHA_RE.fullmatch(value) is None:
        errors.append(f"{name} is not a 40-character lowercase SHA-1")
        return None
    return value


def _test_inputs(root: Path) -> list[Path]:
    tracked = run_git(root, "ls-files").splitlines()
    result: list[Path] = []
    crate_prefix = CRATE_ROOT.as_posix() + "/"
    for raw in tracked:
        path = Path(raw)
        if raw.startswith(crate_prefix) and raw.endswith(".rs"):
            name = path.name
            if "test" in name or raw.startswith((CRATE_ROOT / "tests").as_posix() + "/"):
                result.append(path)
    result.extend([AGENTD_HOST, Path("scripts/test_compact_engine_qualification.py")])
    return sorted(set(result))


def build_readiness_manifest(
    root: Path,
    artifacts: Path,
    output: Path,
    *,
    source_head_sha: str,
    frozen_source_sha: str,
    workflow_sha: str,
    github_merge_sha: str,
    final_merge_sha: str,
    workflow_run_id: str,
    attempt_id: str,
    event_name: str,
    source_result: str,
    qualify_result: str,
    capacity_result: str,
    postmerge_result: str,
) -> dict[str, Any]:
    errors: list[str] = []
    source_head = _validate_sha("source_head_sha", source_head_sha, errors)
    frozen_source = _validate_sha("frozen_source_sha", frozen_source_sha, errors)
    workflow = _validate_sha("workflow_sha", workflow_sha, errors)
    github_merge = _validate_sha(
        "github_merge_sha", github_merge_sha, errors, optional=event_name != "pull_request"
    )
    final_merge = _validate_sha("final_merge_sha", final_merge_sha, errors, optional=True)
    if source_head is not None and frozen_source is not None and source_head != frozen_source:
        errors.append("frozen_source_sha differs from source_head_sha")
    if not workflow_run_id.isdigit():
        errors.append("workflow_run_id must be numeric")
    if not attempt_id.isdigit():
        errors.append("attempt_id must be numeric")

    lanes = {
        "source_snapshot": _load_lane(
            artifacts,
            name="source_snapshot",
            prefix="compact-engine-source-",
            result=source_result,
            source_sha=source_head_sha,
            run_id=workflow_run_id,
            attempt_id=attempt_id,
        ),
        "exact_head": _load_lane(
            artifacts,
            name="exact_head",
            prefix="compact-engine-exact-head-",
            result=qualify_result,
            source_sha=source_head_sha,
            run_id=workflow_run_id,
            attempt_id=attempt_id,
        ),
        "synthetic_merge": _load_lane(
            artifacts,
            name="synthetic_merge",
            prefix="compact-engine-synthetic-merge-",
            result=qualify_result,
            source_sha=source_head_sha,
            run_id=workflow_run_id,
            attempt_id=attempt_id,
        ),
        "capacity": _load_lane(
            artifacts,
            name="capacity",
            prefix="compact-engine-capacity-required-",
            result=capacity_result,
            source_sha=source_head_sha,
            run_id=workflow_run_id,
            attempt_id=attempt_id,
        ),
    }
    for lane in lanes.values():
        errors.extend(lane.errors)

    identities = [lane.identity for lane in lanes.values() if lane.identity is not None]
    base_values = {str(identity.get("base_sha", "")) for identity in identities}
    base_values.discard("")
    base_sha = sorted(base_values)[0] if len(base_values) == 1 else None
    if len(base_values) != 1:
        errors.append(f"lane base SHA set is not singular: {sorted(base_values)}")
    if base_sha is not None:
        _validate_sha("base_sha", base_sha, errors)

    workflow_values = {str(identity.get("workflow_sha", "")) for identity in identities}
    workflow_values.discard("")
    if workflow_values != {workflow_sha}:
        errors.append(
            f"lane workflow SHA set {sorted(workflow_values)} does not equal {workflow_sha}"
        )

    exact_identity = lanes["exact_head"].identity or {}
    synthetic_identity = lanes["synthetic_merge"].identity or {}
    capacity_identity = lanes["capacity"].identity or {}
    source_identity = lanes["source_snapshot"].identity or {}

    if exact_identity.get("checked_sha") != source_head_sha:
        errors.append("exact-head checked SHA does not equal source head")
    if capacity_identity.get("checked_sha") != source_head_sha:
        errors.append("capacity checked SHA does not equal source head")
    if source_identity.get("checked_sha") != source_head_sha:
        errors.append("source snapshot checked SHA does not equal source head")

    deterministic_merge_sha = str(synthetic_identity.get("checked_sha", ""))
    deterministic_merge = _validate_sha(
        "deterministic_merge_sha", deterministic_merge_sha, errors
    )
    if deterministic_merge == source_head_sha:
        errors.append("synthetic merge SHA equals source head")

    github_values = {str(identity.get("github_merge_sha", "")) for identity in identities}
    github_values.discard("")
    if github_merge_sha and github_values != {github_merge_sha}:
        errors.append(
            f"lane GitHub merge SHA set {sorted(github_values)} does not equal {github_merge_sha}"
        )

    source_tree_hash: str | None = None
    if source_head is not None:
        try:
            source_tree_hash = run_git(root, "rev-parse", f"{source_head}^{{tree}}")
        except QualificationError as exc:
            errors.append(str(exc))
        else:
            if _SHA_RE.fullmatch(source_tree_hash) is None:
                errors.append("source_tree_hash is invalid")

    runner_images = {
        lane.name: str((lane.identity or {}).get("runner_image", ""))
        for lane in lanes.values()
    }
    qualification_runner_images = {
        runner_images[name]
        for name in ("exact_head", "synthetic_merge", "capacity")
        if runner_images[name]
    }
    runner_image = (
        sorted(qualification_runner_images)[0]
        if len(qualification_runner_images) == 1
        else None
    )
    if len(qualification_runner_images) != 1:
        errors.append(
            "qualification runner images are not singular: "
            + repr(sorted(qualification_runner_images))
        )

    target_triples = {
        str((lane.identity or {}).get("target_triple", ""))
        for lane in (lanes["exact_head"], lanes["synthetic_merge"], lanes["capacity"])
    }
    target_triples.discard("")
    target_triple = sorted(target_triples)[0] if len(target_triples) == 1 else None
    if len(target_triples) != 1:
        errors.append(f"qualification target triples are not singular: {sorted(target_triples)}")

    hashes: dict[str, str | None] = {}
    try:
        hashes["Cargo.lock_hash"] = sha256_file(
            checked_repo_path(root, "codex-rs/Cargo.lock")
        )
        hashes["migration_hash"] = combined_hash(root, MIGRATION_INPUTS)
        hashes["test_set_hash"] = combined_hash(root, _test_inputs(root))
        hashes["qualification_profile_hash"] = combined_hash(
            root, QUALIFICATION_PROFILE_INPUTS
        )
        hashes["implementation_map_hash"] = sha256_file(
            checked_repo_path(root, MAP_PATH)
        )
        hashes["documentation_hash"] = combined_hash(root, DOCUMENTATION_INPUTS)
    except QualificationError as exc:
        errors.append(str(exc))
        for key in (
            "Cargo.lock_hash",
            "migration_hash",
            "test_set_hash",
            "qualification_profile_hash",
            "implementation_map_hash",
            "documentation_hash",
        ):
            hashes.setdefault(key, None)

    all_lanes_succeeded = all(lanes[name].succeeded for name in REQUIRED_LANES)
    source_values = {
        str((lane.identity or {}).get("source_head_sha", "")) for lane in lanes.values()
    } - {""}
    run_values = {
        str((lane.identity or {}).get("workflow_run_id", "")) for lane in lanes.values()
    } - {""}
    attempt_values = {
        str((lane.identity or {}).get("attempt_id", "")) for lane in lanes.values()
    } - {""}
    event_values = {
        str((lane.identity or {}).get("event_name", "")) for lane in lanes.values()
    } - {""}
    if source_values != {source_head_sha}:
        errors.append(f"lane source SHA set is not exact: {sorted(source_values)}")
    if run_values != {workflow_run_id}:
        errors.append(f"lane workflow run set is not exact: {sorted(run_values)}")
    if attempt_values != {attempt_id}:
        errors.append(f"lane attempt set is not exact: {sorted(attempt_values)}")
    if event_values != {event_name}:
        errors.append(f"lane event set is not exact: {sorted(event_values)}")

    mandatory_identity_present = all(
        value is not None
        for value in (
            source_head,
            frozen_source,
            base_sha,
            deterministic_merge,
            workflow,
            source_tree_hash,
            runner_image,
            target_triple,
        )
    )
    required_lanes_passed = (
        all_lanes_succeeded and mandatory_identity_present and not errors
    )
    premerge_identity_present = github_merge is not None
    if event_name == "pull_request" and github_merge is not None and github_merge != workflow:
        errors.append("pull-request workflow SHA differs from GitHub merge SHA")
        required_lanes_passed = False
    merge_ready = (
        event_name == "pull_request"
        and required_lanes_passed
        and premerge_identity_present
        and not errors
    )
    production_qualified = (
        event_name == "push"
        and required_lanes_passed
        and final_merge is not None
        and postmerge_result == "success"
        and final_merge == workflow
        and final_merge == source_head
    )

    artifact_hashes = {
        lane.artifact_name: lane.artifact_hash
        for lane in lanes.values()
        if lane.artifact_name is not None and lane.artifact_hash is not None
    }

    manifest: dict[str, Any] = {
        "schema": "hepta.compact-engine-readiness-manifest.v1",
        "schema_version": 1,
        "module": "compact.engine",
        "source_head_sha": source_head,
        "frozen_source_sha": frozen_source,
        "base_sha": base_sha,
        "deterministic_merge_sha": deterministic_merge,
        "github_merge_sha": github_merge,
        "workflow_sha": workflow,
        "final_merge_sha": final_merge,
        "workflow_run_id": int(workflow_run_id) if workflow_run_id.isdigit() else None,
        "attempt_id": int(attempt_id) if attempt_id.isdigit() else None,
        "event_name": event_name,
        "runner_image": runner_image,
        "lane_runner_images": runner_images,
        "target_triple": target_triple,
        "Cargo.lock_hash": hashes.get("Cargo.lock_hash"),
        "migration_hash": hashes.get("migration_hash"),
        "test_set_hash": hashes.get("test_set_hash"),
        "qualification_profile_hash": hashes.get("qualification_profile_hash"),
        "implementation_map_hash": hashes.get("implementation_map_hash"),
        "documentation_hash": hashes.get("documentation_hash"),
        "source_tree_hash": source_tree_hash,
        "artifact_hashes": artifact_hashes,
        "required_lanes": {name: lanes[name].as_json() for name in REQUIRED_LANES},
        "hash_inputs": {
            "migration": [path.as_posix() for path in MIGRATION_INPUTS],
            "tests": [path.as_posix() for path in _test_inputs(root)],
            "qualification_profile": [
                path.as_posix() for path in QUALIFICATION_PROFILE_INPUTS
            ],
            "documentation": [path.as_posix() for path in DOCUMENTATION_INPUTS],
        },
        "generation_errors": sorted(set(errors)),
        "requiredLanesPassed": required_lanes_passed,
        "mergeReady": merge_ready,
        "productionQualified": production_qualified,
        "claim_boundary": {
            "single_source_sha": source_values == {source_head_sha},
            "single_workflow_run": run_values == {workflow_run_id},
            "single_attempt": attempt_values == {attempt_id},
            "single_event": event_values == {event_name},
            "external_acceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
    }
    dump_json(output, manifest)
    return manifest


def require_manifest_field(path: Path, field: str) -> None:
    manifest = load_json(path)
    if manifest.get(field) is not True:
        errors = manifest.get("generation_errors", [])
        detail = "; ".join(str(item) for item in errors) or f"{field} is false"
        raise QualificationError(detail)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-map")
    verify.add_argument("--root", type=Path, default=Path.cwd())
    verify.add_argument("--output", type=Path)

    build = subparsers.add_parser("build-manifest")
    build.add_argument("--root", type=Path, default=Path.cwd())
    build.add_argument("--artifacts", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--source-head-sha", required=True)
    build.add_argument("--frozen-source-sha", required=True)
    build.add_argument("--workflow-sha", required=True)
    build.add_argument("--github-merge-sha", default="")
    build.add_argument("--final-merge-sha", default="")
    build.add_argument("--workflow-run-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--event-name", required=True)
    build.add_argument("--source-result", required=True)
    build.add_argument("--qualify-result", required=True)
    build.add_argument("--capacity-result", required=True)
    build.add_argument("--postmerge-result", default="not-run")

    require = subparsers.add_parser("require")
    require.add_argument("--manifest", type=Path, required=True)
    require.add_argument("--field", default="mergeReady")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify-map":
            report = verify_implementation_map(args.root, args.output)
            if args.output is None:
                print(json.dumps(report, sort_keys=True))
        elif args.command == "build-manifest":
            manifest = build_readiness_manifest(
                args.root,
                args.artifacts,
                args.output,
                source_head_sha=args.source_head_sha,
                frozen_source_sha=args.frozen_source_sha,
                workflow_sha=args.workflow_sha,
                github_merge_sha=args.github_merge_sha,
                final_merge_sha=args.final_merge_sha,
                workflow_run_id=args.workflow_run_id,
                attempt_id=args.attempt_id,
                event_name=args.event_name,
                source_result=args.source_result,
                qualify_result=args.qualify_result,
                capacity_result=args.capacity_result,
                postmerge_result=args.postmerge_result,
            )
            print(json.dumps({
                "requiredLanesPassed": manifest["requiredLanesPassed"],
                "mergeReady": manifest["mergeReady"],
                "productionQualified": manifest["productionQualified"],
                "generation_errors": manifest["generation_errors"],
            }, sort_keys=True))
        elif args.command == "require":
            require_manifest_field(args.manifest, args.field)
        else:  # pragma: no cover
            raise AssertionError(args.command)
    except QualificationError as exc:
        print(f"compact.engine qualification error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

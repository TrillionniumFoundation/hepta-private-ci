#!/usr/bin/env python3
"""Generate every kernel.authority current-state projection from one manifest.

The manifest carries a non-self-referential source anchor. The generator proves
that every mapped source/evidence path is unchanged from that anchor to HEAD,
then emits the implementation map, current-state JSON, Markdown summaries and a
machine-readable execution-dossier status companion. Generated projections
cannot grant production implementation, activation or release.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "qualification/kernel-authority/status_manifest.json"
OUTPUTS = {
    "implementationMap": ROOT / "docs/modules/kernel.authority/IMPLEMENTATION_MAP.json",
    "currentState": ROOT / "docs/modules/kernel.authority/CURRENT_STATE.json",
    "currentImplementation": ROOT / "docs/modules/kernel.authority/CURRENT_IMPLEMENTATION.md",
    "traceability": ROOT / "docs/modules/kernel.authority/TRACEABILITY.md",
    "status": ROOT / "docs/modules/kernel.authority/STATUS.md",
    "dossierStatus": ROOT
    / "qualification/module-execution-dossiers/detail/kernel.authority.status.json",
}
SHA1 = re.compile(r"[0-9a-f]{40}")
SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*")
EXECUTION_CLAIMS = (
    "productionImplementation",
    "productExecutionProved",
    "independentAcceptance",
    "activation",
    "release",
)


class StatusError(RuntimeError):
    """Raised when the canonical status source is invalid or stale."""


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise StatusError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def load_manifest() -> dict[str, Any]:
    try:
        value = json.loads(
            MANIFEST.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs
        )
    except (OSError, json.JSONDecodeError) as error:
        raise StatusError(f"invalid status manifest: {error}") from error
    if not isinstance(value, dict):
        raise StatusError("status manifest must be an object")
    return value


def git(*args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    completed = subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value)
    )


def native_symbol(value: Any, name: str) -> str:
    if not isinstance(value, str) or SYMBOL.fullmatch(value) is None:
        raise StatusError(f"{name} must name one atomic code symbol")
    return value


def string_list(value: Any, name: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise StatusError(f"{name} must be a {'non-empty ' if nonempty else ''}list")
    if any(not isinstance(item, str) or not item for item in value):
        raise StatusError(f"{name} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise StatusError(f"{name} contains duplicates")
    return value


def relative_file(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise StatusError(f"{name} must be a non-empty path")
    candidate = (ROOT / value).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as error:
        raise StatusError(f"{name} escapes the repository") from error
    if not candidate.is_file():
        raise StatusError(f"{name} does not exist: {value}")
    return value


def operation_paths(row: dict[str, Any]) -> set[str]:
    paths = {relative_file(row.get("sourcePath"), "operation sourcePath")}
    for path in string_list(row.get("tests", []), "operation tests", nonempty=False):
        paths.add(relative_file(path, "operation test"))
    for path in string_list(
        row.get("delegatedCallees", []), "delegated callees", nonempty=False
    ):
        paths.add(relative_file(path, "delegated callee"))
    return paths


def caller_paths(row: dict[str, Any]) -> set[str]:
    paths = {relative_file(row.get("sourcePath"), "product caller sourcePath")}
    for path in string_list(row.get("tests", []), "product caller tests", nonempty=False):
        paths.add(relative_file(path, "product caller test"))
    return paths


def validate_manifest(manifest: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    if manifest.get("schema") != "hepta.kernel-authority-status-manifest.v1":
        raise StatusError("unsupported status manifest schema")
    if manifest.get("schemaVersion") != 1:
        raise StatusError("unsupported status manifest version")
    for field in ("module", "laneId", "owner", "deputy", "status"):
        if not identifier(manifest.get(field)):
            raise StatusError(f"invalid {field}")
    if manifest["module"] != "kernel.authority":
        raise StatusError("status manifest owns only kernel.authority")

    anchor = manifest.get("sourceAnchor")
    if not isinstance(anchor, dict) or set(anchor) != {"commit", "tree"}:
        raise StatusError("sourceAnchor requires exact commit/tree")
    if any(
        not isinstance(anchor[key], str) or SHA1.fullmatch(anchor[key]) is None
        for key in anchor
    ):
        raise StatusError("sourceAnchor values must be lowercase SHA-1 values")
    if git("cat-file", "-t", anchor["commit"]) != "commit":
        raise StatusError("sourceAnchor commit is not a commit")
    if git("rev-parse", f"{anchor['commit']}^{{tree}}") != anchor["tree"]:
        raise StatusError("sourceAnchor tree does not match commit")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", anchor["commit"], "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

    claims = manifest.get("claimBoundary")
    if not isinstance(claims, dict):
        raise StatusError("claimBoundary must be an object")
    for field in (
        "nativeSourceMappingComplete",
        "sourceRootPresent",
        "implementedOperationMappingComplete",
        *EXECUTION_CLAIMS,
    ):
        if type(claims.get(field)) is not bool:
            raise StatusError(f"claimBoundary.{field} must be boolean")
    if any(claims[field] for field in EXECUTION_CLAIMS):
        raise StatusError("repository projections cannot self-grant execution claims")

    roots = string_list(manifest.get("declaredRoots"), "declaredRoots")
    for root in roots:
        candidate = (ROOT / root).resolve()
        if not candidate.exists() or not candidate.is_relative_to(ROOT.resolve()):
            raise StatusError(f"invalid declared root: {root}")

    technical = relative_file(manifest.get("technicalGuide"), "technicalGuide")
    operations = manifest.get("operations")
    if not isinstance(operations, list) or not operations:
        raise StatusError("operations must be a non-empty list")
    operation_ids: set[str] = set()
    paths: set[str] = {technical}
    for row in operations:
        if not isinstance(row, dict):
            raise StatusError("operation must be an object")
        operation_id = row.get("operation")
        if not identifier(operation_id) or operation_id in operation_ids:
            raise StatusError(f"invalid or duplicate operation: {operation_id}")
        operation_ids.add(operation_id)
        native_symbol(row.get("nativeSymbol"), f"{operation_id}.nativeSymbol")
        for field in ("state", "authority", "designOperation", "mappingClass"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise StatusError(f"{operation_id}: invalid {field}")
        paths.update(operation_paths(row))

    callers = manifest.get("productCallers")
    if not isinstance(callers, list) or not callers:
        raise StatusError("productCallers must be a non-empty list")
    caller_ids: set[str] = set()
    for row in callers:
        if not isinstance(row, dict):
            raise StatusError("product caller must be an object")
        caller_id = row.get("id")
        if not identifier(caller_id) or caller_id in caller_ids:
            raise StatusError(f"invalid or duplicate product caller: {caller_id}")
        caller_ids.add(caller_id)
        native_symbol(row.get("nativeSymbol"), f"{caller_id}.nativeSymbol")
        if not isinstance(row.get("state"), str) or not row["state"]:
            raise StatusError(f"{caller_id}: invalid state")
        paths.update(caller_paths(row))

    for path in string_list(manifest.get("trackedPaths"), "trackedPaths"):
        paths.add(relative_file(path, "tracked path"))
    string_list(manifest.get("repositoryControlledGaps"), "repositoryControlledGaps")
    string_list(manifest.get("externalEvidenceGates"), "externalEvidenceGates")

    tracked = sorted(paths)
    for path in tracked:
        if git("cat-file", "-t", f"HEAD:{path}") != "blob":
            raise StatusError(f"tracked status source is not a committed blob: {path}")
    changed = git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        anchor["commit"],
        "HEAD",
        "--",
        *tracked,
    )
    if changed:
        raise StatusError(
            "mapped status source changed after sourceAnchor; rebind the manifest: "
            + changed.replace("\n", ", ")
        )
    return {"commit": anchor["commit"], "tree": anchor["tree"]}, tracked


def implementation_map(
    manifest: dict[str, Any], anchor: dict[str, str]
) -> dict[str, Any]:
    operations = []
    for original in manifest["operations"]:
        row = dict(original)
        row["sourcePathExists"] = True
        row.setdefault("delegatedCallees", [])
        operations.append(row)
    return {
        "schema": "hepta.module-implementation-map.v3",
        "schemaVersion": 3,
        "sourceBase": anchor,
        "mappingSourceIdentityMode": "path_only",
        "exactSourceEvidenceMode":
            "lane_a_runtime_wiring_only_no_product_execution_claim",
        "laneId": manifest["laneId"],
        "module": manifest["module"],
        "owner": manifest["owner"],
        "deputy": manifest["deputy"],
        "technicalGuide": manifest["technicalGuide"],
        "declaredRoots": manifest["declaredRoots"],
        "resolvedRoots": manifest["declaredRoots"],
        "sourceRootPresent": manifest["claimBoundary"]["sourceRootPresent"],
        "productionImplementation": False,
        "productCallerState": manifest["productCallerState"],
        "productionWriterState": manifest["productionWriterState"],
        "operations": operations,
        "repositoryControlledGaps": manifest["repositoryControlledGaps"],
        "externalEvidenceGates": manifest["externalEvidenceGates"],
        "claimBoundary": manifest["claimBoundary"],
        "sourceRoot": manifest["declaredRoots"],
        "traceability": "docs/modules/kernel.authority/TRACEABILITY.md",
        "trustDecision": "docs/modules/kernel.authority/ADR-0001-LEASE-TRUST-MODEL.md",
        "linearizationContract": "docs/modules/kernel.authority/LINEARIZATION.md",
        "productionTrustProfile":
            "docs/modules/kernel.authority/PRODUCTION_TRUST_PROFILE.md",
        "productionClosure": "docs/modules/kernel.authority/PRODUCTION_CLOSURE.md",
        "capacityQualification":
            "docs/modules/kernel.authority/CAPACITY_QUALIFICATION.md",
        "statusManifest": "qualification/kernel-authority/status_manifest.json",
        "statusGenerator": "qualification/kernel-authority/generate_status.py",
        "productCallers": manifest["productCallers"],
        "evidencePrograms": manifest["evidencePrograms"],
    }


def current_state(manifest: dict[str, Any], anchor: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": "hepta.kernel-authority-current-state.v1",
        "schemaVersion": 1,
        "generatedFrom": "qualification/kernel-authority/status_manifest.json",
        "generatedBy": "qualification/kernel-authority/generate_status.py",
        "sourceBase": anchor,
        "module": manifest["module"],
        "status": manifest["status"],
        "claimBoundary": manifest["claimBoundary"],
        "productionTrustBundle": manifest["productionTrustBundle"],
        "productPilots": manifest["productPilots"],
        "qualification": manifest["qualification"],
        "performanceAndScale": manifest["performanceAndScale"],
        "repositoryControlledGaps": manifest["repositoryControlledGaps"],
        "externalEvidenceGates": manifest["externalEvidenceGates"],
        "activationGranted": False,
        "releaseGranted": False,
    }


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    lines.extend(
        "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"
        for row in rows
    )
    return lines


def current_implementation_md(
    manifest: dict[str, Any], anchor: dict[str, str]
) -> str:
    lines = [
        "# kernel.authority current implementation",
        "",
        "<!-- Generated by qualification/kernel-authority/generate_status.py; do not edit. -->",
        "",
        f"Status: **{manifest['status']}**.",
        "",
        f"Source anchor: `{anchor['commit']}` / tree `{anchor['tree']}`. "
        "Mapped source paths are proven unchanged from this anchor to the candidate.",
        "",
        "Repository source closure is implemented, but production implementation, "
        "product execution proof, independent acceptance, activation and release "
        "remain false. External trust and target-host evidence cannot be manufactured "
        "by repository tests.",
        "",
        "## Native operations",
        "",
    ]
    rows = [
        [
            f"`{row['operation']}`",
            f"`{row['nativeSymbol']}`",
            f"`{row['sourcePath']}`",
            row["state"],
        ]
        for row in manifest["operations"]
    ]
    lines.extend(markdown_table(["Operation", "Native symbol", "Source", "State"], rows))
    lines.extend(["", "## Product callers", ""])
    caller_rows = [
        [
            f"`{row['id']}`",
            f"`{row['nativeSymbol']}`",
            f"`{row['sourcePath']}`",
            row["state"],
        ]
        for row in manifest["productCallers"]
    ]
    lines.extend(markdown_table(["Caller", "Boundary", "Source", "State"], caller_rows))
    lines.extend(["", "## Repository-controlled gaps", ""])
    lines.extend(f"- {item}" for item in manifest["repositoryControlledGaps"])
    lines.extend(["", "## External evidence gates", ""])
    lines.extend(f"- {item}" for item in manifest["externalEvidenceGates"])
    lines.extend(
        [
            "",
            "Detailed contracts: `TECHNICAL.md`, `LINEARIZATION.md`, "
            "`PRODUCTION_TRUST_PROFILE.md` and `PRODUCTION_CLOSURE.md`.",
            "",
        ]
    )
    return "\n".join(lines)


def traceability_md(manifest: dict[str, Any], anchor: dict[str, str]) -> str:
    lines = [
        "# kernel.authority traceability",
        "",
        "<!-- Generated by qualification/kernel-authority/generate_status.py; do not edit. -->",
        "",
        f"Source anchor: `{anchor['commit']}` / tree `{anchor['tree']}`.",
        "",
        "## Operation-to-test mapping",
        "",
    ]
    rows = []
    for row in manifest["operations"]:
        tests = "<br>".join(f"`{path}`" for path in row.get("tests", [])) or "—"
        rows.append(
            [
                f"`{row['operation']}`",
                f"`{row['sourcePath']}`",
                tests,
                row["state"],
            ]
        )
    lines.extend(markdown_table(["Operation", "Source", "Tests/evidence", "Claim"], rows))
    lines.extend(["", "## Product-call mapping", ""])
    caller_rows = []
    for row in manifest["productCallers"]:
        tests = "<br>".join(f"`{path}`" for path in row.get("tests", [])) or "—"
        caller_rows.append(
            [f"`{row['id']}`", f"`{row['sourcePath']}`", tests, row["state"]]
        )
    lines.extend(
        markdown_table(["Caller", "Source", "Tests/evidence", "Claim"], caller_rows)
    )
    lines.extend(
        [
            "",
            "Every exact-head or synthetic-merge receipt is candidate-bound. "
            "Test identity or source composition alone does not establish deployment activation.",
            "",
        ]
    )
    return "\n".join(lines)


def status_md(manifest: dict[str, Any], anchor: dict[str, str]) -> str:
    claims = manifest["claimBoundary"]
    lines = [
        "# kernel.authority status",
        "",
        "<!-- Generated by qualification/kernel-authority/generate_status.py; do not edit. -->",
        "",
        f"**Current state:** `{manifest['status']}`",
        "",
        f"**Mapped source anchor:** `{anchor['commit']}` (`{anchor['tree']}`)",
        "",
        "## Claim boundary",
        "",
    ]
    lines.extend(
        markdown_table(
            ["Claim", "Value"],
            [[f"`{key}`", "true" if value else "false"] for key, value in claims.items()],
        )
    )
    lines.extend(
        [
            "",
            "The repository contains the mandatory production trust-bundle contract, "
            "closed final-use/dispatch APIs, candidate-bound Fleet and Browser/Agentd "
            "process pilots, performance measurement and a WAL/checkpoint/sharding "
            "reference model. Target deployment evidence remains external and fail-closed.",
            "",
            "See `CURRENT_IMPLEMENTATION.md`, `TRACEABILITY.md` and `PRODUCTION_CLOSURE.md`.",
            "",
        ]
    )
    return "\n".join(lines)


def dossier_status(manifest: dict[str, Any], anchor: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": "hepta.kernel-authority-dossier-status.v1",
        "schemaVersion": 1,
        "generatedFrom": "qualification/kernel-authority/status_manifest.json",
        "generatedBy": "qualification/kernel-authority/generate_status.py",
        "sourceBase": anchor,
        "module": manifest["module"],
        "laneId": manifest["laneId"],
        "status": manifest["status"],
        "claimBoundary": manifest["claimBoundary"],
        "operationIds": [row["operation"] for row in manifest["operations"]],
        "productCallerIds": [row["id"] for row in manifest["productCallers"]],
        "evidencePrograms": manifest["evidencePrograms"],
        "externalEvidenceGates": manifest["externalEvidenceGates"],
        "activationGranted": False,
        "releaseGranted": False,
    }


def render() -> dict[Path, bytes]:
    manifest = load_manifest()
    anchor, _paths = validate_manifest(manifest)
    return {
        OUTPUTS["implementationMap"]: canonical_json(
            implementation_map(manifest, anchor)
        ),
        OUTPUTS["currentState"]: canonical_json(current_state(manifest, anchor)),
        OUTPUTS["currentImplementation"]: current_implementation_md(
            manifest, anchor
        ).encode(),
        OUTPUTS["traceability"]: traceability_md(manifest, anchor).encode(),
        OUTPUTS["status"]: status_md(manifest, anchor).encode(),
        OUTPUTS["dossierStatus"]: canonical_json(dossier_status(manifest, anchor)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        rendered = render()
    except (StatusError, subprocess.CalledProcessError) as error:
        print(f"kernel.authority status generation failed: {error}", file=sys.stderr)
        return 1
    failures: list[str] = []
    for path, content in rendered.items():
        if args.check:
            try:
                current = path.read_bytes()
            except OSError:
                current = b""
            if current != content:
                failures.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    if failures:
        print(
            "kernel.authority generated projections are stale: "
            + ", ".join(failures),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

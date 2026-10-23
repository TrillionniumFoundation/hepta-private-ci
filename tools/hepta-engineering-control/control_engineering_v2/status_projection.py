"""Generate and verify the single control.engineering STATUS.json projection."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

from .git_security import run_git

STATUS_SCHEMA = "hepta.control-engineering-status.v1"
API_SCHEMA = "hepta.control-engineering-api-compatibility.v1"
_CRITICAL_REPOSITORY_PATHS = (
    ".github/workflows/blocking-ci.yml",
    ".github/workflows/control-engineering-production-acceptance.yml",
    ".github/workflows/control-engineering-projection.yml",
    ".github/workflows/control-engineering-required.yml",
    ".github/workflows/hepta-consolidated-source.yml",
)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git(root: Path, *args: str) -> str:
    return run_git(root, *args)


def _source_object(root: Path, path: str) -> str:
    value = _git(root, "rev-parse", f"HEAD:{path}")
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"invalid Git object for {path}")
    return value


def _public_exports(root: Path) -> list[str]:
    path = root / "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise ValueError(
                    "control.engineering __all__ must be a literal string list"
                )
            if len(value) != len(set(value)):
                raise ValueError("control.engineering __all__ contains duplicates")
            return sorted(value)
    raise ValueError("control.engineering __all__ is missing")


def api_compatibility_projection(root: Path) -> dict[str, object]:
    exports = _public_exports(root)
    value: dict[str, object] = {
        "schema": API_SCHEMA,
        "module": "control.engineering",
        "mode": "exact_public_export_set",
        "exports": exports,
        "additiveChangesRequireManifestUpdate": True,
        "removalsRequireExplicitCompatibilityReview": True,
    }
    value["manifestDigest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def status_projection(map_value: dict[str, object]) -> dict[str, object]:
    boundary = map_value.get("claimBoundary")
    if not isinstance(boundary, dict):
        raise ValueError("control.engineering claim boundary missing")
    external = {
        "distributedLeaseFenceProvider": False,
        "immutableAuditLog": False,
        "hsmKmsRoleSeparatedCustody": False,
        "independentCiCompletionObserver": False,
        "externalTerminalObserver": False,
        "targetDeploymentObserved": False,
        "backupRestoreRehearsed": False,
        "rollbackRehearsed": False,
        "operatorAcceptance": False,
    }
    repository = {
        "exactBlobObservationBound": True,
        "mergeCommitRequired": True,
        "pullRequestDualLaneReceiptRequired": True,
        "postMergeMainReceiptRequired": True,
        "currentHeadIndependentGithubApprovalRequired": True,
        "qualityGateRequired": True,
        "stressProfileRequired": True,
        "mutationCampaignRequired": True,
    }
    source_objects = map_value.get("sourceObjects", [])
    value: dict[str, object] = {
        "schema": STATUS_SCHEMA,
        "schemaVersion": 1,
        "module": "control.engineering",
        "generatedFrom": [
            "docs/modules/control.engineering/IMPLEMENTATION_MAP.json",
            "docs/modules/control.engineering/EXTENSIONS.json",
            "docs/modules/control.engineering/API_COMPATIBILITY.json",
        ],
        "sourceObservation": map_value.get("observedAtHead"),
        "sourceObjectsDigest": hashlib.sha256(
            json.dumps(
                source_objects,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "sourceRootPresent": bool(map_value.get("sourceRootPresent")),
        "productionImplementation": False,
        "productCallerState": map_value.get("productCallerState"),
        "productionWriterState": map_value.get("productionWriterState"),
        "claimBoundary": {
            **boundary,
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
        "repositoryQualificationGates": repository,
        "externalProductionGates": external,
        "canonicalState": "source_implemented_external_acceptance_pending",
        "trackedStatusSelfReferenceSafe": True,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "activationAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
        "externalEffectAuthority": False,
    }
    value["statusDigest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def prepare_projection(repository: str | Path) -> dict[str, object]:
    root = Path(repository).resolve()
    module_dir = root / "docs/modules/control.engineering"
    map_path = module_dir / "IMPLEMENTATION_MAP.json"
    extension_path = module_dir / "EXTENSIONS.json"
    map_value = _load(map_path)
    extensions = _load(extension_path)
    if not isinstance(map_value, dict) or not isinstance(extensions, dict):
        raise ValueError("control.engineering projection input")
    operations = extensions.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("control.engineering extension operations")
    existing = {
        row.get("operation"): row
        for row in map_value.get("operations", [])
        if isinstance(row, dict)
    }
    evidence_paths: set[str] = set()
    for extension in operations:
        if not isinstance(extension, dict):
            raise ValueError("control.engineering extension operation")
        operation = extension.get("operation")
        source = extension.get("sourcePath")
        symbol = extension.get("nativeSymbol")
        tests = extension.get("tests", [])
        if (
            not isinstance(operation, str)
            or not operation
            or not isinstance(source, str)
            or not source
            or not isinstance(symbol, str)
            or not symbol
            or not isinstance(tests, list)
        ):
            raise ValueError("control.engineering extension operation")
        source_path = root / source
        if not source_path.is_file():
            raise ValueError(f"missing extension source {source}")
        normalized_tests = []
        for test in tests:
            path = test.get("path") if isinstance(test, dict) else test
            if not isinstance(path, str) or not (root / path).is_file():
                raise ValueError(f"missing extension test {path}")
            normalized_tests.append({"path": path})
            evidence_paths.add(path)
        row = {
            "operation": operation,
            "designOperation": extension.get("designOperation", operation),
            "nativeSymbol": symbol,
            "sourcePath": source,
            "state": extension.get("state", "source_implemented"),
            "authority": "none",
            "tests": normalized_tests,
            "sourcePathExists": True,
            "mappingClass": "owner_native",
            "delegatedCallees": extension.get("delegatedCallees", []),
            "sourceBlob": _source_object(root, source),
        }
        existing[operation] = row
        evidence_paths.add(source)
    map_value["operations"] = list(existing.values())
    map_value["observedAtHead"] = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
    }
    map_value["statusFile"] = "docs/modules/control.engineering/STATUS.json"
    map_value["implementationExtensions"] = (
        "docs/modules/control.engineering/EXTENSIONS.json"
    )
    map_value["productCallerState"] = (
        "repository_product_caller_dual_lane_and_post_merge_defined_execution_pending"
    )
    map_value["productionWriterState"] = (
        "named_product_owner_with_renewal_capacity_and_checkpoint_extensions_execution_pending"
    )
    gaps = [
        "Retain exact source-head and deterministic synthetic-merge product receipts for the reviewed pull request.",
        "Merge exact-blob changes with a merge commit and retain the exact post-merge main product receipt.",
        "Require a current-head non-author GitHub approval without treating it as independent semantic acceptance.",
        "Run coverage, type, lint, API compatibility, mutation and stress qualification for the exact candidate.",
    ]
    map_value["repositoryControlledGaps"] = gaps
    boundary = map_value.setdefault("claimBoundary", {})
    if not isinstance(boundary, dict):
        raise ValueError("control.engineering claim boundary")
    boundary.update(
        {
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        }
    )
    paths = {
        entry["path"]
        for entry in map_value.get("sourceObjects", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    paths.update(evidence_paths)
    paths.update(_CRITICAL_REPOSITORY_PATHS)
    paths.add("docs/modules/control.engineering/EXTENSIONS.json")
    paths.add("docs/modules/control.engineering/README.md")
    paths.add("docs/modules/control.engineering/CAPACITY.md")
    paths.add("docs/modules/control.engineering/PRODUCTION_INTEGRATION.md")
    for path in paths:
        if not (root / path).exists():
            raise ValueError(f"missing control.engineering source object {path}")
    map_value["sourceObjects"] = [
        {"path": path, "object": _source_object(root, path)}
        for path in sorted(paths)
    ]
    _write(map_path, map_value)
    _write(
        module_dir / "API_COMPATIBILITY.json",
        api_compatibility_projection(root),
    )
    _write(module_dir / "STATUS.json", status_projection(map_value))
    return {
        "map": str(map_path.relative_to(root)),
        "status": str((module_dir / "STATUS.json").relative_to(root)),
        "api": str((module_dir / "API_COMPATIBILITY.json").relative_to(root)),
        "observation": map_value["observedAtHead"],
    }


def verify_projection(repository: str | Path) -> dict[str, object]:
    root = Path(repository).resolve()
    module_dir = root / "docs/modules/control.engineering"
    map_value = _load(module_dir / "IMPLEMENTATION_MAP.json")
    if not isinstance(map_value, dict):
        raise ValueError("control.engineering map")
    expected_status = status_projection(map_value)
    actual_status = _load(module_dir / "STATUS.json")
    if actual_status != expected_status:
        raise ValueError("control.engineering STATUS.json drift")
    expected_api = api_compatibility_projection(root)
    actual_api = _load(module_dir / "API_COMPATIBILITY.json")
    if actual_api != expected_api:
        raise ValueError("control.engineering API compatibility drift")
    extensions = _load(module_dir / "EXTENSIONS.json")
    expected_operations = {
        row["operation"]
        for row in extensions.get("operations", [])
        if isinstance(row, dict)
    }
    operations = {
        row.get("operation"): row
        for row in map_value.get("operations", [])
        if isinstance(row, dict)
    }
    missing = sorted(expected_operations - set(operations))
    if missing:
        raise ValueError(
            "control.engineering map extensions missing: " + ", ".join(missing)
        )
    for name in expected_operations:
        row = operations[name]
        source = row.get("sourcePath")
        if row.get("sourceBlob") != _source_object(root, source):
            raise ValueError(f"control.engineering source blob drift: {name}")
    object_rows = map_value.get("sourceObjects")
    if not isinstance(object_rows, list):
        raise ValueError("control.engineering source objects missing")
    objects = {
        row.get("path"): row.get("object")
        for row in object_rows
        if isinstance(row, dict)
    }
    for path in _CRITICAL_REPOSITORY_PATHS:
        if objects.get(path) != _source_object(root, path):
            raise ValueError(
                f"control.engineering critical workflow blob drift: {path}"
            )
    return {
        "schema": STATUS_SCHEMA,
        "status": "verified",
        "statusDigest": expected_status["statusDigest"],
        "apiManifestDigest": expected_api["manifestDigest"],
        "operations": len(expected_operations),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = (
            prepare_projection(args.repository)
            if args.command == "prepare"
            else verify_projection(args.repository)
        )
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as error:
        print(
            json.dumps(
                {"schema": STATUS_SCHEMA, "status": "rejected", "error": str(error)}
            )
        )
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

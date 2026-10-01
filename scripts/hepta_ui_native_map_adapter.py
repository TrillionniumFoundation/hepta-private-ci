"""Read-only bridge for ui.native v6; no other map schema is relaxed."""

import re
import subprocess
from pathlib import Path
from typing import Callable

import check_hepta_ui_native_convergence as native
from hepta_module_source_roots import _path as checked_path
from hepta_module_source_roots import resolve_source_roots

OPERATIONS = {
    "connect_runtime": "apps/hepta-native/src/runtime.rs::connect_runtime",
    "refresh_runtime_view": "apps/hepta-native/src/runtime.rs::refresh_runtime_view",
    "request_platform_capability": "apps/hepta-native/src/runtime.rs::request_platform_capability",
    "operation_history_page": "apps/hepta-native/src/runtime.rs::operation_history_page",
    "reconcile_pending": "apps/hepta-native/src/runtime.rs::reconcile_pending",
    "verify_and_stage_update": "apps/hepta-native/src/updater.rs::verify_and_stage",
}
INCOMPLETE_CLAIMS = {
    "repositoryControlledSourceBoundaryGapsClosed",
    "productImplementationCandidateComplete",
    "productExecutionComplete",
    "deploymentQualificationComplete",
    "independentAcceptanceComplete",
    "productionQualified",
    "deploymentQualified",
    "releaseAuthorized",
}
EXECUTION_CLAIMS = INCOMPLETE_CLAIMS | {
    "productionImplementation",
    "productExecutionProved",
    "independentAcceptance",
    "activation",
    "release",
    "qualificationClaim",
    "qualified",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def strict_native_check(root: Path, git: Callable[..., str]) -> dict:
    """Reuse every native rule with the parent verifier's sanitized Git transport.

    Like the parent map verifier this is a quiescent checkout observation. Only
    repository/transport bindings change temporarily; no rule is substituted.
    """
    previous = native.ROOT, native._git_value, native._git_success

    def value(*args: str) -> str | None:
        try:
            return git(*args)
        except (OSError, subprocess.CalledProcessError):
            return None

    def success(*args: str) -> bool:
        return value(*args) is not None

    try:
        native.ROOT, native._git_value, native._git_success = root, value, success
        return native.check_repository()
    except RuntimeError as error:
        raise ValueError(f"native convergence refused: {error}") from error
    finally:
        native.ROOT, native._git_value, native._git_success = previous


def verify_native_map(
    root: Path, row: dict, module: dict, candidate: dict, git: Callable[..., str]
) -> dict:
    require(
        module.get("id") == row.get("module") == "ui.native"
        and row.get("schema") == "hepta.module-implementation-map.v6"
        and type(row.get("schemaVersion")) is int
        and row["schemaVersion"] == 6,
        "native adapter requires only ui.native schema v6",
    )
    for key in ("owner", "deputy"):
        require(
            row.get(key) == module.get(key)
            and isinstance(row.get(key), str)
            and bool(row[key]),
            f"native {key} identity",
        )
    require(
        row.get("sourceMaturity")
        == "implementation-candidate-incomplete-qualification-blocked",
        "native source maturity must remain an incomplete candidate",
    )
    boundary = row.get("claimBoundary")
    require(isinstance(boundary, dict), "native claim boundary is missing")
    require(
        all(type(value) is bool for value in boundary.values()),
        "native claim boundary values must be booleans",
    )
    for key in INCOMPLETE_CLAIMS:
        require(boundary.get(key) is False, f"native incomplete claim promoted: {key}")
    for key in ("productionQualified", "deploymentQualified", "releaseAuthorized"):
        require(row.get(key) is False, f"native qualification claim promoted: {key}")
    for key, value in native._walk(row):
        if key in EXECUTION_CLAIMS:
            require(value is False, f"native execution claim promoted: {key}")

    evidence = strict_native_check(root, git)
    require(
        evidence["repositoryHead"] == candidate["commit"]
        and evidence["repositoryTree"] == candidate["tree"],
        "native checker observed a different candidate",
    )
    source = {
        "commit": evidence["implementationSourceSha"],
        "tree": evidence["implementationSourceTree"],
    }
    require(
        row.get("implementationSourceSha") == source["commit"]
        and row.get("implementationSourceTree") == source["tree"],
        "native map source identity differs from its strict checker",
    )
    git("merge-base", "--is-ancestor", source["commit"], candidate["commit"])

    owned = [binding["path"] for binding in module["rootBindings"]]
    require(owned == ["apps/hepta-native"], "native canonical owned roots changed")
    require(
        resolve_source_roots(root, module) == owned,
        "native canonical owned root cannot be redirected by an alias",
    )
    declared = row.get("declaredRoots")
    require(
        isinstance(declared, list)
        and all(isinstance(path, str) for path in declared)
        and len(declared) == len(set(declared))
        and set(owned).issubset(declared),
        "native declared roots omit ownership or contain duplicates",
    )
    dependencies = set(evidence["localCargoDependencyPaths"])
    require(
        set(declared) - set(owned) <= dependencies,
        "native additional evidence roots are not local dependencies",
    )
    paths = set(declared)
    for path in declared:
        require(
            checked_path(root, path).is_dir(), f"missing native evidence root: {path}"
        )
    shared = row.get("sharedUtilityDependencies", [])
    require(
        isinstance(shared, list)
        and all(isinstance(path, str) for path in shared)
        and len(shared) == len(set(shared))
        and set(shared) <= dependencies,
        "native shared utility roots are not local dependencies",
    )
    paths.update(shared)

    expected_references = {
        "technicalGuide": module["technicalDocument"],
        "developmentGuide": "apps/hepta-native/DEVELOPMENT.md",
        "qualificationWorkflow": ".github/workflows/ui-native-qualification.yml",
        "storageBudget": "apps/hepta-native/STORAGE_BUDGETS.json",
    }
    for key, expected in expected_references.items():
        require(row.get(key) == expected, f"native {key} identity")
        require(checked_path(root, expected).is_file(), f"missing native {key}")
        paths.add(expected)

    operations = row.get("operations")
    require(
        isinstance(operations, list) and len(operations) == len(OPERATIONS),
        "native operation inventory is incomplete",
    )
    names = set()
    for operation in operations:
        require(isinstance(operation, dict), "invalid native operation")
        name = operation.get("operation")
        require(
            isinstance(name, str) and name not in names and name in OPERATIONS,
            "native operation inventory has an unknown or duplicate operation",
        )
        names.add(name)
        require(
            operation.get("entrypoint") == OPERATIONS[name],
            f"native entrypoint identity: {name}",
        )
        path, symbol = OPERATIONS[name].split("::")
        local = checked_path(root, path)
        require(
            local.is_file()
            and re.search(
                rf"\bpub(?:\([^)]*\))?\s+fn\s+{re.escape(symbol)}\s*\(",
                local.read_text(encoding="utf-8"),
            )
            is not None,
            f"missing native entrypoint function: {name}",
        )
        require(
            isinstance(operation.get("state"), str) and operation["state"],
            f"missing native operation state: {name}",
        )
        paths.add(path)

    references = row.get("testSurfaces")
    require(
        isinstance(references, list)
        and references
        and all(isinstance(path, str) for path in references)
        and len(references) == len(set(references)),
        "invalid native test references",
    )
    for pattern in references:
        checked_path(root, pattern)
        matches = list(root.glob(pattern))
        require(matches, f"missing native test reference: {pattern}")
        for match in matches:
            relative = match.relative_to(root).as_posix()
            require(
                checked_path(root, relative).is_file(),
                f"unsafe native test reference: {relative}",
            )
            paths.add(relative)
    # Track every referenced current object and the frozen production closure.
    # Extra evidence paths never become module ownership or execution claims.
    paths.update(evidence["localCargoDependencyPaths"])
    paths.update(native.STATE_FILES)
    for path in sorted(paths):
        git("cat-file", "-e", f"{candidate['commit']}:{path}")
    return {"source": source, "paths": sorted(paths), "ownedRoots": owned}

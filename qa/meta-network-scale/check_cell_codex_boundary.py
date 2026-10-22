#!/usr/bin/env python3
"""Reject direct Codex harness dependencies from Hepta cell/decision crates.

A source-only architectural gate; it does not grant runtime, model, tool or
promotion authority. Cell owners may depend on Hepta contracts and pure
utilities, but execution effects must enter through the typed adapter owner.
"""
from __future__ import annotations

import argparse
import posixpath
from pathlib import Path
import sys
import tomllib
from typing import Any

CELL_CRATES = (
    "hepta-types",
    "hepta-neuron",
    "hepta-intuition",
    "hepta-ndu",
    "hepta-plasticity",
    "hepta-infer-core",
    "hepta-cognitive-types",
)
DEPENDENCY_SECTIONS = frozenset(
    ("dependencies", "dev-dependencies", "build-dependencies")
)
# Admit only reviewed, authority-free Cell/Cognitive contract crates and pure
# paths. Broad codex-hepta-* or codex-utils-* allowances could accidentally
# admit agentd, tool/PTY, governance or production writer dependencies.
ALLOWED_PACKAGES = frozenset(
    (
        "codex-hepta-types",
        "codex-hepta-contracts",
        "codex-hepta-infer-core",
        "codex-hepta-ndu",
        "codex-hepta-intuition",
        "codex-hepta-plasticity",
        "codex-hepta-cognitive-types",
        "codex-utils-absolute-path",
    )
)

# A new dependency must be explicitly reviewed rather than silently acquiring
# an execution client, native host tools, network transport or dynamic loader.
# These external crates are already in the verified Cell crate manifests.
ALLOWED_EXTERNAL_PACKAGES = frozenset(
    (
        "sha2",
        "serde",
        "serde-json",
        "pretty-assertions",
        "ed25519-dalek",
        "tempfile",
    )
)


def normalized_package(name: str) -> str:
    return name.lower().replace("_", "-")


def prohibited_package(package: str) -> bool:
    package = normalized_package(package)
    return package.startswith("codex-") and package not in ALLOWED_PACKAGES



# These are exact checked-in source directories, not merely permitted Cargo
# package names. A crate could otherwise impersonate an approved dependency
# via git, an alternate registry, or a path outside this workspace.
LOCAL_PACKAGE_DIRECTORIES = {
    "codex-hepta-types": "hepta-types",
    "codex-hepta-contracts": "hepta-contracts",
    "codex-hepta-infer-core": "hepta-infer-core",
    "codex-hepta-ndu": "hepta-ndu",
    "codex-hepta-intuition": "hepta-intuition",
    "codex-hepta-plasticity": "hepta-plasticity",
    "codex-hepta-cognitive-types": "hepta-cognitive-types",
    "codex-utils-absolute-path": "utils/absolute-path",
}
SOURCE_OVERRIDE_KEYS = frozenset(("git", "registry", "branch", "tag", "rev"))


def dependency_origin_violation(
    alias: str,
    declaration: Any,
    package: str,
    crate: str,
    workspace_dependencies: dict[str, Any] | None,
) -> str | None:
    """Pin approved package *origins* as well as package names.

    This is lexical Cargo source-custody validation, not a substitute for
    Cargo.lock verification, a complete transitive graph, or an OS sandbox.
    The production caller always supplies the root workspace dependencies.
    """
    normalized = normalized_package(package)
    if (
        normalized not in LOCAL_PACKAGE_DIRECTORIES
        and normalized not in ALLOWED_EXTERNAL_PACKAGES
    ):
        return None

    source = declaration
    inherited = isinstance(declaration, dict) and declaration.get("workspace") is True
    if inherited:
        if workspace_dependencies is None:
            # Standalone unit-callers may lack the root manifest. The actual
            # check_workspace CLI always supplies it.
            return None
        source = workspace_dependencies.get(alias)
        if source is None:
            return "missing inherited workspace source"
        if any(key in declaration for key in (*SOURCE_OVERRIDE_KEYS, "path")):
            return "workspace member overrides inherited dependency source"
        root_package = (
            source.get("package", alias) if isinstance(source, dict) else alias
        )
        member_package = declaration.get("package", root_package)
        if (
            not isinstance(root_package, str)
            or not isinstance(member_package, str)
            or normalized_package(root_package) != normalized_package(member_package)
        ):
            return "workspace dependency package identity differs from member"

    if normalized in LOCAL_PACKAGE_DIRECTORIES:
        if not isinstance(source, dict):
            return "approved local package lacks a pinned local path"
        if any(key in source for key in (*SOURCE_OVERRIDE_KEYS, "version")):
            return "approved local package has a non-local or mixed source"
        relative = source.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or posixpath.isabs(relative)
        ):
            return "approved local package lacks a relative source path"
        # Workspace-root paths resolve relative to codex-rs/. Direct member
        # paths resolve relative to codex-rs/<crate>/.
        resolved = posixpath.normpath(
            posixpath.join("" if inherited else crate, relative)
        )
        if resolved != LOCAL_PACKAGE_DIRECTORIES[normalized]:
            return (
                f"approved local package resolves to {resolved!r}, expected "
                f"{LOCAL_PACKAGE_DIRECTORIES[normalized]!r}"
            )
    elif isinstance(source, dict):
        if any(key in source for key in (*SOURCE_OVERRIDE_KEYS, "path")):
            return "approved external package uses an unreviewed source"
    elif not isinstance(source, str):
        return "approved external package has an invalid source declaration"
    return None



def check_root_source_overrides(workspace: dict[str, Any]) -> list[str]:
    """Disallow Cargo patch/replace rebinding of Cell-approved packages.

    A pinned direct declaration is insufficient if the root manifest can
    replace the same package through [patch] or [replace].
    """
    violations: list[str] = []
    approved = set(LOCAL_PACKAGE_DIRECTORIES) | set(ALLOWED_EXTERNAL_PACKAGES)
    patches = workspace.get("patch", {})
    if not isinstance(patches, dict):
        return ["workspace: patch source overrides must be a table"]
    for registry, entries in patches.items():
        if not isinstance(entries, dict):
            violations.append(f"workspace: malformed patch source {registry}")
            continue
        for alias, declaration in entries.items():
            if not isinstance(alias, str):
                violations.append("workspace: malformed patch dependency alias")
                continue
            package = (
                declaration.get("package", alias)
                if isinstance(declaration, dict)
                else alias
            )
            if (
                normalized_package(alias) in approved
                or isinstance(package, str)
                and normalized_package(package) in approved
            ):
                violations.append(
                    f"workspace: patch.{registry}.{alias} overrides approved "
                    "Cell dependency source"
                )
    replacements = workspace.get("replace", {})
    if not isinstance(replacements, dict):
        violations.append("workspace: replace source overrides must be a table")
    else:
        for key in replacements:
            if not isinstance(key, str):
                violations.append("workspace: malformed replacement package")
                continue
            package = key.rsplit("#", 1)[-1].split(":", 1)[0]
            if normalized_package(package) in approved:
                violations.append(
                    f"workspace: replace.{key} overrides approved "
                    "Cell dependency source"
                )
    return violations


def check_local_source_directories(root: Path) -> list[str]:
    """Require reviewed local Cargo sources to remain real, identified dirs.

    Prevent an approved lexical path from following a checked-in symlink or
    a replaced manifest whose package name no longer matches the allowlist.
    """
    violations: list[str] = []
    workspace = root / "codex-rs"
    if workspace.is_symlink():
        return ["workspace: codex-rs source root is a symbolic link"]
    for package, relative in LOCAL_PACKAGE_DIRECTORIES.items():
        directory = workspace
        diverted = False
        for component in relative.split("/"):
            directory = directory / component
            if directory.is_symlink():
                violations.append(
                    f"workspace: {package} source path contains a symbolic link"
                )
                diverted = True
                break
        if diverted:
            continue
        manifest_path = directory / "Cargo.toml"
        if manifest_path.is_symlink():
            violations.append(
                f"workspace: {package} source Cargo.toml is a symbolic link"
            )
            continue
        try:
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            info = manifest["package"]
            actual = info["name"] if isinstance(info, dict) else None
        except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError) as exc:
            violations.append(
                f"workspace: cannot read reviewed {package} source identity: {exc}"
            )
            continue
        if actual != package:
            violations.append(
                f"workspace: reviewed source {relative} has wrong package identity "
                f"{actual!r} (expected {package!r})"
            )
    return violations


def check_manifest(
    manifest: dict[str, Any], crate: str, workspace_dependencies: dict[str, Any] | None = None
) -> list[str]:
    """Inspect every Cargo dependency table, including target-specific tables.

    Resolve package renaming, so an innocuous dependency alias cannot silently
    bring codex-core back into a cell's compile-time type graph.
    """
    violations: list[str] = []

    def visit(value: Any, keys: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if key in DEPENDENCY_SECTIONS and isinstance(child, dict):
                for alias, declaration in child.items():
                    package = (
                        declaration.get("package", alias)
                        if isinstance(declaration, dict)
                        else alias
                    )
                    if isinstance(package, str) and prohibited_package(package):
                        location = ".".join((*keys, key))
                        violations.append(
                            f"{crate}: {location}.{alias} directly depends on "
                            f"the Codex execution crate {package}"
                        )
                        continue
                    # Cargo workspace = true inherits the root declaration,
                    # including its real package name. A harmless-looking local
                    # alias can otherwise point directly at codex-core.
                    if isinstance(declaration, dict) and declaration.get("workspace") is True:
                        if workspace_dependencies is not None:
                            inherited = workspace_dependencies.get(alias)
                            if inherited is None:
                                violations.append(
                                    f"{crate}: {key}.{alias} has no root workspace dependency"
                                )
                                continue
                            package = (
                                inherited.get("package", alias)
                                if isinstance(inherited, dict)
                                else alias
                            )
                    if isinstance(package, str) and prohibited_package(package):
                        location = ".".join((*keys, key))
                        violations.append(
                            f"{crate}: {location}.{alias} directly depends on "
                            f"the Codex execution crate {package}"
                        )
                    elif isinstance(package, str):
                        normalized = normalized_package(package)
                        location = ".".join((*keys, key))
                        origin_error = dependency_origin_violation(
                            alias, declaration, package, crate, workspace_dependencies
                        )
                        if origin_error is not None:
                            violations.append(
                                f"{crate}: {location}.{alias} source custody: {origin_error}"
                            )
                        if crate == "hepta-types" and normalized != "sha2":
                            violations.append(
                                f"{crate}: {location}.{alias} is not an approved "
                                f"foundational dependency ({package})"
                            )
                        elif (
                            crate != "hepta-types"
                            and normalized not in ALLOWED_PACKAGES
                            and normalized not in ALLOWED_EXTERNAL_PACKAGES
                        ):
                            violations.append(
                                f"{crate}: {location}.{alias} is not an approved "
                                f"Cell dependency ({package})"
                            )
            elif isinstance(child, dict):
                visit(child, (*keys, key))

    visit(manifest, ())
    return violations


def check_workspace(root: Path) -> list[str]:
    violations: list[str] = []
    workspace_file = root / "codex-rs" / "Cargo.toml"
    try:
        workspace = tomllib.loads(workspace_file.read_text(encoding="utf-8"))
        workspace_deps = workspace["workspace"]["dependencies"]
        if not isinstance(workspace_deps, dict):
            raise ValueError("workspace.dependencies must be a table")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as exc:
        return [f"workspace: cannot resolve dependency inheritance: {exc}"]
    violations.extend(check_root_source_overrides(workspace))
    violations.extend(check_local_source_directories(root))
    for name in CELL_CRATES:
        manifest_file = root / "codex-rs" / name / "Cargo.toml"
        try:
            manifest = tomllib.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            violations.append(f"{name}: cannot parse pinned Cargo manifest: {exc}")
            continue
        package_info = manifest.get("package")
        package_name = package_info.get("name") if isinstance(package_info, dict) else None
        if package_name != f"codex-{name}":
            violations.append(f"{name}: crate identity differs from expected codex-{name}")
        violations.extend(check_manifest(manifest, name, workspace_deps))
    return violations



# The Codex facade is a compatibility path, never a second ABI definition.
# Exact explicit re-exports make missing, shadowed and local aliases reviewable.
PURE_NATIVE_EXPORTS = (
    "EXECUTION_CONTRACT_VERSION_V1",
    "CellExecutionIntentV1",
    "CodexTurnBindingV1",
    "ExecutionContractError",
    "ExecutionIntentKindV1",
    "ExecutionReceiptV1",
    "ExecutionStatusV1",
    "FinalPayloadDigestV1",
    "GenerationFenceWitnessV1",
    "NativeExecutionAdapter",
    "RecoveryDispositionV1",
    "RuntimeExecutionError",
    "RuntimeReceiptV1",
    "RuntimeToolIntentV1",
    "ToolOutcomeV1",
)


def check_native_facade_exports(facade_source: str) -> list[str]:
    """Source-only ABI custody guard; Rust compilation remains mandatory."""
    import re

    violations: list[str] = []
    for name in PURE_NATIVE_EXPORTS:
        expected = rf"(?m)^[ \\t]*pub[ \\t]+use[ \\t]+codex_hepta_types[ \\t]*::[ \\t]*{re.escape(name)}[ \\t]*;[ \\t]*(?://.*)?$"
        if not re.search(expected, facade_source):
            violations.append(
                f"hepta-codex-adapter: missing direct pure ABI re-export {name}"
            )

    protected_names = "|".join(re.escape(name) for name in PURE_NATIVE_EXPORTS)
    local_definition = (
        rf"\\b(?:pub(?:\\s*\\([^)]*\\))?\\s+)?"
        rf"(?:struct|enum|trait|type|union|const|static)\\s+"
        rf"(?:{protected_names})\\b"
    )
    if re.search(local_definition, facade_source):
        violations.append("hepta-codex-adapter: duplicate execution contract definition")
    return violations


def check_pure_cell_contract(root: Path) -> list[str]:
    """Ensure source Cell contracts remain independent of Codex and effects.

    This is only a closed-world direct-source and manifest check, not binary
    transitive attestation or a runtime FinalUse grant.
    """
    import re
    errors: list[str] = []
    manifest_path = root / "codex-rs" / "hepta-types" / "Cargo.toml"
    workspace_path = root / "codex-rs" / "Cargo.toml"
    try:
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        workspace = tomllib.loads(workspace_path.read_text(encoding="utf-8"))
        root_deps = workspace["workspace"]["dependencies"]
        if manifest.get("package", {}).get("name") != "codex-hepta-types":
            errors.append("hepta-types: crate identity changed")
        inherited = root_deps.get("sha2")
        if inherited is None or (isinstance(inherited, dict) and inherited.get("package", "sha2") != "sha2"):
            errors.append("hepta-types: sha2 root dependency is absent or renamed")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as exc:
        return [f"hepta-types: cannot validate pure manifest: {exc}"]

    def visit(value: Any, scope: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        for name, child in value.items():
            if name in DEPENDENCY_SECTIONS and isinstance(child, dict):
                for alias, item in child.items():
                    package = item.get("package", alias) if isinstance(item, dict) else alias
                    # Strictly permit only the existing hash primitive; no
                    # direct or renamed Codex, runtime, network or writer deps.
                    if alias != "sha2" or package != "sha2":
                        errors.append(
                            f"hepta-types: {'.'.join((*scope, name))}.{alias} "
                            f"introduces non-pure dependency {package}"
                        )
            if isinstance(child, dict):
                visit(child, (*scope, name))

    visit(manifest, ())
    pure = root / "codex-rs" / "hepta-types" / "src" / "execution_contract.rs"
    facade = root / "codex-rs" / "hepta-codex-adapter" / "src" / "execution_contract.rs"
    try:
        pure_source = pure.read_text(encoding="utf-8")
        facade_source = facade.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return errors + [f"hepta-types: missing source/facade: {exc}"]
    if re.search(r"\bcodex_[a-z0-9_]+::|\bextern\s+crate\s+codex_", pure_source):
        errors.append("hepta-types: pure execution contract imports a Codex crate")
    if "pub trait NativeExecutionAdapter" not in pure_source:
        errors.append("hepta-types: native execution contract missing")
    errors.extend(check_native_facade_exports(facade_source))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args(argv)
    violations = check_workspace(args.root)
    violations.extend(check_pure_cell_contract(args.root))
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        return 1
    print(
        f"Cell/Codex crate isolation: {len(CELL_CRATES)} owners checked; "
        "no direct harness dependencies"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

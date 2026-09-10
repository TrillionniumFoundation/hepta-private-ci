#!/usr/bin/env python3
"""Apply the audited r13 repairs to the r7 global finalizer.

The patch is exact and one-shot: it refuses source drift, prevents inferred
workspace dependency edges from creating cycles, and removes the transient
Lane F bootstrap publisher from the reconciled candidate.
"""
from __future__ import annotations

from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label} patch precondition drifted")
    if new in text:
        raise SystemExit(f"{label} already applied unexpectedly")
    return text.replace(old, new, 1)


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")

    old_lane_f = '''        for path in conflicts:
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
'''
    new_lane_f = '''        for path in conflicts:
            if (
                lane_f_owner_conflict
                and path == ".github/workflows/lane-f-bootstrap.yml"
            ):
                git("rm", "--", path)
                continue
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
'''
    text = replace_once(text, old_lane_f, new_lane_f, "Lane F cleanup")

    marker = '''def repair_missing_local_dependencies(metadata: dict[str, Any]) -> dict[str, Any]:
'''
    helpers = '''def workspace_dependency_graph(
    metadata: dict[str, Any],
) -> dict[str, set[str]]:
    packages = workspace_package_map(metadata)
    graph: dict[str, set[str]] = {name: set() for name in packages}
    for package_name, row in packages.items():
        dependencies = row.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise RuntimeError(f"metadata dependencies are invalid for {package_name}")
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise RuntimeError(
                    f"metadata dependency row is invalid for {package_name}"
                )
            dependency_name = dependency.get("name")
            if dependency_name in packages:
                graph[package_name].add(dependency_name)
    return graph


def dependency_reaches(
    graph: dict[str, set[str]],
    start: str,
    target: str,
) -> bool:
    pending = [start]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(sorted(graph.get(current, ()), reverse=True))
    return False


def repair_missing_local_dependencies(metadata: dict[str, Any]) -> dict[str, Any]:
'''
    if "def workspace_dependency_graph(" in text:
        raise SystemExit("dependency graph helpers already exist unexpectedly")
    text = replace_once(text, marker, helpers, "dependency graph helpers")

    old_body = '''    added: list[dict[str, str]] = []
    for package_name, row in sorted(packages.items()):
        manifest = Path(row["manifest_path"])
        package_root = manifest.parent
        declared = dependency_sections(manifest.read_text(encoding="utf-8"))
        for crate_name in sorted(imported_workspace_crates(package_root)):
            target = crate_to_package.get(crate_name)
            if target is None:
                continue
            dependency_name, dependency_path = target
            if dependency_name == package_name or dependency_name in declared:
                continue
            if add_dependency(manifest, dependency_name, dependency_path):
                declared.add(dependency_name)
                added.append(
                    {
                        "package": package_name,
                        "dependency": dependency_name,
                        "manifest": manifest.relative_to(ROOT).as_posix(),
                    }
                )
    return {"added": added, "count": len(added)}
'''
    new_body = '''    graph = workspace_dependency_graph(metadata)
    added: list[dict[str, str]] = []
    skipped_cycles: list[dict[str, Any]] = []
    for package_name, row in sorted(packages.items()):
        manifest = Path(row["manifest_path"])
        package_root = manifest.parent
        declared = dependency_sections(manifest.read_text(encoding="utf-8"))
        for crate_name in sorted(imported_workspace_crates(package_root)):
            target = crate_to_package.get(crate_name)
            if target is None:
                continue
            dependency_name, dependency_path = target
            if dependency_name == package_name or dependency_name in declared:
                continue
            if dependency_reaches(graph, dependency_name, package_name):
                skipped_cycles.append(
                    {
                        "package": package_name,
                        "dependency": dependency_name,
                        "manifest": manifest.relative_to(ROOT).as_posix(),
                        "reason": "would-create-workspace-dependency-cycle",
                    }
                )
                continue
            if add_dependency(manifest, dependency_name, dependency_path):
                declared.add(dependency_name)
                graph.setdefault(package_name, set()).add(dependency_name)
                added.append(
                    {
                        "package": package_name,
                        "dependency": dependency_name,
                        "manifest": manifest.relative_to(ROOT).as_posix(),
                    }
                )
    return {
        "added": added,
        "count": len(added),
        "skippedCycles": skipped_cycles,
        "skippedCycleCount": len(skipped_cycles),
    }
'''
    text = replace_once(text, old_body, new_body, "cycle-safe dependency repair")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Partition complete browser evidence into source-bound, transferable artifacts."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

BROWSERS = ("chromium", "firefox", "webkit")
GROUPS = {"summary", "diagnostic"} | {
    f"{scope}-{browser}"
    for scope in ("default", "fixtures", "sidebar")
    for browser in BROWSERS
}


def group_for_path(relative):
    parts = relative.parts
    if len(parts) == 2 and parts[0] in ("dist", "dist-robrix-fixtures") and parts[1] == "build-manifest.json":
        return "summary"
    if len(parts) == 2 and parts[0] == "test-results" and parts[1].startswith("robrix-") and parts[1].endswith("-results.json"):
        return "summary"
    if len(parts) < 3 or parts[0] != "test-results":
        raise ValueError(f"Unclassified evidence: {relative}")
    scope = parts[1].removeprefix("robrix-")
    if scope not in ("default", "fixtures", "buffer-diagnostic") or parts[1] != f"robrix-{scope}":
        raise ValueError(f"Unclassified scope: {relative}")
    if scope == "buffer-diagnostic":
        return "diagnostic"
    if len(parts) == 3:
        return "summary"
    browser = parts[2].rsplit("-", 1)[-1]
    if browser not in BROWSERS:
        raise ValueError(f"Unclassified browser evidence: {relative}")
    if parts[2].startswith("robrix-sidebar-"):
        if scope != "fixtures":
            raise ValueError("Sidebar interaction evidence must be an explicit fixture")
        return f"sidebar-{browser}"
    return f"{scope}-{browser}"


def collect_sources(root):
    sources = []
    for scope in ("default", "fixtures", "buffer-diagnostic"):
        directory = root / "test-results" / f"robrix-{scope}"
        if directory.exists():
            sources.extend(source for source in sorted(directory.rglob("*")) if source.is_file())
    sources.extend(sorted((root / "test-results").glob("robrix-*-results.json")))
    for folder in ("dist", "dist-robrix-fixtures"):
        source = root / folder / "build-manifest.json"
        if source.exists():
            sources.append(source)
    return sources


def validate_partition(root, sources, entries):
    expected = {str(source.relative_to(root)) for source in sources}
    actual = [str(source.relative_to(root)) for source, _ in entries]
    if len(sources) != len(expected) or len(actual) != len(set(actual)):
        raise ValueError("Evidence inventory contains duplicate paths")
    if set(actual) != expected:
        raise ValueError("Evidence partition omits or adds source paths")
    for source, group in entries:
        if source.is_symlink():
            raise ValueError("Evidence must contain local regular files")
        if group != group_for_path(source.relative_to(root)):
            raise ValueError("Evidence browser/scope classification differs from its actual path")


def write_groups(root, head, sources, entries):
    output = root / "test-results" / "evidence-groups"
    if output.exists():
        raise ValueError("Evidence grouping must start in a fresh output directory")
    validate_partition(root, sources, entries)
    inventory = []
    for source, group in entries:
        relative = source.relative_to(root)
        data = source.read_bytes()
        inventory.append({"path": str(relative), "group": group, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        destination = output / group / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != inventory[-1]["sha256"]:
            raise ValueError("Evidence copy changed bytes")
    for group in sorted(GROUPS):
        selected = [entry for entry in inventory if entry["group"] == group]
        manifest = {"schema": "hepta.robrix-browser-evidence.v1", "sourceSha": head, "group": group, "qualification": False, "files": inventory if group == "summary" else selected}
        target = output / group / "evidence-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, indent=2) + "\n")
        print(group, len(selected), sum(entry["bytes"] for entry in selected))
    return inventory


def main():
    root = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != os.environ["SOURCE_SHA"]:
        raise ValueError("Evidence source differs from the evaluated head")
    sources = collect_sources(root)
    entries = [(source, group_for_path(source.relative_to(root))) for source in sources]
    write_groups(root, head, sources, entries)


if __name__ == "__main__":
    main()

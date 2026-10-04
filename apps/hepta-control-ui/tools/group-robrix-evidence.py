"""Partition complete browser evidence into source-bound, transferable artifacts."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
head = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=root, text=True
).strip()
if head != os.environ["SOURCE_SHA"]:
    raise ValueError("Evidence source differs from the evaluated head")
output = root / "test-results" / "evidence-groups"
if output.exists():
    raise ValueError("Evidence grouping must start in a fresh output directory")
entries = []
for scope in ("default", "fixtures", "buffer-diagnostic"):
    directory = root / "test-results" / f"robrix-{scope}"
    if not directory.exists():
        continue
    for source in sorted(directory.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(directory)
        if scope == "buffer-diagnostic":
            group = "diagnostic"
        elif len(relative.parts) == 1:
            group = "summary"
        else:
            browser = relative.parts[0].rsplit("-", 1)[-1]
            if browser not in ("chromium", "firefox", "webkit"):
                raise ValueError(f"Unclassified browser evidence: {relative}")
            group = f"{scope}-{browser}"
        entries.append((source, group))
for source in sorted((root / "test-results").glob("robrix-*-results.json")):
    entries.append((source, "summary"))
for folder in ("dist", "dist-robrix-fixtures"):
    source = root / folder / "build-manifest.json"
    if source.exists():
        entries.append((source, "summary"))
inventory = []
for source, group in entries:
    if source.is_symlink():
        raise ValueError("Evidence must contain local regular files")
    relative = source.relative_to(root)
    data = source.read_bytes()
    inventory.append(
        {
            "path": str(relative),
            "group": group,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )
    destination = output / group / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != inventory[-1]["sha256"]:
        raise ValueError("Evidence copy changed bytes")
if len({entry["path"] for entry in inventory}) != len(inventory):
    raise ValueError("Evidence inventory contains duplicate paths")
groups = {"summary", "diagnostic"} | {
    f"{scope}-{browser}"
    for scope in ("default", "fixtures")
    for browser in ("chromium", "firefox", "webkit")
}
for group in sorted(groups):
    selected = [entry for entry in inventory if entry["group"] == group]
    manifest = {
        "schema": "hepta.robrix-browser-evidence.v1",
        "sourceSha": head,
        "group": group,
        "qualification": False,
        "files": inventory if group == "summary" else selected,
    }
    target = output / group / "evidence-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    print(group, len(selected), sum(entry["bytes"] for entry in selected))

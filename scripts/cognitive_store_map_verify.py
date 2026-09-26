#!/usr/bin/env python3
"""Verify the cognitive.store implementation map against one exact Git candidate.

This intentionally scopes verification to cognitive.store. The global map
verifier remains available for repository-wide governance, but unrelated
historical branch provenance cannot cancel this module's independent receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def git(*args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def source_path(value: Any) -> str | None:
    if isinstance(value, str):
        path = value
    elif isinstance(value, dict):
        path = value.get("path", value.get("sourcePath"))
    else:
        return None
    if not isinstance(path, str) or not path:
        return None
    if ".rs::" in path:
        path = path.split(".rs::", 1)[0] + ".rs"
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha")
    parser.add_argument("--expected-tree")
    args = parser.parse_args()

    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    for value, label, observed in (
        (args.expected_sha, "expected SHA", head),
        (args.expected_tree, "expected tree", tree),
    ):
        if value is not None and (HEX40.fullmatch(value) is None or value != observed):
            raise SystemExit(f"FAIL_COGNITIVE_STORE_MAP: {label} mismatch")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: candidate checkout is not clean")

    row = json.loads(MAP.read_text(encoding="utf-8"))
    if row.get("schema") != "hepta.module-implementation-map.v3" or row.get("module") != "cognitive.store":
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: wrong schema or module identity")
    base = row.get("sourceBase")
    if not isinstance(base, dict) or HEX40.fullmatch(str(base.get("commit", ""))) is None or HEX40.fullmatch(str(base.get("tree", ""))) is None:
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: invalid sourceBase")
    if git("rev-parse", f"{base['commit']}^{{tree}}") != base["tree"]:
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: sourceBase tree mismatch")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", base["commit"], head],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    paths: set[str] = set(row.get("resolvedRoots", []))
    paths.add(row["technicalGuide"])
    for caller in row.get("productCallers", []):
        path = source_path(caller)
        if path:
            paths.add(path)
    for operation in row.get("operations", []):
        path = source_path(operation.get("sourcePath"))
        if path:
            paths.add(path)
        for key in ("tests", "delegatedCallees"):
            for entry in operation.get(key, []):
                path = source_path(entry)
                if path:
                    paths.add(path)
    missing = sorted(path for path in paths if not (ROOT / path).exists())
    if missing:
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: missing mapped paths: " + ", ".join(missing))

    objects = row.get("sourceObjects")
    if not isinstance(objects, list) or not objects:
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: sourceObjects are absent")
    observed: dict[str, str] = {}
    for entry in objects:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or HEX40.fullmatch(str(entry.get("object", ""))) is None:
            raise SystemExit("FAIL_COGNITIVE_STORE_MAP: malformed source object")
        path = entry["path"]
        if path in observed:
            raise SystemExit("FAIL_COGNITIVE_STORE_MAP: duplicate source object: " + path)
        current = git("rev-parse", f"HEAD:{path}")
        if current != entry["object"]:
            raise SystemExit("FAIL_COGNITIVE_STORE_MAP: source object drift: " + path)
        observed[path] = current
    uncovered = sorted(path for path in paths if path not in observed)
    if uncovered:
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: mapped paths lack exact objects: " + ", ".join(uncovered))

    canonical = [
        caller for caller in row.get("productCallers", [])
        if caller.get("state") == "canonical_production_write_facade"
    ]
    if canonical != [{
        "sourcePath": "codex-rs/hepta-agentd/src/production_writer_host.rs",
        "nativeSymbol": "AgentdProductionWriterHost",
        "state": "canonical_production_write_facade",
    }]:
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: canonical facade is not unique")
    boundary = row.get("claimBoundary", {})
    for name in ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release"):
        if boundary.get(name) is not False:
            raise SystemExit("FAIL_COGNITIVE_STORE_MAP: unproved claim is not false: " + name)

    print(json.dumps({
        "status": "PASS_COGNITIVE_STORE_MAP",
        "candidate": {"commit": head, "tree": tree},
        "sourceBase": base,
        "mappedPaths": len(paths),
        "sourceObjects": len(objects),
        "canonicalFacade": canonical[0],
        "executionClaim": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

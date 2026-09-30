#!/usr/bin/env python3
"""Explicit source-authoring preparation; never run by qualification.

Works only on a clean, exact cognitive.read PR candidate. Produces ordinary
source and documentation commits. Does not execute, waive or issue acceptance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import tomllib

from cognitive_read_delivery_gates import GUIDE as DELIVERY_GUIDE
from cognitive_read_delivery_gates import SOURCE_PATHS as DELIVERY_SOURCE_PATHS

ROOT = Path(__file__).resolve().parents[1]
BASE = "a126987b84737dbc2ee2592442a314117bddb4a2"
MAP = "docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"
SUPPLEMENT = "docs/modules/cognitive.read/FINAL_USE_CLOSURE.md"
AGENTD = "codex-rs/hepta-agentd/src/"
MEMORY = "codex-rs/hepta-memory/src/"
CAPACITY_GUIDE = "docs/modules/cognitive.read/SELECTED_OWNER_CUT.md"
INTEGRATION_PATHS = [MEMORY + "lane_c_snapshot.rs", MEMORY + "lib.rs", AGENTD + "cognitive_context.rs", AGENTD + "cognitive_context_final_use.rs"]
NEW_PATHS = [AGENTD + "cognitive_context_" + suffix + ".rs" for suffix in (
    "final_use", "plan", "plan_tests", "observation", "observation_tests", "closure_tests",
)] + [MEMORY + "lane_c_selected_snapshot.rs", MEMORY + "lane_c_selected_snapshot_tests.rs"] + list(DELIVERY_SOURCE_PATHS)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "--literal-pathspecs", *args], cwd=ROOT, text=True).strip()


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def replace_once(path: Path, old: str, new: str) -> None:
    body = path.read_text()
    if old not in body and body.count(new) == 1:
        return
    if body.count(old) != 1:
        raise ValueError(f"source shape drift: {path.relative_to(ROOT)}")
    path.write_text(body.replace(old, new, 1))


def prepare_sources() -> None:
    run("python3", "scripts/apply-cognitive-read-selected-cut.py", "--expected-sha", git("rev-parse", "HEAD"))
    replace_once(
        ROOT / (AGENTD + "cognitive_context_final_use.rs"),
        "use crate::CognitiveContextRevalidation;\n",
        "use super::CognitiveContextRevalidation;\n",
    )
    lock = ROOT / "codex-rs/Cargo.lock"
    before_text = lock.read_text()
    before = tomllib.loads(before_text)
    package = [p for p in before["package"] if p["name"] == "codex-hepta-agentd"]
    if len(package) != 1:
        raise ValueError("expected one workspace Agentd lock entry")
    if "codex-otel" not in package[0].get("dependencies", []):
        pattern = re.compile(r'(?ms)^\[\[package\]\]\nname = "codex-hepta-agentd"\n.*?(?=^\[\[package\]\]|\Z)')
        matches = list(pattern.finditer(before_text))
        if len(matches) != 1 or matches[0].group().count("dependencies = [\n") != 1:
            raise ValueError("unexpected Agentd Cargo.lock stanza")
        match = matches[0]
        stanza = match.group().replace("dependencies = [\n", 'dependencies = [\n "codex-otel",\n', 1)
        start = stanza.index("dependencies = [\n") + len("dependencies = [\n")
        end = stanza.index("\n]", start)
        deps = sorted(stanza[start:end].splitlines())
        stanza = stanza[:start] + "\n".join(deps) + stanza[end:]
        after_text = before_text[:match.start()] + stanza + before_text[match.end():]
        after = tomllib.loads(after_text)
        expected = json.loads(json.dumps(before))
        next(p for p in expected["package"] if p["name"] == "codex-hepta-agentd")["dependencies"] = sorted(
            package[0]["dependencies"] + ["codex-otel"]
        )
        if after != expected:
            raise ValueError("lock repair changed more than the Agentd direct dependency")
        lock.write_text(after_text)
    allowed = set(git("diff", "--name-only", BASE, "HEAD", "--", "codex-rs").splitlines())
    allowed.add("codex-rs/Cargo.lock")
    allowed.update(INTEGRATION_PATHS)
    run("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all")
    changed = git("diff", "--name-only").splitlines()
    for path in changed:
        if path not in allowed or not (path.endswith(".rs") or path == "codex-rs/Cargo.lock"):
            raise ValueError(f"formatter escaped reviewed source paths: {path}")
    run("git", "diff", "--check")
    if changed:
        run("git", "add", "--", *changed)
        run("git", "commit", "-m", "fix(cognitive.read): integrate selected owner cuts and prepare locked source")


def refresh_map() -> None:
    source = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    path = ROOT / MAP
    mapping = json.loads(path.read_text())
    before_flags = json.dumps(mapping.get("claimBoundary"), sort_keys=True)
    if mapping.get("productionImplementation") is not False:
        raise ValueError("source preparation cannot elevate production state")
    for name in ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release"):
        if mapping["claimBoundary"].get(name) is not False:
            raise ValueError(f"source preparation cannot elevate {name}")
    for identity in ("sourceBase", "observedAtHead"):
        mapping[identity] = {"commit": source, "tree": tree}
    objects = {entry["path"]: entry for entry in mapping["sourceObjects"]}
    for name in NEW_PATHS + INTEGRATION_PATHS + [SUPPLEMENT, CAPACITY_GUIDE, DELIVERY_GUIDE, "scripts/apply-cognitive-read-selected-cut.py"]:
        if not (ROOT / name).is_file():
            raise ValueError(f"required closure source is absent: {name}")
        objects.setdefault(name, {"path": name})
    for name, entry in objects.items():
        entry["object"] = git("rev-parse", f"{source}:{name}")
    mapping["sourceObjects"] = [objects[name] for name in sorted(objects)]
    exact = mapping.get("exactSourceEvidence")
    if isinstance(exact, dict):
        for entry in exact.get("entries", []):
            entry["blobSha"] = objects[entry["path"]]["object"]
    if not any(op["operation"] == "durable_cognitive_selection_snapshot" for op in mapping["operations"]):
        mapping["operations"].append({
            "operation": "durable_cognitive_selection_snapshot",
            "nativeSymbol": "lane_c_snapshot_ids",
            "sourcePath": MEMORY + "lane_c_selected_snapshot.rs",
            "state": "source_implemented_product_composed",
            "authority": "none",
            "tests": [MEMORY + "lane_c_selected_snapshot_tests.rs"],
            "sourcePathExists": True,
            "designOperation": "acquire_snapshot",
            "mappingClass": "existing_owner_adapter",
            "delegatedCallees": [MEMORY + "lane_c_snapshot.rs"],
            "sourceBlob": git("rev-parse", f"{source}:{MEMORY}lane_c_selected_snapshot.rs"),
        })
    for operation in mapping["operations"]:
        if operation["operation"] == "final_use_revalidate":
            operation["sourcePath"] = AGENTD + "cognitive_context_final_use.rs"
            operation["tests"] = sorted(set(operation["tests"] + [p for p in NEW_PATHS if p.endswith("_tests.rs")]))
            callees = operation.setdefault("delegatedCallees", [])
            for name in [AGENTD + "cognitive_context.rs", AGENTD + "cognitive_context_plan.rs", AGENTD + "cognitive_context_observation.rs", MEMORY + "lane_c_selected_snapshot.rs"]:
                if name not in callees:
                    callees.append(name)
        if "sourceBlob" in operation:
            operation["sourceBlob"] = git("rev-parse", f'{source}:{operation["sourcePath"]}')
    for caller in mapping["productCallers"]:
        if caller["role"] == "owner_final_use_revalidation":
            caller["sourcePath"] = AGENTD + "cognitive_context_final_use.rs"
        caller["blobSha"] = git("rev-parse", f'{source}:{caller["sourcePath"]}')
    mapping["observedSourcePaths"] = sorted(set(mapping.get("observedSourcePaths", []) + NEW_PATHS + INTEGRATION_PATHS + [SUPPLEMENT, CAPACITY_GUIDE, DELIVERY_GUIDE]))
    supplements = mapping.setdefault("technicalSupplements", [])
    for guide in [SUPPLEMENT, CAPACITY_GUIDE, DELIVERY_GUIDE]:
        if guide not in supplements:
            supplements.append(guide)
    if json.dumps(mapping.get("claimBoundary"), sort_keys=True) != before_flags:
        raise ValueError("preparation changed evidence claims")
    path.write_text(json.dumps(mapping, indent=2) + "\n")
    run("git", "diff", "--check")
    run("git", "add", "--", MAP)
    if git("diff", "--cached", "--name-only"):
        run("git", "commit", "-m", "docs(cognitive.read): bind closure map to immutable source parent")
    run("python3", "scripts/verify-cognitive-read-map.py", "--expected-sha", git("rev-parse", "HEAD"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) or git("rev-parse", "HEAD") != args.expected_sha:
        raise ValueError("source preparation requires its exact authored candidate")
    if git("status", "--porcelain"):
        raise ValueError("source preparation requires a clean checkout")
    prepare_sources()
    refresh_map()
    print(f'SOURCE_PREPARED_HEAD={git("rev-parse", "HEAD")}')


if __name__ == "__main__":
    main()

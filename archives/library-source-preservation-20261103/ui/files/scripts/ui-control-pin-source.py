#!/usr/bin/env python3
"""Refresh only exact Rust UI source observations after mapped source is committed.

This writes navigation metadata, never qualification or release claims. The
ordinary source-map verifier still requires the entire candidate to be clean.
"""
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = "docs/modules/ui.control/IMPLEMENTATION_MAP.json"
MANIFEST_PATH = "qualification/ui-control/UI_CONTROL_MANIFEST.json"


def main():
    maps = runpy.run_path(str(Path(__file__).with_name("hepta-implementation-maps.py")))
    row = maps["load"](MAP_PATH)
    manifest = maps["load"](MANIFEST_PATH)
    if manifest.get("implementationLanguage") != "rust":
        raise ValueError("only the canonical Rust migration is supported")
    if maps["validate_claim_types"](row):
        raise ValueError("source rebinding cannot transfer any executable evidence")
    maps["validate_closed_world_bindings"](row)
    for flag in ["productExecutionComplete", "deploymentQualificationComplete", "independentAcceptanceComplete",
                 "productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release"]:
        if row["claimBoundary"].get(flag) is not False:
            raise ValueError("source rebinding cannot preserve or manufacture executable qualification")
    candidate = maps["current_source_base"]()
    paths = maps["tracked_source_paths"](row)
    if maps["git"]("diff", "--name-only", candidate["commit"], "--", *paths):
        raise ValueError("commit every mapped source path before rebinding")
    objects = [{"path": path, "object": maps["git"]("rev-parse", f"{candidate['commit']}:{path}")} for path in paths]
    if maps["current_source_base"]() != candidate:
        raise ValueError("candidate changed during source binding")
    manifest["sourceObservation"] = candidate
    manifest["sourceObjects"] = objects
    (ROOT / MANIFEST_PATH).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["node", "scripts/ui-control-artifacts.mjs", "--write"], cwd=ROOT, check=True)
    print(f"Bound {len(objects)} source objects to {candidate['commit']}; no execution or release authority")


if __name__ == "__main__":
    main()

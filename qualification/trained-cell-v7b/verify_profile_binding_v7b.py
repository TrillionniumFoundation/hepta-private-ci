"""Actual cross-profile rejection checks; V7 and V7b evidence remain immutable."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"trained-cell-v7"))
from handoff_v7 import canonical, checkpoint, require, sha, verified_modules
from qualify_grid_handoff_v7b import INPUT_SHA, PROTOCOL, SOURCE_SHA


def run(workspace, native, output):
    workspace, native, output = map(Path, (workspace, native, output))
    old_path = workspace/"pft-native-v7-development-inputs/manifest.json"
    new_path = workspace/"pft-native-v7b-development-inputs/manifest.json"
    require(sha(old_path.read_bytes()) == "14e2293f83878d70e76754f3de6f5c5b7e4b689fbec1aed728b5f955a0a159b4"
        and sha(new_path.read_bytes()) == INPUT_SHA, "pinned profile manifests changed")
    old, new = json.loads(old_path.read_bytes()), json.loads(new_path.read_bytes())
    code = workspace/"hepta-repo-v7b/qa/stem-bakeoff"
    old_grid, grid = workspace/"pft-development-v7/grid", workspace/"pft-development-v7b/grid"
    closure = (grid/"executed_source.json").read_bytes()
    states, _, _ = verified_modules(code, {}, closure, SOURCE_SHA)
    fit = "v5-agnews-seed7-linear"
    previous = next(r for r in old["rows"] if r["fit_id"] == fit and r["step"] == 17)
    current = next(r for r in new["rows"] if r["fit_id"] == fit and r["step"] == 17)
    require(previous["state_sha256"] == current["state_sha256"], "physical control fixture unexpectedly differs")
    location = Path(current["directory"])/"state"
    meta = json.loads((location/"manifest.json").read_bytes())
    state = states.CellTrainingState.load(location, meta["bindings"], meta["protocol"], meta["contexts"], current["state_sha256"])
    output.mkdir(parents=True, exist_ok=False)
    checks = []
    for name, action, message in [
        ("old_controller_under_new_contract", lambda: checkpoint(state,
            (Path(previous["directory"])/"controller.json").read_bytes(), new["contracts"][fit], code, closure),
            "controller contract changed"),
        ("old_source_map_under_new_source_pin", lambda: verified_modules(code, {},
            (old_grid/"executed_source.json").read_bytes(), SOURCE_SHA), "controller source closure changed")]:
        try:
            action()
        except ValueError as error:
            require(message in str(error), "unexpected rejection boundary")
            checks.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise AssertionError("cross-profile state accepted")
    loader = workspace/"pft-audit-v7b-development"
    require(sha((loader/"export_v7b_planning_only.py").read_bytes()) ==
        "7cfa568c7841df105510df3e0b180df984758c4d1b676a8039aff6abfb5d0cae", "planning loader changed")
    sys.path.insert(0, str(loader))
    from export_v7b_planning_only import load_planning

    try:
        load_planning(workspace/"pft-development-v7/planning-only", "v5", "agnews", grid)
    except ValueError as error:
        require("frozen V7b execution" in str(error), "unexpected planning rejection")
        checks.append({"case": "old_planning_manifest_under_new_grid", "rejected": True, "reason": str(error)})
    else:
        raise AssertionError("old planning profile accepted")
    group = workspace/"pft-native-grid-handoff-v7b/v5/step17"
    payload = group/"handoff.bin"
    refused = output/"must-not-exist.json"
    result = subprocess.run([str(native), str(payload), sha(payload.read_bytes()), old["protocol_sha256"],
        str(group), str(refused)], capture_output=True, text=True)
    require(result.returncode != 0 and not refused.exists() and "controller protocol differs" in result.stderr,
            "native decoder accepted old protocol pin or wrote a false receipt")
    checks.append({"case": "new_native_payload_under_old_protocol_pin", "rejected": True,
        "exit_code": result.returncode, "reason": result.stderr.strip(), "output_created": False})
    prior = json.loads((workspace/"pft-native-grid-handoff-v7/qualification.json").read_bytes())
    require(sha(native.read_bytes()) == prior["native_binary_sha256"] and state.digest() == current["state_sha256"],
        "native executable or physical input state changed")
    receipt = {"schema": "hepta.native-cross-profile-rejection.v7b", "protocol_sha256": PROTOCOL,
        "source_sha256": SOURCE_SHA, "old_protocol_sha256": old["protocol_sha256"],
        "input_manifest_sha256": INPUT_SHA, "physical_state_sha256_equal_across_profiles": current["state_sha256"],
        "unchanged_native_binary_sha256": sha(native.read_bytes()), "checks": checks,
        "all_rejected": len(checks) == 4, "source_sha256_self": sha(Path(__file__).read_bytes()),
        "candidate_published": False, "scientific_acceptance": False, "production_authority": False}
    (output/"qualification.json").write_bytes(canonical(receipt)+b"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "native", "output"):
        parser.add_argument("--"+name, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({"rejected": len(result["checks"]), "all_rejected": result["all_rejected"]}))

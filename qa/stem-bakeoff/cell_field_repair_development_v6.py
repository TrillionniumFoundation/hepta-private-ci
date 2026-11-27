"""Fixed-rule V6 repair on previously disclosed V5 rejected probe-only blocks."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from cell_field_action_io import write_json
from cell_field_features import file_hash
from cell_field_repair_v6 import repair_sequence
from cell_field_replay_v4 import _arrays, _read, _require, _verified_protocol
from cell_field_replay_v5 import _deny
from cell_field_state import CellTrainingState
from cell_learning_models import normalize_features


PROTOCOL_SHA256 = "654994abfb66e8872b0d6632b7d80d5058ad5af06adc2d2dea0de628395ba05e"


def run(v5_run, protocol, output):
    sys.addaudithook(_deny)
    root,protocol,target = map(Path,(v5_run,protocol,output))
    _require(not target.exists() and not target.resolve().is_relative_to(root.resolve()), "fresh external development output")
    plan,seal = _verified_protocol(root,protocol,PROTOCOL_SHA256)
    rows = []
    for fit in _read(root/"run.json")["fits"]:
        directory = root/fit["task"]/f"seed{fit['seed']}-{fit['head']}"
        path = directory/"mpc/response_h8_guarded"
        previous = _read(path/"result.json")
        if previous["status"] == "completed":
            continue
        _require(previous["status"] == "not_executed_rejected" and previous["completed_steps"] == 24,
                 "registered development target must be the known rejected fourth block")
        training = _arrays(root/fit["task"]/"training.npz")
        data = {r:(training[r+"_x"],training[r+"_y"]) for r in ("current_train","old_probe")}
        metadata = _read(path/"midpoint/manifest.json")
        state = CellTrainingState.load(path/"midpoint",metadata["bindings"],metadata["protocol"],
            metadata["contexts"],previous["state_digests"][16])
        trace,receipts = _arrays(path/"trajectory.npz"),_read(path/"receipts.json")
        for k in range(16,24):
            _require(state.advance(*data["current_train"],intervention=plan["h"]*trace["actions"][k]) == receipts[k],
                     "original candidate prefix must replay exactly")
        _require(state.digest() == previous["terminal_state_sha256"], "original rejection checkpoint identity")
        anchor = _read(directory/"warmup/result.json")["old_anchor"]
        actions = _arrays(path/"plans/3.npz")["actions"]
        result = repair_sequence(state,data,actions,anchor,horizon=8,dt=plan["h"],
                                 action_bound=plan["policy_configuration"]["action_bound"])
        record = result["record"]
        if record["certified"]:
            independent = state.clone()
            x,y = data["old_probe"]
            for k,action in enumerate(result["arrays"]["actions"]):
                _require(independent.advance(*data["current_train"],intervention=plan["h"]*action) == result["receipts"][k],
                         "repaired receipt independent replay")
                _require(np.array_equal(independent.vector(),result["arrays"]["states"][k+1]), "repaired state independent replay")
                _require(independent.head.loss_gradients(normalize_features(x),y,0.)[0] <= anchor, "repaired probe threshold")
            _require(independent.digest() == result["state"].digest(), "repaired terminal full-state identity")
        else:
            _require(result["state"].digest() == state.digest(), "failed repair must leave full checkpoint unchanged")
        rows.append({"fit_id":fit["fit_id"],"original_status":previous["status"],"original_steps":24,
            "original_plan_sha256":file_hash(path/"plans/3.npz"),"repair":record,
            "repaired_actions_sha256":hashlib.sha256(result["arrays"]["actions"].tobytes()).hexdigest()})
    _require(len(rows) == 3, "all three original rejected candidate blocks required")
    _verified_protocol(root,protocol,PROTOCOL_SHA256)
    report = {"schema":"hepta.cell-field-fixed-repair-development.v6","status":"completed",
        "source_protocol_sha256":PROTOCOL_SHA256,"sealed_source_files":len(seal["files"]),
        "source_sha256":{name:file_hash(Path(__file__).parent/name) for name in
            ("cell_field_repair_v6.py","cell_field_repair_development_v6.py")},
        "outcomes":dict(Counter(r["repair"]["status"] for r in rows)),"rows":rows,
        "scope":"three previously known V5 probe-only rejections; fixed rule, no held-out labels or scientific acceptance",
        "source_run_unchanged":True,"authority":"DENY_ALL","production_authority":False}
    write_json(target,report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("v5-run","protocol","output"):
        parser.add_argument("--"+name,required=True)
    report = run(**vars(parser.parse_args()))
    print(json.dumps({"outcomes":report["outcomes"],"rows":[{"fit":r["fit_id"],
        "status":r["repair"]["status"],"repaired_steps":r["repair"]["repaired_steps"],
        "maximum_future_excess":r["repair"].get("maximum_future_excess"),
        "cpu_ns":r["repair"]["cpu_ns"]} for r in report["rows"]]}))

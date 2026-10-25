"""Fresh paired guard/repair census and frozen finite-window field forecasts."""

import json

import numpy as np

from cell_field_action_io import save_arrays,write_json
from cell_field_experiments_v5 import fixed_anchor as reference_fixed,pressure_census as guard_census
from cell_field_features import file_hash
from cell_field_fixed_actions import fixed_library
from cell_field_observable_v6 import build_field
from cell_field_repair_v6 import repair_sequence
from cell_field_state import CellTrainingState


def fixed_anchor(state,split,plan,projected,retention_indices,old_anchor,output):
    # This file is committed before reference_fixed executes even its zero branch.
    response,field=build_field(state,split,horizon=8,dt=plan["h"])
    actions=np.asarray([u for _,u in fixed_library(state.parameter_count)])
    predictions=[]
    for action in actions:
        sequence=np.zeros((8,state.parameter_count));sequence[0]=action
        predictions.append(field.forecast(sequence)["losses"])
    extra=output.parent/(output.name+"-future-field.npz")
    save_arrays(extra,{"actions":actions,"predictions":np.asarray(predictions),**field.arrays()})
    metadata={"initial_state_sha256":state.digest(),"predictions_sha256":file_hash(extra),
        "field_dimensions":[len(x) for x in field.observations],"reference_cpu_ns":response.cpu_ns,
        "field_cpu_ns":field.cpu_ns,"field_wall_ns":field.wall_ns,
        "scope":"finite-window LTV loss state; frozen before actual fixed branches"}
    write_json(extra.with_suffix(".json"),metadata)
    result=reference_fixed(state,split,plan,projected,retention_indices,old_anchor,output)
    result["future_field"]=metadata
    return result


def pressure_census(warmup,split,plan,projected,retention_indices,output):
    original=guard_census(warmup,split,plan,projected,retention_indices,output)
    (output/"results.json").rename(output/"guarded-results.json")
    rows=[]
    for checkpoint in ("prevention","recovery"):
        directory=output/checkpoint
        if not directory.exists():
            continue
        (directory/"verified").rename(directory/"guarded")
        manifest=json.loads((directory/"initial/manifest.json").read_bytes())
        state=CellTrainingState.load(directory/"initial",manifest["bindings"],manifest["protocol"],
                                     manifest["contexts"],manifest["state_sha256"])
        frozen=json.loads((directory/"frozen_plans.json").read_bytes())
        anchor=original["search"]["old_anchor"]
        for i,candidate in enumerate(frozen["plans"]):
            actions=None
            path=directory/f"plans/{i}.npz"
            if path.is_file():
                with np.load(path,allow_pickle=False) as a:
                    actions=a["actions"]
            repaired=repair_sequence(state,{k:split[k] for k in ("current_train","old_probe")},actions,anchor,
                horizon=8,dt=plan["h"],action_bound=candidate["bound"],candidate_status=candidate["record"]["status"],commit_steps=8)
            arrays=dict(repaired["arrays"])
            arrays["retention_probabilities"]=np.asarray([state.head_from_vector(v).predict_proba(projected[retention_indices]) for v in arrays["states"]])
            arrays["terminal_probabilities"]=repaired["state"].head.predict_proba(projected)
            save_arrays(directory/f"verified/{i}.npz",arrays)
            row={"checkpoint":checkpoint,"candidate_id":candidate["id"],"plan":candidate["record"],
                 "verification":repaired["record"],"actual_publication":False}
            rows.append(row);write_json(directory/f"verified/{i}.json",row)
    write_json(output/"results.json",rows)
    return {"search":original["search"],"registered_slots":26,"instantiated_slots":len(rows),
        "certified":sum(r["verification"]["certified"] for r in rows),
        "guard_certified":original["certified"],"rows":rows,
        "scope":"paired prospective guard and repair; original warmup threshold and identical intended actions"}

"""Execute the frozen V6 fresh-source experiment before opening evaluation labels."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

from cell_field_action_io import environment, save_arrays, source_hashes, write_json
from cell_field_experiments_v6 import fixed_anchor, pressure_census
from cell_field_features import file_hash
from cell_field_io_v4 import load_task, seal_run
from cell_field_joint_run_v4 import warm_state
from cell_field_policy_v6 import execute_policy


def deny_withheld(event, arguments):
    if event == "open" and arguments:
        name = str(arguments[0]).lower()
        if "validation_labels" in name or "final_labels" in name or "label-key" in name:
            raise PermissionError("runner cannot open withheld evaluation labels or decryption keys")


def save_policy(result, projected, output):
    output.mkdir(parents=True, exist_ok=False)
    result["states"][0].save(output/"initial")
    if len(result["states"]) > 16:
        result["states"][16].save(output/"midpoint")
    result["state"].save(output/"terminal")
    began,cpu = time.perf_counter_ns(),time.process_time_ns()
    probabilities = np.asarray([state.head.predict_proba(projected) for state in result["states"]])
    prediction_cost = {"cpu_ns":time.process_time_ns()-cpu,"wall_ns":time.perf_counter_ns()-began}
    save_arrays(output/"trajectory.npz", {"states":np.asarray([s.vector() for s in result["states"]]),
        "actions":result["actions"],"probabilities":probabilities,"terminal_probabilities":probabilities[-1]})
    write_json(output/"receipts.json",result["receipts"])
    for i,plan in enumerate(result["plans"]):
        save_arrays(output/f"plans/{i}.npz", {"maps":plan["maps"],
            "reference_states":plan["reference_states"],"reference_observations":plan["reference_observations"],
            **({"actions":plan["actions"]} if plan["actions"] is not None else {})})
        write_json(output/f"plans/{i}.json",plan["record"])
        if "field_arrays" in plan:
            save_arrays(output/f"plans/{i}-field.npz",plan["field_arrays"])
    result["record"]["unlabelled_scoring_prediction_cost"] = prediction_cost
    result["record"]["state_digests"] = [s.digest() for s in result["states"]]
    write_json(output/"result.json",result["record"])
    return result["record"]


def execute(data,features,protocol,output):
    sys.addaudithook(deny_withheld)
    data,features,protocol,output = map(Path,(data,features,protocol,output))
    plan = json.loads(protocol.read_bytes())
    if plan["schema"] != "hepta.cell-field-fresh-protocol.v6":
        raise ValueError("exact pre-outcome V6 protocol required")
    output.mkdir(parents=True,exist_ok=False)
    hashes = source_hashes()
    write_json(output/"executed_source.json",hashes)
    write_json(output/"protocol.json",plan)
    began,cpu = time.perf_counter_ns(),time.process_time_ns()
    summary = {"schema":"hepta.cell-field-fresh-run.v6","started_at":datetime.now(timezone.utc).isoformat(),
        "fits":[],"tasks":{},"registered_fits":12,"registered_policy_outputs":72,
        "protocol_sha256":file_hash(protocol),"authority":"DENY_ALL","production_authority":False}
    for task in plan["tasks"]:
        inputs = load_task(data/task,features/task,protocol,task)
        split,projected = inputs["split"],inputs["projected"]
        indices = np.asarray([r["index"] for r in inputs["sources"] if r["role"]=="old_test"])
        save_arrays(output/task/"projected.npz",{"features":projected,"projection":inputs["projection"]})
        save_arrays(output/task/"training.npz",{role+"_"+suffix:v for role,pair in split.items() for suffix,v in zip(("x","y"),pair)})
        write_json(output/task/"inputs.json",{"input_hashes":inputs["input_hashes"],"feature_report":inputs["feature_report"],
            "retention_indices":indices.tolist(),"sources":inputs["sources"],"data_receipt":inputs["receipt"]})
        summary["tasks"][task] = {"rows":len(projected),"feature_report":inputs["feature_report"]}
        for seed in plan["seeds"]:
            for head in plan["head_modes"]:
                fit_id = f"{task}-seed{seed}-{head}"
                directory = output/task/f"seed{seed}-{head}"
                row = {"fit_id":fit_id,"task":task,"seed":seed,"head":head,"status":"failed","fixed":[],"mpc":[]}
                summary["fits"].append(row)
                try:
                    warmup,warm = warm_state(task,seed,head,inputs,directory/"warmup",hashes)
                    row["warmup"] = warm
                    baseline,offset = warmup.clone(),0
                    for target in plan["anchor_offsets"]:
                        while offset < target:
                            baseline.advance(*split["current_train"])
                            offset += 1
                        item = fixed_anchor(baseline,split,plan,projected,indices,warm["old_anchor"],directory/f"fixed/anchor{target}")
                        row["fixed"].append({"offset":target,**item})
                    row["pressure"] = pressure_census(warmup,split,plan,projected,indices,directory/"pressure")
                    for policy in plan["mpc"]["policies"]:
                        result = execute_policy(warmup,split,warm["old_anchor"],policy,plan["policy_configuration"])
                        record = save_policy(result,projected,directory/"mpc"/policy)
                        row["mpc"].append({k:record[k] for k in ("policy","status","cpu_ns","wall_ns","completed_steps")})
                    row["status"] = "completed" if all(r["status"]=="completed" for r in row["fixed"]) else "incomplete_fixed"
                except Exception as error:
                    row["error"] = {"type":type(error).__name__,"message":str(error)}
                write_json(directory/"fit.json",row)
                write_json(output/"run.json",summary)
                print(json.dumps({"fit":fit_id,"status":row["status"],
                    "fixed_completed":sum(r["completed"] for r in row["fixed"]),"policies":row["mpc"],"error":row.get("error")}),flush=True)
    summary.update(cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-began,
        environment=environment(),completed_at=datetime.now(timezone.utc).isoformat())
    write_json(output/"run.json",summary)
    seal_run(output,protocol)
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("data","features","protocol","output"):
        parser.add_argument("--"+name,required=True)
    execute(**vars(parser.parse_args()))

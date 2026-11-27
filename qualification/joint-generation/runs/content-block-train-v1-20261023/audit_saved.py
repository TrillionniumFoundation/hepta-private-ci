"""Inspect saved TRAIN updates/clocks/costs and PNGs without rerunning models."""

import base64
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image

from content_block.learning import HEADS, heads_work
from content_block.run import PRIOR
from data import parse_caption, templates
from independent.accounting import WorkLedger
from independent.learning import CONTENT_PARAMETERS, step_work
from model import JointModel


started=time.process_time()
run=Path(__file__).resolve().parent
b=json.loads((run/"build.json").read_text())
r=json.loads((run/"train-result.json").read_text())
parameters,accounting,outputs=[],{},[]
bases={s:JointModel.load(PRIOR/f"base-{s}.npz") for s in (11,23,47)}
for group,candidates in b["candidates"].items():
    if len(candidates)!=9: raise RuntimeError("missing candidate")
    if b["costs"][group]["complete_cpu"]>10 or b["ledgers"][group]["consumed_units"]>12e9:
        raise RuntimeError("complete cap exceeded")
    expected_units=0
    for row in candidates:
        folder=run/row["name"]
        model=JointModel.load(folder/"model.npz")
        base=bases[row["seed"]]
        price=WorkLedger("audit-price")
        expected_units+=row["update_types"]["joint"]*price.estimate_kernel(**step_work(model.dimensions,group[0],64))
        expected_units+=row["update_types"].get("heads",0)*price.estimate_kernel(**heads_work(model.dimensions,group[0],64))
        with np.load(folder/"updates-and-moments.npz",allow_pickle=False) as saved:
            if len(saved["loss"])!=row["updates"]: raise RuntimeError("loss count mismatch")
            expected_clocks={k:row["update_types"]["joint"] if k in CONTENT_PARAMETERS[:2] else row["updates"] for k in CONTENT_PARAMETERS}
            actual_clocks={k:int(saved["clock/"+k]) for k in CONTENT_PARAMETERS}
            if expected_clocks!=actual_clocks or actual_clocks!=row["clocks"]: raise RuntimeError("clock mismatch")
            joint={k:saved["first_gradient/joint/"+k].copy() for k in CONTENT_PARAMETERS}
            joint_scale=min(1.,5/max(np.sqrt(sum(float(np.sum(g*g)) for g in joint.values())),1e-300))
            first_delta_error=[]
            for key,g in joint.items():
                g=g*joint_scale
                expected=-row["lr"]*g/(np.abs(g)+1e-8)
                first_delta_error.append(float(np.max(np.abs(saved["first_delta/joint/"+key]-expected))))
            if group.endswith("_alt"):
                head={k:saved["first_gradient/heads/"+k].copy() for k in HEADS}
                head_scale=min(1.,5/max(np.sqrt(sum(float(np.sum(g*g)) for g in head.values())),1e-300))
                for key,g in head.items():
                    g1,g2=joint[key]*joint_scale,g*head_scale
                    m=.9*(.1*g1)+.1*g2
                    v=.999*((.001*g1)*g1)+(.001*g2)*g2
                    delta=-row["lr"]*(m/(1-.9**2))/(np.sqrt(v/(1-.999**2))+1e-8)
                    first_delta_error.append(float(np.max(np.abs(saved["first_delta/heads/"+key]-delta))))
                if row["first_head_skip"]["before_sha256"]!=row["first_head_skip"]["after_sha256"]:
                    raise RuntimeError("inactive state changed")
            for key in CONTENT_PARAMETERS:
                if not np.isfinite(saved["first_moment/"+key]).all() or not np.isfinite(saved["second_moment/"+key]).all():
                    raise RuntimeError("nonfinite moment")
                if np.any(saved["second_moment/"+key]<0): raise RuntimeError("negative second moment")
                if not np.allclose(saved["final_delta/"+key],model.params[key]-base.params[key],rtol=0,atol=0):
                    raise RuntimeError("saved final movement inconsistent")
                if np.linalg.norm(saved["final_delta/"+key])==0: raise RuntimeError("no actual content movement")
            if max(first_delta_error)>1e-12: raise RuntimeError("first actual Adam step inconsistent")
        if any(not np.array_equal(model.params[k],base.params[k]) for k in ("decoder","decoder_bias")):
            raise RuntimeError("decoder changed")
        parameters.append({"name":row["name"],"clocks":actual_clocks,"first_delta_max_error":max(first_delta_error),
                           "skip_hashes":row["first_head_skip"]})
    actual=b["ledgers"][group]["stages"]["search_train"]["consumed_units"]
    if actual!=expected_units: raise RuntimeError("charged a nonexecuted derivative/optimizer kernel")
    accounting[group]={"training_kernel_units":actual,"derived_from_executed_update_types":expected_units,
        "complete_cpu":b["costs"][group]["complete_cpu"],"complete_units":b["ledgers"][group]["consumed_units"]}
for group,choice in r["selected"].items():
    for seed in (11,23,47):
        folder=run/f"{group}-{seed}-{choice['lr']}"
        obj=json.loads((folder/"external-output.json").read_text())
        png=(folder/"external-output.png").read_bytes()
        if hashlib.sha256(png).hexdigest()!=obj["png_sha256"] or base64.b64decode(obj["png_base64"])!=png:
            raise RuntimeError("PNG identity mismatch")
        pixels=np.asarray(Image.open(folder/"external-output.png").convert("RGB"),dtype=float).reshape(-1)/255
        image=int(np.mean((templates()-pixels)**2,axis=1).argmin())
        text=parse_caption(obj["caption"])
        outputs.append({"group":group,"seed":seed,"caption":obj["caption"],"PNG_scene":image,
                        "target_scene":1,"joint_correct":text==image==1})
report={"saved_candidate_checks":parameters,"accounting":accounting,"external_observations":outputs,
    "audit_cpu_before_receipt":time.process_time()-started,"scope":"saved TRAIN artifacts only; no repeated training/evaluation"}
(run/"evidence-audit.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
print(json.dumps({"candidates":len(parameters),"all_clocks_moments_deltas_and_unit_checks_pass":True,
                  "external_joint_correct":sum(o["joint_correct"] for o in outputs),"external_rows":len(outputs),
                  "audit_cpu":report["audit_cpu_before_receipt"]}))

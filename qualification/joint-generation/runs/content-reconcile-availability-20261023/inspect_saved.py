"""Read owned TRAIN receipts/NPZ field inventories only; no model execution."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np


started=time.process_time()
root=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
rows,inventory,artifacts,logits=[],[],{},[]
for tag in ("content-control-train-r2-20261023","content-block-train-v1-20261023"):
    run=root/"runs"/tag
    data=json.loads((run/"train-result.json").read_text())
    count=0
    candidates=[]
    for path in run.rglob("*.npz"):
        with np.load(path,allow_pickle=False) as z:
            names=z.files
            fields=[name for name in names if name in ("p","q","pt","pi","text_probabilities","image_probabilities","reward","R","Q","greedy_text_code","greedy_image_code")]
            if fields:candidates.append({"path":path.relative_to(root).as_posix(),"fields":fields})
        count+=1
    inventory.append({"run":tag,"npz_files":count,"explicit_probability_reward_joint_or_greedy_fields":candidates,
                      "per_row_endpoint_fields":sorted(next(iter(data["per_row"].values()))[0])})
    groups=("H","A") if tag.startswith("content-control") else ("H_joint","A_joint","H_alt","A_alt")
    for group in groups:
        sample_pairs=[]
        for index,seed in enumerate((11,23,47)):
            consistency=np.asarray(data["per_row"][group][index]["consistency"])
            disagreement=1-consistency
            rows.append({"run":tag,"group":group,"seed":seed,"rows":len(consistency),
                         "expected_decoded_semantic_disagreement":float(disagreement.mean())})
            rate=data["selected"][group]["lr"]
            folder=run/f"{group}-{seed}-{rate}"
            sample=json.loads((folder/"sample-output.json").read_text())
            sample_pairs.append({"seed":seed,"text":sample["choices"]["text"],"image":sample["choices"]["image"]})
            if tag.startswith("content-control"):
                path=folder/"model.npz"
                artifacts[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
        inventory[-1].setdefault("single_first_row_samples",{})[group]=sample_pairs
    for name in ("build.json","train-result.json"):
        path=run/name
        artifacts[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
base_run=root/"runs/content-control-train-r2-20261023"
for seed in (11,23,47):
    path=base_run/f"features-{seed}.npz"
    with np.load(path,allow_pickle=False) as z:
        fields={name:{"shape":list(z[name].shape),"dtype":str(z[name].dtype)} for name in z.files}
    logits.append({"seed":seed,"path":path.relative_to(root).as_posix(),"fields":fields,
                   "binding":"pre-adaptation supervised base, not selected dense H/A weights"})
    for file in (path,base_run/f"base-{seed}.npz"):
        artifacts[file.relative_to(root).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
report={"scope":"saved TRAIN availability only; no softmax/model/decoder/observer/repair executed",
        "semantic_disagreement":rows,"npz_inventory":inventory,"cached_base_logits":logits,"input_artifact_sha256":artifacts,
        "limits":["semantic consistency is an external decoded endpoint, forbidden as runtime reconciliation input",
                  "selected dense p/q and raw original argmax pairs were not persisted",
                  "R must be recovered from frozen decoder using original observer only after separate authorization and billed work",
                  "base logits cannot be substituted for stronger adapted H/A models",
                  "sparse first-row sampled pairs do not identify population disagreement or threshold decisions"],
        "CPU_seconds_before_receipt":time.process_time()-started}
(out/"availability.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
print(json.dumps({"inventories":inventory,"semantic_disagreement":rows,"cached_base_logits":len(logits),
                  "CPU_seconds_before_receipt":report["CPU_seconds_before_receipt"]}))

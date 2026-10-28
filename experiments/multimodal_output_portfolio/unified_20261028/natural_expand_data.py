"""Predeclared budget expansion on entirely new video-source holdouts."""
import argparse, copy, json, pathlib, time, zipfile
import numpy as np
from . import natural_data as D

EXPANSION={
 "schema":"hepta.natural.budget-expansion.v1","new_actual_gradient_steps_per_arm":64,
 "same_warmstart":True,"same_optimizer_sampling_learning_rate_and_loss":True,
 "training_sources":"original 32 only","selection_sources":"original 8 development only",
 "fresh_calibration_sources":16,"fresh_qualification_sources":32,
 "exclude_every_original_source":64,"previous_qualification_reused":False,
 "decision":"Budget enlargement and fresh-source counts were authorized independently before reading first-study qualification results; retain and report both studies in full.",
 "primary_checkpoint_selection":"Compare 8 and 64 updates only on original development CE; report every checkpoint on fresh qualification.",
 "no_new_hyperparameter_grid":True,
}

def freeze_expansion(original,root):
 root.mkdir(parents=True,exist_ok=True);p=root/"SOURCE_PROTOCOL.json"
 if p.exists():return json.loads(p.read_text())
 old=json.loads((original/"SOURCE_PROTOCOL.json").read_text());used={x["source_id"] for x in old["selected"]}
 # The ontology/annotation byte identities are identical to the first study.
 for _,(name,_) in D.ANNOTATIONS.items():(root/name).write_bytes((original/name).read_bytes())
 ann,receipts=D.annotations(root);remote=D.RemoteZip(D.URL);archive=zipfile.ZipFile(remote)
 candidates=[]
 for info in archive.infolist():
  if not info.filename.endswith(".mp4") or info.file_size>5_000_000:continue
  source=pathlib.PurePosixPath(info.filename).stem
  if source in used or source not in ann["action"] or source not in ann["sound"]:continue
  events=D.eligible_events(ann["action"][source],ann["sound"][source])
  if len(events)<2:continue
  candidates.append({"source_id":source,"member":info.filename,"compressed_bytes":info.compress_size,"bytes":info.file_size,
    "zip_crc32":f"{info.CRC:08x}","events":events,"priority":D.sha(D.canonical([D.SEED,source]))})
 candidates.sort(key=lambda x:x["priority"]);selected=candidates[:48]
 if len(selected)!=48:raise ValueError("Not enough fresh eligible original videos")
 for i,row in enumerate(selected):row["split"]="calibration" if i<16 else "qualification"
 plan=copy.deepcopy(old);plan.pop("protocol_sha256")
 plan.update({"schema":"hepta.natural.sources.expansion.v1","counts":{"train":32,"development":8,"calibration":16,"qualification":32},
   "selected":selected,"inherited_train_and_development":[x for x in old["selected"] if x["split"] in ("train","development")],
   "excluded_original_source_ids":sorted(used),"original_source_protocol_sha256":old["protocol_sha256"],
   "budget_expansion":EXPANSION,"created_at_unix":time.time(),
   "archive":{"url":D.URL,"bytes":remote.length,"generation":remote.generation,"etag":remote.etag,"index_range_receipts":remote.receipts}})
 plan["protocol_sha256"]=D.sha(D.canonical(plan));D.write_json(p,plan)
 D.write_json(root/"BUDGET_EXPANSION.json",{**EXPANSION,"source_protocol_sha256":plan["protocol_sha256"]})
 return plan

def prepare_expansion(original,root):
 plan=freeze_expansion(original,root)
 if (root/"MERGE_RECEIPT.json").exists():return
 D.prepare(root)
 oldmeta=json.loads((original/"EVENTS.json").read_text());newmeta=json.loads((root/"EVENTS.json").read_text())
 indices=[i for i,e in enumerate(oldmeta["events"]) if e["split"] in ("train","development")]
 old=dict(np.load(original/"EVENTS.npz"));new=dict(np.load(root/"EVENTS.npz"))
 combined={k:np.concatenate([old[k][indices],new[k]]) for k in old}
 np.savez_compressed(root/"EVENTS.npz",**combined)
 newmeta["events"]=[oldmeta["events"][i] for i in indices]+newmeta["events"]
 inherited=[r for r in oldmeta["sources"] if r["split"] in ("train","development")]
 newmeta["sources"]=inherited+newmeta["sources"]
 newmeta["arrays_sha256"]=D.sha((root/"EVENTS.npz").read_bytes())
 newmeta["counts"]={s:sum(e["split"]==s for e in newmeta["events"]) for s in ("train","development","calibration","qualification")}
 D.write_json(root/"EVENTS.json",newmeta)
 D.write_json(root/"MERGE_RECEIPT.json",{"old_event_array_sha256":oldmeta["arrays_sha256"],
  "inherited_event_indices":indices,"inherited_splits":["train","development"],
  "new_event_array_sha256":newmeta["arrays_sha256"],"fresh_holdout_source_count":48,
  "old_holdout_source_overlap":False,"source_protocol_sha256":plan["protocol_sha256"]})
 print(json.dumps({"sources":plan["counts"],"events":newmeta["counts"],"source_protocol_sha256":plan["protocol_sha256"]}),flush=True)

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--original",type=pathlib.Path,required=True);p.add_argument("--assets",type=pathlib.Path,required=True);p.add_argument("--freeze-only",action="store_true");a=p.parse_args()
 plan=freeze_expansion(a.original,a.assets);print(json.dumps({"protocol_sha256":plan["protocol_sha256"],"fresh_source_bytes":sum(x["bytes"] for x in plan["selected"])}),flush=True)
 if not a.freeze_only:prepare_expansion(a.original,a.assets)

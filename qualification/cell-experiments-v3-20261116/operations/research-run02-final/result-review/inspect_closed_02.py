"""Read-only schema inspection of the closed Run02 archive; no model/library imports."""
import hashlib, json, pathlib, struct
R=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
E=R/"research-final-evidence-02"
def read(p): return json.loads((E/p).read_bytes())
def show(k,v): print(json.dumps({"kind":k,"value":v},sort_keys=True))
members=[json.loads(x) for x in (R/"research-final-export-02/MEMBERS.jsonl").read_bytes().splitlines()]
paths=[x["path"] for x in members]
result=read("research-sft-02/RESULT.json")
show("operation", {k:result[k] for k in result if k not in ("children","cold_comparisons")})
show("children", [{"arm":c["arm"],"phase":c["phase"],"exit_code":c["exit"]["exit_code"],"result_keys":list((c["result"] or {}).keys())} for c in result["children"]])
show("cold_comparisons",result["cold_comparisons"])
show("interesting_paths",[p for p in paths if (
 p.startswith("research-sft-02/workers/final_answer-primary/research-model/") and "/references/" not in p
 or p.startswith("research-sft-02/workers/final_answer-primary/evaluation/") and p.count("/")<=6
 or p.startswith("operations/") and any(x in p.lower() for x in ("controller","terminal","closure","launch_freeze"))
)])
for arm in ("final_answer","trajectory","shadow_correction","controlled_correction"):
 d="research-sft-02/workers/"+arm+"-primary/research-model/"
 t=read(d+"TRAINING.json")
 show("training_"+arm,{k:v for k,v in t.items() if k not in ("source_inventory","losses")})
 steps=[json.loads(x) for x in (E/(d+"STEPS.jsonl")).read_bytes().splitlines()]
 show("steps_"+arm,{"count":len(steps),"first":steps[0],"last":steps[-1]})
 m=read(d+"manifest.json")
 show("manifest_"+arm,{k:v for k,v in m.items() if k not in ("research_source_inventory","base_manifest")})
 p=E/m["adapter_directory"]/"adapter_model.safetensors"
 with p.open("rb") as s: n=struct.unpack("<Q",s.read(8))[0]; h=json.loads(s.read(n))
 tensors={k:v for k,v in h.items() if k!="__metadata__"}
 show("safetensor_"+arm,{"header_length":n,"metadata":h.get("__metadata__"),"tensor_count":len(tensors),"dtypes":sorted({x["dtype"] for x in tensors.values()}),"first":list(tensors.items())[:6],"last":list(tensors.items())[-2:]})
primary=read("research-sft-02/workers/final_answer-primary/RESULT.json")
ev=primary["evaluation"]
show("eval_keys",list(ev))
show("eval_summary",{k:v for k,v in ev.items() if k not in ("rows","panel_measurements")})
row=ev["rows"][0]
show("one_row_summary",{k:v for k,v in row.items() if k!="steps"})
show("one_step_keys",list(row["steps"][0]))
show("one_step",{k:v for k,v in row["steps"][0].items() if k not in ("output",)})
p="research-sft-02/workers/final_answer-primary/evaluation/A_retention/0"
show("raw_files",[x for x in paths if x.startswith(p+"/")])
show("diag_summary",{k:v for k,v in read("research-diagnostic-02/DIAGNOSTIC.json").items() if k in ("status","binding_errors","fixed_expert_slots","frozen_baselines","separate_shadow_arm","operation_status")})

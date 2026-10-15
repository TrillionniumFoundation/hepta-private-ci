"""Fail-closed E1–E5 paired observational gate; never authorizes a Stem."""
import argparse,hashlib,json,math
from collections import defaultdict
from pathlib import Path
SCHEMA="hepta.stem-e1e5-causal-observation.v1"
STAGES={
"E1":{"no_change","frozen_head","learned_head"},
"E2":{"no_change","frozen_head","cosine","from_zero","residual_2k","residual_8k","residual_16k"},
"E3":{"text_only","ocr_only","unaligned","learned_bridge","native_multimodal"},
"E4":{"text_only","unaligned","audio_bridge","temporal_adapter","temporal_reversed"},
"E5":{"no_change","shared_stem"}}
SPLITS=("train","calibration","test","future1","future2","future3","ood")
READER=("none","retrieved","sufficient","premise_removed")
MODALITY=("text","image","audio","video","sensor")
COSTS=("load_ms","encode_ms","bridge_fit_ms","head_train_ms","cache_ms","migration_ms","recompute_ms","serving_ms","evaluation_ms","checkpoint_ms","peak_rss_bytes","cpu_ms","gpu_ms","energy_joules","throughput_per_sec","p95_ms","p99_ms")
class Invalid(ValueError):pass
def _pairs(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise Invalid("duplicate JSON key")
  d[k]=v
 return d
def read(path):
 b=Path(path).read_bytes()
 if not 0<len(b)<=16*1024*1024:raise Invalid("invalid input size")
 return json.loads(b,object_pairs_hook=_pairs,parse_constant=lambda v:(_ for _ in ()).throw(Invalid("nonfinite JSON"))),hashlib.sha256(b).hexdigest()
def digest(v):
 if not isinstance(v,str) or len(v)!=64 or v=="0"*64 or any(c not in "0123456789abcdef" for c in v):raise Invalid("bad SHA256")
 return v
def ident(v):
 if not isinstance(v,str) or not 1<=len(v)<=128 or not all(c.isascii() and (c.isalnum() or c in "._:-") for c in v):raise Invalid("bad stable ID")
 return v
def number(v,positive=False):
 if type(v) not in (float,int) or not math.isfinite(v) or v<(1e-300 if positive else 0):raise Invalid("missing/invalid physical measurement")
 return float(v)
def audit(doc):
 if not isinstance(doc,dict) or doc.get("schema")!=SCHEMA or doc.get("stage") not in STAGES:raise Invalid("bad schema or stage")
 if doc.get("authority")!="DENY_ALL" or doc.get("production_promotion_permitted") is not False:raise Invalid("not fail closed")
 for k in ("source_tree_sha256","dataset_sha256","plan_sha256","evaluator_sha256"):digest(doc.get(k))
 scope=ident(doc.get("scope"));stage=doc["stage"]
 arms=doc.get("arms");cases=doc.get("cases")
 if not isinstance(arms,list) or not all(isinstance(a,dict) for a in arms):raise Invalid("missing arms")
 names=[ident(a.get("name")) for a in arms]
 if len(names)!=len(set(names)) or not STAGES[stage].issubset(names):raise Invalid("missing/duplicate controls")
 if not isinstance(cases,list) or not 1<=len(cases)<=50000:raise Invalid("missing cases")
 groups=defaultdict(set);inputs=defaultdict(set);times=defaultdict(list);byid={}
 for c in cases:
  if not isinstance(c,dict):raise Invalid("invalid case")
  cid=ident(c.get("case_id"));partition=c.get("split")
  if cid in byid or partition not in SPLITS or c.get("modality") not in MODALITY or c.get("scope")!=scope:raise Invalid("case identity/scope")
  group=ident(c.get("source_group"));source=digest(c.get("input_sha256"))
  if c.get("reader_condition") not in READER or type(c.get("reader_correct")) is not bool:raise Invalid("missing Reader control")
  if type(c.get("answer_label")) is not int or c["answer_label"] not in (0,1):raise Invalid("independent binary label required")
  if stage=="E4" and c["modality"]=="video":
   ident(c.get("counterfactual_pair_id"));digest(c.get("frame_order_sha256"))
  groups[partition].add(group);inputs[partition].add(source);times[partition].append(number(c.get("observed_at"),True));byid[cid]=c
 for i,a in enumerate(SPLITS):
  for b in SPLITS[i+1:]:
   if groups[a]&groups[b] or inputs[a]&inputs[b]:raise Invalid("source/input leakage")
 chronological=[s for s in SPLITS if s!="ood" and times[s]]
 if any(max(times[a])>=min(times[b]) for a,b in zip(chronological,chronological[1:])):raise Invalid("future chronology violated")
 sufficient=[c for c in cases if c["reader_condition"]=="sufficient"]
 if stage in ("E1","E2") and not sufficient:raise Invalid("missing sufficient-evidence Reader arm")
 if stage=="E5":
  n=doc.get("logical_cells");active=doc.get("active_cells")
  if n not in (64,256,1024,4096) or type(active) is not int or not 1<=active<=n:raise Invalid("invalid real active Cell cohort")
 results={}
 for a in arms:
  name=a["name"];digest(a.get("model_sha256"));digest(a.get("head_sha256"))
  if a.get("actual_model_forward") is not True:raise Invalid("physical model forward not declared")
  if type(a.get("reader_invocations")) is not int or a["reader_invocations"]<0:raise Invalid("Reader cost missing")
  r=a.get("resources")
  if not isinstance(r,dict) or set(r)!=set(COSTS):raise Invalid("incomplete lifecycle accounting")
  for k in COSTS:number(r[k],k in ("peak_rss_bytes","throughput_per_sec","p95_ms","p99_ms"))
  if r["p99_ms"]<r["p95_ms"]:raise Invalid("invalid latency quantiles")
  pred=a.get("predictions")
  if not isinstance(pred,list) or len(pred)!=len(cases):raise Invalid("missing paired predictions")
  seen=set();correct=0;brier=0.
  for p in pred:
   if not isinstance(p,dict):raise Invalid("invalid prediction")
   cid=ident(p.get("case_id"))
   if cid in seen or cid not in byid or p.get("input_sha256")!=byid[cid]["input_sha256"]:raise Invalid("swapped/duplicated prediction")
   if p.get("prelabel_sealed") is not True:raise Invalid("unsealed prediction")
   prob=p.get("positive_probability")
   if type(prob) not in (float,int) or not math.isfinite(prob) or not 0<=prob<=1:raise Invalid("bad probability")
   y=byid[cid]["answer_label"];correct+=int((prob>=.5)==bool(y));brier+=(prob-y)**2;seen.add(cid)
  results[name]={"accuracy":correct/len(cases),"brier":brier/len(cases),"reported_total_lifecycle_ms":sum(r[k] for k in COSTS if k.endswith("_ms") and k not in ("cpu_ms","gpu_ms","p95_ms","p99_ms"))}
 return {"schema":"hepta.stem-e1e5-observational-audit.v1","stage":stage,"cases":len(cases),"arms":results,
  "reader_adequacy_on_supplied_sufficient_cases":bool(sufficient) and all(c["reader_correct"] for c in sufficient),
  "claimed_physical_runs_independently_verified":False,"source_and_model_origin_authenticated":False,
  "outcome_and_cost_independently_authenticated":False,"production_promotion_permitted":False,"authority":"DENY_ALL"}
def main():
 p=argparse.ArgumentParser();p.add_argument("--observations",required=True);p.add_argument("--output",required=True);a=p.parse_args()
 data,sha=read(a.observations);result=audit(data);result["observation_file_sha256"]=sha
 with Path(a.output).open("x",encoding="utf8") as out:json.dump(result,out,sort_keys=True,indent=2,allow_nan=False);out.write("\n")
if __name__=="__main__":main()

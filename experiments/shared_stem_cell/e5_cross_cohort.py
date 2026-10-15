"""Cross-cohort E5 evidence consistency screen; never physical attestation."""
import argparse,hashlib,json,math
from pathlib import Path

SCALES=(64,256,1024,4096)
SCHEMA="hepta.stem-e5-scale-cohort-panel.v1"
class Invalid(ValueError):pass
def _pairs(items):
 d={}
 for k,v in items:
  if k in d:raise Invalid("duplicate JSON field")
  d[k]=v
 return d
def sha(x):
 if type(x) is not str or len(x)!=64 or x=="0"*64 or any(c not in "0123456789abcdef" for c in x):raise Invalid("invalid digest")
 return x
def num(x,positive=False):
 if type(x) not in (float,int) or not math.isfinite(x) or x<0 or (positive and x<=0):raise Invalid("invalid numeric metric")
 return float(x)
def read(path):
 b=Path(path).read_bytes()
 if not 0<len(b)<=16*1024*1024:raise Invalid("oversized or empty report")
 return json.loads(b,object_pairs_hook=_pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid("nonfinite"))),hashlib.sha256(b).hexdigest()
def review(panel):
 if type(panel) is not dict or panel.get("schema")!=SCHEMA or panel.get("authority")!="DENY_ALL" or panel.get("production_promotion_permitted") is not False:raise Invalid("not research panel")
 for key in ("source_tree_sha256","plan_sha256","model_sha256","host_sha256","worker_sha256"):sha(panel.get(key))
 cohorts=panel.get("cohorts")
 if type(cohorts) is not list or len(cohorts)!=4:raise Invalid("require all four physical cohorts")
 found={};seen_runs=set();seen_traces=set()
 for row in cohorts:
  if type(row) is not dict:raise Invalid("invalid cohort")
  n=row.get("logical_cells")
  if type(n) is not int or n not in SCALES or n in found:raise Invalid("duplicate/unregistered scale")
  if row.get("authority")!="DENY_ALL" or row.get("production_promotion_permitted") is not False:raise Invalid("unexpected authority")
  for key in ("source_tree_sha256","plan_sha256","model_sha256","host_sha256","worker_sha256"):
   if sha(row.get(key))!=panel[key]:raise Invalid("cross-cohort drift "+key)
  run=sha(row.get("run_sha256"));trace=sha(row.get("trace_sha256"))
  if run in seen_runs or trace in seen_traces:raise Invalid("reused run or trace")
  seen_runs.add(run);seen_traces.add(trace)
  a=row.get("active_cells")
  if type(a) is not int or a<1 or a>n:raise Invalid("invalid active fraction")
  if row.get("observed_active_cells")!=a:raise Invalid("missing active Cell coverage")
  if row.get("final_use_checked_requests")!=row.get("requests") or type(row.get("requests")) is not int or row["requests"]<a:raise Invalid("missing per-request final use")
  if row.get("verified_unclean_recovery") is not True:raise Invalid("missing unclean recovery claim")
  if row.get("failed_requests") is None or type(row["failed_requests"]) is not int or not 0<=row["failed_requests"]<=row["requests"]:raise Invalid("failed requests unreported")
  if type(row.get("source_distinct_inputs")) is not int or not 1<=row["source_distinct_inputs"]<=row["requests"]:raise Invalid("invalid distinct inputs")
  if type(row.get("backend_forwards")) is not int or not 1<=row["backend_forwards"]<=row["requests"]:raise Invalid("invalid backend forwards")
  if type(row.get("real_batches")) is not int or not 1<=row["real_batches"]<=row["backend_forwards"]:raise Invalid("invalid batch accounting")
  if type(row.get("cache_hits")) is not int or not 0<=row["cache_hits"]<=row["requests"]-row["backend_forwards"]:raise Invalid("impossible cache reuse")
  vals=row.get("physical_resources")
  expected={"peak_rss_bytes","cpu_ms","gpu_ms","energy_joules","p50_ms","p95_ms","p99_ms","throughput_per_sec","wall_ms","warmup_ms","training_ms","checkpoint_ms","migration_ms","recompute_ms"}
  if type(vals) is not dict or set(vals)!=expected:raise Invalid("incomplete hardware and lifecycle metrics")
  for k in expected:num(vals[k],k in ("peak_rss_bytes","p50_ms","p95_ms","p99_ms","throughput_per_sec","wall_ms"))
  if not vals["p50_ms"]<=vals["p95_ms"]<=vals["p99_ms"]:raise Invalid("latency ordering")
  found[n]={"reported_active_cells":a,"reported_requests":row["requests"],"reported_failures":row["failed_requests"],
            "reported_cache_hit_fraction":row["cache_hits"]/row["requests"],
            "reported_batches":row["real_batches"],"reported_forward_count":row["backend_forwards"],
            "claimed_resource_metrics":vals}
 return {"schema":"hepta.stem-e5-scale-screen.v1","cohorts":{str(k):found[k] for k in SCALES},
         "all_four_scale_cohorts_present":True,
         "input_model_source_and_host_claims_consistent":True,
         "independently_authenticated_worker_or_hardware_receipts":False,
         "independently_verified_recovery":False,"independently_verified_ndu":False,
         "blocking_ci_accepted":False,"production_promotion_permitted":False,"authority":"DENY_ALL"}
def main():
 p=argparse.ArgumentParser();p.add_argument("--panel",required=True);p.add_argument("--output",required=True)
 a=p.parse_args();panel,h=read(a.panel);result=review(panel);result["panel_sha256"]=h
 with Path(a.output).open("x",encoding="utf8") as out:json.dump(result,out,sort_keys=True,indent=2,allow_nan=False);out.write("\n")
if __name__=="__main__":main()

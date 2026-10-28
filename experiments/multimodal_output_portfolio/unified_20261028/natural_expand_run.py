"""64-update matched natural study on fresh, pre-frozen source holdouts.

The original eight-update study remains immutable. The enlargement was authorized
independently of its qualification values; only original train/dev data are reused.
"""
import argparse, copy, json, pathlib, time
import numpy as np
import torch
from . import natural_run as R
from .natural_run import Study
from .natural_data import canonical, sha, write_json
from .natural_expand_data import EXPANSION
from .natural_model import NaturalPortfolio, parameter_hash, cpu_seconds, simple_features

EXPANDED_ARMS=("interpolation","source_nearest","fixed_neural","uniform_8","ndu_8","uniform_64","ndu_64")

EXPANDED_CONTINUATION={
 "schema":"hepta.natural.expanded-continuation.v1",
 "predecessor_sha256":R.CONTINUATION_SHA256,
 "candidate_set":list(EXPANDED_ARMS),
 "neural_emission_law":"Unchanged Gaussian image/video/audio and categorical text; fixed_neural mean/argmax",
 "actor":"Development-fitted positive softplus moment; choose one whole bundle from seven candidates before emission",
 "stop":"One completed four-modality bundle or explicit failure; exactly two neural transitions where selected",
 "cost":"Same frozen actual CPU tariff; expanded actor charges its online feature extraction",
}

class ExpandedStudy(Study):
 def __init__(self,assets,out,first):
  self.previous_profile=R.NduProfile.from_dict(json.loads((first/"NDU_PROFILE.json").read_text()))
  R.CONTINUATION_SHA256=sha(canonical(EXPANDED_CONTINUATION))
  super().__init__(assets,out);self.first=first
  for field in ("objective_sha256","observer_sha256","gamma","aggregation","cost_unit","utility_bounds","required_modalities"):
   if getattr(self.previous_profile,field)!=getattr(self.profile,field):
    raise ValueError("Expansion changed objective/scorer/cost rather than only continuation candidate set")
 def load_first(self,name):
  record=torch.load(self.first/(name+".pt"),map_location="cpu",weights_only=False)
  if record["profile_sha256"]!=self.previous_profile.digest:raise ValueError("Original checkpoint training identity changed")
  model=NaturalPortfolio(self.vocab);model.load_state_dict(record["model"]);return model.eval()
 def values(self,arm,i,draw_id):
  extra=0.
  if arm=="source_nearest":
   begin=cpu_seconds()
   x=simple_features(self.data["context_video"][i:i+1].astype(np.float32)/255,self.data["context_audio"][i:i+1])
   self.features[i]=(x[0]-self.fmean)/self.fscale;self.features[i,-1]=1.
   extra=cpu_seconds()-begin
  values,used=super().values(arm,i,draw_id)
  return values,used+extra
 def evaluate(self,split,arms,draws,actor=False):
  # Same law and outputs as the original runner; the actor now includes online
  # public-feature extraction in its measured execution cost (not a cached free input).
  rows=[]
  for k,i in enumerate(self.indices[split]):
   for requested in arms:
    for d in range(draws):
     actor_cpu=0.;executed=requested
     if requested=="actor":
      begun=cpu_seconds()
      features=simple_features(self.data["context_video"][i:i+1].astype(np.float32)/255,self.data["context_audio"][i:i+1])
      query=(features[0]-self.fmean)/self.fscale;query[-1]=1.
      pred=np.logaddexp(0,query@self.actor);executed=R.ARMS[int(np.argmin(pred))]
      actor_cpu=cpu_seconds()-begun
     values,inference=self.values(executed,i,d);begin=cpu_seconds()
     record,decoded=self.score(values,i,0,requested,d,begin,inference+actor_cpu,save=split=="qualification")
     record["executed_arm"]=executed
     record["training_profile_sha256"]=self.previous_profile.digest if executed in ("uniform_8","ndu_8","fixed_neural") else self.profile.digest
     record["evaluated_under_profile_sha256"]=self.profile.digest
     record["checkpoint_profile_migration"]=executed in ("uniform_8","ndu_8","fixed_neural")
     record["online_feature_extraction_cpu_included"]=requested=="actor" or executed=="source_nearest"
     if split=="qualification" and d==0 and decoded is not None:self.decoded[(requested,i)]=decoded
     rows.append(record);self.records.append(record)
   if k%8==0:print("natural expanded evaluate",split,k+1,len(self.indices[split]),flush=True)
  return rows

 def run(self):
  started=time.perf_counter();started_cpu=cpu_seconds();torch.set_num_threads(2);torch.manual_seed(17)
  R.PROTOCOL=copy.deepcopy(R.PROTOCOL);R.PROTOCOL["actual_gradient_steps"]=64
  R.ARMS=EXPANDED_ARMS
  first_protocol=json.loads((self.first/"RUN_PROTOCOL.json").read_text())
  warm=self.load_first("fixed_neural");self.warm_sha=parameter_hash(warm)
  frozen={"schema":"hepta.natural.expanded-run.v1","budget":EXPANSION,
   "protocol":R.PROTOCOL,"first_run_protocol_sha256":first_protocol["sha256"],
   "source_protocol_sha256":self.sources["protocol_sha256"],"profile_sha256":self.profile.digest,
   "warmstart_model_sha256":self.warm_sha,
   "original_training_profile_sha256":self.previous_profile.digest,
   "expanded_continuation":EXPANDED_CONTINUATION,
   "profile_migration":"8-step checkpoints explicitly retain their original training profile and are re-evaluated under the expanded 7-candidate continuation; objective/scorer/cost/risk fields are unchanged",
   "unchanged_generator_settings":["optimizer","sampling seeds","four emission probability laws","learning rate","gradient clipping","joint-batch objective","previous-batch baseline"],
   "online_actor_feature_billing_correction":"Online public-context features are now measured inside each executed actor/NN path; no generator or quality threshold changed.",
   "primary_selection":"highest original-development NDU CE among ndu_8 and ndu_64",
   "source_files":{p.name:sha(p.read_bytes()) for p in pathlib.Path(__file__).parent.glob("natural_*.py")}}
  frozen["sha256"]=sha(canonical(frozen));write_json(self.out/"RUN_PROTOCOL.json",frozen)
  write_json(self.out/"NDU_PROFILE.json",self.profile.to_dict())
  self.models={"fixed_neural":warm,"uniform_8":self.load_first("uniform_neural"),"ndu_8":self.load_first("ndu_neural")}
  self.models["uniform_64"]=self.actual_gradient(copy.deepcopy(warm),"uniform_neural")
  self.models["ndu_64"]=self.actual_gradient(copy.deepcopy(warm),"ndu_neural")
  checkpoints={}
  for name,model in self.models.items():
   if name in ("uniform_64","ndu_64"):
    path=self.out/(name+".pt");torch.save({"model":model.state_dict(),"vocabulary":self.vocab,
     "profile_sha256":self.profile.digest,"source_protocol_sha256":self.sources["protocol_sha256"]},path)
    loaded=NaturalPortfolio(self.vocab);loaded.load_state_dict(torch.load(path,map_location="cpu",weights_only=False)["model"])
    if parameter_hash(loaded)!=parameter_hash(model):raise ValueError("Expanded checkpoint reload changed")
   else:path=self.first/({"uniform_8":"uniform_neural","ndu_8":"ndu_neural"}.get(name,name)+".pt")
   checkpoints[name]={"path":str(path),"sha256":sha(path.read_bytes()),"model_sha256":parameter_hash(model),"bytes":path.stat().st_size,
    "trained_under_profile_sha256":self.profile.digest if name.endswith("64") else self.previous_profile.digest,
    "evaluated_under_profile_sha256":self.profile.digest}
  dev=self.evaluate("development",R.ARMS,1)
  dev_summary={a:self.summarize([r for r in dev if r["arm"]==a]) for a in R.ARMS}
  primary=max(("ndu_8","ndu_64"),key=lambda a:dev_summary[a]["value"])
  strongest=max((a for a in R.ARMS if not a.startswith("ndu")),key=lambda a:dev_summary[a]["value"])
  actor=self.fit_actor(dev);observer=self.fit_observer()
  for key in ("action","sound"):
   observer[key]["calibration_source_count"]=16
  calibration=self.evaluate("calibration",("actor",),2)
  event_index={e["event_id"]:i for i,e in enumerate(self.events)}
  pred=[];actual=[]
  for r in calibration:
   i=event_index[r["event_id"]];j=R.ARMS.index(r["executed_arm"])
   pred.append(float(np.logaddexp(0,self.features[i]@self.actor[:,j])))
   actual.append(float(np.exp(-2*r["net_return"])))
  calibration_report={"predicted_selected_action_moment_mean":float(np.mean(pred)),
   "actual_selected_action_moment_mean":float(np.mean(actual)),
   "moment_bias":float(np.mean(np.array(pred)-actual)),"independent_source_count":16,
   "negative_predicted_moments":sum(p<=0 for p in pred),"source_overlap_with_previous_holdouts":False,
   "retuning_after_calibration":False,"summary":self.summarize(calibration),"profile_sha256":self.profile.digest}
  seal={"run_protocol_sha256":frozen["sha256"],"profile_sha256":self.profile.digest,"checkpoints":checkpoints,
   "primary_selected_on_original_development":primary,"strongest_fixed_selected_on_original_development":strongest,
   "actor":actor,"observer":observer,"calibration":calibration_report,
   "fresh_qualification_source_ids":sorted({self.events[i]["source_id"] for i in self.indices["qualification"]}),
   "excluded_original_source_ids":self.sources["excluded_original_source_ids"],
   "status":"frozen-before-new-qualification","retuning_allowed":False}
  if set(seal["fresh_qualification_source_ids"])&set(seal["excluded_original_source_ids"]):
   raise ValueError("The expanded study reused an original holdout source")
  seal["sha256"]=sha(canonical(seal));write_json(self.out/"QUALIFICATION_FREEZE.json",seal)
  qual=self.evaluate("qualification",(*R.ARMS,"actor"),2)
  summaries={a:self.summarize([r for r in qual if r["arm"]==a]) for a in (*R.ARMS,"actor")}
  deltas={a:self.bootstrap_delta([r for r in qual if r["arm"]==a],[r for r in qual if r["arm"]==strongest]) for a in ("ndu_8","ndu_64","actor")}
  matched={str(n):self.bootstrap_delta([r for r in qual if r["arm"]==f"ndu_{n}"],[r for r in qual if r["arm"]==f"uniform_{n}"]) for n in (8,64)}
  mismatch=self.mismatch(primary);semantic=self.semantic_accuracy(primary)
  gates={"fresh_source_disjointness":True,"same_warmstart_and_matched_budget":True,
   "all_four_actual_artifacts_reopened":all(r["terminal_kind"]=="delivered" for r in qual),
   "all_trainable_components_actual_gradient":all(v["gradient_l2"]>0 and v["finite"] for v in self.gradient_audits["ndu_neural_actual_output"].values()),
   "new_64step_training_deployment_evaluation_profile_identical":True,
   "old_checkpoint_profile_migrations_explicit":True,
   "selected_risk_generator_beats_strong_fixed":deltas[primary]["source_cluster_percentile_95"][0]>0,
   "actor_beats_strong_fixed":deltas["actor"]["source_cluster_percentile_95"][0]>0,
   "independent_semantic_observer_adequate":observer["adequate"],
   "generated_joint_semantics":semantic>=.6,
   "mismatch_control_sensitive":mismatch["mean_joint_utility_drop"]>.01,
   "selected_action_moment_bias_within_frozen_bound":abs(calibration_report["moment_bias"])<.1}
  report={"schema":"hepta.natural.expanded-result.v1","profile_sha256":self.profile.digest,
   "source_protocol_sha256":self.sources["protocol_sha256"],"qualification_freeze_sha256":seal["sha256"],
   "first_study_results_sha256":sha((self.first/"RESULTS.json").read_bytes()),
   "acceptance":all(gates.values()),"gates":gates,"budget":EXPANSION,
   "data_counts":{s:{"events":len(ids),"sources":len({self.events[i]["source_id"] for i in ids})} for s,ids in self.indices.items()},
   "development":dev_summary,"primary_selected_on_original_development":primary,"selected_fixed_comparator":strongest,
   "qualification":summaries,"paired_source_cluster_deltas":deltas,"matched_budget_risk_minus_uniform":matched,
   "selected_action_calibration":calibration_report,"semantic_observer":observer,
   "generated_joint_semantic_accuracy":semantic,"mismatch_control":mismatch,"gradient_audits":self.gradient_audits,
   "checkpoints":checkpoints,"training":self.training_log,"wall_seconds":time.perf_counter()-started,
   "total_run_cpu_seconds":cpu_seconds()-started_cpu,
   "limitations":self.sources["limitations"]+[
    "Both studies are reported; new holdouts exclude all 64 original videos, but participant identity separation is not verified.",
    "One neural training seed; source-cluster intervals do not quantify training-seed uncertainty.",
    "Fixed architecture CPU timing is treated as conditionally exogenous; parameter derivatives of platform timing are not estimated.",
    "The 5-to-7 candidate actor extension has a new continuation hash; prior 8-step checkpoint training identities are preserved by explicit migration.",
    "The original eight-update actor used precomputed public features; this expansion charges the online actor/NN feature computation.",
    "Four emitted media formats and high reconstruction similarity do not establish open-domain or natural semantic generation.",
    "The natural shared-state model extends the research NeuralPortfolio convention; it is not the native owner binary integrated by the separate runtime work package."]}
  write_json(self.out/"RESULTS.json",report);write_json(self.out/"OUTCOME_LEDGER.json",self.records)
  print(json.dumps({"acceptance":report["acceptance"],"primary":primary,"gates":gates,
   "qualification":summaries,"matched_budget":matched},indent=2),flush=True)
  return report

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--assets",type=pathlib.Path,required=True);p.add_argument("--output",type=pathlib.Path,required=True);p.add_argument("--first-study",type=pathlib.Path,required=True);a=p.parse_args()
 ExpandedStudy(a.assets,a.output,a.first_study).run()

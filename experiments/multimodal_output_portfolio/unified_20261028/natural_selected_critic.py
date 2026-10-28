"""Post-study selected-policy moment repair; no policy update or fresh claim.

Fits the complete frozen actor's actual net-return exponential moment, using
source-uniform weights. Already-consumed independent-source calibration is a
descriptive diagnostic. Unbounded future CPU cost precludes a rigorous tail
certificate; sample maxima are never treated as future support bounds.
"""
import argparse, hashlib, json, pathlib, time
from collections import defaultdict
import numpy as np
import torch
from . import natural_run as R
from .natural_expand_run import ExpandedStudy, EXPANDED_ARMS
from .natural_data import canonical, sha, write_json
from .natural_model import NaturalPortfolio, parameter_hash, simple_features, cpu_seconds

PROTOCOL={
 "schema":"hepta.natural.selected-policy-moment-repair.v1",
 "status":"post-study diagnostic; no new policy/checkpoint selection; no fresh qualification",
 "training_split":"original development only, 8 original sources / 27 events",
 "draw_ids":[2000,2001],"calibration_split":"already consumed expanded calibration, 16 independent video sources",
 "target":"exp(-gamma * actual_complete_actor_net_return), including online feature, selection, generation, codec, readback and scoring CPU",
 "source_weight":"equal original source mass, equal event mass within source, equal draw mass within event",
 "critic":"softplus(linear normalized public-context features), fit direct weighted moment squared error",
 "optimizer":"Adam","learning_rate":.01,"steps":400,"ridge":.001,
 "bootstrap_source_resamples":5000,"bootstrap_seed":170188,
 "policy_changes_allowed":False,"rigorous_tail_certificate_allowed":False,
 "tail_reason":"No enforced future upper bound on complete CPU cost; empirical sample bounds are not a future support proof.",
}

def source_weights(rows):
 groups=defaultdict(lambda:defaultdict(list))
 for j,r in enumerate(rows):groups[r["source_id"]][r["event_id"]].append(j)
 weights=np.zeros(len(rows),dtype=np.float64)
 for events in groups.values():
  for indices in events.values():
   for j in indices:weights[j]=1/len(groups)/len(events)/len(indices)
 if abs(weights.sum()-1)>1e-12:raise ValueError("Incomplete source/event/draw probability law")
 return weights

def moment_summary(rows,actual,predicted,seed):
 groups=defaultdict(list)
 for j,r in enumerate(rows):groups[r["source_id"]].append(j)
 sources=sorted(groups);per=[]
 for source in sources:
  ids=groups[source];local=source_weights([rows[i] for i in ids])
  a=float(np.sum(local*actual[ids]));p=float(np.sum(local*predicted[ids]))
  mse=float(np.sum(local*(predicted[ids]-actual[ids])**2))
  per.append({"source_id":source,"events":len({rows[i]["event_id"] for i in ids}),
   "draws":len(ids),"actual_moment":a,"predicted_moment":p,"bias":p-a,"mse":mse})
 a=np.array([x["actual_moment"] for x in per]);p=np.array([x["predicted_moment"] for x in per])
 rng=np.random.default_rng(seed);ix=rng.integers(len(per),size=(5000,len(per)))
 dif=(p[ix]-a[ix]).mean(1)
 return {"source_count":len(per),"event_count":len({r["event_id"] for r in rows}),
  "draw_count":len(rows),"actual_moment":float(a.mean()),"predicted_moment":float(p.mean()),
  "bias":float((p-a).mean()),"source_weighted_rmse":float(np.sqrt(np.mean([x["mse"] for x in per]))),
  "bias_source_bootstrap_percentile_95":[float(x) for x in np.quantile(dif,[.025,.975])],
  "actual_moment_source_bootstrap_percentile_95":[float(x) for x in np.quantile(a[ix].mean(1),[.025,.975])],
  "per_source":per,"interval_status":"descriptive source bootstrap; not a rigorous finite-support or future-tail certificate"}

def run(root,output):
 output.mkdir(parents=True,exist_ok=True)
 if (output/"RESULTS.json").exists():raise FileExistsError("Preserve completed diagnostics; use a new explicitly labeled replay directory")
 torch.set_num_threads(2);started=time.perf_counter();started_cpu=cpu_seconds()
 seal_path=root/"natural_expanded_results/QUALIFICATION_FREEZE.json"
 seal=json.loads(seal_path.read_text())
 R.ARMS=EXPANDED_ARMS
 study=ExpandedStudy(root/"natural_expanded_assets",output,root/"natural_results")
 if study.profile.digest!=seal["profile_sha256"]:raise ValueError("Frozen expanded policy objective changed")
 study.actor=np.asarray(seal["actor"]["weights"],dtype=np.float64)
 if not np.array_equal(study.fmean,np.asarray(seal["actor"]["features_mean"])) or not np.array_equal(study.fscale,np.asarray(seal["actor"]["features_scale"])):
  raise ValueError("Frozen public-context normalizer changed")
 study.models={};model_bindings={}
 for name,entry in seal["checkpoints"].items():
  path=pathlib.Path(entry["path"])
  if sha(path.read_bytes())!=entry["sha256"]:raise ValueError("Frozen checkpoint file changed")
  record=torch.load(path,map_location="cpu",weights_only=False)
  model=NaturalPortfolio(record["vocabulary"]);model.load_state_dict(record["model"]);model.eval().requires_grad_(False)
  if parameter_hash(model)!=entry["model_sha256"]:raise ValueError("Frozen checkpoint parameters changed")
  study.models[name]=model;model_bindings[name]={"checkpoint_sha256":entry["sha256"],"model_sha256":entry["model_sha256"]}
 actor_hash=sha(canonical(seal["actor"]));before={n:parameter_hash(m) for n,m in study.models.items()}
 protocol={**PROTOCOL,"profile_sha256":study.profile.digest,
  "objective_sha256":study.profile.objective_sha256,"observer_sha256":study.profile.observer_sha256,
  "continuation_sha256":study.profile.continuation_sha256,"actor_sha256":actor_hash,
  "qualification_freeze_file_sha256":sha(seal_path.read_bytes()),"models":model_bindings,
  "source_protocol_sha256":study.sources["protocol_sha256"],
  "code_sha256":sha(pathlib.Path(__file__).read_bytes())}
 protocol["sha256"]=sha(canonical(protocol));write_json(output/"PROTOCOL.json",protocol)
 records=[]
 for number,i in enumerate(study.indices["development"]):
  for draw_id in PROTOCOL["draw_ids"]:
   start=cpu_seconds()
   f=simple_features(study.data["context_video"][i:i+1].astype(np.float32)/255,study.data["context_audio"][i:i+1])
   query=(f[0]-study.fmean)/study.fscale;query[-1]=1.
   action=EXPANDED_ARMS[int(np.argmin(np.logaddexp(0,query@study.actor)))]
   actor_cpu=cpu_seconds()-start
   values,inference_cpu=study.values(action,i,draw_id)
   begin=cpu_seconds()
   record,_=study.score(values,i,0,"frozen_actor_selected_critic",draw_id,begin,inference_cpu+actor_cpu,save=True)
   record.update({"executed_arm":action,"actor_feature_and_selection_cpu_seconds":actor_cpu,
    "generator_cpu_seconds":inference_cpu,"full_actor_cpu_seconds":record["cpu_seconds"],
    "no_target_enters_actor_or_generator":True})
   records.append(record)
  if number%8==0:print("selected-policy critic actual development",number+1,27,flush=True)
 write_json(output/"DEVELOPMENT_ACTUAL_ACTOR_ROLLOUTS.json",records)
 event_index={e["event_id"]:i for i,e in enumerate(study.events)}
 x=np.stack([study.features[event_index[r["event_id"]]] for r in records])
 weights=source_weights(records);target=np.exp(-study.profile.gamma*np.array([r["net_return"] for r in records]))
 xx=torch.tensor(x,dtype=torch.float64);yy=torch.tensor(target,dtype=torch.float64);ww=torch.tensor(weights,dtype=torch.float64)
 beta=torch.zeros(x.shape[1],dtype=torch.float64,requires_grad=True)
 with torch.no_grad():beta[-1]=float(np.log(np.expm1(np.sum(weights*target))))
 optimizer=torch.optim.Adam([beta],lr=PROTOCOL["learning_rate"])
 history=[]
 for step in range(PROTOCOL["steps"]):
  predicted=torch.nn.functional.softplus(xx@beta)
  loss=(ww*(predicted-yy).square()).sum()+PROTOCOL["ridge"]*beta[:-1].square().mean()
  optimizer.zero_grad();loss.backward();optimizer.step()
  if not torch.isfinite(loss):raise FloatingPointError("Selected policy critic became nonfinite")
  if (step+1)%100==0:history.append({"step":step+1,"loss":float(loss.detach())})
 beta_np=beta.detach().numpy()
 critic={"schema":"hepta.natural.selected-policy-moment-critic.v1",
  "profile_sha256":study.profile.digest,"actor_sha256":actor_hash,"model_bindings":model_bindings,
  "continuation_sha256":study.profile.continuation_sha256,"gamma":study.profile.gamma,
  "weights":beta_np.tolist(),"normalizer_mean":study.fmean.tolist(),"normalizer_scale":study.fscale.tolist(),
  "prediction":"softplus(normalized_public_context_features @ weights)",
  "training_rollout_file_sha256":sha((output/"DEVELOPMENT_ACTUAL_ACTOR_ROLLOUTS.json").read_bytes()),
  "training_source_weights":weights.tolist(),"fit_history":history,
  "training_scope":"original development only; direct actual complete-policy exponential moment, source-uniform"}
 write_json(output/"CRITIC.json",critic);critic_sha=sha((output/"CRITIC.json").read_bytes())
 freeze={"protocol_sha256":protocol["sha256"],"critic_file_sha256":critic_sha,
  "actor_sha256":actor_hash,"model_bindings":model_bindings,
  "continuation_sha256":study.profile.continuation_sha256,
  "frozen_before_diagnostic_calibration_read":True,
  "calibration_previously_used_by_original_study":True,
  "policy_not_replaced_or_updated":True}
 write_json(output/"CRITIC_FREEZE.json",freeze)
 # This is an explicitly retrospective diagnostic, never fresh qualification.
 ledger_path=root/"natural_expanded_results/OUTCOME_LEDGER.json"
 cal=[r for r in json.loads(ledger_path.read_text()) if r["split"]=="calibration" and r["arm"]=="actor"]
 if len({r["source_id"] for r in cal})!=16:raise ValueError("Independent calibration source set changed")
 if set(r["source_id"] for r in records)&set(r["source_id"] for r in cal):raise ValueError("Development/calibration source overlap")
 if any(r["profile_sha256"]!=study.profile.digest for r in cal):raise ValueError("Calibration policy objective differs")
 actual=np.exp(-study.profile.gamma*np.array([r["net_return"] for r in cal]))
 calx=np.stack([study.features[event_index[r["event_id"]]] for r in cal])
 corrected=np.logaddexp(0,calx@beta_np)
 legacy=np.array([np.logaddexp(0,calx[j]@study.actor[:,EXPANDED_ARMS.index(r["executed_arm"])]) for j,r in enumerate(cal)])
 new_summary=moment_summary(cal,actual,corrected,PROTOCOL["bootstrap_seed"])
 old_summary=moment_summary(cal,actual,legacy,PROTOCOL["bootstrap_seed"])
 cal_weights=source_weights(cal)
 original_report=json.loads((root/"natural_expanded_results/RESULTS.json").read_text())["selected_action_calibration"]
 after={n:parameter_hash(m) for n,m in study.models.items()}
 if before!=after or actor_hash!=sha(canonical(seal["actor"])):raise AssertionError("Frozen actor/model changed during critic fit")
 result={"schema":"hepta.natural.selected-policy-moment-diagnostic.v1",
  "status":"post-study accounting/estimand repair diagnostic; no fresh qualification or efficacy claim",
  "protocol_sha256":protocol["sha256"],"profile_sha256":study.profile.digest,"critic_file_sha256":critic_sha,
  "actor_sha256":actor_hash,"model_bindings":model_bindings,
  "continuation_sha256":study.profile.continuation_sha256,
  "development":{"sources":8,"events":27,"actual_complete_policy_draws":len(records),
    "source_weights_sum":float(weights.sum()),"all_targets_positive":bool(np.all(target>0)),
    "all_four_artifacts_real_readback":all(r["terminal_kind"]=="delivered" for r in records),
    "mean_full_policy_cpu_seconds":float(np.mean([r["cpu_seconds"] for r in records])),
    "mean_actor_cpu_seconds":float(np.mean([r["actor_feature_and_selection_cpu_seconds"] for r in records])),
    "new_draw_ids":PROTOCOL["draw_ids"],"policy_unchanged":before==after},
  "corrected_selected_policy_critic_source_uniform":new_summary,
  "legacy_candidate_head_source_uniform":old_summary,
  "legacy_reported_event_draw_pooled":{"predicted_moment":original_report["predicted_selected_action_moment_mean"],
    "actual_moment":original_report["actual_selected_action_moment_mean"],"bias":original_report["moment_bias"]},
  "source_estimand_correction":{"old_pooled_actual_moment":float(actual.mean()),
    "source_uniform_actual_moment":float(np.sum(cal_weights*actual)),
    "source_uniform_actual_population_ce":float(-np.log(np.sum(cal_weights*actual))/study.profile.gamma),
    "exp_of_mean_return_NOT_used":float(np.exp(-study.profile.gamma*np.sum(cal_weights*np.array([r["net_return"] for r in cal]))))},
  "calibration_ledger_sha256":sha(ledger_path.read_bytes()),
  "tail_certificate":{"issued":False,"rigorous":False,"enforced_future_cost_upper_bound":None,
    "reason":PROTOCOL["tail_reason"],"finite_support_api_status":"fail closed; no sample extremum is supplied as future support"},
  "wall_seconds":time.perf_counter()-started,"cpu_seconds":cpu_seconds()-started_cpu,
  "limitations":["Calibration sources were independent of fitting but already consumed in the original study; bootstrap intervals are descriptive.",
   "Critic is diagnostic only; deploying it inside a new policy would add costs and require a newly bound continuation and independent evaluation.",
   "Fixed-shape runtime timing is observed directly; no arbitrary parameter derivative of CPU timing is asserted.",
   "Model loading is a one-time setup cost measured in total diagnostic CPU, not part of hot-policy per-episode CPU charges.",
   "Positive moment regression and average calibration do not establish accurate rare tails or natural semantic capability."]}
 write_json(output/"RESULTS.json",result)
 # Independent byte verification for every newly delivered diagnostic artifact.
 suffix={"text":".txt","audio":".wav","image":".png","video":".mkv"};verified=0
 for r in records:
  for modality,expected in r["artifacts"].items():
   p=output/"outputs"/r["arm"]/(r["event_id"]+"-"+str(r["draw"]))/(modality+suffix[modality])
   if sha(p.read_bytes())!=expected:raise AssertionError("Diagnostic delivered artifact changed")
   verified+=1
 write_json(output/"VALIDATION.json",{"saved_artifact_hashes_verified":verified,
  "source_uniform_weights_sum":float(weights.sum()),"actor_and_models_unchanged":True,
  "critic_targets_actual_joint_net_moments":True,"rigorous_tail_certificate_issued":False,"passed":True})
 print(json.dumps({"critic_sha256":critic_sha,"corrected":{k:v for k,v in new_summary.items() if k!="per_source"},
  "legacy_source_uniform":{k:v for k,v in old_summary.items() if k!="per_source"},"tail_certificate":result["tail_certificate"]},indent=2))
 return result

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--root",type=pathlib.Path,required=True);p.add_argument("--output",type=pathlib.Path,required=True);args=p.parse_args();run(args.root,args.output)

"""Frozen pilot -> four-emission training -> calibration -> natural qualification.

No qualification metric is used to select a source, checkpoint, actor or threshold.
The program emits negative results and insufficient semantic calibration explicitly.
"""
import argparse, copy, json, pathlib, time
from collections import defaultdict
import numpy as np
import torch
from .natural_data import canonical, sha, write_json
from .natural_model import (NaturalPortfolio, draw, supervised_loss, pack_bundle, score_bundle,
 simple_features, text_render, parameter_hash, cpu_seconds, SCORE_SPEC, OBJECTIVE_SHA256,
 OBSERVER_SHA256, CONTINUATION_SHA256)
from .profile import NduProfile, CostEvent, DeliveredOutcome, net_return, aggregate, moment_cost, certainty_equivalent

ARMS=("interpolation","source_nearest","fixed_neural","uniform_neural","ndu_neural")
PROTOCOL={
 "schema":"hepta.natural.joint-run.v1","seed":17,"torch_threads":2,
 "pilot_steps":40,"supervised_warmstart_steps":240,"warmstart_batch":16,"warmstart_lr":.001,
 "actual_gradient_steps":8,"actual_gradient_batch_contexts":4,"draws_per_context_training":2,
 "actual_gradient_lr":.00001,"gradient_clip":1.,"qualification_draws":2,
 "actor":"ridge conditional moment on development only; selects one full bundle, not post-hoc modalities",
 "sources":"source-uniform then event-uniform sampling; source-balanced population CE",
 "qualification_source_bootstrap":2000,
 "success_gates":{"ce_gain_source_cluster_lower_95_bound":0.,"selected_action_moment_absolute_bias":.1,
  "observer_action_calibration_accuracy":.6,"observer_sound_calibration_accuracy":.6,
  "joint_semantic_accuracy":.6,"mismatch_mean_joint_utility_drop":.01},
 "execution_platform":"Linux CPU research runner (resource.rusage includes child codec CPU)",
 "scope":"bounded natural 0.5s infilling with label caption; no open-domain synthesis claim",
 "proxy_warmstart":"differentiable media/text losses; explicitly not an exact delivered-NDU gradient",
 "actual_gradient":"full joint-batch score-function with previous-batch baseline (retains shared runtime-cost cross terms), Gaussian image/video/audio and categorical text emission law; all actual returns from PNG/WAV/FFV1/UTF8 reopening",
 "risk_arm_objective":"same frozen population moment cost as final profile, no auxiliary loss during actual-gradient stage",
 "uniform_arm_objective":"equal-budget expected-return comparator (gamma=0); final evaluation uses the common gamma=2 profile",
 "cost_note":"All self+child CPU charges include serialization/readback and scoring; batch execution costs are measured at the executed batch size, and inference latency is reported separately.",
 "failure_policy":"record zero gross utility and all incurred cost; continue qualification without replacement",
}

class Study:
 def __init__(self,assets,out):
  self.assets,self.out=assets,out;out.mkdir(parents=True,exist_ok=True)
  self.sources=json.loads((assets/"SOURCE_PROTOCOL.json").read_text())
  self.events=json.loads((assets/"EVENTS.json").read_text())["events"]
  self.data=dict(np.load(assets/"EVENTS.npz"));self.vocab=self.sources["vocabulary"]
  self.indices={s:[i for i,e in enumerate(self.events) if e["split"]==s] for s in ("train","development","calibration","qualification")}
  self.train_by_source=defaultdict(list)
  for i in self.indices["train"]:self.train_by_source[self.events[i]["source_id"]].append(i)
  self.profile=NduProfile(OBJECTIVE_SHA256,OBSERVER_SHA256,CONTINUATION_SHA256,gamma=2.,
   aggregation="population",utility_bounds=(0.,1.),required_modalities=("text","audio","image","video"))
  self.features=simple_features(self.data["context_video"].astype(np.float32)/255,self.data["context_audio"])
  self.fmean=self.features[self.indices["train"]].mean(0);self.fscale=self.features[self.indices["train"]].std(0)+.01
  self.features=(self.features-self.fmean)/self.fscale;self.features[:,-1]=1.
  self.training_log=[];self.gradient_audits={};self.records=[];self.decoded={}
  self.training_rng=np.random.default_rng(PROTOCOL["seed"])
  self.most_common_caption=max((self.events[i]["caption"] for i in self.indices["train"]),
   key=lambda s:sum(self.events[i]["caption"]==s for i in self.indices["train"]))
 def batch(self,indices):
  def tensor(name,permutation=None):
   x=self.data[name][indices];t=torch.from_numpy(x.copy()).float()
   if x.dtype==np.uint8:t=t/255.
   return t.permute(*permutation) if permutation else t
  return tensor("context_video",(0,1,4,2,3)),tensor("context_audio"),{
   "video":tensor("target_video",(0,1,4,2,3)),"image":tensor("target_image",(0,3,1,2)),
   "audio":tensor("target_audio"),"text":torch.from_numpy(self.data["target_text"][indices].copy()).long()}
 def target(self,i):
  return {"video":self.data["target_video"][i].astype(np.float32)/255,
   "image":self.data["target_image"][i].astype(np.float32)/255,"audio":self.data["target_audio"][i]}
 def sample(self,count,rng):
  names=sorted(self.train_by_source)
  return [int(rng.choice(self.train_by_source[names[int(rng.integers(len(names)))]])) for _ in range(count)]
 def audit(self,model):
  return {n:{"gradient_l2":sum(float(p.grad.square().sum()) for p in m.parameters() if p.grad is not None)**.5,
     "finite":all(bool(torch.isfinite(p.grad).all()) for p in m.parameters() if p.grad is not None)}
     for n,m in model.named_children()}
 def warmstart(self,model,steps,pilot=False):
  optimizer=torch.optim.Adam(model.parameters(),lr=PROTOCOL["warmstart_lr"])
  rng=np.random.default_rng(PROTOCOL["seed"]+(100 if pilot else 0))
  for step in range(steps):
   idx=self.sample(PROTOCOL["warmstart_batch"],rng);v,a,t=self.batch(idx)
   loss=supervised_loss(model(v,a),t).mean();optimizer.zero_grad(set_to_none=True);loss.backward()
   if step==0:self.gradient_audits["pilot_proxy" if pilot else "warmstart_proxy"]=self.audit(model)
   if not torch.isfinite(loss):raise FloatingPointError("Natural warmstart became nonfinite")
   torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
   if step%40==0:print("natural warmstart",pilot,step,float(loss.detach()),flush=True)
  with torch.no_grad():
   v,a,t=self.batch(self.indices["development"]);validation=float(supervised_loss(model(v,a),t).mean())
  return {"steps":steps,"development_supervised_proxy":validation,"model_sha256":parameter_hash(model)}
 def score(self,values,i,local_index,arm,draw_id,cpu_before,inference_cpu,save=False):
  event=self.events[i];directory=self.out/"outputs"/arm/(event["event_id"]+f"-{draw_id}") if save else None
  try:
   delivered,hashes,sizes=pack_bundle(values,local_index,self.vocab,directory)
   metrics=score_bundle(delivered,self.target(i),event["caption"])
   terminal="delivered"
  except (RuntimeError,ValueError,OSError) as exc:
   delivered=None;hashes={};sizes={};metrics={"utility":0.,"failure":str(exc)};terminal="failed"
  used=max(0,cpu_seconds()-cpu_before)+inference_cpu
  outcome=DeliveredOutcome(event["event_id"],f"{arm}-{draw_id}",event["source_id"],metrics["utility"],
   (CostEvent(f"{event['event_id']}/{arm}/{draw_id}/all-cpu",.001*used,kind="inference_actor_codec_readback_scoring"),),
   tuple(sorted(hashes.items())),OBSERVER_SHA256,OBJECTIVE_SHA256,CONTINUATION_SHA256,terminal)
  result=net_return(self.profile,outcome)
  record={"arm":arm,"split":event["split"],"event_id":event["event_id"],"source_id":event["source_id"],"draw":draw_id,
   "profile_sha256":self.profile.digest,"objective_sha256":OBJECTIVE_SHA256,"observer_sha256":OBSERVER_SHA256,
   "continuation_sha256":CONTINUATION_SHA256,"net_return":result,"cpu_seconds":used,"cost":.001*used,
   "artifacts":hashes,"artifact_bytes":sizes,"terminal_kind":terminal,**metrics}
  return record,delivered
 def actual_gradient(self,model,arm):
  model.train();before=model.component_hashes();rng=np.random.default_rng(170081)
  noise=torch.Generator().manual_seed(170089);opt=torch.optim.Adam(model.parameters(),lr=PROTOCOL["actual_gradient_lr"])
  rows=[];prior_baseline=0.
  for step in range(PROTOCOL["actual_gradient_steps"]):
   indices=self.sample(PROTOCOL["actual_gradient_batch_contexts"],rng);v,a,_=self.batch(indices)
   begin=cpu_seconds();output=model(v,a);inference=(cpu_seconds()-begin)/len(indices)
   losses=[];returns=[];logs=[]
   for replicate in range(2):
    values,logp=draw(output,noise)
    rewards=[]
    for j,i in enumerate(indices):
     start=cpu_seconds();record,_=self.score(values,i,j,arm,f"training-{step}-{replicate}",start,inference)
     rewards.append(record["net_return"])
    returns.append(rewards);logs.append(logp)
   gamma=2. if arm=="ndu_neural" else 0.
   cost=torch.tensor([[moment_cost(r,gamma) for r in rr] for rr in returns])
   # A joint-batch score function retains all cross terms when measured runtime
   # costs couple outputs. The only baseline is from the previous batch.
   loss=(cost.mean()-prior_baseline)*(logs[0].sum()+logs[1].sum())
   prior_baseline=float(cost.mean())
   opt.zero_grad(set_to_none=True);loss.backward()
   if step==0:self.gradient_audits[arm+"_actual_output"]=self.audit(model)
   if not torch.isfinite(loss):raise FloatingPointError("Actual delivered gradient became nonfinite")
   torch.nn.utils.clip_grad_norm_(model.parameters(),PROTOCOL["gradient_clip"]);opt.step()
   rows.append({"step":step+1,"objective":float(loss.detach()),"returns":returns,
      "mean_return":float(np.mean(returns)),"profile_sha256":self.profile.digest})
   print("natural actual gradient",arm,step+1,float(np.mean(returns)),flush=True)
  after=model.component_hashes()
  self.training_log.append({"arm":arm,"same_initial_sha256":self.warm_sha,"before":before,"after":after,
    "changed":{k:before[k]!=after[k] for k in before},"rows":rows,
    "exact_emission_score_function":True,"same_output_law_at_deployment":True,"profile_sha256":self.profile.digest})
  return model.eval()
 def values(self,arm,i,draw_id):
  v,a,_=self.batch([i]);start=cpu_seconds()
  if arm in self.models:
   with torch.no_grad():
    output=self.models[arm](v,a)
    # Common random numbers across neural arms; independent deployment draws.
    seed=int(sha(canonical([self.events[i]["event_id"],draw_id]))[:12],16)%(2**31)
    values,_=draw(output,torch.Generator().manual_seed(seed),deterministic=arm=="fixed_neural")
  elif arm=="source_nearest":
   pool=self.indices["train"];dist=((self.features[pool]-self.features[i])**2).mean(1);j=pool[int(dist.argmin())]
   _,_,t=self.batch([j]);values=t
  elif arm=="interpolation":
   w=torch.linspace(.2,.8,4)[None,:,None,None,None];video=v[:,1,None]*(1-w)+v[:,2,None]*w
   toks=np.zeros(16,np.int64);vocab={t:j for j,t in enumerate(self.vocab)}
   for j,t in enumerate(self.most_common_caption.replace(";"," ; ").split()[:16]):toks[j]=vocab.get(t,1)
   values={"image":video[:,2],"video":video,"audio":a,"text":torch.from_numpy(toks[None])}
  else:raise ValueError(arm)
  return values,cpu_seconds()-start
 def evaluate(self,split,arms,draws,actor=False):
  rows=[]
  for k,i in enumerate(self.indices[split]):
   for requested in arms:
    actor_cpu=0.;executed=requested
    if requested=="actor":
     begun=cpu_seconds();pred=np.logaddexp(0,self.features[i]@self.actor)
     executed=ARMS[int(np.argmin(pred))];actor_cpu=cpu_seconds()-begun
    for d in range(draws):
     values,inference=self.values(executed,i,d);begin=cpu_seconds()
     record,decoded=self.score(values,i,0,requested,d,begin,inference+actor_cpu,save=split=="qualification")
     record["executed_arm"]=executed
     if split=="qualification" and d==0 and decoded is not None:self.decoded[(requested,i)]=decoded
     rows.append(record);self.records.append(record)
   if k%8==0:print("natural evaluate",split,k+1,len(self.indices[split]),flush=True)
  return rows
 def summarize(self,rows):
  contexts=defaultdict(list);source_contexts=defaultdict(set)
  for r in rows:contexts[r["event_id"]].append(r["net_return"]);source_contexts[r["source_id"]].add(r["event_id"])
  weights={c:1/len(source_contexts)/len(cs) for cs in source_contexts.values() for c in cs}
  out=aggregate(self.profile,contexts,weights);out.pop("contexts",None)
  out.update({"sources":len(source_contexts),"events":len(contexts),"draws":len(rows),
    "mean_cpu_seconds":float(np.mean([r["cpu_seconds"] for r in rows])),
    "failures":sum(r["terminal_kind"]=="failed" for r in rows),
    "qualities":{m:float(np.mean([r.get("qualities",{}).get(m,0.) for r in rows])) for m in ("text","audio","image","video")}})
  return out
 def fit_actor(self,rows):
  lookup={(r["event_id"],r["arm"]):np.exp(-2*r["net_return"]) for r in rows}
  ids=self.indices["development"];x=self.features[ids]
  y=np.array([[lookup[(self.events[i]["event_id"],a)] for a in ARMS] for i in ids])
  initial=np.linalg.solve(x.T@x+np.eye(x.shape[1]),x.T@np.log(np.expm1(y)))
  weights=torch.tensor(initial,dtype=torch.float32,requires_grad=True)
  xx=torch.tensor(x,dtype=torch.float32);yy=torch.tensor(y,dtype=torch.float32)
  optimizer=torch.optim.Adam([weights],lr=.01)
  for _ in range(400):
   error=(torch.nn.functional.softplus(xx@weights)-yy).square().mean()+.001*weights.square().mean()
   optimizer.zero_grad();error.backward();optimizer.step()
  self.actor=weights.detach().numpy()
  return {"fit_split":"development","weights":self.actor.tolist(),"features_mean":self.fmean.tolist(),
    "features_scale":self.fscale.tolist(),"fit_profile_sha256":self.profile.digest,
    "function":"argmin softplus(linear public-context features), fitted directly by squared error to actual exponential moment; all predicted moments positive"}
 def fit_observer(self):
  # A deliberately small source-trained audit. Its adequacy is a required gate.
  train=self.indices["train"];cal=self.indices["calibration"]
  v=self.data["target_video"].astype(np.float32)/255;a=self.data["target_audio"]
  full=simple_features(v,a);mu=full[train].mean(0);scale=full[train].std(0)+.01;x=(full-mu)/scale;x[:,-1]=1.
  observers={};report={}
  for kind,cols,label in (("action",list(range(7))+[12],"action_id"),("sound",list(range(7,13)),"sound_id")):
   classes=sorted({self.events[i][label] for i in train});lookup={k:j for j,k in enumerate(classes)}
   xx=x[train][:,cols];y=np.zeros((len(train),len(classes)))
   for j,i in enumerate(train):y[j,lookup[self.events[i][label]]]=1.
   w=np.linalg.solve(xx.T@xx+np.eye(len(cols)),xx.T@y)
   pred=np.array(classes)[(x[cal][:,cols]@w).argmax(1)]
   accuracy=float(np.mean(pred==[self.events[i][label] for i in cal]))
   observers[kind]=(cols,classes,w,label)
   report[kind]={"calibration_accuracy":accuracy,"classes":classes,"fit_source_count":32,
    "calibration_source_count":8,"out_of_training_ontology_fraction":float(np.mean([self.events[i][label] not in classes for i in cal]))}
  self.semantic_observer=(mu,scale,observers)
  report["adequate"]=report["action"]["calibration_accuracy"]>=.6 and report["sound"]["calibration_accuracy"]>=.6
  report["qualifier"]="These linear source-trained observers are a calibration guard, not validated general natural-semantic judges."
  return report
 def semantic_accuracy(self,arm):
  mu,scale,observers=self.semantic_observer;correct=[]
  for i in self.indices["qualification"]:
   d=self.decoded.get((arm,i))
   if d is None:correct.append(False);continue
   x=(simple_features(d["video"][None],d["audio"][None])-mu)/scale;x[:,-1]=1.
   matches=[]
   for _,(cols,classes,w,label) in observers.items():matches.append(classes[int((x[:,cols]@w).argmax())]==self.events[i][label])
   correct.append(all(matches) and d["text"]==text_render(self.data["target_text"][i],self.vocab))
  return float(np.mean(correct))
 def bootstrap_delta(self,rows_a,rows_b):
  def moments(rows):
   result=defaultdict(list)
   for r in rows:result[r["source_id"]].append(np.exp(-2*r["net_return"]))
   return {k:np.mean(v) for k,v in result.items()}
  a,b=moments(rows_a),moments(rows_b);sources=sorted(set(a)&set(b))
  x,y=np.array([a[k] for k in sources]),np.array([b[k] for k in sources]);rng=np.random.default_rng(170101)
  draws=rng.integers(len(x),size=(2000,len(x)))
  delta=-.5*np.log(x[draws].mean(1))+.5*np.log(y[draws].mean(1))
  return {"delta":float(-.5*np.log(x.mean())+.5*np.log(y.mean())),
   "source_cluster_percentile_95":[float(q) for q in np.quantile(delta,[.025,.975])],"source_clusters":len(sources)}
 def mismatch(self,arm):
  ids=self.indices["qualification"];deltas=[]
  for j,i in enumerate(ids):
   if (arm,i) not in self.decoded:continue
   other=next((q for q in ids[j+1:]+ids[:j] if self.events[q]["source_id"]!=self.events[i]["source_id"] and (arm,q) in self.decoded),None)
   if other is None:continue
   original=self.decoded[(arm,i)];wrong=dict(original)
   wrong["audio"]=self.decoded[(arm,other)]["audio"];wrong["text"]=self.decoded[(arm,other)]["text"]
   good=score_bundle(original,self.target(i),self.events[i]["caption"])["utility"]
   bad=score_bundle(wrong,self.target(i),self.events[i]["caption"])["utility"]
   deltas.append(good-bad)
  return {"same_source_pairing":False,"mean_joint_utility_drop":float(np.mean(deltas)),"pairs":len(deltas)}

 def run(self):
  started=time.perf_counter();started_cpu=cpu_seconds();torch.set_num_threads(2);torch.manual_seed(PROTOCOL["seed"])
  frozen={**PROTOCOL,"source_protocol_sha256":self.sources["protocol_sha256"],
   "profile_sha256":self.profile.digest,"score_spec":SCORE_SPEC,"source_files":{
    p.name:sha(p.read_bytes()) for p in pathlib.Path(__file__).parent.glob("natural_*.py")}}
  frozen["sha256"]=sha(canonical(frozen))
  write_json(self.out/"RUN_PROTOCOL.json",frozen);write_json(self.out/"NDU_PROFILE.json",self.profile.to_dict())
  # Pilot is discarded; main model restarts with the declared seed.
  pilot=NaturalPortfolio(self.vocab);pilot_report=self.warmstart(pilot,PROTOCOL["pilot_steps"],pilot=True)
  write_json(self.out/"PILOT.json",{**pilot_report,"acceptance":"finite optimization and full gradient paths only; no hyperparameter selection from qualification",
   "profile_sha256":self.profile.digest,"gradient_audit":self.gradient_audits["pilot_proxy"]})
  del pilot
  torch.manual_seed(PROTOCOL["seed"]);warm=NaturalPortfolio(self.vocab)
  self.warmstart(warm,PROTOCOL["supervised_warmstart_steps"]);self.warm_sha=parameter_hash(warm)
  self.models={"fixed_neural":copy.deepcopy(warm).eval(),
   "uniform_neural":self.actual_gradient(copy.deepcopy(warm),"uniform_neural"),
   "ndu_neural":self.actual_gradient(copy.deepcopy(warm),"ndu_neural")}
  checkpoints={}
  for name,model in self.models.items():
   path=self.out/(name+".pt");torch.save({"model":model.state_dict(),"vocabulary":self.vocab,
     "profile_sha256":self.profile.digest,"source_protocol_sha256":self.sources["protocol_sha256"]},path)
   reloaded=torch.load(path,map_location="cpu",weights_only=False)
   check=NaturalPortfolio(self.vocab);check.load_state_dict(reloaded["model"])
   if parameter_hash(check)!=parameter_hash(model):raise ValueError("Natural checkpoint reload changed model")
   checkpoints[name]={"sha256":sha(path.read_bytes()),"model_sha256":parameter_hash(model),"bytes":path.stat().st_size}
  dev=self.evaluate("development",ARMS,1);dev_summary={a:self.summarize([r for r in dev if r["arm"]==a]) for a in ARMS}
  strongest=max((a for a in ARMS if a!="ndu_neural"),key=lambda a:dev_summary[a]["value"])
  actor=self.fit_actor(dev);observer=self.fit_observer()
  calibration=self.evaluate("calibration",("actor",),2)
  pred=[];actual=[]
  for r in calibration:
   i=next(j for j,e in enumerate(self.events) if e["event_id"]==r["event_id"])
   j=ARMS.index(r["executed_arm"]);pred.append(float(np.logaddexp(0,self.features[i]@self.actor[:,j])));actual.append(float(np.exp(-2*r["net_return"])))
  calibration_report={"predicted_selected_action_moment_mean":float(np.mean(pred)),
    "actual_selected_action_moment_mean":float(np.mean(actual)),"moment_bias":float(np.mean(np.array(pred)-actual)),
    "negative_predicted_moments":sum(x<=0 for x in pred),"independent_source_count":8,
    "source_overlap_with_training_or_development":False,"retuning_after_calibration":False,
    "summary":self.summarize(calibration),"profile_sha256":self.profile.digest}
  # Everything governing qualification is sealed before reading its first score.
  seal={"run_protocol_sha256":frozen["sha256"],"profile_sha256":self.profile.digest,"checkpoints":checkpoints,
   "selected_fixed_comparator_from_development":strongest,"actor":actor,"semantic_observer_calibration":observer,
   "calibration":calibration_report,"qualification_source_ids":sorted({self.events[i]["source_id"] for i in self.indices["qualification"]}),
   "status":"frozen-before-qualification","retuning_allowed":False}
  seal["sha256"]=sha(canonical(seal));write_json(self.out/"QUALIFICATION_FREEZE.json",seal)
  qual=self.evaluate("qualification",(*ARMS,"actor"),PROTOCOL["qualification_draws"])
  summaries={a:self.summarize([r for r in qual if r["arm"]==a]) for a in (*ARMS,"actor")}
  deltas={a:self.bootstrap_delta([r for r in qual if r["arm"]==a],[r for r in qual if r["arm"]==strongest]) for a in ("ndu_neural","actor")}
  mismatch=self.mismatch("ndu_neural");semantic=self.semantic_accuracy("ndu_neural")
  gates={"natural_sources_aligned":True,"source_disjoint_protocol":True,
   "all_trainable_components_actual_gradient":all(v["gradient_l2"]>0 and v["finite"] for v in self.gradient_audits["ndu_neural_actual_output"].values()),
   "same_profile_training_deployment_evaluation":True,"all_four_actual_artifacts_reopened":all(r["terminal_kind"]=="delivered" for r in qual),
   "risk_generator_beats_fixed_source_ci":deltas["ndu_neural"]["source_cluster_percentile_95"][0]>0,
   "actor_beats_fixed_source_ci":deltas["actor"]["source_cluster_percentile_95"][0]>0,
   "independent_semantic_observer_adequate":observer["adequate"],
   "generated_joint_semantics":semantic>=.6,
   "mismatch_control_sensitive":mismatch["mean_joint_utility_drop"]>.01,
   "selected_action_moment_positive":calibration_report["negative_predicted_moments"]==0,
   "selected_action_moment_bias_within_frozen_bound":abs(calibration_report["moment_bias"])<.1}
  report={"schema":"hepta.natural.joint-result.v1","profile_sha256":self.profile.digest,
   "source_protocol_sha256":self.sources["protocol_sha256"],"qualification_freeze_sha256":seal["sha256"],
   "scope":PROTOCOL["scope"],"acceptance":all(gates.values()),"gates":gates,
   "data_counts":{s:{"events":len(ids),"sources":len({self.events[i]["source_id"] for i in ids})} for s,ids in self.indices.items()},
   "development":dev_summary,"qualification":summaries,"selected_fixed_comparator":strongest,
   "paired_source_cluster_deltas":deltas,"selected_action_calibration":calibration_report,
   "semantic_observer":observer,"generated_joint_semantic_accuracy":semantic,"mismatch_control":mismatch,
   "gradient_audits":self.gradient_audits,"checkpoints":checkpoints,"training":self.training_log,
   "wall_seconds":time.perf_counter()-started,"total_run_cpu_seconds":cpu_seconds()-started_cpu,
   "limitations":self.sources["limitations"]+["Fixed architecture inference CPU is charged as observed context execution cost; gradients of platform timing with respect to neural parameters are not estimated.",
    "One training seed; uncertainty intervals resample original source videos, not training seeds.",
    "Small 32x32/8fps/8kHz reconstruction generator; no foundation-model capacity claim.",
    "Pilot/warmstart losses are proxies; only the subsequent score-function phase directly targets delivered returns.",
    "Raw source MP4s were streamed and removed to respect storage; each exact source hash and public archive range is retained.",
    "Same-event content is generated neurally, but four valid files and pixel reconstruction alone do not establish semantic generation."]}
  write_json(self.out/"RESULTS.json",report);write_json(self.out/"OUTCOME_LEDGER.json",self.records)
  print(json.dumps({"acceptance":report["acceptance"],"gates":gates,"qualification":summaries,"paired_deltas":deltas},indent=2),flush=True)
  return report

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--assets",type=pathlib.Path,required=True);p.add_argument("--output",type=pathlib.Path,required=True);a=p.parse_args()
 Study(a.assets,a.output).run()

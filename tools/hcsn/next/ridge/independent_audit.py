"""Independent v4 read-only verification; never trains or selects a checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.data import make_data,fingerprint
from next.sequence.run import make_suite
from next.sequence.challenge import retrieval
from next.ridge.models import (apply_model,init_model,matched_width,update_statistics,
    closed_write,read_statistics,financial_table,KEY_DIM,RIDGE)

STANDARDS=dict(replay_metric_absolute_error=1e-10,statistics_absolute_error=3e-5,
    float32_state_roundoff=2e-5,solve_adjoint_normalized_error=2e-5,
    finite_difference_steps=[2e-3,5e-4,1e-4,2e-5],last_query_statistics_exact=True)
RIDGE_KINDS=("full_hx","hcsn","sigmoid","ridge_memory_only")


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):return json.loads((HERE/name).read_text())


def frozen_sources():
    frozen=load("freeze.json")
    rows=[dict(path=name,expected=digest,actual=sha(ROOT/name))
          for name,digest in frozen["source_sha256"].items()]
    return dict(passed=all(r["actual"]==r["expected"] for r in rows),checks=rows,
        freeze_sha256=sha(HERE/"freeze.json"),frozen_at=frozen["frozen_at_utc"])


def mathematical_checks():
    rng=np.random.default_rng(2907311)
    length,batch,width=2048,3,11
    key=jnp.asarray(np.tanh(rng.normal(size=(length,batch,KEY_DIM)))/np.sqrt(KEY_DIM),jnp.float32)
    value=jnp.asarray(np.tanh(rng.normal(size=(length,batch,width))),jnp.float32)
    write=closed_write(jnp.asarray(rng.normal(size=(length,batch,1)),jnp.float32))
    initial=(jnp.zeros((batch,KEY_DIM,KEY_DIM),jnp.float32),
        jnp.zeros((batch,KEY_DIM,width),jnp.float32),jnp.ones((batch,1),jnp.float32))
    def step(state,item):return update_statistics(*state,*item),None
    state,_=jax.jit(lambda:jax.lax.scan(step,initial,(key,value,write)))()
    g,h,r=(np.asarray(a,dtype=np.float64) for a in state)
    k,v,w=(np.asarray(a,dtype=np.float64) for a in (key,value,write))
    denominator=1+w.sum(0)
    reference=(np.einsum("tbi,tbj,tb->bij",k,k,w[...,0])/denominator[...,None],
        np.einsum("tbi,tbj,tb->bij",k,v,w[...,0])/denominator[...,None],1/denominator)
    error=max(float(np.max(np.abs(a-b))) for a,b in zip((g,h,r),reference))
    held=update_statistics(*state,key[0],value[0],jnp.zeros((batch,1),jnp.float32))
    exact=all(np.array_equal(np.asarray(a),np.asarray(b)) for a,b in zip(state,held))
    eig=np.linalg.eigvalsh(.5*(g+g.swapaxes(-1,-2)))
    bound=bool(eig.min()>=-STANDARDS["float32_state_roundoff"]
        and np.trace(g,axis1=-2,axis2=-1).max()<=1+STANDARDS["float32_state_roundoff"]
        and np.linalg.norm(h,axis=1).max()<=1+STANDARDS["float32_state_roundoff"])
    return dict(passed=error<STANDARDS["statistics_absolute_error"] and exact and bound,
        weighted_sum_max_absolute_error=error,exact_zero_write_retention=exact,
        minimum_gram_eigenvalue=float(eig.min()),maximum_gram_trace=float(np.trace(g,axis1=-2,axis2=-1).max()),
        maximum_cross_column_norm=float(np.linalg.norm(h,axis=1).max()),
        maximum_condition=float(((eig[:,-1]+RIDGE)/(eig[:,0]+RIDGE)).max()),
        proof="r=1/(1+sum w); G=sum(w kkT)/(1+sum w); H=sum(w kvT)/(1+sum w). "
              "Norm(k)<=1 and coordinatewise |v|<=1 imply PSD G, trace(G)<=1, each column ||H_j||<=1. "
              "A=G+.01I has eigenvalues [.01,1.01], condition<=101, and |q^T A^-1 H_j|<=100. "
              "These are exact-arithmetic bounds, not uniform long-time BPTT guarantees.")


def solve_adjoint_checks():
    rows=[];key=np.ones(KEY_DIM)/np.sqrt(KEY_DIM);value=np.linspace(-.99,.99,7)
    for scale in (0.,1e-8,.5,1.-1e-6):
        g=jnp.asarray((scale*np.outer(key,key))[None],jnp.float32)
        h=jnp.asarray((scale*np.outer(key,value))[None],jnp.float32)
        q=jnp.asarray(key[None],jnp.float32)
        loss=jax.jit(lambda gg,hh:jnp.sum(read_statistics(gg,hh,q)**2))
        gradients=jax.jit(jax.grad(loss,argnums=(0,1)))(g,h)
        gn,hn,qn=(np.asarray(a[0],dtype=np.float64) for a in (g,h,q))
        # Independent closed-form adjoint, using actual rounded FP32 inputs.
        matrix=.5*(gn+gn.T)+RIDGE*np.eye(KEY_DIM)
        fitted=np.linalg.solve(matrix,hn);read=qn@fitted
        adjoint_h=2*np.outer(np.linalg.solve(matrix.T,qn),read)
        adjoint_g=-adjoint_h@fitted.T;adjoint_g=.5*(adjoint_g+adjoint_g.T)
        reference=(adjoint_g,adjoint_h)
        errors=[float(np.max(np.abs(np.asarray(a[0])-b))/max(1.,np.max(np.abs(b))))
                for a,b in zip(gradients,reference)]
        scans=[]
        for eps in STANDARDS["finite_difference_steps"]:
            directional=[]
            for index,(array,gradient) in enumerate(zip((g,h),gradients)):
                direction=np.arange(array.size,dtype=np.float64).reshape(array.shape)+1
                if index==0:direction=.5*(direction+direction.swapaxes(-1,-2))
                direction=jnp.asarray(direction/np.linalg.norm(direction),jnp.float32)
                plus,minus=array+eps*direction,array-eps*direction
                finite=(loss(plus,h)-loss(minus,h))/(2*eps) if index==0 else (loss(g,plus)-loss(g,minus))/(2*eps)
                analytic=jnp.sum(gradient*direction)
                directional.append(float(jnp.abs(finite-analytic)/jnp.maximum(1.,jnp.abs(analytic))))
            scans.append(dict(step=eps,normalized_errors=directional))
        rows.append(dict(scale=scale,adjoint_normalized_errors=errors,finite_difference_sweep=scans,
            passed=max(errors)<STANDARDS["solve_adjoint_normalized_error"]))
    previous=load("stress_solve_results.json") if (HERE/"stress_solve_results.json").exists() else None
    return dict(passed=all(r["passed"] for r in rows),checks=rows,
        prior_stress_passed=None if previous is None else previous["passed"],
        prior_stress_sha256=sha(HERE/"stress_solve_results.json") if previous else None,
        interpretation="Original finite-difference failures remain unchanged; the analytic adjoint "
                       "and full declared step sweep diagnose precision separately from training performance.")


def query_and_resources():
    rng=np.random.default_rng(2907312)
    x=jnp.asarray(rng.normal(size=(3,19,16)),jnp.float32)
    dt=jnp.asarray(rng.uniform(.05,2.,size=(3,19)),jnp.float32)
    changed=x.at[:,-1].set(x[:,-1]*-2.+.7)
    changed_dt=dt.at[:,-1].set(dt[:,-1]*3.)
    rows=[]
    initialization_hashes={}
    for kind in RIDGE_KINDS:
        width,count=matched_width(kind,16,4)
        p=init_model(kind,jax.random.PRNGKey(2907312),16,width,4)
        initialization_hashes[kind]=hashlib.sha256(b"".join(
            name.encode()+np.asarray(p[name]).tobytes() for name in sorted(p))).hexdigest()
        fn=jax.jit(lambda pp,xx,dd:apply_model(pp,xx,dd,kind,True))
        logits,a=fn(p,x,dt);other,b=fn(p,changed,changed_dt)
        differences={name:float(np.max(np.abs(np.asarray(a[name])-np.asarray(b[name]))))
                     for name in ("gram","cross","inverse_mass","fast","slow")}
        exact=all(differences[name]==0 for name in ("gram","cross","inverse_mass"))
        actual=sum(int(v.size) for v in jax.tree_util.tree_leaves(p))
        states=KEY_DIM*KEY_DIM+KEY_DIM*width+1+(0 if kind=="ridge_memory_only" else 2*width)
        rows.append(dict(kind=kind,width=width,parameters=actual,formula_parameters=count,
            logical_persistent_state_scalars=states,final_query_change=differences,
            logits_change=float(np.max(np.abs(np.asarray(logits)-np.asarray(other)))),
            passed=exact and actual==count))
    source_bytes=sum(a.nbytes for a in np.load(ROOT/"next/full_kernel/baseline_table.npz").values())
    runtime_bytes=sum(a.nbytes for a in financial_table().values())
    baselines=[]
    for kind in ("gru","transformer","snn"):
        width,count=matched_width(kind,16,4)
        params=init_model(kind,jax.random.PRNGKey(2907312),16,width,4)
        actual=sum(int(v.size) for v in jax.tree_util.tree_leaves(params))
        baselines.append(dict(kind=kind,width=width,parameters=actual,formula_parameters=count,
            logical_persistent_state_scalars=width if kind=="gru" else 3*width if kind=="snn" else None,
            passed=actual==count))
    identical=len({initialization_hashes[k] for k in ("full_hx","hcsn","sigmoid")})==1
    return dict(passed=all(r["passed"] for r in rows+baselines) and identical,checks=rows,
        baseline_resources=baselines,
        dynamic_initial_parameter_hashes=initialization_hashes,
        dynamic_shapes_and_initial_parameters_identical=identical,
        actual_fixed_float32_table_bytes=runtime_bytes,source_float64_array_bytes=source_bytes,
        runner_fixed_operator_bytes_means="Source float64 arrays, not runtime FP32 table; frozen field is retained",
        v3_dynamic_state_scalars=630,v3_memory_only_state_scalars=536,
        full_state_ratio_to_v3=1373/630,memory_only_state_ratio_to_v3=1313/536,
        contract="Final query does not write G/H/r; it does update fast/slow states and current residual. "
                 "Only x and dt enter apply_model; labels are used by loss/metrics, never inference. "
                 "All input coordinates use generic learned dense maps; there is no task/marker/answer dispatch.",
        complexity="Prefix update O(K^2+Kh), learned value projection O(h^2), final solve O(K^3+K^2h). "
                   "One K=16 solve per sequence; this is not a measured token-by-token decoder.")


def dataset_audit():
    protocol=load("protocol.json");development=load("development_protocol.json")
    registry=[];train_inputs={};evaluations=[];overlaps=[]
    def input_hashes(data):
        return [hashlib.sha256(data["x"][i].tobytes()+data["dt"][i].tobytes()).hexdigest()
                for i in range(len(data["y"]))]
    def register(cohort,task,seed,split,data):
        tag=f"{cohort}/{task}/{seed}/{split}"
        registry.append(dict(cohort=cohort,task=task,seed=seed,split=split,
            examples=len(data["y"]),length=data["x"].shape[1],sha256=fingerprint(data)))
        key=(task,data["x"].shape[1]);samples=set(input_hashes(data))
        if split.startswith("train"):
            train_inputs.setdefault(key,set()).update(samples)
        elif cohort.startswith("confirmation"):evaluations.append((tag,key,samples))
    for task_index,task in enumerate(development["tasks"]):
        base=development["data_seed_base"]+1000*task_index
        for length in development["training_lengths"]:
            register("development",task,137,f"train_{length}",make_data(task,base+length,2048,length))
        register("development",task,137,"validation",make_data(task,base+201,1024,32))
    old_protocol=json.loads((ROOT/"next/sequence/protocol.json").read_text())
    old_challenges=json.loads((ROOT/"next/sequence/challenge_results.json").read_text())
    old_hashes={r["data_sha256"] for r in old_challenges["runs"]}
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            old_train,old_suite,hashes=make_suite(task,seed,old_protocol)
            old_hashes.update(hashes.values())
            for length,data in zip(old_protocol["training_lengths"],old_train):
                register("v3_training",task,seed,f"train_{length}",data)
            train,suite,hashes=make_suite(task,seed,protocol)
            for length,data in zip(protocol["training_lengths"],train):
                register("confirmation",task,seed,f"train_{length}",data)
            for name,data in suite.items():register("confirmation",task,seed,name,data)
    challenge=load("challenge_protocol.json")
    for index,spec in enumerate(challenge["tasks"]):
        for seed in challenge["training_seeds"]:
            data_seed=challenge["data_seed_base"]+1000*seed+index
            data=make_data("memory",data_seed,spec["examples"],spec["length"]) if spec["trained_task"]=="memory" else retrieval(
                data_seed,spec["examples"],spec["length"],spec["associations"],spec["filler_noise"])
            register("confirmation_challenge",spec["trained_task"],seed,spec["name"],data)
    for tag,key,samples in evaluations:
        shared=samples&train_inputs.get(key,set())
        if shared:overlaps.append(dict(evaluation=tag,exact_input_duplicates_with_any_training=len(shared)))
    for i,(left,key,a) in enumerate(evaluations):
        for right,key_b,b in evaluations[i+1:]:
            if key==key_b and a&b:overlaps.append(dict(left=left,right=right,exact_evaluation_input_duplicates=len(a&b)))
    new=[r for r in registry if r["cohort"].startswith("confirmation")]
    dev={r["sha256"] for r in registry if r["cohort"]=="development"}
    hashes=[r["sha256"] for r in new]
    reused=sorted(set(hashes)&(dev|old_hashes))
    collisions=len(hashes)-len(set(hashes))
    return dict(passed=not(overlaps or reused or collisions),registry=registry,
        confirmation_dataset_count=len(hashes),duplicate_whole_confirmation_dataset_hashes=collisions,
        prior_v3_or_development_whole_dataset_hash_reuse=reused,
        exact_confirmation_evaluation_overlap_checks=overlaps,
        scope="Whole-dataset SHA plus exact (x,dt) input overlap against all v3/development/v4 training "
              "and between v4 evaluation splits. Repeated examples within short finite training tasks "
              "are not forbidden. The same task/seed data are intentionally paired across all seven models.")


def metrics(logits,labels):
    a=np.asarray(logits,np.float64);z=a-a.max(1,keepdims=True)
    logp=z-np.log(np.exp(z).sum(1,keepdims=True));p=np.exp(logp)
    correct=p.argmax(1)==labels;confidence=p.max(1);ece=0.
    bins=np.minimum((10*confidence).astype(np.int64),9)
    for i in range(10):
        selected=bins==i
        if selected.any():ece+=selected.mean()*abs(correct[selected].mean()-confidence[selected].mean())
    return dict(loss=float(-logp[np.arange(len(labels)),labels].mean()),accuracy=float(correct.mean()),
        brier=float(((p-np.eye(p.shape[1])[labels])**2).sum(1).mean()),ece=float(ece))


def replay():
    trained=load("results.json");challenge=load("challenge_results.json")
    if not trained["complete"] or not challenge["complete"]:raise RuntimeError("Wait for completed frozen matrices")
    protocol=load("protocol.json");cases=load("challenge_protocol.json")
    functions={kind:jax.jit(lambda p,x,dt,k=kind:apply_model(p,x,dt,k)) for kind in protocol["models"]}
    def infer(row,data,batch):
        path=HERE/row["checkpoint_file"]
        if sha(path)!=row["checkpoint_sha256"]:raise RuntimeError("Checkpoint hash changed")
        params={k:jnp.asarray(v) for k,v in np.load(path).items()}
        actual=sum(int(v.size) for v in params.values())
        kind,width=row["kind"],row["width"]
        states=width if kind=="gru" else None if kind=="transformer" else 3*width if kind=="snn" else (
            KEY_DIM**2+KEY_DIM*width+1+(0 if kind=="ridge_memory_only" else 2*width))
        if actual!=row["parameter_count"] or states!=row["persistent_state_scalars"]:
            raise RuntimeError("Parameter or logical state count differs from source implementation")
        outputs=[np.asarray(functions[row["kind"]](params,jnp.asarray(data["x"][i:i+batch]),
            jnp.asarray(data["dt"][i:i+batch]))) for i in range(0,len(data["x"]),batch)]
        return metrics(np.concatenate(outputs),data["y"])
    checks=[];thresholds=[]
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            _,suite,hashes=make_suite(task,seed,protocol)
            for row in trained["runs"]:
                if row["task"]!=task or row["seed"]!=seed:continue
                t=row["timing"];best=min(row["history"],key=lambda h:h["validation"]["loss"])["step"]
                budget=(t["steps"]==600 and t["train_examples_seen"]==19200 and t["batch_size"]==32
                    and t["learning_rate"]==.003 and t["warmup_optimizer_updates"]==0
                    and t["compiled_training_shapes"]==3 and t["optimizer_signature_stable"] and t["best_step"]==best)
                for split in ("test_64","test_128"):
                    score=infer(row,suite[split],128)
                    error=max(abs(score[k]-row["metrics"][split][k]) for k in score)
                    checks.append(dict(task=task,seed=seed,kind=row["kind"],split=split,metrics=score,
                        maximum_metric_error=error,passed=error<STANDARDS["replay_metric_absolute_error"]
                        and hashes==row["data_sha256"] and budget))
                if task in protocol["primary_acceptance"]:
                    target=protocol["primary_acceptance"][task]["minimum_every_seed_and_heldout_length"]
                    for length in protocol["heldout_lengths"]:
                        accuracy=row["metrics"][f"test_{length}"]["accuracy"]
                        thresholds.append(dict(task=task,kind=row["kind"],seed=seed,length=length,
                            accuracy=accuracy,target=target,passed=accuracy>=target))
        print("Replayed confirmation",task,flush=True)
    challenges=[]
    for index,spec in enumerate(cases["tasks"]):
        for seed in cases["training_seeds"]:
            data_seed=cases["data_seed_base"]+1000*seed+index
            data=make_data("memory",data_seed,spec["examples"],spec["length"]) if spec["trained_task"]=="memory" else retrieval(
                data_seed,spec["examples"],spec["length"],spec["associations"],spec["filler_noise"])
            for row in trained["runs"]:
                if row["task"]!=spec["trained_task"] or row["seed"]!=seed:continue
                recorded=next(r for r in challenge["runs"] if r["challenge"]==spec["name"]
                    and r["seed"]==seed and r["kind"]==row["kind"])
                score=infer(row,data,32);error=max(abs(score[k]-recorded["metrics"][k]) for k in score)
                challenges.append(dict(challenge=spec["name"],seed=seed,kind=row["kind"],metrics=score,
                    maximum_metric_error=error,passed=error<STANDARDS["replay_metric_absolute_error"]
                    and fingerprint(data)==recorded["data_sha256"] and row["checkpoint_sha256"]==recorded["checkpoint_sha256"]))
        print("Replayed challenge",spec["name"],flush=True)
    failed=[r for r in thresholds if not r["passed"]]
    return dict(passed=len(checks)==210 and len(challenges)==140 and all(r["passed"] for r in checks+challenges),
        confirmation_checks=checks,challenge_checks=challenges,all_seed_length_threshold_checks=thresholds,
        failed_seed_length_targets=failed,primary_full_hx_targets_passed=not any(r["kind"]=="full_hx" for r in failed),
        source_results_sha256=sha(HERE/"results.json"),source_challenge_results_sha256=sha(HERE/"challenge_results.json"),
        training_performed=False,checkpoint_selection_performed=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--phase",choices=("static","replay"),required=True)
    args=parser.parse_args();started=time.perf_counter()
    if args.phase=="static":
        result=dict(standards=STANDARDS,source_sha256=sha(Path(__file__)),frozen_sources=frozen_sources(),
            mathematical_checks=mathematical_checks(),solve_adjoint_checks=solve_adjoint_checks(),
            query_and_resources=query_and_resources(),dataset_audit=dataset_audit(),replay_pending=True)
        result["static_passed"]=all(result[k]["passed"] for k in
            ("frozen_sources","mathematical_checks","solve_adjoint_checks","query_and_resources","dataset_audit"))
    else:
        result=load("independent_audit.json")
        if sha(Path(__file__))!=result["source_sha256"]:raise RuntimeError("Independent audit source changed between phases")
        if not frozen_sources()["passed"]:raise RuntimeError("Frozen source changed")
        result["replay"]=replay();result["replay_pending"]=False
    result[args.phase+"_seconds"]=time.perf_counter()-started
    (HERE/"independent_audit.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(dict(phase=args.phase,static_passed=result["static_passed"],
        replay_pending=result["replay_pending"],replay_passed=result.get("replay",{}).get("passed"))))


if __name__=="__main__":main()

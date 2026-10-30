"""Independent checkpoint, branch and paired-outcome audit; no model selection."""
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
from jax.flatten_util import ravel_pytree
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
FOLDER=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from benchmarks.v2_models import matched_width
from next.ablation import models
from next.common import predict_model
from next.full_kernel import as_jax_table,full_gates

CACHE=Path("/tmp/hcsn-next-encoder-assets")
FIELDS=("loss","accuracy","brier","ece")
BASE_KEYS={"out","out_bias","inp","recurrent","boundary_weights","candidate_weights",
           "bias","boundary","tau_fast","tau_slow","regen","recover","call",
           "memory_feedback","read_fast","read_slow"}
REMOVED={"full":set(),"full_sigmoid":set(),"no_call":{"call"},
    "no_recovery":{"tau_slow","recover","read_slow"},
    "static_boundary":{"boundary_weights","memory_feedback"},
    "no_memory":{"candidate_weights","memory_feedback"},
    "memory_only":{"inp","recurrent","bias","tau_fast","tau_slow","regen",
                   "recover","call","read_fast","read_slow"}}
STATE_MULTIPLIER={"full":3,"full_sigmoid":3,"no_call":3,"no_recovery":2,
                  "static_boundary":3,"no_memory":2,"memory_only":1}
BOOTSTRAP_REPLICATES=5000
BOOTSTRAP_SEED=2026103008


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def independent_metrics(logits,labels):
    shifted=np.asarray(logits,np.float64)-np.asarray(logits,np.float64).max(1,keepdims=True)
    exponential=np.exp(shifted);normalizer=exponential.sum(1)
    probabilities=exponential/normalizer[:,None]
    predictions=logits.argmax(1);correct=predictions==labels
    confidence=probabilities.max(1);bin_ids=np.minimum((confidence*10).astype(int),9)
    calibration=0.
    for number in range(10):
        mask=bin_ids==number
        if mask.any():calibration+=mask.mean()*abs(correct[mask].mean()-confidence[mask].mean())
    target=np.zeros_like(probabilities);target[np.arange(len(labels)),labels]=1
    return dict(loss=float(np.mean(np.log(normalizer)-shifted[np.arange(len(labels)),labels])),
        accuracy=float(correct.mean()),brier=float(np.square(probabilities-target).sum(1).mean()),
        ece=float(calibration))


def paired_bootstrap(lhs,rhs,labels,seed):
    difference=lhs.astype(np.float64)-rhs.astype(np.float64)
    rng=np.random.default_rng(seed);groups=[np.flatnonzero(labels==c) for c in np.unique(labels)]
    crossed=np.empty(BOOTSTRAP_REPLICATES);seed_only=np.empty_like(crossed)
    for index in range(BOOTSTRAP_REPLICATES):
        seeds=rng.integers(0,len(difference),len(difference))
        samples=np.concatenate([rng.choice(group,len(group),replace=True) for group in groups])
        selected=difference[seeds]
        crossed[index]=selected[:,samples].mean();seed_only[index]=selected.mean()
    per_seed=difference.mean(1)
    return dict(mean_difference=float(per_seed.mean()),paired_seed_differences=per_seed.tolist(),
        paired_seed_sd=float(per_seed.std(ddof=1)),
        seed_and_stratified_sample_percentile95=np.percentile(crossed,[2.5,97.5]).tolist(),
        seed_only_percentile95=np.percentile(seed_only,[2.5,97.5]).tolist(),
        bootstrap_seed=seed,replicates=BOOTSTRAP_REPLICATES)


def branch_and_gradient_checks(table32):
    """One deterministic short BPTT witness per actual branch, plus dependencies."""
    records={};rng=np.random.default_rng(2026103009)
    with jax.experimental.enable_x64():
        table={k:jnp.asarray(np.asarray(v,np.float32),jnp.float64) for k,v in table32.items()}
        x=jnp.asarray(rng.normal(0,.4,(2,4,3)),jnp.float64)
        dt=jnp.asarray([[.15,.4,1.,1.7],[.25,.6,1.2,.8]],jnp.float64)
        labels=jnp.asarray([0,2],jnp.int32)
        changed_call=dict(table);changed_risk=dict(table)
        for key in ("call_coeff","call_end"):changed_call[key]=table[key]*.9
        for key in ("risk_coeff","risk_end"):changed_risk[key]=table[key]*.9
        for index,variant in enumerate(models.VARIANTS):
            p=models.init_model(variant,jax.random.PRNGKey(900+index),3,4,3)
            p=jax.tree_util.tree_map(lambda a:jnp.asarray(a,jnp.float64),p)
            flat,unravel=ravel_pytree(p)
            direction=rng.normal(size=len(flat));direction/=np.linalg.norm(direction)
            direction=jnp.asarray(direction,jnp.float64)
            def loss(vector):
                logits=models.apply_model(unravel(vector),x,dt,variant,table)
                return -jax.nn.log_softmax(logits)[jnp.arange(2),labels].mean()
            objective=jax.jit(loss);value,gradient=jax.jit(jax.value_and_grad(loss))(flat)
            ad=float(jnp.vdot(gradient,direction));differences=[]
            for epsilon in (1e-4,3e-5):
                fd=float((objective(flat+epsilon*direction)-objective(flat-epsilon*direction))/(2*epsilon))
                error=abs(fd-ad);limit=2e-6+2e-4*abs(ad)
                assert error<=limit,(variant,ad,fd,error)
                differences.append(dict(epsilon=epsilon,finite_difference=fd,absolute_error=error,tolerance=limit))
            evaluate=jax.jit(lambda lookup:models.apply_model(p,x,dt,variant,lookup))
            original=np.asarray(evaluate(table))
            call_change=float(np.max(np.abs(np.asarray(evaluate(changed_call))-original)))
            risk_change=float(np.max(np.abs(np.asarray(evaluate(changed_risk))-original)))
            expected_call=variant not in ("no_call","memory_only")
            expected_risk=variant not in ("full_sigmoid","memory_only")
            assert (call_change>1e-12)==expected_call,(variant,"Call dependency",call_change)
            assert (risk_change>1e-12)==expected_risk,(variant,"risk dependency",risk_change)
            if variant=="memory_only":
                one=models.apply_model(p,x[:,:1],dt[:,:1],variant,{})
                assert np.array_equal(np.asarray(one),np.broadcast_to(np.asarray(p["out_bias"]),(2,3)))
            records[variant]=dict(parameter_count=len(flat),loss=float(value),
                gradient_finite=bool(np.isfinite(gradient).all()),gradient_l2=float(jnp.linalg.norm(gradient)),
                directional_ad=ad,central_finite_difference=differences,
                call_lookup_perturbation_output_max_abs=call_change,
                risk_lookup_perturbation_output_max_abs=risk_change,
                expected_call_dependency=expected_call,expected_risk_dependency=expected_risk)
    return dict(scope="Two examples, four irregular positive time gaps, three input coordinates, width4; all seven actual recurrence branches",
        precision="float64 short BPTT with the actual runtime float32 table values promoted to float64",
        purpose="Finite-difference check of parameter gradients and runtime dependency witnesses; not a global gradient or optimization proof",
        full_gates_identity=models.full_gates is full_gates,
        table_perturbation="Scale selected Call/risk coefficients and endpoints by0.9 solely as a dependency probe; not an alternative financial calibration",
        memory_only_length1_reads_zero_old_memory=True,branches=records,all_passed=True)


def main():
    started=time.perf_counter()
    originals={name:json.loads((FOLDER/(name+"_results.json")).read_text()) for name in ("ag_news","cifar10")}
    assert all(x["complete"] and len(x["runs"])==35 for x in originals.values()),"Wait until both training runs finish"
    protocol=json.loads((FOLDER/"protocol.json").read_text())
    table_file=ROOT/"next/full_kernel/baseline_table.npz"
    table_metadata=json.loads(table_file.with_suffix(".json").read_text())
    assert table_metadata["fixed_parameters"] and table_metadata["sha256"]==sha(table_file)
    table=as_jax_table(dict(np.load(table_file)),jnp.float32)
    assert models.full_gates is full_gates
    audit=dict(training_repeated=False,datasets={},all_passed=False,
        source_sha256_base="Paths relative to hcsn_research root",
        statistical_protocol=dict(contrasts=["full-full_sigmoid","full-memory_only"],
            replicate_count=BOOTSTRAP_REPLICATES,base_seed=BOOTSTRAP_SEED,
            method="Paired crossed resampling of5 training seeds and class-stratified test examples; same indices for both models",
            interval="95 percent percentile; no multiple-comparison correction across8 contrasts/conditions",
            declaration="Fixed before checkpoint replay and per-example analysis; AG aggregate scores already seen, so descriptive post-hoc audit, not test-blind preregistration",
            selection_use=False,limitations="Five shared-data seeds; fixed encoders, split and hyperparameters; no model-selection or pretraining uncertainty"),
        fixed_financial_parameters=table_metadata["financial_parameters"],
        financial_parameter_learning=False,financial_table_sha256=sha(table_file),
        financial_table_numeric_float32_bytes=sum(v.size*4 for v in table.values()),
        financial_table_numpy_float64_bytes=table_metadata["numeric_bytes"],
        environment=dict(jax=jax.__version__,numpy=np.__version__,cpu_affinity=sorted(os.sched_getaffinity(0))))
    analysis_index=0
    for dataset,result in originals.items():
        metadata=result["metadata"];assert metadata["protocol"]==protocol
        for name,digest in metadata["source_sha256"].items():assert sha(ROOT/name)==digest,name
        feature_file=CACHE/(dataset+"_features.npz")
        assert sha(feature_file)==metadata["feature_sha256"]==result["feature_sha_after_training"]
        manifest=json.loads((ROOT/"next/encoder"/(dataset+"_manifest.json")).read_text())
        assert manifest["features_sha256"]==sha(feature_file)
        assert metadata["table_sha256"]==sha(table_file)
        assert metadata["table_float32_bytes"]==audit["financial_table_numeric_float32_bytes"]
        raw=np.load(feature_file)
        data={split:{key:raw[split+"_"+key] for key in ("x","dt","y")}
              for split in ("train","validation","test","corrupted_test")}
        classes=int(data["train"]["y"].max()+1);dimension=data["train"]["x"].shape[-1]
        width,count=matched_width("hcsn",dimension,classes,6000);assert width==metadata["width"]
        assert np.array_equal(data["test"]["y"],data["corrupted_test"]["y"])
        for split,values in data.items():
            assert metadata["data_shapes"][split]==list(values["x"].shape)
            assert np.isfinite(values["x"]).all() and np.all(values["dt"]>0)
        rows=[];correct={split:{} for split in ("test","corrupted_test")};budgets={}
        functions={v:partial(models.apply_model,variant=v,table=table) for v in models.VARIANTS}
        seen=set()
        for run in result["runs"]:
            variant,seed=run["variant"],run["seed"]
            assert (variant,seed) not in seen;seen.add((variant,seed))
            checkpoint=FOLDER/run["checkpoint_file"];assert sha(checkpoint)==run["checkpoint_sha256"]
            with np.load(checkpoint) as archive:p={k:jnp.asarray(archive[k]) for k in archive.files}
            assert set(p)==BASE_KEYS-REMOVED[variant]
            assert not set(table_metadata["financial_parameters"])&set(p)
            assert all(np.isfinite(v).all() and v.dtype==np.dtype("float32") for v in p.values())
            shapes={key:(width,) for key in BASE_KEYS}
            shapes.update(out=(width,classes),out_bias=(classes,),inp=(dimension+1,width),
                recurrent=(width,width),boundary_weights=(dimension+1,width),candidate_weights=(dimension+1,width))
            assert all(tuple(value.shape)==shapes[key] for key,value in p.items())
            params=sum(v.size for v in p.values());states=STATE_MULTIPLIER[variant]*width
            assert params==run["parameter_count"] and states==run["effective_persistent_state_scalars"]
            if variant in ("full","full_sigmoid"):assert params==count
            budgets[variant]=dict(width=width,trainable_parameters=params,effective_state_scalars=states)
            timing=run["timing"];history=run["history"]
            assert timing["steps"]==300 and timing["batch_size"]==32 and timing["learning_rate"]==.003
            assert timing["warmup_optimizer_updates"]==0 and timing["optimizer_signature_stable"]
            best=min(history,key=lambda h:h["validation"]["loss"])
            assert best["step"]==timing["best_step"]
            assert abs(best["validation"]["loss"]-run["metrics"]["validation"]["loss"])<1e-12
            errors={}
            for split in ("validation","test","corrupted_test"):
                logits=predict_model(functions[variant],p,data[split]);assert np.isfinite(logits).all()
                metrics=independent_metrics(logits,data[split]["y"])
                differences={key:abs(metrics[key]-run["metrics"][split][key]) for key in FIELDS}
                assert max(differences.values())<5e-10,(dataset,variant,seed,split,differences)
                errors[split]=differences
                if split in correct:correct[split][(variant,seed)]=logits.argmax(1)==data[split]["y"]
                if split=="test":assert np.array_equal(logits.argmax(1),run["test_predictions"])
            rows.append(dict(variant=variant,seed=seed,metric_absolute_differences=errors,
                stored_clean_predictions_identical=True,parameter_keys_counts_states_passed=True))
            print("replayed",dataset,variant,seed,flush=True)
        assert seen=={(variant,seed) for variant in models.VARIANTS for seed in range(5)}
        comparisons={}
        for other in ("full_sigmoid","memory_only"):
            comparison={}
            for split in ("test","corrupted_test"):
                left=np.stack([correct[split][("full",seed)] for seed in range(5)])
                right=np.stack([correct[split][(other,seed)] for seed in range(5)])
                comparison[split]=paired_bootstrap(left,right,data[split]["y"],BOOTSTRAP_SEED+analysis_index)
                analysis_index+=1
            comparisons["full_minus_"+other]=comparison
        audit["datasets"][dataset]=dict(checkpoints_replayed=len(rows),runs=rows,
            budgets=budgets,paired_analysis=comparisons,feature_sha256=sha(feature_file),
            source_data_table_protocol_hashes_passed=True,checkpoint_selection_passed=True,
            summary=result["summary"],training_results_sha256=sha(FOLDER/(dataset+"_results.json")))
    audit["branch_and_gradient_checks"]=branch_and_gradient_checks(table)
    paths=[Path(__file__),FOLDER/"models.py",FOLDER/"run_heads.py",FOLDER/"protocol.json",
           ROOT/"benchmarks/v2_models.py",ROOT/"benchmarks/models.py",ROOT/"next/common.py"]
    paths+=list((ROOT/"next/full_kernel").glob("*.py"))
    audit["source_sha256"]={str(p.relative_to(ROOT)):sha(p) for p in paths}
    audit["all_passed"]=True;audit["elapsed_seconds"]=time.perf_counter()-started
    (FOLDER/"audit_results.json").write_text(json.dumps(audit,indent=2)+"\n")
    print(json.dumps({d:x["paired_analysis"] for d,x in audit["datasets"].items()},indent=2),flush=True)


if __name__=="__main__":
    main()

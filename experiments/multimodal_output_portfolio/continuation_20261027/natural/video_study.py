"""Actual pixel generation and source-cluster video allocation experiment."""
import argparse
import hashlib
from pathlib import Path
import time

import cv2
import numpy as np

from .common import freeze, read, save, sha, verify_files
from .video_generator import cheap_features, endpoints, fit_mixer, render, score


def public_sources(rows):
    return [{key:row[key] for key in ("id","source","left","right")} for row in rows]


def fit_gate(rows):
    x=np.asarray([r["features"] for r in rows])
    mean,scale=x.mean(0),np.maximum(x.std(0),1e-5)
    z=np.column_stack((np.ones(len(x)),(x-mean)/scale))
    y=np.asarray([r["flow_score"]["PSNR"]-r["blend_score"]["PSNR"] for r in rows])
    penalty=np.eye(z.shape[1])*.1
    penalty[0,0]=0
    weights=np.linalg.solve(z.T@z+penalty,z.T@y)
    return {"mean":mean.tolist(),"scale":scale.tolist(),"weights":weights.tolist(),"training_rows":len(x)}


def batch(sources,weights,predictor,arm,fraction,output):
    if any("private_target" in row for row in sources):
        raise ValueError("Private target cannot enter video inference")
    output.mkdir(parents=True,exist_ok=False)
    wall,cpu=time.perf_counter(),time.process_time()
    control_wall,control_cpu=time.perf_counter(),time.process_time()
    cache={}
    adaptive=arm in {"learned_budget","matched_random_budget"}
    if adaptive:
        for row in sources:
            cache[row["id"]]=endpoints(row["left"],row["right"])
        if arm=="learned_budget":
            x=np.asarray([cheap_features(*cache[row["id"]]) for row in sources])
            z=np.column_stack((np.ones(len(x)),(x-np.asarray(predictor["mean"]))/np.asarray(predictor["scale"])))
            estimates=z@np.asarray(predictor["weights"])
            order=sorted(range(len(sources)),key=lambda i:(-estimates[i],i))
        else:
            estimates=np.zeros(len(sources))
            order=sorted(range(len(sources)),key=lambda i:hashlib.sha256(("natural-video-2717"+sources[i]["id"]).encode()).hexdigest())
        chosen=set(order[:round(fraction*len(sources))])
    else:
        estimates=[]
        chosen=set() if arm=="fixed_blend" else set(range(len(sources)))
    decision={"arm":arm,"fraction":fraction,"selected_ids":[sources[i]["id"] for i in sorted(chosen)],
        "predicted_gains":list(map(float,estimates)),"flow_calls_before_allocation":0,
        "private_target_received":False,"cache_bytes":sum(a.nbytes+b.nbytes for a,b in cache.values()),
        "frozen_before_generation_ns":time.time_ns()}
    save(output/"DECISION.json",decision)
    controller_cpu,controller_wall=time.process_time()-control_cpu,time.perf_counter()-control_wall
    active_weights=None if arm=="fixed_pure_flow" else (np.zeros(4) if arm=="fixed_initial_mixer" else weights)
    rows=[]
    for i,row in enumerate(sources):
        delivered=render(row["left"],row["right"],active_weights,i in chosen,output/row["id"],cache.get(row["id"]))
        rows.append({"id":row["id"],"source":row["source"],"arm":arm,**delivered,
            "controller_cpu_share":controller_cpu/len(sources),"controller_wall_share":controller_wall/len(sources)})
    total_cpu,total_wall=time.process_time()-cpu,time.perf_counter()-wall
    residual_cpu=total_cpu-sum(r["cpu_seconds"] for r in rows)
    residual_wall=total_wall-sum(r["wall_seconds"] for r in rows)
    for row in rows:
        row["whole_cpu_seconds"]=row["cpu_seconds"]+residual_cpu/len(rows)
        row["whole_wall_seconds"]=row["wall_seconds"]+residual_wall/len(rows)
    save(output/"BATCH_RUNTIME.json",{"whole_cpu_seconds":total_cpu,"whole_wall_seconds":total_wall,
        "sum_row_cpu":sum(r["whole_cpu_seconds"] for r in rows),"sum_row_wall":sum(r["whole_wall_seconds"] for r in rows),
        "controller_cpu_seconds":controller_cpu,"controller_wall_seconds":controller_wall,
        "measurement_receipt_write_excluded":True,"amortized_batch_cost_not_latency":True})
    return rows


def score_batch(private,delivered):
    for source,row in zip(private,delivered):
        if source["id"]!=row["id"]:
            raise ValueError("Evaluator identity mismatch")
        row.update(score(source["private_target"],row["output_path"]))
        row["cost_adjusted_return"]=row["PSNR"]-10*row["whole_cpu_seconds"]
        row["private_scoring_ns"]=time.time_ns()
    return delivered


def summarize(rows,arms,repetitions):
    cases=[]
    for identity in sorted({r["id"] for r in rows}):
        by_arm={}
        for arm in arms:
            group=[r for r in rows if r["id"]==identity and r["arm"]==arm]
            if len(group)!=repetitions or len({r["output_sha256"] for r in group})!=1:
                raise ValueError("Missing or changed generated frame repetitions")
            by_arm[arm]={key:float(np.mean([r[key] for r in group])) for key in
                ("PSNR","pixel_MSE","whole_cpu_seconds","whole_wall_seconds","cost_adjusted_return","expensive_calls")}
        cases.append({"id":identity,"source":group[0]["source"],"arms":by_arm})
    sources=sorted({r["source"] for r in cases})
    source_rows={source:{arm:{key:float(np.mean([r["arms"][arm][key] for r in cases if r["source"]==source]))
        for key in ("PSNR","pixel_MSE","whole_cpu_seconds","whole_wall_seconds","cost_adjusted_return","expensive_calls")}
        for arm in arms} for source in sources}
    summary={arm:{key:float(np.mean([source_rows[source][arm][key] for source in sources]))
        for key in ("PSNR","pixel_MSE","whole_cpu_seconds","whole_wall_seconds","cost_adjusted_return","expensive_calls")}
        for arm in arms}
    comparisons={}
    pairs=[("learned_budget","fixed_learned_flow"),("learned_budget","fixed_blend"),
        ("learned_budget","matched_random_budget"),("fixed_learned_flow","fixed_initial_mixer"),
        ("fixed_learned_flow","fixed_pure_flow")]
    for treatment,baseline in pairs:
        keys=("PSNR","whole_cpu_seconds","whole_wall_seconds","cost_adjusted_return")
        delta=np.asarray([[source_rows[source][treatment][key]-source_rows[source][baseline][key] for key in keys] for source in sources])
        rng=np.random.default_rng(2718)
        sample=delta[rng.integers(len(sources),size=(4000,len(sources)))].mean(1)
        comparison={key:{"difference":float(delta[:,i].mean()),"CI95":np.quantile(sample[:,i],[.025,.975]).tolist()} for i,key in enumerate(keys)}
        comparison["quality_cost_acceptance_passed"]=bool(treatment=="learned_budget" and baseline=="fixed_learned_flow"
            and comparison["PSNR"]["CI95"][0]>=-.25 and comparison["whole_cpu_seconds"]["CI95"][1]<0
            and comparison["whole_wall_seconds"]["CI95"][1]<0)
        comparisons[treatment+" minus "+baseline]=comparison
    return {"summary":summary,"source_rows":source_rows,"comparisons":comparisons,"independent_test_sources":len(sources),
        "test_frames":len(cases),"generated_test_images":len(rows),"population_generalization_proven":False}


def run(assets,output):
    source=Path(__file__).parent
    spec=read(source/"VIDEO_PROTOCOL.json")
    manifest=read(assets/"MANIFEST.json")
    if sha(source/"VIDEO_PROTOCOL.json")!=manifest["protocol_sha256"]:
        raise ValueError("Video protocol changed after allocation")
    verify_files(manifest["files"])
    output.mkdir(parents=True,exist_ok=False)
    registration=freeze(source,source/"VIDEO_PROTOCOL.json",assets/"MANIFEST.json",output,{"opencv_version":cv2.__version__})
    cv2.setNumThreads(1)
    training=[r for r in manifest["samples"] if r["role"]=="train"]
    fit_wall,fit_cpu=time.perf_counter(),time.process_time()
    weights,training_record=fit_mixer(training,spec["trainable_mixer"])
    np.save(output/"PIXEL_MIXER.npy",weights,allow_pickle=False)
    if not np.array_equal(weights,np.load(output/"PIXEL_MIXER.npy",allow_pickle=False)):
        raise ValueError("Generator parameter reload differs")
    training_record.update(cpu_seconds=time.process_time()-fit_cpu,wall_seconds=time.perf_counter()-fit_wall,
        checkpoint_sha256=sha(output/"PIXEL_MIXER.npy"))
    save(output/"TRAINING.json",training_record)
    fit=[]
    for row in training:
        left,right=endpoints(row["left"],row["right"])
        blend=render(row["left"],row["right"],weights,False,output/"fit"/row["id"]/"blend")
        flow=render(row["left"],row["right"],weights,True,output/"fit"/row["id"]/"learned_flow")
        fit.append({"id":row["id"],"source":row["source"],"features":cheap_features(left,right),
            "blend_score":score(row["private_target"],blend["output_path"]),"flow_score":score(row["private_target"],flow["output_path"])})
    predictor=fit_gate(fit)
    save(output/"GATE_TRAINING_ROWS.json",fit)
    save(output/"PREDICTOR.json",predictor)
    validation=[r for r in manifest["samples"] if r["role"]=="validation"]
    choices,valid_rows=[],[]
    for index,fraction in enumerate(spec["controller"]["budgets"]):
        executed=[]
        for clip in sorted({r["source"] for r in validation}):
            group=[r for r in validation if r["source"]==clip]
            raw=batch(public_sources(group),weights,predictor,"learned_budget",fraction,output/"validation"/str(index)/clip)
            executed.extend(score_batch(group,raw))
        choices.append({"fraction":fraction,"validation_objective":float(np.mean([r["cost_adjusted_return"] for r in executed]))})
        valid_rows.extend({"candidate_fraction":fraction,**row} for row in executed)
    choice=min(choices,key=lambda r:(-r["validation_objective"],r["fraction"]))
    gate={"fraction":choice["fraction"],"candidates":choices,"frozen_ns":time.time_ns(),"test_not_started":True}
    save(output/"VALIDATION_ROWS.json",valid_rows)
    save(output/"GATE_FROZEN.json",gate)
    test=[r for r in manifest["samples"] if r["role"]=="test"]
    rows=[]
    for repetition in range(spec["timing_repetitions"]):
        for i,clip in enumerate(sorted({r["source"] for r in test})):
            group=[r for r in test if r["source"]==clip]
            shift=(repetition+i)%len(spec["test_arms"])
            order=spec["test_arms"][shift:]+spec["test_arms"][:shift]
            for arm in order:
                raw=batch(public_sources(group),weights,predictor,arm,choice["fraction"],output/"test"/str(repetition)/clip/arm)
                rows.extend({"repetition":repetition,**r} for r in score_batch(group,raw))
            print({"video_repetition":repetition,"source":clip},flush=True)
    save(output/"ROWS.json",rows)
    result={"schema":"hepta.ndu.continuation.natural.video.result.v1","status":"completed","training":training_record,
        "gate":gate,**summarize(rows,spec["test_arms"],spec["timing_repetitions"]),
        "model_is_small_trained_pixel_mixer":True,"semantic_video_generation_or_multimodal_LLM":False,
        "original_Hepta_neuron_integration":False,"common_input_preparation_seconds":manifest["common_source_preprocessing_wall_seconds"]}
    save(output/"RESULT.json",result)
    for name,digest in registration["source_sha256"].items():
        if sha(source/name)!=digest:
            raise ValueError("Executed scientific source changed")
    verify_files(manifest["files"])
    print(result["comparisons"],flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    try:
        run(args.assets,args.output)
    except Exception as error:
        if args.output.exists():
            save(args.output/"FAILED.json",{"error":type(error).__name__+": "+str(error),"partial_evidence_retained":True})
        raise

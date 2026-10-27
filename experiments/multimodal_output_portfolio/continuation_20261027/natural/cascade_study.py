"""Actual two-model speech portfolio with a matched acquisition-call budget."""
import argparse
import hashlib
from pathlib import Path
import time

import numpy as np

from ...repair_20261026.natural.speech import score
from .common import freeze, read, save, sha, verify_files
from .speech_engine import SpeechEngine


def features(record, duration):
    first = record["generations"][0]
    return [first["confidence"], first["no_speech_probability"], np.log1p(len(first["tokens"])), np.log1p(duration)]


def fit_predictor(rows):
    x = np.asarray([r["features"] for r in rows])
    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-4)
    z = np.column_stack((np.ones(len(x)), (x-mean)/scale))
    y = np.asarray([min(1, r["tiny_score"]["WER"])-min(1, r["base_score"]["WER"]) for r in rows])
    penalty = np.eye(z.shape[1])
    penalty[0, 0] = 0
    weights = np.linalg.solve(z.T @ z + penalty, z.T @ y)
    return {"mean": mean.tolist(), "scale": scale.tolist(), "weights": weights.tolist(),
        "train_examples": len(rows), "target": "clipped tiny WER minus clipped base WER",
        "ridge": 1, "neural_generator_parameters_updated": False}


def predict(predictor, x):
    z = (np.asarray(x)-np.asarray(predictor["mean"]))/np.asarray(predictor["scale"])
    return np.column_stack((np.ones(len(z)), z)) @ np.asarray(predictor["weights"])


def certainty_equivalent(values, gamma=2):
    a = -gamma*np.asarray(values)
    shift = a.max()
    return float(-(shift+np.log(np.exp(a-shift).mean()))/gamma)


def collect_fit(engine_tiny, engine_base, items, output):
    rows = []
    for source in items:
        tiny = engine_tiny.episode(source["path"], "fixed_greedy", -1000, output / source["id"] / "tiny")
        base = engine_base.episode(source["path"], "fixed_beam5", -1000, output / source["id"] / "base")
        rows.append({"id": source["id"], "speaker_id": source["speaker_id"], "tiny": tiny, "base": base,
            "features": features(tiny, source["duration"]),
            "tiny_score": score(source["reference"], tiny["transcript"]), "base_score": score(source["reference"], base["transcript"])})
    return rows


def batch(engine_tiny, engine_base, sources, arm, predictor, fraction, output):
    if any("reference" in source for source in sources):
        raise ValueError("Batch inference accepts public-only source records")
    output.mkdir(parents=True, exist_ok=False)
    batch_wall, batch_cpu = time.perf_counter(), time.process_time()
    first = []
    for source in sources:
        engine = engine_base if arm == "fixed_base" else engine_tiny
        mode = "fixed_beam5" if arm == "fixed_base" else "fixed_greedy"
        first.append(engine.episode(source["path"], mode, -1000, output / source["id"] / "first"))
    wall, cpu = time.perf_counter(), time.process_time()
    k = round(fraction*len(sources)) if arm in {"learned_budget", "matched_random_budget"} else 0
    if arm == "learned_budget":
        x = [features(record, source["duration"]) for record, source in zip(first, sources)]
        predicted = predict(predictor, x).tolist()
        order = sorted(range(len(sources)), key=lambda i: (-predicted[i], i))
    elif arm == "matched_random_budget":
        predicted = []
        order = sorted(range(len(sources)), key=lambda i: hashlib.sha256(("natural-cascade-2713"+sources[i]["id"]).encode()).hexdigest())
    else:
        predicted = []
        order = list(range(len(sources)))
    acquired = set(order[:k])
    decision = {"arm": arm, "fraction": fraction, "acquisition_budget": k, "source_order": [r["id"] for r in sources],
        "predicted_gains": predicted, "selected_source_ids": [sources[i]["id"] for i in order[:k]],
        "targets_or_base_outputs_received": False, "first_deliveries_complete_ns": time.time_ns()}
    save(output / "BATCH_DECISION.json", decision)
    decision_cpu, decision_wall = time.process_time()-cpu, time.perf_counter()-wall
    rows = []
    for index, (source, start) in enumerate(zip(sources, first)):
        records = [start]
        if index in acquired:
            records.append(engine_base.episode(source["path"], "fixed_beam5", -1000,
                output / source["id"] / "continued"))
        wall, cpu = time.perf_counter(), time.process_time()
        destination = output / source["id"] / "DELIVERED.txt"
        destination.write_text(records[-1]["transcript"]+"\n", encoding="utf-8")
        delivered = destination.read_text(encoding="utf-8").strip()
        public = {"id": source["id"], "speaker_id": source["speaker_id"], "arm": arm,
            "transcript": delivered, "actual_tiny_calls": int(arm != "fixed_base"),
            "actual_base_calls": int(arm == "fixed_base" or index in acquired), "calls": records,
            "controller_cpu_share": decision_cpu/len(sources), "controller_wall_share": decision_wall/len(sources),
            "final_path": str(destination), "final_sha256": sha(destination),
            "delivered_before_scoring_ns": time.time_ns()}
        save(output / source["id"] / "PUBLIC_RESULT.json", public)
        public["whole_cpu_seconds"] = sum(r["whole_cpu_seconds"] for r in records)+decision_cpu/len(sources)+time.process_time()-cpu
        public["whole_wall_seconds"] = sum(r["whole_wall_seconds"] for r in records)+decision_wall/len(sources)+time.perf_counter()-wall
        rows.append(public)
    total_cpu, total_wall = time.process_time()-batch_cpu, time.perf_counter()-batch_wall
    residual_cpu = total_cpu-sum(row["whole_cpu_seconds"] for row in rows)
    residual_wall = total_wall-sum(row["whole_wall_seconds"] for row in rows)
    for row in rows:
        row["whole_cpu_seconds"] += residual_cpu/len(rows)
        row["whole_wall_seconds"] += residual_wall/len(rows)
    runtime = {"batch_cpu_seconds": total_cpu, "batch_wall_seconds": total_wall,
        "amortized_loop_and_bookkeeping_cpu_share": residual_cpu/len(rows),
        "amortized_loop_and_bookkeeping_wall_share": residual_wall/len(rows),
        "sum_row_cpu_seconds": sum(row["whole_cpu_seconds"] for row in rows),
        "sum_row_wall_seconds": sum(row["whole_wall_seconds"] for row in rows),
        "not_per_utterance_response_latency": True,
        "measurement_receipt_write_excluded_from_timer": True}
    save(output / "BATCH_RUNTIME.json", runtime)
    return rows, decision


def public_sources(sources):
    return [{key: source[key] for key in ("id", "speaker_id", "path", "duration")} for source in sources]


def score_batch(sources, rows):
    # Called by the evaluator after the public-only batch function has returned.
    for source, row in zip(sources, rows):
        if source["id"] != row["id"]:
            raise ValueError("Private evaluator source ordering differs")
        row.update(score(source["reference"], row["transcript"]))
        row["quality"] = 1-min(1, row["WER"])
        row["return"] = row["quality"]-.01*row["whole_cpu_seconds"]
        row["private_score_ns"] = time.time_ns()
    return rows


def summarize(rows, arms, repetitions):
    speakers = sorted({r["speaker_id"] for r in rows})
    identities = sorted({r["id"] for r in rows})
    by_source = []
    for identity in identities:
        group = {}
        for arm in arms:
            records = [r for r in rows if r["id"] == identity and r["arm"] == arm]
            if len(records) != repetitions or len({r["transcript"] for r in records}) != 1:
                raise ValueError("Incomplete or changed actual transcript repetitions")
            row = records[0]
            group[arm] = {"errors": row["word_errors"], "words": row["reference_words"],
                "cpu": np.mean([r["whole_cpu_seconds"] for r in records]),
                "wall": np.mean([r["whole_wall_seconds"] for r in records]),
                "return": np.mean([r["return"] for r in records]),
                "tiny_calls": row["actual_tiny_calls"], "base_calls": row["actual_base_calls"]}
        by_source.append({"id": identity, "speaker_id": records[0]["speaker_id"], "arms": group})
    summary = {}
    for arm in arms:
        selected = [r["arms"][arm] for r in by_source]
        summary[arm] = {"independent_speakers": len(speakers), "utterances": len(selected),
            "micro_WER": sum(r["errors"] for r in selected)/sum(r["words"] for r in selected),
            "word_errors": int(sum(r["errors"] for r in selected)), "reference_words": int(sum(r["words"] for r in selected)),
            "mean_cpu_seconds": float(np.mean([r["cpu"] for r in selected])),
            "mean_wall_seconds": float(np.mean([r["wall"] for r in selected])),
            "mean_return": float(np.mean([r["return"] for r in selected])),
            "entropic_CE": certainty_equivalent([r["return"] for r in selected]),
            "tiny_calls_per_repetition": sum(r["tiny_calls"] for r in selected),
            "base_calls_per_repetition": sum(r["base_calls"] for r in selected)}
    comparisons = {}
    for baseline in ("fixed_base", "fixed_tiny", "matched_random_budget"):
        groups = []
        for speaker in speakers:
            selected = [r for r in by_source if r["speaker_id"] == speaker]
            treatment = [r["arms"]["learned_budget"] for r in selected]
            control = [r["arms"][baseline] for r in selected]
            groups.append([sum(a["errors"]-b["errors"] for a,b in zip(treatment,control)), sum(a["words"] for a in treatment),
                np.mean([a["cpu"]-b["cpu"] for a,b in zip(treatment,control)]),
                np.mean([a["wall"]-b["wall"] for a,b in zip(treatment,control)]),
                np.mean([a["return"]-b["return"] for a,b in zip(treatment,control)]),
                np.mean([np.exp(-2*a["return"]) for a in treatment]),
                np.mean([np.exp(-2*b["return"]) for b in control])])
        matrix = np.asarray(groups)
        rng = np.random.default_rng(2714)
        sampled = matrix[rng.integers(len(speakers),size=(4000,len(speakers)))]
        metrics = {"WER": sampled[:,:,0].sum(1)/sampled[:,:,1].sum(1), "CPU": sampled[:,:,2].mean(1),
            "wall": sampled[:,:,3].mean(1), "return": sampled[:,:,4].mean(1),
            "CE": -.5*np.log(sampled[:,:,5].mean(1))+.5*np.log(sampled[:,:,6].mean(1))}
        differences = [matrix[:,0].sum()/matrix[:,1].sum(), *matrix[:,2:5].mean(0).tolist(),
            -.5*np.log(matrix[:,5].mean())+.5*np.log(matrix[:,6].mean())]
        result = {name: {"difference": float(value), "CI95": np.quantile(metrics[name],[.025,.975]).tolist()}
            for name,value in zip(("WER","CPU","wall","return","CE"),differences)}
        result["strong_fixed_acceptance_passed"] = bool(baseline == "fixed_base" and result["WER"]["CI95"][1] <= .01
            and result["CPU"]["CI95"][1] < 0 and result["wall"]["CI95"][1] < 0)
        comparisons[baseline] = result
    return {"summary": summary,"comparisons": comparisons,
        "cluster_CI_scope": "Conditional delivered outcomes of this frozen cohort allocation; bootstrap does not reallocate a new cohort"}


def run(assets, output):
    source=Path(__file__).parent
    spec=read(source/"CASCADE_PROTOCOL.json")
    manifest=read(assets/"MANIFEST.json")
    if sha(source/"CASCADE_PROTOCOL.json") != manifest["protocol_sha256"]:
        raise ValueError("Cascade protocol changed after source freeze")
    verify_files(manifest["files"])
    output.mkdir(parents=True,exist_ok=False)
    registration=freeze(source,source/"CASCADE_PROTOCOL.json",assets/"MANIFEST.json",output)
    loading=time.perf_counter()
    tiny=SpeechEngine(manifest["tiny_model_directory"],2)
    base=SpeechEngine(manifest["base_model_directory"],2)
    load=time.perf_counter()-loading
    train=[r for r in manifest["speech"] if r["role"]=="train"]
    validation=[r for r in manifest["speech"] if r["role"]=="validation"]
    fit=collect_fit(tiny,base,train,output/"train")
    predictor=fit_predictor(fit)
    save(output/"TRAINING_ROWS.json",fit)
    save(output/"PREDICTOR.json",predictor)
    options,valid=[],[]
    for index,fraction in enumerate(spec["controller"]["budget_fractions"]):
        executed,_=batch(tiny,base,public_sources(validation),"learned_budget",predictor,fraction,
            output/"validation"/f"quota-{index}")
        executed=score_batch(validation,executed)
        valid.extend({"candidate_fraction":fraction,**row} for row in executed)
        options.append({"fraction":fraction,"validation_CE":certainty_equivalent([row["return"] for row in executed])})
        print({"cascade_validation_quota":fraction,"episodes":len(executed)},flush=True)
    chosen=min(options,key=lambda r:(-r["validation_CE"],r["fraction"]))
    gate={"fraction":chosen["fraction"],"candidates":options,"frozen_ns":time.time_ns(),"test_not_started":True}
    save(output/"VALIDATION_ROWS.json",valid)
    save(output/"GATE_FROZEN.json",gate)
    test=[r for r in manifest["speech"] if r["role"]=="test"]
    rows=[]
    for repetition in range(spec["timing_repetitions"]):
        order=spec["arms"][repetition:]+spec["arms"][:repetition]
        for arm in order:
            result,_=batch(tiny,base,public_sources(test),arm,predictor,chosen["fraction"],output/"test"/f"repeat-{repetition}"/arm)
            result=score_batch(test,result)
            rows.extend({"repetition":repetition,**row} for row in result)
            print({"cascade_repetition":repetition,"arm":arm,"utterances":len(test)},flush=True)
    save(output/"ROWS.json",rows)
    result={"schema":"hepta.ndu.continuation.natural.cascade.result.v1","status":"completed",
        "gate":gate,"model_load_wall_seconds":load,"fitted_predictor_parameters":len(predictor["weights"]),
        "neural_generator_weights_updated":False,"original_Hepta_neuron_integrated":False,
        **summarize(rows,spec["arms"],spec["timing_repetitions"])}
    save(output/"RESULT.json",result)
    for name,digest in registration["source_sha256"].items():
        if sha(source/name)!=digest:
            raise ValueError("Registered source changed during execution")
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

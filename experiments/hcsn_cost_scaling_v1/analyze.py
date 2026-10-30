"""Audit raw predictions and report all registered CPU-scale jobs and gates."""

import argparse
from collections import defaultdict
import itertools
import json
from pathlib import Path
import statistics

import numpy as np

from .study import ROOT, PACKAGE, digest, factory, read, verify, write


def metrics_from_predictions(path, stated, expected_y):
    with np.load(path, allow_pickle=False) as z:
        logits, labels = z["logits"].astype(np.float64), z["labels"]
        si, ti = z["sample_indices"], z["step_indices"]
        expected_si, expected_ti = np.nonzero(expected_y != -100)
        assert np.array_equal(si, expected_si) and np.array_equal(ti, expected_ti), "prediction coordinates"
        assert np.array_equal(labels, expected_y[si, ti]), "prediction labels"
        assert np.array_equal(logits.argmax(-1), z["predictions"]), "prediction argmax"
        assert np.isfinite(logits).all(), "nonfinite predictions"
        shifted = logits - logits.max(-1, keepdims=True)
        ce = np.mean(np.log(np.exp(shifted).sum(-1)) - shifted[np.arange(len(labels)), labels])
        accuracy = np.mean(logits.argmax(-1) == labels)
    assert abs(float(ce) - stated["cross_entropy"]) < 1e-5, "CE replay"
    assert abs(float(accuracy) - stated["accuracy"]) < 1e-12, "accuracy replay"
    return dict(cross_entropy=float(ce), accuracy=float(accuracy), supervised_positions=len(labels))


def aggregate(values):
    return dict(n=len(values), mean=statistics.mean(values),
                sd=statistics.stdev(values) if len(values) > 1 else None,
                minimum=min(values), maximum=max(values))


def analyze(protocol, study, output):
    import torch
    from experiments.hcsn_free_boundary_v1.training import load_weights
    p, study, output = verify(protocol), Path(study), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    terminal = study / "COMPLETE.json"
    if not terminal.exists():
        terminal = study / "ABORTED.json"
    receipt = read(terminal)
    assert receipt["protocol_sha256"] == digest(protocol), "execution protocol"
    data = {}
    for name, record in p["data"].items():
        with np.load(ROOT / record["path"], allow_pickle=False) as z:
            data[name] = {key: z["test_" + key].copy() for key in ("x", "dt", "y")}
    rows, errors, all_quality, indexed = [], [], {}, {}
    for record in receipt["records"]:
        job, directory = record["job"], study / record["directory"]
        key = (job["task"], job["model"], job["width"], job["depth"], job["seed"])
        if record["returncode"] != 0:
            errors.append(dict(job=job, reason="worker failure", receipt=record))
            continue
        try:
            cost, summary = read(directory / "COST.json"), read(directory / "summary.json")
            assert cost["job"] == job and cost["protocol_sha256"] == digest(protocol)
            assert read(directory / "selection.json") == summary["selection"], "durable selection lock"
            quality_lock = read(directory / "QUALITY_SELECTION.json")
            assert quality_lock["points"] == cost["quality_selection"], "durable quality operating point lock"
            assert quality_lock["selection_sha256"] == digest(directory / "selection.json")
            assert summary["access_log"][0]["split"] == "train"
            assert summary["access_log"][1]["split"] == "val"
            assert summary["access_log"][2]["event"] == "selected_and_quality_operating_points_locked"
            assert summary["access_log"][3]["split"] == "test"
            candidate = summary["candidates"][0]
            assert candidate["updates"] > 0 and candidate["stopping_reason"] == "cpu_budget"
            assert candidate["primary_cpu_targets"] == p["optimization"]["primary_cpu_checkpoints"]
            primary = [c for c in candidate["checkpoints"] if c["primary_eligible"]]
            best = min(primary, key=lambda c:(c["validation"]["cross_entropy"],c["training_cpu_seconds"],c["step"]))
            assert best["sha256"] == digest(directory / "selected.npz") == cost["selected_checkpoint_sha256"]
            for checkpoint in candidate["checkpoints"]:
                assert digest(directory / "candidate" / checkpoint["weights"]) == checkpoint["sha256"]
            evaluations = cost["evaluations"]
            for sha, ev in evaluations.items():
                assert digest(directory / ev["predictions"]) == ev["predictions_sha256"]
                metrics_from_predictions(directory / ev["predictions"], ev["test"], data[job["task"]]["y"])
                assert [t["batch"] for t in ev["timing"]] == p["timing"]["batches"]
                assert all(len(t["raw"]) == p["timing"]["repetitions"] for t in ev["timing"])
                for timing in ev["timing"]:
                    assert timing["median_cpu_seconds"] == statistics.median(r["cpu_seconds"] for r in timing["raw"])
                    assert timing["median_wall_seconds"] == statistics.median(r["wall_seconds"] for r in timing["raw"])
            for q in cost["quality_selection"]:
                eligible = [c for c in primary if c["validation"]["accuracy"] >= q["target"]]
                expected = min(eligible,key=lambda c:(c["training_cpu_seconds"],c["step"])) if eligible else None
                assert q["checkpoint"] == expected, "quality operating point selection"
            selected = evaluations[cost["selected_checkpoint_sha256"]]
            model = factory(job["model"],64,p["data"][job["task"]]["output_dim"],job["width"],job["depth"],job["seed"])
            load_weights(directory / "selected.npz", model)
            model.eval()
            with torch.inference_mode():
                replay = model(torch.from_numpy(data[job["task"]]["x"][:4]),
                               torch.from_numpy(data[job["task"]]["dt"][:4]),
                               return_sequence=True, return_aux=False).numpy()
            with np.load(directory / selected["predictions"],allow_pickle=False) as z:
                keep = z["sample_indices"] < 4
                si,ti=z["sample_indices"][keep],z["step_indices"][keep]
                difference=float(np.max(np.abs(replay[si,ti]-z["logits"][keep])))
                assert difference <= 5e-5, "trained checkpoint inference replay"
            changes = candidate["selected_parameter_changes"]
            assert all(v["max_abs"] > 0 for v in changes.values()), "unchanged parameter group"
            row=dict(**job, test_accuracy=selected["test"]["accuracy"], test_ce=selected["test"]["cross_entropy"],
                updates=candidate["updates"], training_cpu_seconds=candidate["training_cpu_seconds"],
                whole_worker_cpu_seconds=record["whole_worker_cpu_seconds"],
                whole_worker_wall_seconds=record["wall_seconds"], peak_rss_bytes=record["peak_rss_bytes"],
                parameters=cost["counts"]["total"], backbone_parameters=cost["counts"]["backbone"],
                selected_timing=selected["timing"], selected_parameter_changes=changes,
                inference_replay_max_abs=difference)
            rows.append(row)
            indexed[key] = row
            all_quality[key] = (cost["quality_selection"], evaluations)
            del model
        except Exception as error:
            errors.append(dict(job=job,reason=type(error).__name__+": "+str(error)))
    groups=defaultdict(list)
    for row in rows:
        groups[(row["task"],row["model"],row["width"],row["depth"])].append(row)
    aggregates=[]
    for (task,model,width,depth),group in sorted(groups.items()):
        aggregates.append(dict(task=task,model=model,width=width,depth=depth,
            **{key:aggregate([r[key] for r in group]) for key in
               ("test_accuracy","updates","whole_worker_cpu_seconds","peak_rss_bytes")},
            parameters=group[0]["parameters"],backbone_parameters=group[0]["backbone_parameters"]))
    tasks=sorted({j["task"] for j in p["jobs"]})
    scales=sorted({(j["width"],j["depth"]) for j in p["jobs"]})
    seeds=sorted({j["seed"] for j in p["jobs"]})
    controls=sorted({j["model"] for j in p["jobs"]}-{"distribution_free_dual"})
    gates=[]
    for task,(width,depth),control,target in itertools.product(tasks,scales,controls,p["quality"]["targets"]):
        pairs=[]
        for seed in seeds:
            pair=dict(seed=seed,qualified=False)
            evidence=[]
            for model in ("distribution_free_dual",control):
                key=(task,model,width,depth,seed)
                if key not in all_quality:
                    break
                qs,evs=all_quality[key]
                point=next(q["checkpoint"] for q in qs if q["target"]==target)
                if point is None:
                    break
                ev=evs[point["sha256"]]
                evidence.append(dict(model=model,validation=point["validation"],test=ev["test"],
                    training_cpu_to_gate=point["training_cpu_seconds"],timing=ev["timing"]))
            pair["models"]=evidence
            if len(evidence)==2:
                pair["qualified"]=(all(e["test"]["accuracy"]>=target for e in evidence) and
                    abs(evidence[0]["test"]["accuracy"]-evidence[1]["test"]["accuracy"])<=p["quality"]["paired_test_accuracy_tolerance"])
                if pair["qualified"]:
                    pair["cpu_inference_speedup_hcsn_vs_control"]={str(a["batch"]):b["median_cpu_seconds"]/a["median_cpu_seconds"]
                        for a,b in zip(evidence[0]["timing"],evidence[1]["timing"])}
            pairs.append(pair)
        gates.append(dict(task=task,width=width,depth=depth,control=control,target=target,pairs=pairs,
            qualified_seed_count=sum(r["qualified"] for r in pairs),
            all_seeds_qualify=all(r["qualified"] for r in pairs)))
    result=dict(schema="hcsn-cpu-scale-analysis.v1",protocol_sha256=digest(protocol),
        analyzer_sha256=digest(__file__),integrity_passed=not errors,
        expected=len(p["jobs"]),executed=len(receipt["records"]),audited=len(rows),errors=errors,
        all_registered_jobs_completed=receipt["completed"] and len(rows)==len(p["jobs"]),
        rows=rows,aggregates=aggregates,equal_quality_gates=gates,
        complete_child_cpu_seconds=receipt["complete_child_cpu_seconds"],
        scope="CPU full-sequence inference and small trained networks, no accelerator/energy/LLM-scale claim",
        timing_repeat_scope="5 repeated timings are not independent training seeds",
        qualification_scope="Quality-conditioned descriptive comparison; qualification is not a significance or equivalence test")
    write(output / "ANALYSIS.json",result)
    lines=["# Trained CPU scale extension", "",f"Audited {len(rows)}/{len(p['jobs'])} registered jobs; errors: {len(errors)}.","",
        "| Task | Model | Width × depth | Parameters | Test accuracy mean ± sample SD | Updates mean | Whole worker CPU mean (s) |",
        "|---|---|---:|---:|---:|---:|---:|"]
    for r in aggregates:
        a=r["test_accuracy"]
        lines.append(f"| {r['task']} | {r['model']} | {r['width']} × {r['depth']} | {r['parameters']} | {100*a['mean']:.2f}% ± {100*(a['sd'] or 0):.2f} pp | {r['updates']['mean']:.1f} | {r['whole_worker_cpu_seconds']['mean']:.2f} |")
    qualified=[g for g in gates if g["all_seeds_qualify"]]
    lines += ["",f"All-three-seed quality qualification: {len(qualified)}/{len(gates)} prespecified task/scale/control/target combinations.","",
        "These are quality-conditioned descriptive operating points, not statistical equivalence. Unqualified comparisons cannot support an equal-quality speed claim. All thresholds were fixed before heldout access; all cost, failed candidates and incomplete comparisons remain in ANALYSIS.json.","",
        "Latency is full-sequence inference from predecoded in-memory features on a shared CPU host. It includes boundary/analytic evaluation. No media decoding or cached autoregressive decoder is included. Peak RSS is a complete-process high-water mark and not isolated model allocation. GPU memory and energy were not measured. The largest model here remains a small encoder; these runs do not establish large-model scaling."]
    (output / "REPORT.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({k:result[k] for k in ("expected","executed","audited","integrity_passed","complete_child_cpu_seconds")}))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--protocol",type=Path,default=PACKAGE/"PROTOCOL.json")
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    analyze(args.protocol,args.study,args.output)

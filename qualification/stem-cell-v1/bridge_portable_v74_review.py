"""Independent stdlib admission of completed V7.4 portable 3x3 observations.

Never loads Torch or an Encoder. Source/weight identity and ORIGINAL TRAIN
metrics are re-evaluated, but a receipt does not authenticate a GPU/host or
prove prospective utility. A missing original pretrained study is a denial.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from bridge_portable_v74 import ARMS, SCHEMA, SEEDS, canonical, file_sha, originals, require, source_id


def read(path, maximum=100_000_000):
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
            "bounded real receipt file required")
    return json.loads(path.read_text(), object_pairs_hook=lambda pairs: _pairs(pairs),
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def _pairs(pairs):
    out={}
    for k,v in pairs:
        require(k not in out,"duplicate receipt JSON property")
        out[k]=v
    return out


def old_score(rows, probabilities):
    """Independent complete binding TRAIN label/pair count, no model calls."""
    require(len(rows)==len(probabilities)==128 and all(type(p) in (float,int)
            and math.isfinite(p) and 0 <= p <= 1 for p in probabilities),
            "complete finite original binding probabilities required")
    pairs=defaultdict(dict)
    correct=0
    for row,p in zip(rows,probabilities):
        require(type(p) is not bool,"no boolean output as probability")
        predicted=int(p>.5)
        correct+=predicted==row["label"]
        prefix, sep, world=row["paragraph_id"].rpartition("/world-")
        require(sep=="/world-" and world in ("0","1") and row["answer_id"] in ("0","1"),
                "original paired-world identity required")
        key=(prefix,row["answer_id"])
        require(world not in pairs[key], "duplicate world candidate")
        pairs[key][world]=(predicted,row["label"])
    require(len(pairs)==64 and all(set(v)=={"0","1"} for v in pairs.values()),
            "complete 64 opposite-world candidate pairs required")
    both=sum(all(pred==truth for pred,truth in values.values()) for values in pairs.values())
    flips=sum(values["0"][0]!=values["1"][0] for values in pairs.values())
    return dict(accuracy=correct/128,both_worlds_correct=both/64,
                evidence_switch_rate=flips/64,original_candidate_correct=correct,
                original_world_pair_correct=both)



def deny_unobserved_future(completion):
    """Never let an old training-only receipt claim generalization or authority."""
    require(completion.get("source_disjoint_future_windows") == 0 and
            completion.get("old_future_retention_verified") is False and
            completion.get("independent_new_task_verified") is False and
            completion.get("cell_split_authorized") is False and
            completion.get("production_authorized") is False and
            completion.get("model_selected") is False,
            "new research training cannot self-certify future efficacy or authority")


def evaluate(output, archives):
    from bridge_gradient_archive_replay import decode_fp32_checkpoint
    from bridge_gradient_review import check_gradient_rows

    output=Path(output)
    source=archives["source"]["reader_train"]
    start=read(output/"start.json",2_000_000)
    complete=read(output/"completed.json",10_000_000)
    deny_unobserved_future(complete)
    require(start["schema"]==complete["schema"]==SCHEMA and
            start["status"]=="started" and complete["status"]=="completed" and
            start["archive"]==archives["archive"] and
            complete["seeds"]==list(SEEDS) and complete["arms"]==list(ARMS) and
            complete["full_candidate_grid_completed"] is True and
            start["production_authorized"] is False and
            complete["production_authorized"] is False and
            complete["cell_split_authorized"] is False and
            complete["old_future_retention_verified"] is False and
            complete["source_disjoint_future_windows"]==0 and
            complete["complete_lifecycle_cost_measured"] is False and
            complete["cache_kind"] in ("exact_historical_v5","new_pretrained_physical_encoding"),
            "unqualified V7.4 completion/authority/experiment identity")
    require(set(complete["results"])=={f"{seed}/{arm}" for seed in SEEDS for arm in ARMS},
            "every seed/arm must have a terminal result")
    models={}
    work=dict(training_step_forwards=0,training_step_backwards=0,
              attempted_optimizer_steps=0,accepted_optimizer_steps=0,
              rejected_optimizer_steps=0)
    for seed in SEEDS:
        parity=start["old_input_parity"][str(seed)]
        require(parity["n"]==128 and parity["class_flips"]==0 and
                parity["independent_numpy_class_flips"]==0 and
                0 <= parity["max_absolute_probability_difference"] <= .001 and
                0 <= parity["independent_numpy_max_abs"] <= .0015 and
                parity["actual_granite_features"] is True and
                parity["historical_training_only_not_future"] is True,
                "authentic-token original V6 warmup parity missing")
        plan=read(output/f"seed-{seed}"/"plan.json",2_000_000)
        require(plan==archives["plans"][seed], "old V6 fixed schedule differs")
        for arm in ARMS:
            folder=output/f"seed-{seed}"/arm
            require(not (folder/"failed.json").exists(), "failed source arm cannot pass")
            attempt=read(folder/"attempt.json",2_000_000)
            require(attempt["seed"]==seed and attempt["arm"]==arm and
                    attempt["plan_sha256"]==plan["plan_sha256"] and
                    attempt["original_model_file_sha256"]==archives["warmup"][seed]["model_file_sha256"] and
                    attempt["production_authorized"] is False,
                    "unaligned original weights/source/arm attempt")
            manifest=read(folder/"candidate-model.json",2_000_000)
            require(manifest["architecture"]["arm"]=="bridge" and manifest["seed"]==seed and
                    manifest["parameter_count"]==42562 and
                    manifest["initial_execution_parameter_sha256"]==archives["warmup"][seed]["execution_parameter_sha256"],
                    "new candidate wrongly bound to original frozen source")
            checkpoint=folder/"candidate.pt"
            require(manifest["file"]=="candidate.pt" and
                    file_sha(checkpoint,8*1024*1024)==manifest["file_sha256"],
                    "candidate checkpoint file bytes changed")
            parsed=decode_fp32_checkpoint(checkpoint.read_bytes())
            require(parsed["parameter_count"]==42562 and
                    parsed["training_parameter_sha256"]==manifest["training_parameter_sha256"] and
                    parsed["execution_parameter_sha256"]==manifest["execution_parameter_sha256"],
                    "independent candidate tensor values do not match recorded model")
            training_file=folder/manifest["training_receipt_file"]
            require(manifest["training_receipt_file"]=="candidate-training.json" and
                    file_sha(training_file)==manifest["training_receipt_sha256"],
                    "training receipt file identity changed")
            receipt=read(training_file,40_000_000)
            counters=check_gradient_rows(receipt,plan,arm)
            work["training_step_forwards"]+=counters["forwards"]
            work["training_step_backwards"]+=counters["backwards"]
            work["attempted_optimizer_steps"]+=500
            work["accepted_optimizer_steps"]+=counters["accepted"]
            work["rejected_optimizer_steps"]+=counters["rejected"]
            observation=read(folder/"old-binding-train.json",5_000_000)
            require(observation["case_ids"]==[source_id(r) for r in source],
                    "old validation case ID or source ordering drift")
            replay=old_score(source,observation["probabilities"])
            for key in ("accuracy","both_worlds_correct","evidence_switch_rate"):
                require(abs(replay[key]-observation["metrics"][key])<1e-12,
                        "independently scored old Binding TRAIN output differs")
            summary=read(folder/"descriptive.json",5_000_000)
            for key in ("accuracy","both_worlds_correct"):
                require(abs(summary["old_training_metrics"][key]-replay[key])<1e-12,
                        "train retention report differs from independent raw score")
            require(summary["production_authorized"] is False and
                    summary["source_disjoint_future_not_evaluated"] is True and
                    complete["results"][f"{seed}/{arm}"]["retained_old_training_cases"] ==
                    summary["old_training_retention"]["passed"],
                    "candidate outcome/retention/authority mismatch")
            models[f"{seed}/{arm}"]=dict(weights_sha256=manifest["file_sha256"],
                old_train_correct=replay["original_candidate_correct"],
                old_train_both_worlds_correct=replay["original_world_pair_correct"],
                accepted_optimizer_steps=counters["accepted"],
                rejected_optimizer_steps=counters["rejected"])
    require(work["training_step_forwards"]==13500 and
            work["training_step_backwards"]==9000 and
            work["attempted_optimizer_steps"]==4500 and
            work["accepted_optimizer_steps"]+work["rejected_optimizer_steps"]==4500,
            "incomplete actual candidate step accounting")
    return dict(schema="hepta.bridge.portable-v74.independent-review.v1",
                status="SOURCE_AND_NUMERIC_RECEIPTS_CONSISTENT_NOT_PRODUCTION",
                archives=archives["archive"],work=work,models=models,
                independent_external_observation_verified=False,
                actual_host_hardware_attested=False,source_disjoint_future_windows=0,
                old_task_future_retention_verified=False,model_promoted=False,
                native_ndu_authority=False,cell_split_authorized=False,
                production_authorized=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("v4","v5","v6","run","report"):
        ap.add_argument("--"+name,type=Path,required=True)
    args=ap.parse_args()
    require(not args.report.exists() and not args.report.is_symlink(),
            "review report is write-once")
    archives=originals(args.v4,args.v5,args.v6)
    result=evaluate(args.run,archives)
    with args.report.open("x") as sink:
        json.dump(result,sink,sort_keys=True,indent=2,allow_nan=False)
        sink.write("\n")


if __name__=="__main__":
    main()

"""Post-hoc training/validation target-shift diagnostic; never opens test data.

Ten acquisition schedules are repeated views of each historical object, not
independent recordings. Actor identities come from the copied train/validation
source ledgers, and binding pairs are also pooled by their original audio ID.
This diagnostic neither changes training nor selects models or seeds.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_parts(identifier):
    if identifier.startswith("audio:"):
        return tuple(part.split(":",1)[1] for part in identifier.split("|"))
    return (identifier,)


def summarize(objects,actor_map,prediction):
    by_recording,by_actor={},{}
    for obj in objects:
        y,mask=obj["y"],obj["mask"]
        p=np.full_like(y,prediction,dtype=float)
        bce=float(((-y*np.log(p)-(1-y)*np.log1p(-p))*mask).sum()/mask.sum())
        positive=float((y*mask).sum()/mask.sum())
        item={"source_id":obj["id"],"target_positive_rate_masked":positive,"bce":bce,
              "complete_endpoint_correct":float(obj["endpoints"][15])}
        parts=source_parts(obj["id"])
        key=parts[0]
        actors=tuple(sorted({str(actor_map[part]) for part in parts}))
        by_recording.setdefault(key,[]).append(item)
        by_actor.setdefault("|".join(actors),[]).append(item)
    def grouped(values):
        return {key:{"objects":len(rows),
            "target_positive_rate_masked":float(np.mean([r["target_positive_rate_masked"] for r in rows])),
            "bce":float(np.mean([r["bce"] for r in rows])),
            "complete_endpoint_correctness":float(np.mean([r["complete_endpoint_correct"] for r in rows]))}
            for key,rows in values.items()}
    recordings,actors=grouped(by_recording),grouped(by_actor)
    return {"by_original_audio_recording":recordings,"by_actor_group":actors,
        "recording_macro_target_positive_rate":float(np.mean([r["target_positive_rate_masked"] for r in recordings.values()])),
        "recording_macro_bce":float(np.mean([r["bce"] for r in recordings.values()])),
        "actor_macro_bce":float(np.mean([r["bce"] for r in actors.values()])),
        "complete_endpoint_recording_macro_accuracy":float(np.mean([r["complete_endpoint_correctness"] for r in recordings.values()]))}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();base=args.input
    plan=json.loads((base/"PLAN.json").read_text());report={}
    for task in plan["tasks"]:
        ledger=json.loads((base/task/"INPUTS.json").read_text())
        datasets,source_hashes,split_meta={}, {}, {}
        for split,filename in (("train","training.npz"),("validation","validation.npz")):
            path=base/task/filename
            assert sha(path)==plan["input_sha256"][f"{task}/{filename}"]
            data=np.load(path,allow_pickle=False)
            ids=ledger[split]["source_ids"]
            sequences,steps,endpoints=data["y"].shape
            assert len(ids)>0 and sequences%len(ids)==0 and endpoints==16 and steps==6
            repeats=sequences//len(ids)
            y=data["y"].reshape(len(ids),repeats,steps,endpoints)
            mask=data["mask"].reshape(y.shape)
            assert np.isfinite(y).all() and np.isfinite(mask).all()
            assert np.isin(y,[0,1]).all() and np.isin(mask,[0,1]).all()
            # The source target table is the same across all schedule prefixes.
            assert np.array_equal(y,np.broadcast_to(y[:,:1,:1],y.shape))
            source_name="train.npz" if split=="train" else "validation.npz"
            source_path=base/"assets/data"/source_name
            assert sha(source_path)==plan["input_sha256"][f"assets/data/{source_name}"]
            source=np.load(source_path,allow_pickle=False)
            actors=dict(zip(source["clip_ids"].astype(str),source["actors"].astype(str),strict=True))
            objects=[{"id":identifier,"y":y[i],"mask":mask[i],"endpoints":y[i,0,0]} for i,identifier in enumerate(ids)]
            unique_recordings={part for identifier in ids for part in source_parts(identifier)}
            actor_groups={actors[part] for part in unique_recordings}
            eligible=mask.any(axis=(1,2))
            unique_positive=[float(y[i,0,0][eligible[i]].mean()) for i in range(len(ids))]
            datasets[split]=(objects,actors)
            split_meta[split]={"objects":len(ids),"acquisition_schedules_per_object":repeats,
                "source_recordings":sorted(unique_recordings),"distinct_source_recordings":len(unique_recordings),
                "actors":sorted(actor_groups),"distinct_actors":len(actor_groups),
                "unique_eligible_endpoints_per_object":np.sum(eligible,axis=1).tolist(),
                "object_macro_unique_endpoint_target_positive_rate":float(np.mean(unique_positive)),
                "complete_endpoint_object_accuracy":float(y[:,0,0,15].mean())}
            source_hashes[str(path.relative_to(base))]=sha(path)
            source_hashes[str(source_path.relative_to(base))]=sha(source_path)
        assert not set(split_meta["train"]["source_recordings"])&set(split_meta["validation"]["source_recordings"])
        assert not set(split_meta["train"]["actors"])&set(split_meta["validation"]["actors"])
        initial=summarize(*datasets["train"],.5)
        train_prior=float(np.clip(initial["recording_macro_target_positive_rate"],1e-6,1-1e-6))
        statistics={split:{"constant_half":summarize(*values,.5),
                           "constant_training_prior":summarize(*values,train_prior)} for split,values in datasets.items()}
        report[task]={"metadata":split_meta,"training_masked_prior":train_prior,
            "baseline_prior_clip":[1e-6,1-1e-6],"statistics":statistics,"input_sha256":source_hashes}
    result={"schema":"hcsn-v10-historical-AV-target-shift-diagnostic.v1","post_hoc":True,
        "test_bytes_or_labels_opened":False,"model_or_seed_selection_performed":False,
        "target":"Actual correctness of the old fixed content head at legal future cache endpoints",
        "schedule_replicates_are_independent_recordings":False,
        "scope":"Descriptive train/validation shift and constant correctness baselines; no new recording or generalization qualification",
        "source_sha256":sha(Path(__file__)),"tasks":report}
    with args.output.open("x") as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write("\n")
    print(json.dumps({t:{"train_positive":r["statistics"]["train"]["constant_half"]["recording_macro_target_positive_rate"],
        "validation_positive":r["statistics"]["validation"]["constant_half"]["recording_macro_target_positive_rate"],
        "train_prior_validation_bce":r["statistics"]["validation"]["constant_training_prior"]["recording_macro_bce"],
        "half_validation_bce":r["statistics"]["validation"]["constant_half"]["recording_macro_bce"]} for t,r in report.items()},indent=2))


if __name__=="__main__":
    main()

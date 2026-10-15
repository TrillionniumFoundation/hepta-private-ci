"""Model- and fit-independent synthetic-image task scorer, pure stdlib.

Prediction and label artifacts are separately SHA-pinned before the scorer opens
future labels. This does NOT authenticate the ground-truth owner or physical model.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "hepta.e2.crossmodal-synthetic-physical.v1"
ARMS = ("fitted", "rotated_target_control", "unaligned_identity")
CLASSES = ("red-square", "blue-circle", "green-triangle", "yellow-diamond")

class Reject(ValueError):
    pass

def canonical(x):
    return (json.dumps(x, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def strict_pairs(pairs):
    x = {}
    for k, v in pairs:
        if k in x: raise Reject("duplicate JSON key")
        x[k] = v
    return x

def read_file(path: Path, expected: str, *, jsonl=False):
    if (type(expected) is not str or len(expected) != 64 or
        any(c not in "0123456789abcdef" for c in expected)):
        raise Reject("invalid file SHA pin")
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 5_000_000:
        raise Reject("unsafe or oversized file")
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise Reject("content digest mismatch")
    if jsonl:
        if not raw.endswith(b"\n"): raise Reject("noncanonical JSONL")
        result=[]
        for line in raw.splitlines():
            obj = json.loads(line, object_pairs_hook=strict_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(Reject("nonfinite")))
            if canonical(obj) != line + b"\n": raise Reject("noncanonical row")
            result.append(obj)
        return result
    obj = json.loads(raw, object_pairs_hook=strict_pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(Reject("nonfinite")))
    if canonical(obj) != raw: raise Reject("noncanonical JSON")
    return obj

def score(prediction, targets, future_sources, train_sources, producer):
    if (type(prediction) is not dict or set(prediction) != {
            "schema", "synthetic_data", "arms", "geometry_pred_sha256", "class_names",
            "rows", "future_labels_seen", "production_accepted", "authority"}
        or prediction["schema"] != SCHEMA + ".class-predictions"
        or prediction["synthetic_data"] is not True
        or prediction["arms"] != list(ARMS)
        or prediction["class_names"] != list(CLASSES)
        or prediction["future_labels_seen"] is not False
        or prediction["production_accepted"] is not False
        or prediction["authority"] != "DENY_ALL"):
        raise Reject("invalid class prediction or authority")
    if (type(producer) is not dict or producer.get("schema") != SCHEMA + ".producer-receipt"
        or producer.get("synthetic_data") is not True
        or producer.get("future_labels_seen") is not False
        or producer.get("model_publisher_independently_authenticated") is not False
        or producer.get("stem_selected") is not False
        or producer.get("production_accepted") is not False
        or producer.get("authority") != "DENY_ALL"):
        raise Reject("untrusted producer envelope")
    if producer.get("dino_train_forwards") != 16 or producer.get("dino_future_forwards") != 8:
        raise Reject("physical DINO count claim missing")
    if type(producer.get("granite_train_forwards")) is not int or producer["granite_train_forwards"] < 1:
        raise Reject("missing Granite actual-forward claim")
    if producer.get("sealed_geometry_predictions_sha256") != prediction["geometry_pred_sha256"]:
        raise Reject("classification not derived from corresponding sealed geometry predictions")
    if not all(isinstance(v, list) for v in (targets, future_sources, train_sources)) or len(targets) != 8 or len(future_sources) != 8 or len(train_sources) != 16:
        raise Reject("wrong complete source/target cardinality")
    groups = {r["group_id"] for r in train_sources}
    images = {r["image_sha256"] for r in train_sources}
    max_train = max(r["observed_at"] for r in train_sources)
    by_source={}
    for src in future_sources:
        keys={"case_id", "group_id", "scope", "observed_at", "split", "condition", "image_path",
              "image_sha256", "question", "source_sha256"}
        if type(src) is not dict or set(src) != keys or src["split"] != "future":
            raise Reject("bad future source fields")
        if src["case_id"] in by_source or src["group_id"] in groups or src["image_sha256"] in images or src["observed_at"] <= max_train:
            raise Reject("source collision with train or duplicate")
        if src["condition"] != "vision_required":
            raise Reject("out-of-scope synthetic condition")
        casehash = sha(canonical(["hepta.e2.image-case.v1", src["case_id"], src["group_id"],
                                  src["scope"], src["observed_at"], src["condition"],
                                  src["image_sha256"], src["question"]]))
        if casehash != src["source_sha256"]:
            raise Reject("source case identity not actually bound")
        by_source[src["case_id"]] = src
    labelled={}
    for label in targets:
        fields={"case_id", "group_id", "scope", "observed_at", "source_sha256",
                "source_input_sha256", "class_label"}
        if type(label) is not dict or set(label) != fields or label["case_id"] in labelled or label["class_label"] not in CLASSES:
            raise Reject("unapproved, duplicated, or invalid target label")
        labelled[label["case_id"]]=label
    seen=set()
    tallies={arm: {"correct":0,"total":0} for arm in ARMS}
    paired={arm: {"rescued":0,"harmed":0,"both_correct":0,"both_wrong":0} for arm in ARMS if arm!="unaligned_identity"}
    for pred in prediction["rows"]:
        fields={"case_id", "group_id", "scope", "observed_at", "source_input_sha256", "predicted_labels"}
        if type(pred) is not dict or set(pred) != fields or pred["case_id"] in seen:
            raise Reject("missing/extra or duplicate prediction fields")
        cid=pred["case_id"]
        if cid not in by_source or cid not in labelled:
            raise Reject("unknown prediction case")
        seen.add(cid)
        src=by_source[cid]; target=labelled[cid]
        for key in ("case_id", "group_id", "scope", "observed_at"):
            if pred[key]!=src[key] or target[key]!=src[key]:
                raise Reject("case/group/scope/time mismatch")
        if pred["source_input_sha256"]!=src["image_sha256"] or target["source_input_sha256"]!=src["image_sha256"] or target["source_sha256"]!=src["source_sha256"]:
            raise Reject("image or question source hash drift")
        if type(pred["predicted_labels"]) is not dict or set(pred["predicted_labels"])!=set(ARMS):
            raise Reject("missing or extra experiment arms")
        right={}
        for arm in ARMS:
            if pred["predicted_labels"][arm] not in CLASSES:
                raise Reject("class label outside training task")
            right[arm]=pred["predicted_labels"][arm]==target["class_label"]
            tallies[arm]["correct"]+=int(right[arm]);tallies[arm]["total"]+=1
        for arm in paired:
            curr,baseline=right[arm],right["unaligned_identity"]
            paired[arm]["rescued" if curr and not baseline else
                        "harmed" if baseline and not curr else
                        "both_correct" if curr else "both_wrong"]+=1
    if seen!=set(by_source) or seen!=set(labelled):
        raise Reject("source/target/label coverage incomplete")
    return {"schema": SCHEMA + ".independent-class-outcomes", "cases":len(seen),
            "source_cohorts": "synthetic-single-future-panel-not-three-prospective-windows",
            "synthetic_data":True, "label_origin_independently_authenticated":False,
            "model_forwards_independently_attested":False,
            "task_arms":[{"arm":arm,**tallies[arm],"accuracy":tallies[arm]["correct"]/tallies[arm]["total"]}
                         for arm in ARMS],
            "paired_against_unaligned":[{"arm":arm,**paired[arm]} for arm in ARMS if arm in paired],
            "native_multimodal_and_ocr_not_executed":True,
            "three_future_windows_available":False,
            "complete_e2_five_arm_result":False,
            "stem_selected":False,"production_accepted":False,"authority":"DENY_ALL"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--predicted",type=Path,required=True)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--withheld",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    predp=a.predicted/"sealed_class_predictions.json"
    rcp=a.predicted/"producer_receipt.json"
    pred=read_file(predp,sha(predp.read_bytes()))
    receipt=read_file(rcp,sha(rcp.read_bytes()))
    if sha(predp.read_bytes())!=receipt["sealed_class_predictions_sha256"]:
        raise Reject("class predictions changed after seal")
    manifest_p=a.source.parent/"source-manifest.json"
    manifest=read_file(manifest_p,sha(manifest_p.read_bytes()))
    if manifest.get("synthetic_data") is not True or manifest.get("production_accepted") is not False:
        raise Reject("not the declared synthetic research panel")
    paths=[(a.withheld/"future_class_targets.jsonl", "future_class_targets.jsonl"),
           (a.source/"future_images.jsonl", "future_images.jsonl"),
           (a.source/"train_images.jsonl", "train_images.jsonl")]
    data=[read_file(path,manifest["file_sha256s"][name],jsonl=True) for path,name in paths]
    result=score(pred,*data,receipt)
    from os import fsync
    if a.output.exists(): raise Reject("refuse to replace result")
    with a.output.open('xb') as out:
        out.write(canonical(result));out.flush();fsync(out.fileno())
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()

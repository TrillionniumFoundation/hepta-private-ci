#!/usr/bin/env python3
"""Read-only independent replay of a registered AG News Q24 -> 64D Cell panel.

Does not import the Encoder producer, conversion implementation, Torch, or
training/evaluation code. Verifies data lineage/arithmetic, not external origin,
model execution, provenance signatures, future-time outcomes, or NDU utility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

ORIGINAL_SHA = "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4"
MODEL_REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
SHARED_SOURCE = "e05f939f65fb76f6bdbf7470eef7e63b77284dcd"
INDEX = (("old_train", "train", 0, 64), ("new_train", "train", 64, 128),
         ("old_retention", "calibration", 0, 16), ("future_1", "test", 0, 32),
         ("future_2", "test", 32, 64), ("ood", "calibration", 16, 32))
Q24 = 1 << 24
MAX_SIZE = 4 * 1024 * 1024

class Denied(ValueError):
    pass

def need(ok: bool, msg: str) -> None:
    if not ok:
        raise Denied(msg)

def canonical(x: object) -> bytes:
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def sha(x: object) -> str:
    return hashlib.sha256(canonical(x)).hexdigest()

def no_duplicate(pairs):
    obj = {}
    for key, value in pairs:
        need(key not in obj, "duplicate source field")
        obj[key] = value
    return obj

def read(path: Path) -> dict:
    fd = os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_SIZE,
             "invalid source file")
        raw = os.read(fd,MAX_SIZE+1)
        after = os.fstat(fd)
        need(len(raw) == before.st_size and (before.st_ino,before.st_mtime_ns,before.st_dev,
             before.st_size)==(after.st_ino,after.st_mtime_ns,after.st_dev,after.st_size),
             "changed source while reading")
    finally:
        os.close(fd)
    try:
        result=json.loads(raw,object_pairs_hook=no_duplicate,
                          parse_constant=lambda x: (_ for _ in ()).throw(Denied("nonfinite JSON")))
    except (ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise Denied("invalid JSON") from exc
    need(type(result) is dict, "top-level must be an object")
    return result

def independent_replay(source: dict, table: dict, panel: dict, receipt: dict, *,seed:int) -> dict:
    need(sha(source)==ORIGINAL_SHA and source.get("case_count")==224 and
         source.get("cross_sectional_not_future") is True, "source not the frozen 224-row study")
    source_cases=source.get("cases")
    need(type(source_cases) is list and len(source_cases)==224, "missing source rows")
    need(type(table) is dict and table.get("schema")=="hepta.cell-meta-granite-q24-rows.v1" and
         table.get("dataset_panel_sha256")==ORIGINAL_SHA and
         table.get("model_id")==MODEL_ID and
         table.get("model_revision")==MODEL_REVISION and
         table.get("encoder_source_sha")==SHARED_SOURCE and
         table.get("dim")==384 and table.get("pooling")=="cls_l2_q24" and
         table.get("reported_physical_model_requests")==224 and
         table.get("independent_model_origin_verified") is False and
         table.get("production_admission")=="BLOCKED", "unsafe feature table")
    snapshot=table.get("snapshot_files_sha256")
    need(type(snapshot) is str and len(snapshot)==64 and
         all(c in "0123456789abcdef" for c in snapshot) and
         any(c!="0" for c in snapshot),"local snapshot digest required")
    raw_rows=table.get("rows")
    need(type(raw_rows) is list and len(raw_rows)==224, "feature rows missing")
    q_by_id={}
    for original, feature in zip(source_cases,raw_rows,strict=True):
        need(type(original) is dict and type(feature) is dict and
             set(feature)=={"case_id","source_digest","joint_input_digest","feature_q24",
                            "original_tokens","feature_sha256"},"strict source/feature inventory")
        identity=original.get("source_digest")
        need(type(identity) is str and len(identity)==64 and
             feature["case_id"]==original.get("case_id")==identity[:24] and
             feature["source_digest"]==identity and
             feature["joint_input_digest"]==original.get("joint_input_digest") and
             identity not in q_by_id, "source row swapped or duplicated")
        joint=original.get("joint_input")
        need(type(joint) is dict and
             hashlib.sha256(joint["state"].encode()).hexdigest()==identity and
             sha(joint)==original.get("joint_input_digest"), "source text changed")
        q=feature["feature_q24"]
        need(type(q) is list and len(q)==384 and
             all(type(x) is int and abs(x)<=Q24 for x in q) and
             any(x for x in q) and
             .998 <= sum(x*x for x in q)/(Q24*Q24) <= 1.002 and
             type(feature["original_tokens"]) is int and
             0 < feature["original_tokens"]<=512,"invalid original Q24 tensor")
        need(sha({"case_id":feature["case_id"],"source_digest":identity,
                  "feature_q24":q})==feature["feature_sha256"],"invalid feature digest")
        q_by_id[identity]=q
    need(type(panel) is dict and panel.get("schema")=="hepta.cell-meta-router-panel.v1" and
         type(panel.get("source")) is dict and panel["source"].get("kind")=="external_unverified" and
         panel["source"].get("rule")=="external" and panel["source"].get("dim")==64 and
         panel["source"].get("router_feature_index")==0 and
         panel["source"].get("seed")==seed, "actual Router input contract changed")
    expected_manifest={"model_id":table["model_id"],"model_revision":table["model_revision"],
                       "snapshot_files_sha256":table["snapshot_files_sha256"],
                       "pooling":"cls_l2_q24","projection":"contiguous-six-q24-mean64-v1"}
    need(panel["source"].get("stem_sha256")==sha(expected_manifest), "stem manifest drift")
    partitions=panel.get("partitions")
    need(type(partitions) is dict and set(partitions)=={t[0] for t in INDEX},"partition inventory")
    for part, split, left, right in INDEX:
        cases=[c for c in source_cases if c["split"]==split][left:right]
        entries=partitions[part]
        need(type(entries) is list and len(entries)==len(cases),"partition count drift")
        for i,(origin,row) in enumerate(zip(cases,entries,strict=True)):
            q=q_by_id[origin["source_digest"]]
            expected=[sum(q[6*j:6*j+6])/(6*Q24) for j in range(64)]
            need(type(row) is dict and set(row)=={"id","source_group","step","features","label"}
                 and row["id"]==origin["case_id"] and
                 row["source_group"]==origin["source_digest"] and
                 row["step"]==list(zip(*INDEX))[0].index(part)*10000+i and
                 type(row["label"]) is int and row["label"]==origin["label"],
                 "source/label/cohort or artificial order drift")
            vals=row["features"]
            need(type(vals) is list and len(vals)==64 and
                 all(type(v) in (int,float) and math.isfinite(v) and
                     abs(v-expected[j])<1e-12 for j,v in enumerate(vals)),
                 "projection must replay from original 384 Q24 coordinates")
    need(type(receipt) is dict and receipt.get("schema")=="hepta.cell-meta-granite-retrospective-bind.v1" and
         receipt.get("source_panel_sha256")==ORIGINAL_SHA and
         receipt.get("real_encoder_feature_table_sha256")==sha(table) and
         receipt.get("meta_trial_panel_sha256")==sha(panel) and
         receipt.get("panel_seed")==seed and
         receipt.get("artificial_step_order_not_observation_time") is True and
         receipt.get("future_1_2_are_retrospective_test_slices") is True and
         receipt.get("ood_is_calibration_samesource_placeholder") is True and
         receipt.get("future_window_prospective") is False and
         receipt.get("real_ood_verified") is False and
         receipt.get("independent_model_origin_verified") is False and
         receipt.get("independent_scientific_outcomes_verified") is False and
         receipt.get("production_admission")=="BLOCKED" and
         receipt.get("authority_posture")=="DENY_ALL",
         "unsound scientific or authority claim")
    return {"outcome":"PINNED_SOURCE_AND_Q24_PROJECTION_REPLAY_ONLY",
            "sources":224,"seed":seed,"original_panel_sha256":ORIGINAL_SHA,
            "converted_panel_sha256":sha(panel),
            "original_model_inference_independently_attested":False,
            "prospective_future_or_ood_verified":False,
            "production_selection_authorized":False,"authority_posture":"DENY_ALL"}

def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-panel",type=Path,required=True)
    p.add_argument("--features",type=Path,required=True)
    p.add_argument("--panel",type=Path,required=True)
    p.add_argument("--receipt",type=Path,required=True)
    p.add_argument("--seed",type=int,required=True)
    opts=p.parse_args(argv)
    try:
        print(json.dumps(independent_replay(read(opts.source_panel),read(opts.features),
                                            read(opts.panel),read(opts.receipt),seed=opts.seed),
                         sort_keys=True))
        return 0
    except (Denied,KeyError,IndexError,OSError,ValueError,TypeError,RecursionError) as exc:
        print("AUDIT BLOCKED:",exc,file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())

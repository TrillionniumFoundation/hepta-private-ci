"""P0.7 historical source-bound pretrained feature-necessity experiment.

Two DIFFERENT encoders, publishers and label spaces.  No new pretrained forward,
no future-window claim, no CellSplit/FinalUse authority.  The source adapter sees
original publisher-gold co-residency for AG News; the model producer only sees a
label-redacted view.  BANKING77 original held gold is a separate postseal ZIP.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import stat
from typing import Any
from zipfile import ZipFile

import numpy as np

from agnews_crossfamily import ARCHIVE_SHA256 as AG_ARCHIVE, read_original as read_ag
from fabric import Denied
from matched_router_p06 import staged_bundle as ag_staged
from original_replay import ARCHIVES as BANK_ARCHIVES
from science_gate import exact_mcnemar

SCHEMA = "hepta.cell-fabric.p07.dual-encoder-feature-necessity.v1"
TEMPERATURES = (0.125, 0.25, 0.5, 1., 2., 4., 8., 16.)
SCALE = 4.
MAX_FILE = 6_000_000
ROUTE_SHIFTS = 11
EXPECTED_BANK_MEMBER = {
    "hdcf-original-features.zip": {
        "features.json": "d6837a075fd894a2617d8d71f3e6a9a5570ce329958413eb0170149ce2d6f860",
        "feature-receipt.json": "e0697ff64ad4e145fa6db5b3b5be4abd1d9c382e5988f97c12f3cc813bd56566",
    },
    "hdcf-original-public.zip": {
        "public.json": "3322f27832a9fd029b691690ea6c456bf2b969da12f9d650d4184f021c92e01a",
    },
    "hdcf-original-targets.zip": {
        "targets.json": "e1f5590a888522d2401c7103fdd8ab85c523133a4dc61a4449dd980c3acd8882",
    },
    "hdcf-original-head-trial.zip": {
        "trial.json": "6d1105462a4bcee79da3b84fbd123cd53bbdc8e9465af2fa0e5be5f35cf10f09",
    },
}


def deny(condition: bool, reason: str) -> None:
    if not condition:
        raise Denied(reason)


def pairs(items):
    obj = {}
    for k, v in items:
        deny(k not in obj, "duplicate JSON key")
        obj[k] = v
    return obj


def reject_constant(s):
    raise Denied("nonfinite JSON scalar")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_regular(path: Path, limit: int = MAX_FILE) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as reader:
        deny(stat.S_ISREG(os.fstat(reader.fileno()).st_mode), "not a regular source")
        raw = reader.read(limit + 1)
    deny(len(raw) <= limit, "oversized source")
    return raw


def strict_json(raw: bytes) -> Any:
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def read_json(path: Path) -> dict:
    result = strict_json(open_regular(path))
    deny(type(result) is dict, "expected JSON object")
    return result


def commit(path: Path, value: dict) -> str:
    deny(not path.exists() and not path.is_symlink() and not path.parent.is_symlink(),
         "create-only output")
    raw = canonical(value) + b"\n"
    deny(len(raw) <= MAX_FILE, "oversized output")
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                        getattr(os, "O_NOFOLLOW", 0))
    try:
        deny(stat.S_ISDIR(os.fstat(directory).st_mode) and
             stat.S_IMODE(os.fstat(directory).st_mode) & 0o077 == 0, "nonprivate directory")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as writer:
            writer.write(raw)
            writer.flush()
            os.fsync(writer.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)
    return sha(raw)


def bank_member(path: Path, kind: str) -> dict[str, object]:
    """Exact independently verified bytes; stage never reads held labels."""
    deny(path.name == kind and kind in BANK_ARCHIVES, "unregistered archive")
    raw = open_regular(path, 2_000_000)
    deny(sha(raw) == BANK_ARCHIVES[kind][0], "original BANKING77 ZIP SHA mismatch")
    expected = EXPECTED_BANK_MEMBER[kind]
    with ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        deny(len(names) == len(set(names)) and set(names) == set(expected), "original ZIP member drift")
        out = {}
        for name, digest in expected.items():
            item = z.getinfo(name)
            deny(not item.is_dir() and 0 < item.file_size <= 2_000_000, "invalid original member")
            data = z.read(name)
            deny(len(data) == item.file_size and sha(data) == digest, "member source SHA mismatch")
            out[name] = strict_json(data)
        return out


def normalise(vector: Any, dim: int) -> list[float]:
    deny(type(vector) in (list, tuple) and len(vector) == dim,
         "invalid pretrained feature dimensions")
    deny(all(type(x) in (float, int) and math.isfinite(x) for x in vector), "nonfinite feature")
    arr = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    deny(1e-6 < norm < 1e6, "invalid pretrained feature norm")
    return (arr * (SCALE / norm)).tolist()


def stage_bank(bank_dir: Path) -> dict:
    features_pack = bank_member(bank_dir / "hdcf-original-features.zip", "hdcf-original-features.zip")
    public_pack = bank_member(bank_dir / "hdcf-original-public.zip", "hdcf-original-public.zip")
    features, public = features_pack["features.json"], public_pack["public.json"]
    receipt = features_pack["feature-receipt.json"]
    deny(features["dimension"] == 768 and len(features["fit"]) == 64 and
         len(features["held"]) == 32 and receipt["observed_encoder_forward_calls"] == 96 and
         receipt["model_snapshot_sha256"] == features["producer"]["encoder_sha256"] and
         receipt["held_labels_loaded_in_encoder_producer"] is False and
         public["production_authorized"] is False,
         "BANKING77 original feature lineage mismatch")
    ids = set()
    train, held = [], []
    for split, frows, prows, target in (
        ("train", features["fit"], public["fit"], train),
        ("heldout", features["held"], public["heldout"], held),
    ):
        deny(len(frows) == len(prows), "source row census")
        for f, p in zip(frows, prows, strict=True):
            i = f["id"]
            deny(type(i) is str and i not in ids and i == p["id"] and
                 f["type"] in ("hash0", "hash1") and
                 f["family"].startswith("BANKING77-") and
                 ("label" not in p if split == "heldout" else type(p.get("label")) is int),
                 "BANKING77 source/label/case lineage mismatch")
            ids.add(i)
            row = {"id": i, "cell": features["types"].index(f["type"]),
                   "x": normalise(f["vector"], 768)}
            if split == "train":
                deny(f["target"] == p["label"] % 2, "train label mismatch")
                row["target"] = f["target"]
            target.append(row)
    return {"classes": 2, "dimension": 768,
            "source_sha256": BANK_ARCHIVES["hdcf-original-features.zip"][0],
            "model_sha256": receipt["model_snapshot_sha256"],
            "train": train, "heldout": held}


def stage_agnews(path: Path) -> dict:
    packet = ag_staged(path)  # Existing exact SHA/member/source+model check.
    return {"classes": 4, "dimension": 384,
            "source_sha256": AG_ARCHIVE,
            "model_sha256": packet["feature_sha256"],
            "train": [{"id":r["id"],"cell":r["cell"],"x":r["features"],
                       "target":r["target"]} for r in packet["train"]],
            "heldout": [{"id":r["id"],"cell":r["cell"],"x":r["features"]}
                        for r in packet["holdout"]]}


def stage(agnews_zip: Path, bank_dir: Path) -> dict:
    return {"schema": SCHEMA,
            "tasks": {"agnews_mmbert_384": stage_agnews(agnews_zip),
                      "banking77_modernbert_768": stage_bank(bank_dir)},
            "provenance": {"historical_labels_previously_exposed": True,
                           "new_pretrained_forwards": 0,
                           "same_encoder_for_both_tasks": False,
                           "publisher_issuer_verified": False,
                           "production_authority": "DENY_ALL"}}


def verify(bundle: dict) -> None:
    deny(type(bundle) is dict and set(bundle) == {"schema", "tasks", "provenance"} and
         bundle["schema"] == SCHEMA, "unsupported source bundle")
    deny(bundle["provenance"] == {"historical_labels_previously_exposed": True,
         "new_pretrained_forwards": 0, "same_encoder_for_both_tasks": False,
         "publisher_issuer_verified": False, "production_authority": "DENY_ALL"},
         "unqualified material")
    expected = {"agnews_mmbert_384": (4,384,64,32,AG_ARCHIVE),
                "banking77_modernbert_768": (2,768,64,32,
                    BANK_ARCHIVES["hdcf-original-features.zip"][0])}
    deny(type(bundle["tasks"]) is dict and set(bundle["tasks"]) == set(expected),
         "two unrelated sources required")
    for name, (classes, dim, fit_size, held_size, src_sha) in expected.items():
        task = bundle["tasks"][name]
        deny(type(task) is dict and set(task)=={"classes","dimension","source_sha256",
                "model_sha256","train","heldout"} and task["classes"]==classes and
             task["dimension"]==dim and task["source_sha256"]==src_sha and
             type(task["model_sha256"]) is str and len(task["model_sha256"])==64,
             "task identity/encoder drift")
        seen = set()
        for split, size in (("train",fit_size),("heldout",held_size)):
            seq = task[split]
            deny(type(seq) is list and len(seq)==size, "source row count")
            for r in seq:
                needed={"id","cell","x","target"} if split=="train" else {"id","cell","x"}
                deny(type(r) is dict and set(r)==needed and type(r["id"]) is str and
                     1<=len(r["id"])<=128 and r["id"] not in seen and
                     type(r["cell"]) is int and r["cell"] in (0,1) and
                     type(r["x"]) is list and len(r["x"])==dim and
                     all(type(v) in (int,float) and math.isfinite(v) for v in r["x"]),
                     "source ID, shape or hidden held label")
                seen.add(r["id"])
                norm=math.sqrt(math.fsum(v*v for v in r["x"]))
                deny(abs(norm-SCALE)<1e-6, "feature L2 normalization drift")
                if split=="train":
                    deny(type(r["target"]) is int and 0<=r["target"]<classes,
                         "invalid train target")
        counts=Counter(r["target"] for r in task["train"])
        deny(set(counts)==set(range(classes)) and min(counts.values())>=2,
             "insufficient train support for LOO")


def softmax(z: np.ndarray) -> np.ndarray:
    zz=z-np.max(z,axis=-1,keepdims=True)
    ex=np.exp(zz)
    return ex/np.sum(ex,axis=-1,keepdims=True)


def prototype_train(train: list, classes: int, temperatures=TEMPERATURES) -> tuple[np.ndarray,dict]:
    x=np.asarray([r["x"] for r in train],dtype=np.float64)
    y=np.asarray([r["target"] for r in train],dtype=np.int64)
    centers=np.stack([np.mean(x[y==j],axis=0) for j in range(classes)])
    # Only training labels are accessed. Every leave-one-out row pays an
    # explicit class-conditional fit; no held labels or features inform tuning.
    nll=[]
    for temp in temperatures:
        loss=0.
        for i in range(len(y)):
            candidates=np.stack([np.mean(x[(y==j)&(np.arange(len(y))!=i)],axis=0)
                                 for j in range(classes)])
            p=softmax(temp*(candidates@x[i]))
            loss-=math.log(max(1e-300,float(p[y[i]])))
        nll.append(loss/len(y))
    choice=min(range(len(temperatures)),key=lambda i:(nll[i],temperatures[i]))
    return centers,{"grid":list(temperatures),"train_only_loo_nll":nll,
                    "selected_temperature":temperatures[choice],
                    "paid_loo_evaluations":len(temperatures)*len(y),
                    "temperature_at_grid_boundary":choice in (0,len(temperatures)-1)}


def score_features(centers: np.ndarray, x: np.ndarray, temperature: float,
                   permutation: np.ndarray | None = None) -> np.ndarray:
    if permutation is None:
        return softmax(temperature*(x@centers.T))
    return softmax(temperature*(x[:,permutation]@centers.T))


def evaluate_unlabeled(task: dict) -> dict:
    classes,dim=task["classes"],task["dimension"]
    centers,cal=prototype_train(task["train"],classes)
    held=np.asarray([r["x"] for r in task["heldout"]],dtype=np.float64)
    ordinary=score_features(centers,held,cal["selected_temperature"])
    negatives=[score_features(centers,np.roll(held,k,axis=0),cal["selected_temperature"])
               for k in range(1,len(held))]
    cells=np.asarray([r["cell"] for r in task["heldout"]],dtype=np.int64)
    route_mismatches=[]
    for shift in range(1,ROUTE_SHIFTS+1):
        changed=held.copy()
        for route in (0,1):
            idx=np.flatnonzero(cells==route)
            deny(len(idx)>ROUTE_SHIFTS,"not enough held Cell cases for strict derangement")
            changed[idx]=np.roll(held[idx],shift,axis=0)
        route_mismatches.append(score_features(centers,changed,cal["selected_temperature"]))
    zero=score_features(centers,np.zeros_like(held),cal["selected_temperature"])
    # One deterministic coordinate-level lesion. Shared train+test permutation
    # preserves dot products and is a positive control against implementation bugs.
    dim_perm=np.arange(dim,dtype=int)
    import random
    random.Random(20261017+dim).shuffle(dim_perm)  # see test: explicit deterministic digest
    held_coordinate_shuffle=score_features(centers,held[:,dim_perm],cal["selected_temperature"])
    both_coordinate_shuffle=score_features(centers[:,dim_perm],held[:,dim_perm],cal["selected_temperature"])
    deny(float(np.max(np.abs(both_coordinate_shuffle-ordinary)))<5e-13,
         "identity-preserving shared coordinate permutation changed probabilities")
    priors=Counter(r["target"] for r in task["train"])
    global_prior=np.array([(priors[i]+1)/(len(task["train"])+classes) for i in range(classes)],dtype=np.float64)
    return {"classes":classes,"dimension":dim,"train":len(task["train"]),
            "held":len(task["heldout"]),"temperature_selection":cal,
            "centroid_sha256":sha(b"hepta.p07.centroid.fp64.v1\x00"+centers.tobytes()),
            "held_order_digest":sha(b"hepta.p07.held.case-order.v1\x00"+canonical([r["id"] for r in task["heldout"]])),
            "normal":ordinary.tolist(),"zero":zero.tolist(),
            "all_cyclic_mismatches":[r.tolist() for r in negatives],
            "route_preserving_mismatches":[r.tolist() for r in route_mismatches],
            "held_only_coordinate_mismatch":held_coordinate_shuffle.tolist(),
            "common_coordinate_permutation":both_coordinate_shuffle.tolist(),
            "global_train_only_prior":global_prior.tolist(),
            "physical_new_encoder_forwards":0,
            "source_family_windows":1,
            "authority":"DENY_ALL","disposition":"HOLD_NO_GO"}


def produce(bundle: dict) -> dict:
    verify(bundle)
    return {"schema":SCHEMA,"source_digest":sha(canonical(bundle)),
            "original_archive_digests":{k:v["source_sha256"] for k,v in bundle["tasks"].items()},
            "runs":{k:evaluate_unlabeled(v) for k,v in bundle["tasks"].items()},
            "training_label_visibility":"TRAIN_ONLY",
            "held_labels_in_producer":False,"historical_gold_previously_exposed":True,
            "independent_original_issuer_verified":False,
            "global_optimization_or_cell_split_proved":False,
            "authority":"DENY_ALL","disposition":"HOLD_NO_GO"}


def seal_read(prelabel: Path, seal: Path) -> dict:
    st=read_json(seal)
    deny(st.get("schema")==SCHEMA and st.get("authority")=="DENY_ALL" and
         st.get("held_labels_opened") is False,"invalid prelabel seal")
    raw=open_regular(prelabel)
    deny(sha(raw)==st.get("prelabel_sha256"),"modified sealed predictions")
    obj=strict_json(raw)
    deny(type(obj) is dict and obj.get("source_digest")==st.get("source_digest") and
         obj.get("disposition")=="HOLD_NO_GO" and obj.get("held_labels_in_producer") is False,
         "invalid source-bound producer material")
    return obj


def audit_vector(centers: np.ndarray,x: np.ndarray,t: float,p: np.ndarray) -> None:
    """Independent numerical kernel: scalar fsum instead of producer matmul."""
    deny(np.all(np.isfinite(p)),"nonfinite candidate")
    for row,observed in zip(x,p,strict=True):
        logits=[math.fsum(float(a)*float(b) for a,b in zip(c,row,strict=True))*t for c in centers]
        m=max(logits)
        ex=[math.exp(z-m) for z in logits];s=math.fsum(ex)
        expected=[z/s for z in ex]
        deny(max(abs(float(a)-b) for a,b in zip(observed,expected,strict=True))<=2e-12,
             "independent model math disagreement")


def text_overlap_audit(train_text: list[str], held_text: list[str]) -> dict:
    """Late-review descriptive source-text leakage audit (no text exported)."""
    deny(len(train_text)==64 and len(held_text)==32 and
         all(type(t) is str and 1<=len(t)<=4096 for t in train_text+held_text),
         "untrusted original source text cohort")
    norm=lambda t: " ".join(t.casefold().split())
    train_norm={norm(t) for t in train_text}
    held_norm=[norm(t) for t in held_text]
    tokens=lambda t:set(re.findall(r"\w+",t.casefold()))
    train_tokens=[tokens(t) for t in train_text]
    scores=[]
    for item in held_text:
        h=tokens(item)
        scores.append(max(len(h & tr)/max(1,len(h | tr)) for tr in train_tokens))
    return {"exact_cross_split_normalized_text_duplicates":sum(t in train_norm for t in held_norm),
            "train_to_held_max_token_jaccard_median":float(np.median(scores)),
            "train_to_held_max_token_jaccard_max":float(max(scores)),
            "held_with_train_text_jaccard_at_least_0_80":int(sum(v>=.8 for v in scores)),
            "text_or_case_ids_exported":False}


def ncorrect(probs: np.ndarray, truth: np.ndarray) -> int:
    return int(np.sum(np.argmax(probs,axis=1)==truth))


def brier(probs: np.ndarray, truth: np.ndarray) -> float:
    return float(np.mean(np.sum((probs-np.eye(probs.shape[1])[truth])**2,axis=1)))


def review(agnews_zip: Path,bank_dir: Path,source_path: Path,prelabel: Path,seal: Path) -> dict:
    # Verify sealed proposal before opening original held gold.
    result=seal_read(prelabel,seal)
    bundle=read_json(source_path)
    verify(bundle)
    deny(sha(canonical(bundle))==result["source_digest"],"prelabel input changed")
    authentic=stage(agnews_zip,bank_dir)
    deny(canonical(authentic)==canonical(bundle),"historical original source drift")
    reference=produce(bundle)
    deny(canonical(reference)==canonical(result),"independently replayed source mismatch")
    # SOURCE LABEL ACCESS BELOW: both datasets have historical exposed gold.
    agraw=read_ag(agnews_zip)
    agrows=[strict_json(s) for s in agraw["dataset.jsonl"].splitlines()]
    aggold={r["case_id"]:r["label"] for r in agrows if r["split"]=="holdout"}
    target=bank_member(bank_dir/"hdcf-original-targets.zip","hdcf-original-targets.zip")["targets.json"]
    bankgold={r["id"]:r["target"] for r in target["targets"]}
    original_trial=bank_member(bank_dir/"hdcf-original-head-trial.zip","hdcf-original-head-trial.zip")["trial.json"]
    banking_public=bank_member(bank_dir/"hdcf-original-public.zip","hdcf-original-public.zip")["public.json"]
    text_observer={
        "agnews_mmbert_384":text_overlap_audit(
            [r["text"] for r in agrows if r["split"]=="train"],
            [r["text"] for r in agrows if r["split"]=="holdout"]),
        "banking77_modernbert_768":text_overlap_audit(
            [r["text"] for r in banking_public["fit"]],
            [r["text"] for r in banking_public["heldout"]]),
    }
    original_split={r["id"]:r["p1"] for r in original_trial["predictions"]["split"]}
    # Independent post-label score without exposing per-case outputs.
    outcomes={}
    for name,gold in (("agnews_mmbert_384",aggold),("banking77_modernbert_768",bankgold)):
        task=bundle["tasks"][name];output=result["runs"][name]
        ids=[r["id"] for r in task["heldout"]]
        deny(len(gold)==32 and set(ids)==set(gold),"wrong independent original held labels")
        y=np.asarray([gold[i] for i in ids],dtype=np.int64)
        good=np.asarray(output["normal"],dtype=np.float64)
        neg=[np.asarray(m,dtype=np.float64) for m in output["all_cyclic_mismatches"]]
        route_neg=[np.asarray(m,dtype=np.float64) for m in output["route_preserving_mismatches"]]
        deny(len(route_neg)==ROUTE_SHIFTS and all(v.shape==(32,task["classes"]) for v in route_neg),
             "incomplete route-preserving blinded lesions")
        deny(len(neg)==31 and good.shape==(32,task["classes"]) and
             all(k.shape==good.shape for k in neg),"incomplete source-ordered ablations")
        centers=np.stack([np.mean(np.asarray([r["x"] for r in task["train"] if r["target"]==c],dtype=np.float64),axis=0)
                          for c in range(task["classes"])])
        x=np.asarray([r["x"] for r in task["heldout"]],dtype=np.float64)
        temperature=output["temperature_selection"]["selected_temperature"]
        # Independently compute true and several shuffled views using fsum;
        # full 31-shift identity is separately compared with the original actor.
        audit_vector(centers,x,temperature,good)
        for shift, proposal in enumerate(neg, start=1):
            audit_vector(centers,np.roll(x,shift,axis=0),temperature,proposal)
        cells=np.asarray([r["cell"] for r in task["heldout"]],dtype=np.int64)
        for shift, proposal in enumerate(route_neg, start=1):
            changed=x.copy()
            for route in (0,1):
                ids_route=np.flatnonzero(cells==route)
                changed[ids_route]=np.roll(x[ids_route],shift,axis=0)
            audit_vector(centers,changed,temperature,proposal)
        mismatch_correct=[ncorrect(pred,y) for pred in neg]
        route_mismatch_correct=[ncorrect(pred,y) for pred in route_neg]
        ordinary_correct=ncorrect(good,y)
        bc=brier(good,y)
        normal_dec=np.argmax(good,axis=1)
        if name=="banking77_modernbert_768":
            historical=np.asarray([int(original_split[i]>=.5) for i in ids]);
            split_correct=int(np.sum(historical==y))
            only_centroid=int(np.sum((normal_dec==y)&(historical!=y)))
            only_split=int(np.sum((normal_dec!=y)&(historical==y)))
            registered_comparator={"name":"historical_split_not_matched_training_budget",
                "correct":split_correct,"only_centroid":only_centroid,
                "only_split":only_split,
                "nominal_paired_exact_p":exact_mcnemar(only_centroid,only_split)}
        else:
            # Use the original published rows as the comparator rather than
            # hardcoding a prior PR's 22/32 outcome. Still NOT equal budget.
            archival = strict_json(agraw["execution/predictions.json"])
            gated = {r["case_id"]:r["probabilities"] for r in archival["predictions"]
                     if r.get("arm")=="gated" and r.get("split")=="holdout"}
            deny(set(gated)==set(ids),"original gated reference identity mismatch")
            gp = np.asarray([gated[i] for i in ids],dtype=np.float64)
            deny(gp.shape==(32,4) and np.all(np.isfinite(gp)) and
                 np.max(np.abs(gp.sum(axis=1)-1))<1e-5,"untrusted original gated probabilities")
            gated_pred=np.argmax(gp,axis=1)
            wins=int(np.sum((normal_dec==y)&(gated_pred!=y)))
            losses=int(np.sum((normal_dec!=y)&(gated_pred==y)))
            registered_comparator={"name":"historical_original_gated_not_matched_training_budget",
                "correct":int(np.sum(gated_pred==y)),"only_centroid":wins,
                "only_gated":losses,"nominal_paired_exact_p":exact_mcnemar(wins,losses),
                "actual_original_rows_checked":32}
        outcomes[name]={"classes":task["classes"],"trained_on_original_pretrained_features":True,
            "new_encoder_forwards":0,"train":64,"held":32,
            "train_only_loo_temperature":temperature,
            "loo_grid_boundary":output["temperature_selection"]["temperature_at_grid_boundary"],
            "paid_train_loo_validations":output["temperature_selection"]["paid_loo_evaluations"],
            "original_aligned_correct":ordinary_correct,
            "original_multiclass_brier":bc,
            "held_feature_zero_correct":ncorrect(np.asarray(output["zero"]),y),
            "held_feature_coordinate_shuffle_correct":ncorrect(np.asarray(output["held_only_coordinate_mismatch"]),y),
            "shared_coordinate_permutation_max_abs_delta":float(np.max(abs(np.asarray(output["common_coordinate_permutation"])-good))),
            "cyclic_label_blind_mismatches":31,
            "cyclic_accuracy_min":int(min(mismatch_correct)),
            "cyclic_accuracy_median":float(np.median(mismatch_correct)),
            "cyclic_accuracy_max":int(max(mismatch_correct)),
            "cyclic_at_least_aligned":int(sum(v>=ordinary_correct for v in mismatch_correct)),
            "permutation_diagnostic_addone_fraction":(1+sum(v>=ordinary_correct for v in mismatch_correct))/32,
            "within_cell_route_mismatches":ROUTE_SHIFTS,
            "within_cell_correct_min":int(min(route_mismatch_correct)),
            "within_cell_correct_median":float(np.median(route_mismatch_correct)),
            "within_cell_correct_max":int(max(route_mismatch_correct)),
            "within_cell_at_least_aligned":int(sum(v>=ordinary_correct for v in route_mismatch_correct)),
            "within_cell_addone_fraction":(1+sum(v>=ordinary_correct for v in route_mismatch_correct))/(ROUTE_SHIFTS+1),
            "historical_comparator":registered_comparator,
            "source_text_overlap_audit":text_observer[name],
            "cross_data_comparison_prohibited":True}
    return {"schema":SCHEMA,"source_digest":result["source_digest"],
            "sealing_sha256":sha(open_regular(prelabel)),
            "tasks":outcomes,
            "distinct_encoders_and_label_spaces":True,
            "original_publisher_gold_historically_exposed":True,
            "external_model_weight_material_not_reloaded":True,
            "new_pretrained_encoder_forwards":0,
            "actual_task_reasoning_or_multimodal_ability_verified":False,
            "independent_publisher_original_issuer_verified":False,
            "cross_source_family_future_generalization_verified":False,
            "cell_split_learning_promotable":False,
            "native_execution_authorized":False,
            "authority":"DENY_ALL","disposition":"HOLD_NO_GO"}


def cli() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="mode",required=True)
    a=sub.add_parser("source");a.add_argument("--agnews",type=Path,required=True)
    a.add_argument("--bank",type=Path,required=True);a.add_argument("--out",type=Path,required=True)
    b=sub.add_parser("producer");b.add_argument("--source",type=Path,required=True)
    b.add_argument("--prelabel",type=Path,required=True);b.add_argument("--seal",type=Path,required=True)
    c=sub.add_parser("review");c.add_argument("--agnews",type=Path,required=True)
    c.add_argument("--bank",type=Path,required=True);c.add_argument("--source",type=Path,required=True)
    c.add_argument("--prelabel",type=Path,required=True);c.add_argument("--seal",type=Path,required=True)
    c.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    if args.mode=="source":
        source=stage(args.agnews,args.bank);verify(source);commit(args.out,source)
    elif args.mode=="producer":
        source=read_json(args.source);report=produce(source)
        digest=commit(args.prelabel,report)
        commit(args.seal,{"schema":SCHEMA,"authority":"DENY_ALL", "held_labels_opened":False,
                           "source_digest":report["source_digest"],"prelabel_sha256":digest})
    else:
        r=review(args.agnews,args.bank,args.source,args.prelabel,args.seal)
        digest=commit(args.out,r)
        print(json.dumps({"report_sha256":digest,"statuses":{k:v["original_aligned_correct"] for k,v in r["tasks"].items()},
                          "disposition":"HOLD_NO_GO"},sort_keys=True))


if __name__=="__main__":
    cli()

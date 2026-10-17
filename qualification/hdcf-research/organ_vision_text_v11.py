"""Original DINOv2 image -> Granite97 class-text Organ contrast (research only).

Immutable publisher/source and original pretrained feature archives are re-read.
No model is trained on TEST labels; independent reviewer may read withheld labels
only after immutable prediction sealing. All outcomes DENY_ALL and HOLD_NO_GO.

Uses NumPy for real CPU SGD, not simulated/predeclared favorable predictions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import stat
import time
from zipfile import ZipFile

import numpy as np

SOURCE_SHA = "49ee4b855879e8ad463fb3f0ffb21e30b332fb24d1626360aa8f382d16ef82ad"
FEATURE_SHA = "92536c949e16ee0722357ccb1d881f371707df3c26424cd93dd2bfc96e49511e"
TARGET_SHA = "946101fe7e57a151ce5ae9ec314fc6e01b7244aeac48f49034ee0a581e09c67d"
SOURCE_MANIFEST_SHA = "0233221fae3986612ed34c86b3da2e708b2423a77d19a74f1d0a73ed46e81490"
DATA_REV = "27aa014ce09b193e1a6f58112d4a66e0eddb69c5"
DINO_REV = "150c8e7bb7cef2d30ec31b13a517af14840ee3f7"
DINO_ENCODER = "66301a1057dffff05adbb24d8e635b74d1b01e4d3ebb477bee1f25fdd5e3d8a8"
DINO_WEIGHT_SHA = "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"
DINO_PREPROCESS_SHA = "14e780d86fa1861f8751f868d7f45425b5feb55c38ca26f152ca5097ab30f828"
GRANITE_ENCODER = "651431e0ce6e37a34a7f576d1164b277a87d39466c77418b9d0bf4d5a15c0257"
GRANITE_REV = "835ad14087e140460703cf0fae09f97d469d65c2"
CLASSES = ("angular_leaf_spot", "bean_rust", "healthy")
WIDTH = 384
RANK = 8
ORGAN_STEPS = 160
HEAD_STEPS = 256
SEED = 217
SOURCE_RUN = 38680856403
SCHEMA = "hepta.hdcf.real-vision-text-organ-v11"

class Reject(ValueError):
    pass

def check(cond: bool, why: str):
    if not cond:
        raise Reject(why)

def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def canonical(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")

def dig(o) -> str:
    return sha(b"hepta.hdcf.real-organ.v11\0" + canonical(o))

def pairs(items):
    o = {}
    for k, v in items:
        check(k not in o, "duplicate JSON key")
        o[k] = v
    return o

def parse(b: bytes):
    check(len(b) < 8_000_000, "oversized JSON")
    try:
        return json.loads(b, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(Reject("nonfinite JSON")))
    except (UnicodeError, ValueError, TypeError) as e:
        raise Reject("invalid JSON") from e

def lines(b: bytes):
    check(b.endswith(b"\n") and b.count(b"\n") <= 100, "noncanonical source rows")
    return [parse(s) for s in b.splitlines()]

class OriginalZip:
    def __init__(self, path, expected):
        p = Path(path)
        check(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size < 16_000_000, "invalid original ZIP path")
        with p.open("rb") as f:
            check(hashlib.file_digest(f, "sha256").hexdigest() == expected, "original outer ZIP digest")
        self.z = ZipFile(p)
        names = self.z.infolist()
        check(0 < len(names) <= 100 and sum(i.file_size for i in names) < 32_000_000,
              "unbounded archive")
        actual = [i.filename for i in names]
        check(len(set(actual)) == len(actual), "duplicate archive member")
        for i in names:
            n = i.filename
            check(n and not n.startswith("/") and "\\" not in n and
                  all(p not in ("", ".", "..") for p in n.split("/")) and
                  ((i.external_attr >> 16) & 0o170000) != 0o120000 and
                  not i.is_dir() and i.file_size <= 8_000_000, "unsafe archive member")
    def read(self, name):
        check(name in self.z.namelist(), "original member missing")
        return self.z.read(name)
    def close(self):
        self.z.close()

def _as_features(rows, images, phase):
    check(len(rows) == len(images), "original count mismatch")
    mat = []
    for expected, row in zip(images, rows, strict=True):
        check(row["case_id"] == expected["case_id"] and row["group_id"] == expected["group_id"] and
              row["image_sha256"] == expected["image_sha256"] and row["scope"] == expected["scope"] and
              row["split"] == phase and row["source"]["encoder_sha256"] == DINO_ENCODER and
              row["source"]["input_sha256"] == expected["image_sha256"] and
              row["source"]["modality"] == "image" and not any(k in row for k in ("target", "label")),
              "DINO feature/source binding")
        v = row["source"]["values"]
        check(type(v) is list and len(v) == WIDTH and
              all(type(x) in (float, int) and math.isfinite(x) and abs(x) <= 8 for x in v),
              "invalid frozen feature")
        mat.append(v)
    arr = np.array(mat, dtype=np.float64)
    check(np.all(np.isfinite(arr)), "nonfinite original features")
    return arr

def load_original(source_zip, feature_zip):
    src = OriginalZip(source_zip, SOURCE_SHA)
    feat = OriginalZip(feature_zip, FEATURE_SHA)
    try:
        raw_manifest = src.read("source-manifest.json")
        check(sha(raw_manifest) == SOURCE_MANIFEST_SHA, "source manifest SHA")
        manifest = parse(raw_manifest)
        check(manifest["dataset_revision"] == DATA_REV and manifest["train_cases"] == 36 and
              manifest["test_cases"] == 24 and manifest["natural_images"] is True and
              manifest["authority"] == "DENY_ALL", "original source manifest")
        train = lines(src.read("source/train_images.jsonl"))
        test = lines(src.read("source/future_images.jsonl"))
        class_rows = lines(src.read("source/train_class.jsonl"))
        check(len(train) == len(class_rows) == 36 and len(test) == 24, "source census")
        label_by_case = {r["case_id"]: r["class_label"] for r in class_rows}
        check(len(label_by_case) == 36 and set(label_by_case) == {r["case_id"] for r in train} and
              set(label_by_case.values()) == set(CLASSES), "train-only labels")
        ids, assets, groups = set(), set(), set()
        for phase, rows in (("train", train), ("future", test)):
            for row in rows:
                check(row["split"] == phase and row["condition"] == "vision_required" and
                      row["case_id"] not in ids and row["image_sha256"] not in assets and
                      row["group_id"] not in groups and
                      sha(src.read("source/images/" + row["image_path"])) == row["image_sha256"],
                      "image identity/cross-split collision")
                ids.add(row["case_id"]); assets.add(row["image_sha256"]); groups.add(row["group_id"])
        frec_train = parse(feat.read("vision_train/receipt.json"))
        frec_test = parse(feat.read("vision_future/receipt.json"))
        for receipt, phase, n, path in ((frec_train, "train", 36, "vision_train/features.jsonl"),
                                        (frec_test, "future", 24, "vision_future/features.jsonl")):
            raw = feat.read(path)
            check(receipt["phase"] == phase and receipt["actual_model_forwards"] == n and
                  receipt["encoder_repo"] == "facebook/dinov2-small" and
                  receipt["encoder_revision"] == DINO_REV and receipt["feature_width"] == WIDTH and
                  receipt["output_sha256"] == sha(raw) and receipt["labels_seen"] is False and
                  receipt["checkpoint_locally_byte_verified"] is True and
                  receipt["snapshot_file_sha256s"]["model.safetensors"] == DINO_WEIGHT_SHA and
                  receipt["snapshot_file_sha256s"]["preprocessor_config.json"] == DINO_PREPROCESS_SHA and
                  receipt["production_accepted"] is False, "original genuine DINO receipt")
        xtrain = _as_features(lines(feat.read("vision_train/features.jsonl")), train, "train")
        xtest = _as_features(lines(feat.read("vision_future/features.jsonl")), test, "future")
        texts = lines(feat.read("granite_train/encoded.jsonl"))
        receipt = parse(feat.read("granite_train/receipt.json"))
        check(receipt["encoded_sha256"] == sha(feat.read("granite_train/encoded.jsonl")) and
              receipt["examples"] == 36 and receipt["physical_forwards"] > 0 and
              receipt["model_revision"] == GRANITE_REV and
              receipt["feature_encoder_identity"] == GRANITE_ENCODER and
              receipt["model_checkpoint_locally_verified"] is True and
              receipt["production_accepted"] is False,
              "actual pretrained Granite feature receipt")
        prototypes = {}
        text_hashes = {}
        for row, txt in zip(train, texts, strict=True):
            k = label_by_case[row["case_id"]]
            check(txt["case_id"] == row["case_id"] and txt["group_id"] == row["group_id"] and
                  txt["source"]["encoder_sha256"] == DINO_ENCODER and
                  txt["source"]["input_sha256"] == row["image_sha256"] and
                  txt["target"]["encoder_sha256"] == GRANITE_ENCODER and
                  txt["target"]["modality"] == "text", "paired original image/text mismatch")
            p = np.array(txt["target"]["values"], dtype=np.float64)
            check(p.shape == (WIDTH,) and np.isfinite(p).all(), "bad real Granite vector")
            digest = txt["target"]["input_sha256"]
            if k in prototypes:
                check(text_hashes[k] == digest and np.array_equal(prototypes[k], p),
                      "same class has different pretrained prototype")
            else:
                prototypes[k], text_hashes[k] = p, digest
        check(set(prototypes) == set(CLASSES) and len(set(text_hashes.values())) == 3,
              "text prototype census")
        p = np.stack([prototypes[k] for k in CLASSES])
        p /= np.maximum(np.linalg.norm(p, axis=1, keepdims=True), 1e-12)
        y = np.array([CLASSES.index(label_by_case[row["case_id"]]) for row in train], dtype=np.int64)
        return {"train": train, "held": test, "xtrain": xtrain, "xtest": xtest,
                "ytrain": y, "teacher": p, "source_sha256": SOURCE_MANIFEST_SHA,
                "teacher_text_digests": {k: text_hashes[k] for k in CLASSES}}
    finally:
        src.close();feat.close()

def norm(x):
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)

def softmax(z):
    u = z - z.max(axis=-1, keepdims=True)
    e = np.exp(u)
    return e / e.sum(axis=-1, keepdims=True)

def _loss_and_grad(x, labels, p, A, B, scale=16.0):
    u = x @ A
    pre = x + u @ B
    z = norm(pre)
    logits = scale * z @ p.T
    probs = softmax(logits)
    grad_logits = probs.copy()
    grad_logits[np.arange(len(labels)), labels] -= 1
    grad_logits /= len(labels)
    deriv = scale * grad_logits @ p
    denom = np.maximum(np.linalg.norm(pre, axis=1, keepdims=True), 1e-12)
    deriv = (deriv - z * (deriv * z).sum(axis=1, keepdims=True)) / denom
    dB = u.T @ deriv
    dA = x.T @ (deriv @ B.T)
    loss = -np.log(np.maximum(probs[np.arange(len(labels)), labels], 1e-15)).mean()
    return float(loss), dA, dB

def train_organ(xtrain, y, prototypes, *, seed=SEED):
    rng = np.random.default_rng(seed)
    A = rng.normal(0, .015, (WIDTH, RANK))
    B = np.zeros((RANK, WIDTH), dtype=np.float64)
    start_cpu = time.process_time_ns();start_wall = time.perf_counter_ns()
    losses = []
    for step in range(ORGAN_STEPS):
        loss, dA, dB = _loss_and_grad(xtrain, y, prototypes, A, B)
        gnorm = math.sqrt(float((dA*dA).sum() + (dB*dB).sum()))
        clip = min(1.0, 2.0 / max(gnorm, 1e-12))
        A -= .15 * clip * dA
        B -= .15 * clip * dB
        if step in (0, ORGAN_STEPS - 1):
            losses.append(loss)
        check(np.isfinite(A).all() and np.isfinite(B).all(), "nonfinite organ update")
    check(not np.array_equal(B, np.zeros_like(B)), "organ did not learn")
    return (A,B), {"steps": ORGAN_STEPS, "train_losses": losses,
                   "parameters": int(A.size+B.size),
                   "cpu_ns": time.process_time_ns()-start_cpu,
                   "wall_ns": time.perf_counter_ns()-start_wall,
                   "weights_sha256": sha(A.astype('<f8').tobytes()+B.astype('<f8').tobytes())}

def transform(x, weights):
    a,b=weights
    return norm(x + (x @ a) @ b)

def _type(case_id):
    h=hashlib.sha256(("hepta.hdcf.beans-image-type.v9\0"+case_id).encode()).digest()
    return int(h[0] & 1)

def train_heads(x, y, cases, *, mode, seed=SEED, steps=HEAD_STEPS):
    check(mode in ("shared_one_touch","split"), "invalid head mode")
    rng=np.random.default_rng(seed)
    w = rng.normal(0, .0015, (2, WIDTH+1, 3))
    x_aug = np.concatenate((x, np.ones((len(x),1))),axis=1)
    order=list(range(len(x)))
    scheduler=random.Random(seed+1)
    indices=[]
    while len(indices)<steps:
        scheduler.shuffle(order);indices.extend(order)
    started=time.process_time_ns()
    for step,j in enumerate(indices[:steps]):
        t=_type(cases[j]["case_id"])
        effective=(w[0]+w[1])*.5 if mode=="shared_one_touch" else w[t]
        logits=x_aug[j] @ effective
        prob=softmax(logits.reshape(1,3))[0]
        prob[y[j]]-=1
        k=step%2 if mode=="shared_one_touch" else t
        # Exactly one (WIDTH+1)*3 head touched per step, as in HDCF matched control.
        w[k]-=.08*np.outer(x_aug[j],prob)
    return w, {"steps":steps,"parameter_touches":steps*(WIDTH+1)*3,
               "parameters_total":int(w.size),"cpu_ns":time.process_time_ns()-started,
               "weights_sha256":sha(w.astype('<f8').tobytes())}

def head_prob(x, cases, weights, mode):
    xaug=np.concatenate((x,np.ones((len(x),1))),axis=1)
    out=[]
    for i,row in enumerate(cases):
        k=_type(row["case_id"])
        if mode=="shared_one_touch":w=(weights[0]+weights[1])*.5
        elif mode=="split":w=weights[k]
        elif mode=="swapped":w=weights[1-k]
        else:raise Reject("unknown head route")
        out.append(softmax((xaug[i]@w).reshape(1,3))[0].tolist())
    return out

def run_fit(source, features):
    original=load_original(source,features)
    x=original["xtrain"];xt=original["xtest"];y=original["ytrain"]
    proto=original["teacher"]
    # Geometry-preserving fixed orthogonal coordinate permutation, no new text semantics.
    rng=np.random.default_rng(SEED)
    perm=rng.permutation(WIDTH)
    signs=rng.choice(np.array([-1.0,1.0]),WIDTH)
    null_proto=proto[:,perm]*signs
    real, real_work=train_organ(x,y,proto)
    null, null_work=train_organ(x,y,null_proto)
    zx=transform(x,real);zt=transform(xt,real)
    znull=transform(x,null);tnull=transform(xt,null)
    # All heads have same total dimensions and same SGD step/order schedules.
    arms={}
    head_work={}
    for label, train_x, eval_x in (("raw",x,xt), ("organ",zx,zt), ("null_organ",znull,tnull)):
        for mode in (("shared_one_touch","split") if label=="organ" else ("shared_one_touch",)):
            w,work=train_heads(train_x,y,original["train"],mode=mode)
            key=label+"_"+mode
            arms[key]=head_prob(eval_x,original["held"],w,mode)
            head_work[key]=work
            if key=="organ_split":
                arms["organ_swapped"]=head_prob(eval_x,original["held"],w,"swapped")
                head_work["organ_swapped"]={"steps":0,"parameter_touches":0,"reuses":"organ_split"}
    arms["frozen_text_cosine"]=softmax(16.0*norm(xt)@proto.T).tolist()
    arms["trained_text_organ_cosine"]=softmax(16.0*zt@proto.T).tolist()
    arms["trained_null_organ_cosine"]=softmax(16.0*tnull@null_proto.T).tolist()
    # No pretrained model inference now: archive is verified, frozen original features reused.
    manifest={"schema":SCHEMA,"experiment":"original_dino_granite_organs_3way",
      "source_artifact_sha256":SOURCE_SHA,"feature_artifact_sha256":FEATURE_SHA,
      "source_manifest_sha256":SOURCE_MANIFEST_SHA,"original_source_run_id":SOURCE_RUN,
      "dinov2_revision":DINO_REV,"granite_revision":GRANITE_REV,
      "train_count":len(x),"held_count":len(xt),"train_class_counts":dict(Counter(CLASSES[i] for i in y)),
      "teacher_text_digests":original["teacher_text_digests"],
      "architecture":{"width":WIDTH,"organ_rank":RANK,"organ_updates":ORGAN_STEPS,
                      "head_updates":HEAD_STEPS,"head_per_arm_parameters":2*(WIDTH+1)*3},
      "organ_work":{"text":real_work,"orthogonal_null":null_work},
      "head_work":head_work,"original_model_new_forwards":0,"label_source":"original_train_only",
      "blind_labels_in_fit":False,"future_time_outcome":False,
      "production_authorized":False,"model_selected":False,
      "issuer_independent":False,"host_cpu_cost_attested":False,"total_lifecycle_cost_attested":False}
    check(len(arms)==8 and all(len(v)==24 for v in arms.values()),"arm census")
    predictions=[{"id":r["case_id"],"family":r["group_id"],
                  "event_sha256":r["source_sha256"],
                  "probabilities":{k:arms[k][i] for k in sorted(arms)}}
                 for i,r in enumerate(original["held"])]
    seal={"schema":SCHEMA+".sealed", "manifest":manifest,
          "predictions":predictions,"authority":"DENY_ALL"}
    seal["seal_sha256"]=dig(seal)
    return seal

def _late_labels(source, targets):
    src=OriginalZip(source,SOURCE_SHA);tg=OriginalZip(targets,TARGET_SHA)
    try:
        rows=lines(src.read("source/future_images.jsonl"))
        plan=parse(tg.read("target-manifest.json"))
        check(plan["production_accepted"] is False and plan["source_manifest_sha256"]==SOURCE_MANIFEST_SHA and
              plan["original_test_parquet_sha256"]=="534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27",
              "original held plan is not compatible")
        targets=lines(tg.read("future_class_targets.jsonl"))
        check(len(rows)==len(targets)==24,"held original labels count")
        out={}
        for row,t in zip(rows,targets,strict=True):
            check(row["case_id"]==t["case_id"] and row["source_sha256"]==t["source_sha256"] and
                  row["image_sha256"]==t["source_input_sha256"] and
                  t["class_label"] in CLASSES and row["group_id"]==t["group_id"],
                  "held label/source provenance mismatch")
            out[row["case_id"]]=(CLASSES.index(t["class_label"]),row["group_id"],row["source_sha256"])
        return out
    finally:
        src.close();tg.close()

def score_postseal(seal, source, features, targets):
    check(type(seal) is dict and seal.get("schema")==SCHEMA+".sealed" and
          seal.get("authority")=="DENY_ALL" and seal.get("manifest",{}).get("blind_labels_in_fit") is False,
          "sealed research prediction required")
    check(type(seal.get("seal_sha256")) is str and
          dig({k:v for k,v in seal.items() if k!="seal_sha256"})==seal["seal_sha256"],
          "sealed probabilities altered")
    m=seal["manifest"]
    check(m["source_artifact_sha256"]==SOURCE_SHA and m["feature_artifact_sha256"]==FEATURE_SHA and
          m["original_model_new_forwards"]==0 and m["production_authorized"] is False and
          m["train_count"]==36 and m["held_count"]==24 and
          m["model_selected"] is False and m["future_time_outcome"] is False and
          m["issuer_independent"] is False and m["total_lifecycle_cost_attested"] is False and
          m["dinov2_revision"]==DINO_REV and m["granite_revision"]==GRANITE_REV and
          m["architecture"]=={"width":WIDTH,"organ_rank":RANK,"organ_updates":ORGAN_STEPS,
                               "head_updates":HEAD_STEPS,"head_per_arm_parameters":2*(WIDTH+1)*3} and
          all(m["organ_work"][arm]["steps"]==ORGAN_STEPS and
              m["organ_work"][arm]["parameters"]==2*WIDTH*RANK
              for arm in ("text","orthogonal_null")) and
          all(m["head_work"][arm]["steps"]==HEAD_STEPS and
              m["head_work"][arm]["parameter_touches"]==HEAD_STEPS*(WIDTH+1)*3
              for arm in ("organ_shared_one_touch","organ_split",
                          "raw_shared_one_touch","null_organ_shared_one_touch")),
          "original source/permission drift")
    gold=_late_labels(source,targets)
    preds=seal["predictions"]
    check(type(preds) is list and len(preds)==24,"prediction census")
    results={}
    arms=set(preds[0]["probabilities"])
    expect={"raw_shared_one_touch","organ_shared_one_touch","organ_split","organ_swapped",
            "null_organ_shared_one_touch","frozen_text_cosine","trained_text_organ_cosine",
            "trained_null_organ_cosine"}
    # Require the actual frozen original visual prototype separately in reviewer.
    check(arms==expect and len(gold)==len(preds),"model arm census mismatch")
    case_seen=set(); hits={a:{} for a in arms}
    for rec in preds:
        case=rec["id"]
        check(case in gold and case not in case_seen and
              rec["family"]==gold[case][1] and rec["event_sha256"]==gold[case][2],
              "case/source mismatch or duplicate")
        case_seen.add(case)
        check(set(rec["probabilities"])==arms,"unequal per-case arms")
        for a,values in rec["probabilities"].items():
            check(type(values) is list and len(values)==3 and all(type(p) in (float,int) and
                  math.isfinite(p) and 0<=p<=1 for p in values) and abs(sum(values)-1)<1e-8,
                  "invalid probabilities")
            hits[a][case]=(int(np.argmax(values))==gold[case][0])
    # Independent original, unchanged three-class pretrained DINO prototype.
    visual=OriginalZip(features,FEATURE_SHA)
    try:
        original_prototypes=parse(visual.read("sealed_class_predictions.json"))
        check(original_prototypes["schema"]=="hepta.e2.beans-natural-retrospective.v1.class-predictions" and
              original_prototypes["authority"]=="DENY_ALL" and
              original_prototypes["future_labels_seen"] is False and
              len(original_prototypes["rows"])==24,
              "frozen original visual prototype receipt")
        ref={}
        for row in original_prototypes["rows"]:
            case=row["case_id"]
            check(case in gold and case not in ref and
                  row["group_id"]==gold[case][1] and
                  row["predicted_labels"]["vision_prototype"] in CLASSES,
                  "historical original frozen prototype identity")
            ref[case]=(CLASSES.index(row["predicted_labels"]["vision_prototype"])==gold[case][0])
        check(len(ref)==24,"missing prototype predictions")
        hits["original_frozen_visual_prototype"]=ref
    finally:
        visual.close()
    results["original_frozen_visual_prototype"]={"correct":sum(hits["original_frozen_visual_prototype"].values()),"n":len(gold)}
    def cmp(a,b):
        ha,hb=hits[a],hits[b]
        wins=sum(ha[k] and not hb[k] for k in gold)
        losses=sum(hb[k] and not ha[k] for k in gold)
        d=wins+losses
        p=min(1.0,2*sum(math.comb(d,i) for i in range(min(wins,losses)+1))/(2**d))
        return {"candidate_only":wins,"control_only":losses,"same_correct":sum(ha[k] and hb[k] for k in gold),
                "both_wrong":sum(not ha[k] and not hb[k] for k in gold),
                "nominal_case_level_exact_p":p}
    for a in sorted(arms):
        results[a]={"correct":sum(hits[a].values()),"n":len(gold)}
    return {"schema":SCHEMA+".review", "sealed_sha256":seal["seal_sha256"],
            "original_fit":36,"original_held":24,"task":"3way_original_leaf_disease",
            "arm_scores":results,"paired":{
                "organ_split_vs_organ_shared":cmp("organ_split","organ_shared_one_touch"),
                "text_organ_shared_vs_null_organ_shared":cmp("organ_shared_one_touch","null_organ_shared_one_touch"),
                "text_organ_shared_vs_raw_shared":cmp("organ_shared_one_touch","raw_shared_one_touch"),
                "text_organ_cosine_vs_null_cosine":cmp("trained_text_organ_cosine","trained_null_organ_cosine"),
                "text_organ_shared_vs_frozen_visual_prototype":cmp("organ_shared_one_touch","original_frozen_visual_prototype"),
                "text_organ_cosine_vs_frozen_visual_prototype":cmp("trained_text_organ_cosine","original_frozen_visual_prototype")},
            "independent_future_outcomes":False,"independent_source_issuer":False,
            "physical_feature_source_replayed":True,"publisher_source_prior_v9_review_required":True,
            "general_multimodal_capability_verified":False,"organ_benefit_verified":False,
            "cell_split_benefit_verified":False,"complete_cost_verified":False,
            "production_authorized":False,"stem_selected":False,"disposition":"HOLD_NO_GO_DENY_ALL"}

def secure_read(path):
    p=Path(path)
    check(p.is_file() and not p.is_symlink() and p.stat().st_size<3_000_000,
          "missing/oversized input")
    return parse(p.read_bytes())

def secure_write(path,data):
    raw=canonical(data)+b"\n"
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(raw);f.flush();os.fsync(f.fileno())

def main(argv=None):
    ap=argparse.ArgumentParser()
    subs=ap.add_subparsers(dest="mode",required=True)
    fit=subs.add_parser("fit")
    for opt in ("source","features","out"):
        fit.add_argument("--"+opt,required=True)
    review=subs.add_parser("review")
    for opt in ("sealed","source","features","targets","out"):
        review.add_argument("--"+opt,required=True)
    a=ap.parse_args(argv)
    try:
        if a.mode=="fit":
            result=run_fit(a.source,a.features)
        else:
            result=score_postseal(secure_read(a.sealed),a.source,a.features,a.targets)
        secure_write(a.out,result)
    except (Reject, OSError, KeyError, IndexError, ZeroDivisionError) as e:
        ap.exit(2,f"DENY_ALL: {type(e).__name__}: {e}\n")
    return 0

if __name__=="__main__":
    raise SystemExit(main())

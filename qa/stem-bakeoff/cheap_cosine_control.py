#!/usr/bin/env python3
"""Independent post-hoc cheap cosine benchmark over P39 source-bound COCO evidence.

This is a diagnostic on the ALREADY-EXAMINED 256-row source-pairing test.
Train fits only two scalar logistic parameters; calibration picks temperature.
No new blind trial, Encoder call, semantic-quality claim or production authority.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import re
import resource
import time
import numpy as np

ARCHIVE_SHA = "2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e"
DATA_SHA = "4d7eec98a8546f8af64b0a5f2b4f192b30c6c43cb086f73f67bb0793a4509d63"
BANK_SHA = "e620c7ac8264979136cf39d992ddd575ab37c71baa6a729269af41bc42ca290d"
SPLITS = ("train", "dev", "calibration", "test")
TEMPS = (.25, .5, .75, 1., 1.5, 2., 3., 4., 8.)
HEX = re.compile(r"[0-9a-f]{64}\Z")
THRESHOLD = .7
REQUIRED = tuple(f"cohorts/{s}.jsonl" for s in SPLITS) + (
    "cohorts/manifest.json", "bank/manifest.json", "bank/features.npz",
    "results/text_image-gated-test/rows.json", "results/report.json")

def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()

def sha(x):
    return hashlib.sha256(x).hexdigest()

def source_file(path, record):
    path = Path(path)
    size, expected = record["bytes"], record["sha256"]
    if (path.is_symlink() or not path.is_file() or type(size) is not int
            or not 0 < size <= 24_000_000 or path.stat().st_size != size
            or not isinstance(expected, str) or not HEX.fullmatch(expected)):
        raise ValueError("source must be a size/hash-bound regular file")
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError("original P39 archive member mutated")
    return raw

def inspect_rows(splits):
    if set(splits) != set(SPLITS):
        raise ValueError("four source-isolated splits required")
    all_images, all_captions, all_rows, all_blocks = set(), set(), set(), set()
    audit = {}
    for split in SPLITS:
        rows, blocks, image_bytes, caption_bytes = splits[split], defaultdict(list), {}, {}
        if len(rows) % 4 or not 4 <= len(rows) <= 4096:
            raise ValueError("complete source pair blocks required")
        for row in rows:
            if (row.get("split") != split or any(type(row.get(k)) is not int for k in
                    ("image_id", "source_caption_image_id", "caption_id", "label"))
                    or row["label"] not in (0, 1)
                    or any(not isinstance(row.get(k), str) or not HEX.fullmatch(row[k]) for k in
                           ("row_id", "pair_block_id", "image_sha256", "text_sha256"))
                    or row["row_id"] != sha(canon({k:v for k,v in row.items() if k != "row_id"}))
                    or row["row_id"] in all_rows
                    or row["label"] != int(row["image_id"] == row["source_caption_image_id"])):
                raise ValueError("unbound, repeated or forged source-pair row")
            all_rows.add(row["row_id"])
            for mapping, key, val in ((image_bytes, row["image_id"], row["image_sha256"]),
                                      (caption_bytes, row["caption_id"],
                                       (row["source_caption_image_id"], row["text_sha256"]))):
                if key in mapping and mapping[key] != val:
                    raise ValueError("source ID conflicts with its immutable bytes")
                mapping[key] = val
            blocks[row["pair_block_id"]].append(row)
        for name, block in blocks.items():
            ids = {r["image_id"] for r in block}
            if (name in all_blocks or len(block) != 4 or len(ids) != 2
                    or ids != {r["source_caption_image_id"] for r in block}
                    or len({(r["image_id"],r["source_caption_image_id"]) for r in block}) != 4
                    or sum(r["label"] for r in block) != 2):
                raise ValueError("incomplete or reused original-photo source block")
            all_blocks.add(name)
        if all_images.intersection(image_bytes) or all_captions.intersection(caption_bytes):
            raise ValueError("original photo/caption endpoints leak across splits")
        all_images.update(image_bytes)
        all_captions.update(caption_bytes)
        audit[split] = {"rows":len(rows),"pair_blocks":len(blocks)}
    return audit

def load_frozen(root, external_manifest):
    root, external_manifest = Path(root), Path(external_manifest)
    if (root.is_symlink() or not root.is_dir() or external_manifest.is_symlink()
            or not external_manifest.is_file() or external_manifest.stat().st_size > 512000
            or sha(external_manifest.read_bytes()) != ARCHIVE_SHA):
        raise ValueError("externally pinned P39 archive required")
    archive = json.loads(external_manifest.read_bytes())
    if (archive.get("schema") != "hepta.multimodal-evidence-archive.v1"
            or archive.get("authority") != "DENY_ALL"
            or archive.get("production_activation_allowed") is not False):
        raise ValueError("original source archive has wrong authority or schema")
    files = {k:source_file(root/k, archive["members"][k]) for k in REQUIRED}
    if sha(files["cohorts/manifest.json"]) != DATA_SHA or sha(files["bank/manifest.json"]) != BANK_SHA:
        raise ValueError("original source cohort or bank external pin differs")
    data, bank = (json.loads(files[k]) for k in ("cohorts/manifest.json", "bank/manifest.json"))
    if (data.get("schema") != "hepta.real-coco-pair-cohorts.v1"
            or data.get("authority") != "DENY_ALL"
            or bank.get("schema") != "hepta.multimodal-feature-bank.v1"
            or bank.get("authority") != "DENY_ALL"
            or bank.get("features_sha256") != sha(files["bank/features.npz"])
            or bank.get("plan",{}).get("dataset_manifest_sha256") != DATA_SHA):
        raise ValueError("original bank provenance is inconsistent")
    rows = {name:[json.loads(line) for line in files[f"cohorts/{name}.jsonl"].splitlines()]
            for name in SPLITS}
    audit = inspect_rows(rows)
    with np.load(BytesIO(files["bank/features.npz"]),allow_pickle=False) as parts:
        if set(parts.files) != {"text","image"}:
            raise ValueError("original feature inventory is not text/image")
        text, image = parts["text"].copy(), parts["image"].copy()
    ids = bank["image_ids"]
    if (type(ids) is not list or len(ids) != 384 or len(set(ids)) != 384
            or not all(type(i) is int for i in ids)
            or text.shape != (384,768) or image.shape != text.shape
            or text.dtype != np.float32 or image.dtype != np.float32
            or not np.isfinite(text).all() or not np.isfinite(image).all()):
        raise ValueError("wrong original feature bank tensor shape, type or IDs")
    digest = hashlib.sha256()
    for name,values in (("text",text),("image",image)):
        digest.update(canon([name,str(values.dtype),list(values.shape)]))
        digest.update(values.tobytes(order="C"))
    if digest.hexdigest() != bank["feature_tensor_sha256"]:
        raise ValueError("frozen feature tensors do not match their source manifest")
    primary = json.loads(files["results/text_image-gated-test/rows.json"])
    report = json.loads(files["results/report.json"])
    if (len(primary) != 256 or report.get("authority") != "DENY_ALL"
            or report.get("production_activation_allowed") is not False):
        raise ValueError("original trained-Head test evidence incomplete")
    return audit, rows, ids, text, image, primary

def cosine(rows,ids,text,image):
    table={v:i for i,v in enumerate(ids)}
    try:
        x=text[[table[r["source_caption_image_id"]] for r in rows]].astype(np.float64)
        y=image[[table[r["image_id"]] for r in rows]].astype(np.float64)
    except KeyError as exc:
        raise ValueError("unbound caption or image endpoint") from exc
    lengths=np.linalg.norm(x,axis=1)*np.linalg.norm(y,axis=1)
    if not np.isfinite(lengths).all() or (lengths<=1e-12).any():
        raise ValueError("invalid vector norms")
    result=np.sum(x*y,axis=1)/lengths
    if not np.isfinite(result).all() or np.max(np.abs(result))>1.000001:
        raise ValueError("invalid original cosine")
    return np.clip(result,-1.,1.)

def sigmoid(z):
    return np.exp(-np.logaddexp(0.,-z))

def nll(z,labels):
    return float(np.mean(np.logaddexp(0.,z)-labels*z))

@dataclass(frozen=True)
class Calibrator:
    center:float
    scale:float
    weight:float
    bias:float
    regularization:float=.0001
    def logits(self,scores):
        return self.weight*((scores-self.center)/self.scale)+self.bias

def fit_train_only(scores,labels):
    scores,labels=np.asarray(scores,dtype=float),np.asarray(labels,dtype=float)
    if (scores.ndim!=1 or scores.shape!=labels.shape or len(scores)<4
            or not np.isfinite(scores).all() or np.max(abs(scores))>1.000001
            or not np.isin(labels,(0,1)).all() or len(np.unique(labels))!=2):
        raise ValueError("train-only fitting requires finite two-class rows")
    mu=float(scores.mean())
    scale=max(float(scores.std()),1e-6)
    x=(scores-mu)/scale
    w,b,lam=0.,0.,.0001
    for _ in range(64):
        z=w*x+b
        p=sigmoid(z)
        v=p*(1-p)
        g=np.array([np.mean((p-labels)*x)+lam*w,np.mean(p-labels)])
        h=np.array([[np.mean(v*x*x)+lam,np.mean(v*x)],
                    [np.mean(v*x),np.mean(v)+1e-9]])
        step=np.linalg.solve(h,g)
        before=nll(z,labels)+lam*w*w/2
        alpha=1.
        for _ in range(24):
            nw,nb=w-alpha*step[0],b-alpha*step[1]
            if nll(nw*x+nb,labels)+lam*nw*nw/2<=before+1e-12:
                break
            alpha/=2
        else:
            raise ValueError("no finite bounded train update")
        w,b=float(nw),float(nb)
        if max(abs(alpha*step[0]),abs(alpha*step[1]))<1e-10: break
    if not math.isfinite(w) or not math.isfinite(b):
        raise ValueError("nonfinite calibrator")
    return Calibrator(mu,scale,w,b)

def evaluate(logits,rows,t):
    y=np.array([r["label"] for r in rows],dtype=np.int64)
    p=sigmoid(logits/t)
    pred=(p>=.5).astype(np.int64)
    accepted=np.maximum(p,1-p)>=THRESHOLD
    correct=pred==y
    tp=np.sum((pred==1)&(y==1))
    tn=np.sum((pred==0)&(y==0))
    pos=np.sum(y==1)
    neg=np.sum(y==0)
    return {"rows":len(y),"accuracy":float(np.mean(correct)),
            "balanced_accuracy":float((tp/pos+tn/neg)/2),
            "positive_recall":float(tp/pos),"nll":nll(logits/t,y),
            "confidence_threshold":THRESHOLD,"coverage":float(np.mean(accepted)),
            "accepted":int(np.sum(accepted)),"accepted_errors":int(np.sum(accepted&~correct)),
            "selective_risk":float(np.mean(~correct[accepted])) if accepted.any() else None}

def paired_delta(rows,head,cheap):
    blocks=defaultdict(list)
    for i,row in enumerate(rows):blocks[row["pair_block_id"]].append(i)
    if len(blocks)<2 or any(len(v)!=4 for v in blocks.values()):
        raise ValueError("complete independent paired groups required")
    gains=np.array([np.mean(np.asarray(head)[i])-np.mean(np.asarray(cheap)[i])
                    for i in blocks.values()])
    rng=np.random.default_rng(20261023)
    resamples=rng.integers(0,len(gains),size=(2000,len(gains)))
    values=gains[resamples].mean(axis=1)
    return {"learned_minus_cheap_accuracy":float(gains.mean()),
            "lower_one_sided_95":float(np.quantile(values,.05)),
            "upper_one_sided_95":float(np.quantile(values,.95)),
            "pair_blocks":len(gains),"new_independent_trial":False}

def run(*,restored,archive_manifest,output):
    root,target=Path(restored),Path(output)
    if (target.exists() or not target.parent.is_dir() or target.parent.is_symlink()
            or any(p.is_symlink() for p in (root,root/"cohorts",root/"bank",root/"results"))):
        raise ValueError("a new separate output directory and real source parents required")
    code_sha=sha(Path(__file__).read_bytes())
    t0=time.perf_counter()
    audit,rows,ids,text,image,primary=load_frozen(root,archive_manifest)
    scores={s:cosine(rows[s],ids,text,image) for s in SPLITS}
    labels={s:np.array([r["label"] for r in rows[s]],dtype=int) for s in SPLITS}
    plan={"schema":"hepta.cheap-cosine-control-plan.v1",
          "original_archive_sha256":ARCHIVE_SHA,"data_sha256":DATA_SHA,
          "feature_bank_sha256":BANK_SHA,"code_sha256":code_sha,
          "trainable_scalar_parameters":2,"temperature_candidates":list(TEMPS),
          "selection":"train labels only; temperature uses calibration only",
          "threshold":THRESHOLD,"new_blind_trial":False,
          "authority":"DENY_ALL","production_activation_allowed":False}
    target.mkdir(mode=0o700)
    (target/"plan.json").write_bytes(canon(plan)+b"\n")
    trained=fit_train_only(scores["train"],labels["train"])
    cal_logits=trained.logits(scores["calibration"])
    temp=min(TEMPS,key=lambda t:(nll(cal_logits/t,labels["calibration"]),abs(math.log(t)),t))
    scored={s:evaluate(trained.logits(scores[s]),rows[s],temp) for s in SPLITS}
    test_logits=trained.logits(scores["test"])
    probabilities=sigmoid(test_logits/temp)
    cheap_pred=(probabilities>=.5).astype(int)
    original={r["source_id"]:r for r in primary}
    if len(original)!=len(rows["test"]):
        raise ValueError("duplicate original Head test rows")
    head_correct,details=[],[]
    for i,r in enumerate(rows["test"]):
        witness=original.get(r["row_id"])
        if (witness is None or witness["label"]!=r["label"]
                or witness["pair_block_id"]!=r["pair_block_id"]
                or witness["arm"]!="text_image" or witness["intervention"]!="paired"
                or type(witness["prediction"]) is not int):
            raise ValueError("historical prediction is not tied to this original row")
        accurate=witness["prediction"]==r["label"]
        head_correct.append(accurate)
        details.append({"row_id":r["row_id"],"image_id":r["image_id"],
                        "caption_id":r["caption_id"],"pair_block_id":r["pair_block_id"],
                        "label":r["label"],"image_sha256":r["image_sha256"],
                        "caption_sha256":r["text_sha256"],
                        "frozen_cosine":float(scores["test"][i]),
                        "cheap_probability_positive":float(probabilities[i]),
                        "cheap_prediction":int(cheap_pred[i]),
                        "cheap_accepted":bool(max(probabilities[i],1-probabilities[i])>=THRESHOLD),
                        "learned_prediction":witness["prediction"],"learned_correct":bool(accurate)})
    paired=paired_delta(rows["test"],head_correct,cheap_pred==labels["test"])
    if sha(Path(__file__).read_bytes())!=code_sha:raise ValueError("code changed during assessment")
    report={"schema":"hepta.cheap-cosine-control-result.v1","plan_sha256":sha(canon(plan)),
            "cohorts":audit,"calibration_temperature":temp,
            "train_only_parameters":asdict(trained),"split_metrics":scored,
            "original_trained_head_correct":int(sum(head_correct)),
            "paired_learned_head_vs_cheap_cosine":paired,
            "cpu_wall_ms":(time.perf_counter()-t0)*1000,
            "process_lifetime_peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            "measurement_scope":"headless replay of existing bank, not Encoder execution",
            "scope":"historical source-pair classification; post-hoc, descriptive",
            "new_blind_trial":False,"semantic_quality_qualified":False,
            "authority":"DENY_ALL","production_activation_allowed":False}
    (target/"report.json").write_bytes(canon(report)+b"\n")
    (target/"test-rows.json").write_bytes(canon(details)+b"\n")
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("restored","archive-manifest","output"):p.add_argument("--"+arg,required=True)
    a=p.parse_args()
    result=run(restored=a.restored,archive_manifest=a.archive_manifest,output=a.output)
    print(json.dumps({"test":result["split_metrics"]["test"],
                      "paired":result["paired_learned_head_vs_cheap_cosine"],
                      "new_blind_trial":False,"production_activation_allowed":False},sort_keys=True))

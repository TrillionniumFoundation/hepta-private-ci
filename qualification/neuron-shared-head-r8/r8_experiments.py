#!/usr/bin/env python3
"""Shadow-only Neuron shared-encoder / per-cell head experiments (no promotion authority).

All model features are provided by callers. The optional synthetic fixture is not a
Laya or ModernBERT run, and the scale microbench uses a synthetic numeric encoder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCHEMA = "hepta.neuron.head-experiments.v1"
DIMS = (2_048, 16_384, 65_536, 262_144)
KINDS = ("linear", "film", "lowrank8", "lowrank16", "mlp", "swiglu")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def softmax(x: np.ndarray) -> np.ndarray:
    a = x - np.max(x, axis=1, keepdims=True)
    z = np.exp(a)
    return z / z.sum(axis=1, keepdims=True)


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def load_features(path: Path, *, labelled: bool) -> dict:
    with np.load(path, allow_pickle=False) as data:
        fields = set(data.files)
        required = {"x", "id", "group", "time", "cell", "encoder_digest", "scope_digest"}
        if labelled:
            required.add("y")
        if not required.issubset(fields) or (not labelled and "y" in fields):
            raise ValueError(f"invalid feature file: missing or forbidden fields {required ^ fields}")
        payload = {key: data[key].copy() for key in fields}
    if fields - (required | {"teacher"}):
        raise ValueError("unknown/unexpected feature fields")
    x = payload["x"]
    if x.ndim != 2 or x.shape[1] > 512 or x.shape[1] == 0 or x.shape[0] == 0:
        raise ValueError("invalid bounded feature shape")
    if x.dtype != np.float32 or not np.isfinite(x).all():
        raise ValueError("features must be finite float32")
    for key in ("id", "group", "time", "cell"):
        if payload[key].shape != (len(x),):
            raise ValueError(f"invalid {key} shape")
    for key in ("encoder_digest", "scope_digest"):
        if payload[key].shape != () or not str(payload[key].item()):
            raise ValueError(f"missing binding: {key}")
    ids = [str(s) for s in payload["id"]]
    if len(set(ids)) != len(ids) or not all(ids):
        raise ValueError("duplicate or blank event id")
    if labelled and (payload["y"].shape != (len(x),) or payload["y"].dtype.kind not in "iu"):
        raise ValueError("class labels must be integer 1D")
    if not labelled and "teacher" in fields:
        raise ValueError("unlabelled inference cannot include teacher predictions")
    if "teacher" in fields:
        p = payload["teacher"]
        if p.ndim != 2 or len(p) != len(x) or not np.isfinite(p).all() or not np.allclose(p.sum(axis=1), 1, atol=1e-4) or np.any(p < 0):
            raise ValueError("invalid teacher probabilities")
    return payload


def same_binding(left: dict, right: dict) -> None:
    for key in ("encoder_digest", "scope_digest"):
        if left[key].item() != right[key].item():
            raise ValueError(f"incompatible {key}")
    if left["x"].shape[1] != right["x"].shape[1]:
        raise ValueError("feature dimension mismatch")


def check_train_valid(train: dict, valid: dict) -> None:
    same_binding(train, valid)
    for k in ("id", "group"):
        if set(map(str, train[k])) & set(map(str, valid[k])):
            raise ValueError(f"train/validation {k} leakage")
    if max(train["time"]) >= min(valid["time"]):
        raise ValueError("future validation must follow training")


@dataclass
class Head:
    kind: str
    dim: int
    classes: int
    budget: int
    seed: int = 7

    def __post_init__(self):
        if self.kind not in KINDS or self.dim <= 0 or self.classes < 2 or self.budget < 16:
            raise ValueError("unsupported head configuration")
        rng = np.random.default_rng(self.seed)
        self.p: dict[str, np.ndarray] = {}
        self.frozen: dict[str, np.ndarray] = {}
        d, c, b = self.dim, self.classes, self.budget

        def init(name: str, shape: tuple[int, ...], identity=False):
            self.p[name] = (np.ones(shape, dtype=np.float32) if identity else ((rng.standard_normal(shape) * (0.05 / np.sqrt(d))).astype(np.float32)))

        if self.kind in ("linear", "film"):
            init("w", (d, c)); init("b", (c,))
            if self.kind == "film":
                init("gamma", (d,), True); self.p["beta"] = np.zeros(d, dtype=np.float32)
        elif self.kind.startswith("lowrank"):
            rank = int(self.kind.removeprefix("lowrank"))
            self.frozen["w0"] = (rng.standard_normal((d, c)) * (0.05 / np.sqrt(d))).astype(np.float32)
            init("a", (d, rank)); init("b", (rank, c)); self.p["bias"] = np.zeros(c, dtype=np.float32)
        elif self.kind == "mlp":
            h = (b - c) // (d + c + 1)
            h = max(1, min(h, 2_048))
            init("w1", (d, h)); self.p["b1"] = np.zeros(h, dtype=np.float32)
            init("w2", (h, c)); self.p["b2"] = np.zeros(c, dtype=np.float32)
        else:
            h = max(1, min((b-c)//(2*d+c+3), 2_048))
            for name in ("v", "g"):
                init("w" + name, (d, h)); self.p["b" + name] = np.zeros(h, dtype=np.float32)
            init("wo", (h, c)); self.p["bo"] = np.zeros(c, dtype=np.float32)
        if self.nparams > self.budget:
            raise ValueError(f"{self.kind} needs {self.nparams:,} trainable parameters, > cap {self.budget:,}")

    @property
    def nparams(self) -> int:
        return sum(a.size for a in self.p.values())

    def forward(self, x: np.ndarray):
        p = self.p
        if self.kind == "linear":
            return x @ p["w"] + p["b"], (x,)
        if self.kind == "film":
            h = x * p["gamma"] + p["beta"]
            return h @ p["w"] + p["b"], (x, h)
        if self.kind.startswith("lowrank"):
            h = x @ p["a"]
            return x @ self.frozen["w0"] + h @ p["b"] + p["bias"], (x, h)
        if self.kind == "mlp":
            h = np.tanh(x @ p["w1"] + p["b1"])
            return h @ p["w2"] + p["b2"], (x, h)
        v = x @ p["wv"] + p["bv"]
        g = x @ p["wg"] + p["bg"]
        s = sigmoid(g)
        t = g*s
        h = v*t
        return h @ p["wo"] + p["bo"], (x, v, g, s, t, h)

    def backward(self, cache, dz: np.ndarray) -> dict:
        p = self.p
        if self.kind == "linear":
            (x,) = cache
            return {"w":x.T @ dz, "b":dz.sum(axis=0)}
        if self.kind == "film":
            x, h = cache
            dx = dz @ p["w"].T
            return {"w":h.T @ dz, "b":dz.sum(axis=0), "gamma":(dx*x).sum(axis=0), "beta":dx.sum(axis=0)}
        if self.kind.startswith("lowrank"):
            x, h = cache
            return {"a":x.T @ (dz @ p["b"].T), "b":h.T @ dz, "bias":dz.sum(axis=0)}
        if self.kind == "mlp":
            x, h = cache
            dh = (dz @ p["w2"].T)*(1-h*h)
            return {"w1":x.T @ dh, "b1":dh.sum(axis=0), "w2":h.T @ dz, "b2":dz.sum(axis=0)}
        x, v, g, s, t, h = cache
        dh = dz @ p["wo"].T
        dv = dh*t
        dg = dh*v*(s + g*s*(1-s))
        return {"wv":x.T @ dv, "bv":dv.sum(axis=0), "wg":x.T @ dg, "bg":dg.sum(axis=0), "wo":h.T @ dz, "bo":dz.sum(axis=0)}

    def probs(self, x: np.ndarray) -> np.ndarray:
        return softmax(self.forward(x)[0])


def train_head(head: Head, train: dict, valid: dict, *, steps: int, seed: int, alpha: float = 0) -> dict:
    if steps < 1 or steps > 100_000 or not 0 <= alpha <= 1:
        raise ValueError("invalid training budget")
    check_train_valid(train, valid)
    if len(set(map(str,train["cell"])))!=1 or set(map(str,train["cell"]))!=set(map(str,valid["cell"])):
        raise ValueError("single-Cell Head trainer cannot pool data across cells")
    classes = head.classes
    if np.any(train["y"] < 0) or np.any(train["y"] >= classes) or np.any(valid["y"] < 0) or np.any(valid["y"] >= classes):
        raise ValueError("label outside class space")
    if alpha and "teacher" not in train:
        raise ValueError("distillation requires independently measured teacher probabilities")
    if alpha and train["teacher"].shape[1] != classes:
        raise ValueError("teacher width mismatch")
    rng = np.random.default_rng(seed)
    m = {k:np.zeros_like(p) for k,p in head.p.items()}
    v = {k:np.zeros_like(p) for k,p in head.p.items()}
    history = []
    n = len(train["y"])
    start = time.perf_counter()
    for t in range(1, steps+1):
        ix = rng.integers(0, n, size=min(64, n))
        x, y = train["x"][ix], train["y"][ix]
        out, cache = head.forward(x)
        proba = softmax(out)
        target = np.eye(classes, dtype=np.float32)[y]
        if alpha:
            target = (1-alpha)*target+alpha*train["teacher"][ix]
        grad = (proba-target)/len(ix)
        grads = head.backward(cache, grad)
        norm = math.sqrt(sum(float(np.sum(g*g)) for g in grads.values()))
        factor = min(1.0, 1.0/max(norm, 1e-12))
        for k in head.p:
            g = grads[k]*factor
            m[k] = 0.9*m[k]+0.1*g
            v[k] = 0.999*v[k]+0.001*g*g
            mh = m[k]/(1-0.9**t)
            vh = v[k]/(1-0.999**t)
            head.p[k] -= 0.003*mh/(np.sqrt(vh)+1e-8)
        if t in (1,steps//4,steps//2,steps) or (t==steps):
            pred = head.probs(valid["x"])
            history.append({"step":t,"validation_brier":brier(pred,valid["y"]),"validation_accuracy":float((pred.argmax(1)==valid["y"]).mean())})
    return {"history":history,"steps":steps,"train_rows":n,"train_groups":sorted(set(map(str,train["group"]))),"valid_groups":sorted(set(map(str,valid["group"]))),"train_time_max":int(max(train["time"])),"valid_time_max":int(max(valid["time"])),"train_wall_seconds":time.perf_counter()-start,"optimizer_bytes":sum(int(a.nbytes) for a in list(m.values())+list(v.values())) }


def brier(proba: np.ndarray, labels: np.ndarray) -> float:
    nclass = proba.shape[1]
    return float(np.square(proba - np.eye(nclass)[labels]).sum(axis=1).mean())


def ece(proba: np.ndarray, labels: np.ndarray, bins: int=10) -> float:
    confidences = proba.max(axis=1)
    correct = (proba.argmax(axis=1)==labels)
    result = 0.0
    for i in range(bins):
        mask = (confidences >= i/bins) & ((confidences < (i+1)/bins) if i<bins-1 else (confidences <=1))
        if mask.any():
            result += mask.mean()*abs(correct[mask].mean()-confidences[mask].mean())
    return float(result)


def auroc(id_scores: np.ndarray, ood_scores: np.ndarray) -> float:
    """Tie-aware OOD AUROC; larger scores mean more likely out-of-distribution."""
    if not len(id_scores) or not len(ood_scores):
        raise ValueError("OOD AUROC requires both ID and OOD samples")
    scores=np.concatenate((np.asarray(id_scores,dtype=np.float64),np.asarray(ood_scores,dtype=np.float64)))
    if not np.isfinite(scores).all():
        raise ValueError("non-finite OOD score")
    indices=np.argsort(scores,kind="mergesort")
    ranks=np.empty(len(scores),dtype=np.float64)
    begin=0
    while begin<len(scores):
        end=begin+1
        while end<len(scores) and scores[indices[end]]==scores[indices[begin]]:
            end+=1
        ranks[indices[begin:end]]=(begin+1+end)/2
        begin=end
    n0=len(id_scores);n1=len(ood_scores)
    return float((ranks[n0:].sum()-n1*(n1+1)/2)/(n0*n1))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def save_head(head: Head, train: dict, valid: dict, record: dict, out: Path) -> None:
    if out.suffix != '.npz':
        raise ValueError("model artifact must be .npz")
    meta = {"schema":SCHEMA,"kind":head.kind,"dim":head.dim,"classes":head.classes,"budget":head.budget,"seed":head.seed,"trainable_params":head.nparams,"encoder_digest":str(train["encoder_digest"].item()),"scope_digest":str(train["scope_digest"].item()),"train_file_sha256":record["train_file_sha256"],"valid_file_sha256":record["valid_file_sha256"],"train_groups":record["train_groups"],"valid_groups":record["valid_groups"],"valid_time_max":record["valid_time_max"],"steps":record["steps"],"shadow_only":True}
    out.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out,**{"p_"+k:v for k,v in head.p.items()},**{"f_"+k:v for k,v in head.frozen.items()},meta=np.array(json.dumps(meta,sort_keys=True)))


def load_head(path: Path) -> tuple[Head,dict]:
    with np.load(path,allow_pickle=False) as z:
        meta=json.loads(str(z["meta"].item()))
        if meta.get("schema")!=SCHEMA or meta.get("shadow_only") is not True:
            raise ValueError("invalid shadow model metadata")
        head=Head(meta["kind"],int(meta["dim"]),int(meta["classes"]),int(meta["budget"]),int(meta["seed"]))
        for prefix,target in (("p_",head.p),("f_",head.frozen)):
            for k in target:
                v=z[prefix+k].copy()
                if v.shape!=target[k].shape or v.dtype!=np.float32 or not np.isfinite(v).all():
                    raise ValueError("model tensor mismatch")
                target[k]=v
    return head,meta


def cmd_train(args):
    train=load_features(Path(args.train),labelled=True)
    valid=load_features(Path(args.valid),labelled=True)
    head=Head(args.kind,train["x"].shape[1],args.classes,args.budget,args.seed)
    metrics=train_head(head,train,valid,steps=args.steps,seed=args.seed,alpha=args.distill)
    metrics.update({"schema":SCHEMA,"experiment":"01_head_capacity","kind":head.kind,"budget_cap":args.budget,"actual_params":head.nparams,"train_file_sha256":sha(Path(args.train)),"valid_file_sha256":sha(Path(args.valid)),"model_file_sha256":None,"provenance":"external_feature_input","production_admitted":False})
    save_head(head,train,valid,metrics,Path(args.output))
    metrics["model_file_sha256"]=sha(Path(args.output))
    write_json(Path(args.report),metrics)


def cmd_predict(args):
    head,meta=load_head(Path(args.model))
    data=load_features(Path(args.input),labelled=False)
    if data["x"].shape[1]!=head.dim or str(data["encoder_digest"].item())!=meta["encoder_digest"] or str(data["scope_digest"].item())!=meta["scope_digest"]:
        raise ValueError("incompatible inference representation")
    if set(map(str,data["group"])) & (set(meta["train_groups"]) | set(meta["valid_groups"])):
        raise ValueError("inference group overlaps training or validation")
    if int(min(data["time"])) <= meta["valid_time_max"]:
        raise ValueError("inference future window must follow validation")
    preds=head.probs(data["x"])
    write_json(Path(args.output),{"schema":SCHEMA,"model_file_sha256":sha(Path(args.model)),"input_sha256":sha(Path(args.input)),"encoder_digest":meta["encoder_digest"],"scope_digest":meta["scope_digest"],"train_groups":meta["train_groups"],"valid_groups":meta["valid_groups"],"valid_time_max":meta["valid_time_max"],"rows":[{"id":str(data["id"][i]),"group":str(data["group"][i]),"time":int(data["time"][i]),"probabilities":[float(z) for z in preds[i]]} for i in range(len(preds))],"production_admitted":False})


def _load_predictions(path: Path):
    p=json.loads(path.read_text(encoding="utf-8"))
    if p.get("schema")!=SCHEMA or p.get("production_admitted") is not False:
        raise ValueError("untrusted prediction schema")
    if not p.get("model_file_sha256") and p.get("model_file_sha256")!="no-change":
        raise ValueError("missing model provenance")
    rows={}
    for row in p.get("rows",[]):
        k=row["id"]
        probs=np.array(row["probabilities"],dtype=np.float64)
        if k in rows or probs.ndim!=1 or len(probs)<2 or not np.isfinite(probs).all() or np.min(probs)<0 or not np.isclose(probs.sum(),1,atol=1e-5):
            raise ValueError("duplicate/non-normalized predictions")
        rows[k]=(row,probs)
    if not rows:
        raise ValueError("empty predictions")
    return p,rows


def _score(rows, labels):
    prob=np.stack([rows[k][1] for k in sorted(rows)])
    y=np.array([labels[k]["label"] for k in sorted(rows)],dtype=np.int64)
    if np.any(y<0) or np.any(y>=prob.shape[1]):
        raise ValueError("invalid evaluator class")
    return {"rows":len(y),"accuracy":float((prob.argmax(1)==y).mean()),"brier":brier(prob,y),"ece":ece(prob,y),"nll":float(-np.log(np.clip(prob[np.arange(len(y)),y],1e-12,1)).mean())}


def cmd_evaluate(args):
    # This command is intentionally separate from train/predict. It accepts an
    # independent outcome file, and never emits a promotion/selection receipt.
    candidate,cr=_load_predictions(Path(args.candidate))
    baseline,br=_load_predictions(Path(args.baseline))
    rows=json.loads(Path(args.outcomes).read_text(encoding="utf-8"))
    if rows.get("schema")!=SCHEMA or rows.get("window")!="future" or rows.get("source")!="independent_observation":
        raise ValueError("future outcomes must have independent-observation provenance")
    labels={}
    for item in rows.get("rows",[]):
        k=item["id"]
        if k in labels:
            raise ValueError("duplicate outcome id")
        labels[k]=item
    if set(cr)!=set(br) or set(cr)!=set(labels):
        raise ValueError("paired baseline, candidate and future outcomes required")
    for item in (candidate,baseline):
        if set(map(str,item.get("train_groups",[]))) & {str(v["group"]) for v in labels.values()}:
            raise ValueError("future outcome group overlaps training")
        if set(map(str,item.get("valid_groups",[]))) & {str(v["group"]) for v in labels.values()}:
            raise ValueError("future outcome group overlaps validation")
    for item in (candidate, baseline):
        if item.get("valid_time_max") is not None and min(int(v["time"]) for v in labels.values()) <= int(item["valid_time_max"]):
            raise ValueError("future outcome predates validation")
    for k in labels:
        if any(raw[k][0]["group"]!=labels[k]["group"] or int(raw[k][0]["time"])!=int(labels[k]["time"]) for raw in (cr,br)):
            raise ValueError("prediction/outcome identity mismatch")
    a=_score(cr,labels)
    b=_score(br,labels)
    ood={"candidate":"NOT_MEASURED","no_change":"NOT_MEASURED"}
    candidate_ood=getattr(args,"candidate_ood",None)
    baseline_ood=getattr(args,"baseline_ood",None)
    ood_outcomes=getattr(args,"ood_outcomes",None)
    if len([value for value in (candidate_ood,baseline_ood,ood_outcomes) if value]) not in (0,3):
        raise ValueError("candidate, no-change and independently observed OOD all required")
    if candidate_ood:
        ood_claim=json.loads(Path(ood_outcomes).read_text(encoding="utf-8"))
        if ood_claim.get("schema")!=SCHEMA or ood_claim.get("source")!="independent_observation" or ood_claim.get("window")!="ood":
            raise ValueError("OOD class requires an independent observation source")
        co,c_rows=_load_predictions(Path(candidate_ood))
        bo,b_rows=_load_predictions(Path(baseline_ood))
        claimed={str(item["id"]):item for item in ood_claim.get("rows",[])}
        if len(claimed)!=len(ood_claim.get("rows",[])) or set(c_rows)!=set(claimed):
            raise ValueError("OOD independent observation and predicted rows mismatch")
        if set(c_rows)!=set(b_rows):
            raise ValueError("OOD candidate and no-change event identities differ")
        if set(c_rows)&set(cr):
            raise ValueError("OOD/ID decision ids overlap")
        for k in c_rows:
            if c_rows[k][0]["group"]!=claimed[k]["group"] or int(c_rows[k][0]["time"])!=int(claimed[k]["time"]):
                raise ValueError("OOD independent observation identity drift")
            if c_rows[k][0]["group"]!=b_rows[k][0]["group"] or int(c_rows[k][0]["time"])!=int(b_rows[k][0]["time"]):
                raise ValueError("paired OOD group or time drift")
        for observed in (co,bo):
            if set(map(str,observed.get("train_groups",[]))) & {str(row[0]["group"]) for row in c_rows.values()}:
                raise ValueError("OOD leaked from training groups")
        ood={"candidate":auroc(np.array([v[1].max() for v in cr.values()])*-1,np.array([v[1].max() for v in c_rows.values()])*-1),
             "no_change":auroc(np.array([v[1].max() for v in br.values()])*-1,np.array([v[1].max() for v in b_rows.values()])*-1)}
    # NDU requires separately measured outcomes/counterfactual support and formal
    # existing evaluator/selector. Classification accuracy is not NDU.
    write_json(Path(args.output),{"schema":SCHEMA,"experiment":"future_window_independent_evaluator","candidate":a,"no_change":b,"delta_brier":a["brier"]-b["brier"],"delta_accuracy":a["accuracy"]-b["accuracy"],"future_outcomes_sha256":sha(Path(args.outcomes)),"candidate_predictions_sha256":sha(Path(args.candidate)),"baseline_predictions_sha256":sha(Path(args.baseline)),"ndu_gain":"NOT_MEASURED","ood_auroc":ood,"negative_transfer":"NOT_MEASURED","promotion":"BLOCKED","evidence_authenticated":False,"synthetic_outcome":bool(rows.get("SYNTHETIC",False)),"production_admitted":False})


def cmd_compare_representations(args):
    """Evaluate aligned, external, held-out predictions from the four declared arms.

    Generating authentic original Laya and ModernBERT predictions is the
    responsibility of separate version-pinned model backends. Do not replace
    those arms with a synthetic stand-in.
    """
    expected=("laya_original", "shared_laya_head", "organ_expert_bank", "modernbert_base_head")
    declarations={}
    for arm in args.arm:
        if "=" not in arm:
            raise ValueError("arm must be name=path")
        name,path=arm.split("=",1)
        if name not in expected or name in declarations:
            raise ValueError("invalid/duplicate representation arm")
        declarations[name]=Path(path)
    if set(declarations)!=set(expected):
        raise ValueError("all four real representation arms are mandatory")
    outcomes=json.loads(Path(args.outcomes).read_text(encoding="utf-8"))
    if outcomes.get("schema")!=SCHEMA or outcomes.get("window")!="future" or outcomes.get("source")!="independent_observation":
        raise ValueError("invalid independent future outcomes")
    if outcomes.get("SYNTHETIC"):
        raise ValueError("representation comparison cannot use synthetic outcomes")
    labels={str(r["id"]):r for r in outcomes.get("rows",[])}
    if len(labels)!=len(outcomes.get("rows",[])) or not labels:
        raise ValueError("empty/duplicate outcome IDs")
    scored={};all_ids=set(labels)
    for name,path in declarations.items():
        payload,prs=_load_predictions(path)
        if set(prs)!=all_ids:
            raise ValueError("representation arms must have exactly paired events")
        if payload.get("arm")!=name or not payload.get("model_file_sha256") or payload["model_file_sha256"]=="no-change":
            raise ValueError("missing typed model arm provenance")
        if name=="laya_original" and payload.get("backend")!="laya_original_model":
            raise ValueError("original Laya must be executed by an explicit model backend")
        for key,row in labels.items():
            if row["group"]!=prs[key][0]["group"] or int(row["time"])!=int(prs[key][0]["time"]):
                raise ValueError("representation arm identity drift")
        groups={str(x["group"]) for x in labels.values()}
        if groups & (set(map(str,payload.get("train_groups",[]))) | set(map(str,payload.get("valid_groups",[])))):
            raise ValueError("future group leakage")
        if payload.get("valid_time_max") is not None and min(int(x["time"]) for x in labels.values())<=int(payload["valid_time_max"]):
            raise ValueError("representation future time leakage")
        scored[name]={"metrics":_score(prs,labels),"artifact_sha256":sha(path),"model_file_sha256":payload["model_file_sha256"],"encoder_digest":payload.get("encoder_digest"),"backend":payload.get("backend","external")}
    original=scored["laya_original"]["metrics"]
    for name in expected[1:]:
        item=scored[name]["metrics"]
        scored[name]["delta_brier_vs_original_laya"]=item["brier"]-original["brier"]
        scored[name]["delta_accuracy_vs_original_laya"]=item["accuracy"]-original["accuracy"]
    write_json(Path(args.output),{"schema":SCHEMA,"experiment":"02_representation_external_model_predictions","arms":scored,"paired_future_outcomes_sha256":sha(Path(args.outcomes)),"authenticity":"EXTERNAL_CLAIMS_UNVERIFIED","missing_metrics":["OOD AUROC","negative transfer","NDU future-window benefit","model token compute","peak GPU memory"],"promotion":"BLOCKED","production_admitted":False})


def cmd_scale(args):
    if args.cells not in (64,256,1024,4096) or not 0 < args.active <= 1 or not 0 <= args.train_frequency <= 1:
        raise ValueError("invalid preregistered scale/active/update profile")
    if args.pattern not in ("same","partial","distinct") or args.requests<1 or args.requests>100_000:
        raise ValueError("invalid workload")
    if args.dim<1 or args.dim>512 or args.cache_entries<0 or args.max_head_bytes<1:
        raise ValueError("invalid bounded scale dimensions or memory")
    rng=np.random.default_rng(args.seed)
    # A bounded synthetic numeric projection, not Laya/ModernBERT inference.
    raw_dim=32
    probe=Head(args.kind,args.dim,2,args.budget,args.seed)
    expected_head_bytes=args.cells*sum(v.nbytes for v in probe.p.values())
    if expected_head_bytes>args.max_head_bytes:
        raise ValueError("head memory cap exceeded in allocation preflight")
    projection=rng.normal(0,0.05,(raw_dim,args.dim)).astype(np.float32)
    heads=[probe]+[Head(args.kind,args.dim,2,args.budget,args.seed+i) for i in range(1,args.cells)]
    resident_weights=sum(sum(v.nbytes for v in h.p.values()) for h in heads)
    assert resident_weights==expected_head_bytes
    cache={}
    from collections import deque
    order=deque()
    times=[]; hits=0; updates=0
    limit=min(128,args.cache_entries)
    raw_table = rng.standard_normal((args.requests if args.pattern=="distinct" else (1 if args.pattern=="same" else max(1,args.requests//4)),raw_dim)).astype(np.float32)
    t0=time.perf_counter()
    for i in range(args.requests):
        started=time.perf_counter()
        cell_index=(i*37)%args.cells
        if (cell_index/args.cells) >= args.active:
            continue
        j=0 if args.pattern=="same" else (i if args.pattern=="distinct" else i % len(raw_table))
        raw=raw_table[j]
        key=hashlib.blake2s(raw.tobytes()+b"owner:demo;encoder:synthetic-v1",digest_size=16).digest()
        if limit and key in cache:
            x=cache[key];hits+=1
        else:
            x=np.tanh(raw @ projection)
            if limit:
                if len(cache)>=limit:
                    del cache[order.popleft()]
                cache[key]=x
                order.append(key)
        h=heads[cell_index]
        prob=h.probs(x[None,:].copy())
        if args.train_frequency and rng.random()<args.train_frequency:
            # Artificial error-driven updates only: NOT NDU and NOT a durable cell model update.
            lab=int(rng.integers(0,2))
            logits, intermediate=h.forward(x[None,:].copy())
            dz=softmax(logits); dz[0,lab]-=1
            for k,g in h.backward(intermediate,dz).items():
                h.p[k]-=0.0001*np.clip(g,-1,1)
            updates+=1
        times.append((time.perf_counter()-started)*1000)
    elapsed=time.perf_counter()-t0
    if not times:
        raise ValueError("no active requests")
    rss_kb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result={"schema":SCHEMA,"experiment":"03_scale_synthetic_numeric_surrogate","kind":args.kind,"cells":args.cells,"budget_cap":args.budget,"parameters_per_cell":heads[0].nparams,"allocated_head_weight_bytes":resident_weights,"pattern":args.pattern,"active_fraction_requested":args.active,"train_frequency_requested":args.train_frequency,"observed_request_count":len(times),"updates":updates,"cache_hits":hits,"cache_hit_ratio":hits/len(times),"requests_per_second":len(times)/elapsed,"p50_ms":float(np.percentile(times,50)),"p95_ms":float(np.percentile(times,95)),"p99_ms":float(np.percentile(times,99)),"wall_seconds":elapsed,"process_peak_rss_kib":rss_kb,"platform":platform.platform(),"python":platform.python_version(),"numpy":np.__version__,"encoder":"SYNTHETIC_NUMERIC_PROJECTION_NOT_MODERNBERT","ndu_gain":"NOT_MEASURED","checkpoint_wal":"NOT_MEASURED","gpu_peak_memory":"NOT_AVAILABLE","production_admitted":False}
    write_json(Path(args.output),result)


def fixture(directory:Path, *, seed=13):
    directory.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(seed)
    weights=rng.standard_normal((32,2)).astype(np.float32)
    common={"encoder_digest":np.array("synthetic-encoder-do-not-promote"),"scope_digest":np.array("synthetic-scope")}
    events=[]
    for split,n,base in (("train",160,0),("valid",32,1000),("future",32,2000)):
        x=rng.standard_normal((n,32)).astype(np.float32)
        y=np.argmax(x@weights+0.25*rng.standard_normal((n,2)),axis=1).astype(np.int64)
        data={**common,"x":x,"id":np.array([f"{split}-{i}" for i in range(n)]),"group":np.array([f"{split}-episode-{i//4}" for i in range(n)]),"time":np.arange(base,base+n,dtype=np.int64),"cell":np.array(["cell:a"]*n)}
        if split!="future":
            np.savez_compressed(directory/f"{split}.npz",**data,y=y)
        else:
            np.savez_compressed(directory/"future_unlabelled.npz",**data)
            events=[{"id":str(data["id"][i]),"group":str(data["group"][i]),"time":int(data["time"][i]),"label":int(y[i])} for i in range(n)]
    write_json(directory/"future_outcomes.json",{"schema":SCHEMA,"window":"future","source":"independent_observation","rows":events,"SYNTHETIC":True})
    uniform=[{"id":e["id"],"group":e["group"],"time":e["time"],"probabilities":[0.5,0.5]} for e in events]
    write_json(directory/"no_change.json",{"schema":SCHEMA,"model_file_sha256":"no-change","train_groups":[],"valid_groups":[],"rows":uniform,"production_admitted":False})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="command",required=True)
    f=subs.add_parser("synthetic-fixture");f.add_argument("--dir",required=True);f.set_defaults(action=lambda a:fixture(Path(a.dir)))
    t=subs.add_parser("train")
    for flag in ("train","valid","output","report"):
        t.add_argument("--"+flag,required=True)
    t.add_argument("--kind",choices=KINDS,required=True);t.add_argument("--budget",type=int,choices=DIMS,required=True)
    t.add_argument("--steps",type=int,default=200);t.add_argument("--classes",type=int,default=2);t.add_argument("--seed",type=int,default=13);t.add_argument("--distill",type=float,default=0)
    t.set_defaults(action=cmd_train)
    p=subs.add_parser("predict")
    for flag in ("model","input","output"):
        p.add_argument("--"+flag,required=True)
    p.set_defaults(action=cmd_predict)
    e=subs.add_parser("evaluate")
    for flag in ("candidate","baseline","outcomes","output"):
        e.add_argument("--"+flag,required=True)
    e.add_argument("--candidate-ood"); e.add_argument("--baseline-ood"); e.add_argument("--ood-outcomes")
    e.set_defaults(action=cmd_evaluate)
    c=subs.add_parser("compare-representations")
    c.add_argument("--arm",action="append",required=True,help="name=prediction.json; four arms required")
    c.add_argument("--outcomes",required=True); c.add_argument("--output",required=True)
    c.set_defaults(action=cmd_compare_representations)
    s=subs.add_parser("scale")
    s.add_argument("--cells",type=int,choices=(64,256,1024,4096),required=True)
    s.add_argument("--pattern",choices=("same","partial","distinct"),required=True)
    s.add_argument("--kind",choices=KINDS,default="film");s.add_argument("--budget",type=int,choices=DIMS,default=2048)
    s.add_argument("--requests",type=int,default=512);s.add_argument("--dim",type=int,default=32)
    s.add_argument("--active",type=float,default=1);s.add_argument("--train-frequency",type=float,default=0)
    s.add_argument("--seed",type=int,default=13);s.add_argument("--cache-entries",type=int,default=128)
    s.add_argument("--max-head-bytes",type=int,default=512*1024*1024)
    s.add_argument("--output",required=True);s.set_defaults(action=cmd_scale)
    args=parser.parse_args()
    args.action(args)

if __name__=="__main__":main()
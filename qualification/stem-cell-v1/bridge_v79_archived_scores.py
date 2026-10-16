"""Immutable historic V6+V7 pretrained score interface for real-label Cell experiments.

NO original Granite97 Encoder tensors or 97D Reader hidden tensors are present.
This file intentionally exposes only original model probabilities + original
public question/answer/facts, strictly excluding original labels from features.
The experiment cannot be described as a pretrained-hidden-feature adaptation.
"""
from __future__ import annotations
from collections import Counter
from hashlib import sha256, blake2s
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import stat
import zipfile

import numpy as np

V6_SHA = "197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a"
V7_SHA = "199789fd66eee967269b3a137fc493c8991ecba695b8f81485a5a5b0cef9f463"
SIZES = {"v6": 20928479, "v7": 20818685}
SEEDS = (41, 47, 53)
SCHEMA = "hepta.bridge.v79.archived-frozen-score-cell.shadow.v1"
FEAT_SCHEMA = "hepta.bridge.v79.public-lexical-plus-historical-score.v1"
N_FEATURES = 97
WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*", re.I)
STOP = frozenset("a an and are as at be been by can could do does did for from had has have he her hers him his how in is it its of on or our she that the their them there these they this those to was were what when where which who whom why will with would you your".split())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def file_bytes(path, version):
    """FD-bound exact source, no symlink or mutable-path race."""
    path = Path(path)
    require(not path.is_symlink(), "source archive symlink refused")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size == SIZES[version],
                "original archive source size changed")
        payload = handle.read(SIZES[version] + 1)
        after = os.fstat(handle.fileno())
        require((before.st_ino, before.st_dev, before.st_mtime_ns, before.st_size) ==
                (after.st_ino, after.st_dev, after.st_mtime_ns, after.st_size),
                "source archive changed during read")
    require(len(payload) == SIZES[version] and sha(payload) == {"v6":V6_SHA, "v7":V7_SHA}[version],
            "original source archive SHA256 mismatched")
    return payload


def _pairs(pairs):
    result={}
    for k,v in pairs:
        require(k not in result, "duplicate JSON properties rejected")
        result[k]=v
    return result


def _json(z, name, maximum=20_000_000):
    record=z.getinfo(name)
    require(0 < record.file_size <= maximum, "oversized or absent bounded source")
    return json.loads(z.read(name), object_pairs_hook=_pairs,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def case_id(row):
    return json.dumps([row[n] for n in ("source_split", "paragraph_id", "question_id", "answer_id")],
                      separators=(",", ":"))


def load_sources(v6_path, v7_path):
    """Cross-bind V7 genuine original 3909 frozen logits to V6 original 827 panel.

    V7 start-natural-train SHA must be V6 frozen warmup model SHA per seed.
    An independent original paragraph source inventory is mandatory.
    """
    with zipfile.ZipFile(BytesIO(file_bytes(v6_path,"v6"))) as v6, \
         zipfile.ZipFile(BytesIO(file_bytes(v7_path,"v7"))) as v7:
        originals=_json(v6,"reader-v5-independent-audit/natural-cases.json")
        require(set(originals)=={"train","tune"},"unregistered V6 source roles")
        train,tune=originals["train"],originals["tune"]
        require(len(train)==3909 and len(tune)==827,"complete original real-label MultiRC source roster required")
        train_ids,tune_ids=[case_id(x) for x in train],[case_id(x) for x in tune]
        require(len(set(train_ids))==3909 and len(set(tune_ids))==827 and
                not set(train_ids).intersection(tune_ids),"duplicate or overlapping case IDs")
        groups_train={x["source_hash"] for x in train}; groups_tune={x["source_hash"] for x in tune}
        require(len(groups_train)==64 and len(groups_tune)==16 and not groups_train.intersection(groups_tune),
                "train/tune source groups overlap")
        require(len({(r["paragraph_id"],r["question_id"]) for r in train}) == 722 and
                len({(r["paragraph_id"],r["question_id"]) for r in tune}) == 194,
                "exact human question inventory changed")
        for role, rows in (("train",train),("tune",tune)):
            require(all(r["source_split"]=="train" and type(r["label"]) is int and r["label"] in (0,1)
                        and type(r["question"]) is str and type(r["candidate"]) is str
                        and type(r["facts"]) is list and len(r["facts"])>0
                        and all(type(f) is str and bool(f.strip()) for f in r["facts"])
                        for r in rows),f"original {role} human labels/public fields required")
        old_design=_json(v6, "reader-v6-bridge/design.json", maximum=2_000_000)
        v7_design=_json(v7, "reader-v7-retention/design.json",maximum=2_000_000)
        require(v7_design["previous_v6_design_sha256"]==sha(v6.read("reader-v6-bridge/design.json")),
                "V7 continued from an unknown original V6 source")
        reports={}
        for seed in SEEDS:
            parent=f"reader-v6-bridge/seed-{seed}/bridge/"
            manifest=_json(v6,parent+"warmup-model.json",maximum=100_000)
            require(manifest["seed"]==seed and manifest["architecture"]["arm"]=="bridge"
                    and manifest["parameter_count"]==42562 and
                    sha(v6.read(parent+"warmup.pt"))==manifest["file_sha256"],
                    "wrong genuine original V6 frozen Bridge model")
            start=_json(v7,f"reader-v7-retention/seed-{seed}/start-natural-train.json",maximum=4_000_000)
            hold=_json(v6,parent+"warmup-natural-internal.json",maximum=2_000_000)
            for record, ids, role in ((start,train_ids,"train"),(hold,tune_ids,"tune")):
                p=record["probabilities"]
                require(record["case_ids"]==ids and len(p)==len(ids)
                        and record["model_execution_parameter_sha256"]==manifest["execution_parameter_sha256"]
                        and all(type(x) in (int,float) and math.isfinite(x) and 0<=x<=1 for x in p),
                        "original pretrained model logits/source alignment changed")
                require(record["scope"] == ("complete_natural_training_partition_before_updates" if role=="train"
                        else "old_training_source_internal_tune_not_fresh") and
                        record["threshold_selected"] is False,
                        "incorrect original frozen-score chronology/scope")
            require(start["labels_entered_model"] is False,
                    "model input may not contain original human labels")
            reports[seed]=dict(train_p=tuple(start["probabilities"]),tune_p=tuple(hold["probabilities"]),
                model_sha256=manifest["execution_parameter_sha256"],
                model_file_sha256=manifest["file_sha256"],
                train_panel_sha256=sha(v7.read(f"reader-v7-retention/seed-{seed}/start-natural-train.json")),
                tune_panel_sha256=sha(v6.read(parent+"warmup-natural-internal.json")))
        return dict(train=train,tune=tune,reports=reports,
                    train_ids=train_ids,tune_ids=tune_ids,
                    train_source_groups=tuple(sorted(groups_train)),
                    tune_source_groups=tuple(sorted(groups_tune)),
                    source_sha256=sha(canonical(dict(train=train_ids,tune=tune_ids))),
                    archive_sha256={"v6":V6_SHA,"v7":V7_SHA},
                    labels_are_original_human=True,original_granite_encoder_loaded=False)


def words(text):
    return WORD.findall(text.lower())


def content_words(tokens):
    return [x for x in tokens if x not in STOP]


def _coverage(a, b):
    return len(set(a)&set(b))/max(1,len(set(a)))


def encode(row, p):
    """Cheap deterministic 97D public lexical sidecar; NOT V6 97D Reader state."""
    require(type(row) is dict and type(p) in (int,float) and math.isfinite(p) and 0<p<1,
            "original finite probability in (0,1) required")
    q=words(row["question"]); a=words(row["candidate"])
    sentences=[words(s) for s in row["facts"]]
    passage=[item for sent in sentences for item in sent]
    pq=set(passage); qset=set(q); aset=set(a)
    qa=content_words(q); aa=content_words(a)
    unique_qa=set(qa); unique_aa=set(aa)
    sentence_set=[set(s) for s in sentences]
    result=np.zeros((N_FEATURES,),dtype=np.float32)
    numeric=[
        max(-8.,min(8.,math.log(p/(1-p))))/4., p, 1.,
        _coverage(a,passage), _coverage(aa,passage),_coverage(qa,passage),
        float(bool(a) and " ".join(a) in " ".join(passage)),
        _coverage(aa,qa),
        max((_coverage(aa,list(s)) for s in sentence_set),default=0.),
        max((_coverage(qa,list(s)) for s in sentence_set),default=0.),
        max(((len(unique_aa&s)+len(unique_qa&s))/max(1,len(unique_aa)+len(unique_qa))
             for s in sentence_set),default=0.),
        len(aset&pq)/max(1,len(aset|pq)),
        math.log1p(len(a))/5., math.log1p(len(q))/5.,math.log1p(len(passage))/9.,
        float(len(a)==1 and a[0] in {"yes","no","true","false"}),
        float(any(t in ("not","never","no") for t in a)),
        float(any(t in ("not","never","no") for t in q)),
        float(any(t.isdigit() for t in a) and any(t in pq for t in a if t.isdigit())),
        float(bool(a) and len(set(a)-pq)==0),
    ]
    result[:len(numeric)]=numeric
    counts=np.zeros(N_FEATURES-20,dtype=np.float32)
    for prefix,tokens in (("answer:",unique_aa),("question:",unique_qa),("overlap:",unique_aa&pq),
                          ("joined:",unique_aa&unique_qa)):
        for token in sorted(tokens):
            h=blake2s((prefix+token).encode(),digest_size=8).digest()
            bucket=int.from_bytes(h[:4],"little")%len(counts)
            counts[bucket]+=1. if h[4]&1 else -1.
    size=np.sqrt(float(np.sum(counts*counts)))
    if size>0:counts=counts/np.float32(size)
    result[20:]=counts
    require(result.shape==(97,) and bool(np.isfinite(result).all()),"bounded source-only lexical feature required")
    return result


def make_features(rows, p, *, mode):
    require(mode in ("score_only","score_text") and len(rows)==len(p),"known feature ablation with complete rows")
    values=np.stack([encode(row, float(score)) for row,score in zip(rows,p)],axis=0)
    if mode=="score_only":values[:,3:]=0
    return values


def score(rows, decisions):
    require(len(rows)==len(decisions)>0 and all(type(p) in (int,np.integer) and p in (0,1) for p in decisions),
            "one finite binary decision per original row")
    labels=[r["label"] for r in rows]
    tp=sum(y==p==1 for y,p in zip(labels,decisions))
    positives=sum(labels)+sum(decisions)
    grouped={}
    for row,y,p in zip(rows,labels,decisions):
        key=(row["source_split"],row["paragraph_id"],row["question_id"])
        grouped.setdefault(key,[]).append(y==p)
    return dict(candidates=len(rows),questions=len(grouped),source_groups=len({r["source_hash"] for r in rows}),
                f1_a=2*tp/positives if positives else 0.,
                exact_match=sum(all(x) for x in grouped.values())/len(grouped),
                accuracy=sum(y==p for y,p in zip(labels,decisions))/len(rows),
                correct=sum(y==p for y,p in zip(labels,decisions)))


def original_logits(p):
    a=np.asarray(p,dtype=np.float64)
    z=np.log(np.clip(a,1e-6,1-1e-6)/(1-np.clip(a,1e-6,1-1e-6)))
    return np.stack([np.zeros(len(a)),z],axis=1).astype(np.float32)

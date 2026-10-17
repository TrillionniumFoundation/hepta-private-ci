"""V9 real-Pretrained-feature Head retention TRAIN-only diagnostic, no heldout selection.

Runs original 6,914-param Torch Head forwards on the exact 6 original
TRAIN-only source roots and checks byte-identical retrained weights. Pre/after
old and new weak-source pair BCE/accuracy are TRAIN diagnostics, NOT independent
relation transfer, future task success, V6 repair, or model promotion.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time

from stem_v9_original_continual import (
    ARMS, HELD, NEW, OLD, SEEDS, SCHEMA, GatedHead, file_sha, jbytes,
    private_head_sha, sample_pairs, train
)


def check_private(folder):
    import numpy as np
    import torch
    folder = Path(folder)
    src = json.loads((folder / "source-only.json").read_bytes())
    training = json.loads((folder / "train-only-labels.json").read_bytes())
    receipt = json.loads((folder / "physical-receipt.json").read_bytes())
    pre = json.loads((folder / "precommit.json").read_bytes())
    if (src["source_contains_publisher_gold"] is not False
        or training["heldout_labels_present"] is not False
        or receipt["original_predictions_sha256"] != file_sha(folder / "original-predictions.json")
        or pre["source_sha256"] != file_sha(folder / "source-only.json")
        or pre["train_sha256"] != file_sha(folder / "train-only-labels.json")
        or receipt["production_authorized"] is not False):
        raise ValueError("not original zero-test-label TRAIN source")
    matrix = np.load(folder / "private-vectors.npy", allow_pickle=False)
    if (matrix.dtype != np.float32
            or matrix.shape != (receipt["encoded_original_sources_and_questions"], 384)
            or not np.isfinite(matrix).all()
            or hashlib.sha256(matrix.tobytes()).hexdigest() != receipt["private_feature_matrix_sha256"]):
        raise ValueError("changed original source-model feature tensor bytes")
    keys=[]
    for fam in sorted(src["families"]):
        body=src["families"][fam]
        keys.extend(fam + "/" + d["id"] for d in body["passages"])
        keys.extend(q["id"] for q in body["questions"])
    if len(keys) != len(matrix) or len(set(keys)) != len(keys):
        raise ValueError("source feature index drift")
    return src, training, receipt, {k:torch.from_numpy(matrix[i].copy()) for i,k in enumerate(keys)}


def diagnostic(head, x, y):
    import torch
    import torch.nn.functional as F
    if x.ndim != 2 or x.shape[1] != 384 or len(x) != len(y) or len(x) % 2:
        raise ValueError("complete balanced training pairs only")
    with torch.no_grad():
        logits = head(x)
        if not torch.isfinite(logits).all():
            raise ValueError("nonfinite actual original physical Head result")
        pred = logits >= 0
        correct = pred == (y == 1)
        pairs = correct.reshape(-1,2).all(-1)
        ce = F.binary_cross_entropy_with_logits(logits, y).item()
        sha = hashlib.sha256(logits.float().contiguous().numpy().tobytes()).hexdigest()
    return {"correct": int(correct.sum()), "total": len(y),
            "pairs_correct": int(pairs.sum()), "pairs_total": len(y)//2,
            "bce": ce, "raw_logits_sha256": sha}


def run(folder):
    import torch
    torch.set_num_threads(2)
    src, labels, receipt, vectors = check_private(folder)
    oldx,oldy,oldn=sample_pairs(src,labels,vectors,OLD)
    newx,newy,newn=sample_pairs(src,labels,vectors,NEW)
    results=[]
    expected={(x["seed"],x["arm"]):x for x in receipt["physical_train_rows"]}
    start=time.process_time()
    for seed in SEEDS:
        common=GatedHead(seed)
        train(common,oldx,oldy,seed=seed*100+1,steps=240,lr=.001)
        before={"old_train":diagnostic(common,oldx,oldy),
                "new_train":diagnostic(common,newx,newy)}
        before_sha=private_head_sha(common)
        for arm in ARMS:
            child=common.clone()
            if arm!="frozen":
                train(child,newx,newy,seed=seed*1000+7,steps=240,
                      lr=.0002 if arm=="low_lr" else .001,
                      replay=(oldx,oldy) if arm=="equal_budget_replay" else None)
            head_record=expected[(seed,arm)]
            if (head_record["head_start_sha256"] != before_sha
                    or head_record["head_end_sha256"] != private_head_sha(child)):
                raise ValueError("actual tensor SHA disagrees with original sealed experiment")
            results.append({"seed":seed,"arm":arm,"start_head_sha256":before_sha,
                            "end_head_sha256":private_head_sha(child),
                            "before":before, "after":{
                                "old_train":diagnostic(child,oldx,oldy),
                                "new_train":diagnostic(child,newx,newy)}})
    return {"schema":SCHEMA+".postsealed-train-retention-diagnostic",
            "original_prediction_sha256":receipt["original_predictions_sha256"],
            "complete_original_train_roots":len(OLD+NEW),
            "old_original_train_questions":oldn,
            "new_original_train_questions":newn,
            "actual_train_head_forwards_replayed":12*2*2+3*2,
            "measured_train_diagnostic_cpu_seconds":time.process_time()-start,
            "read_publisher_heldout_answers":False,
            "independent_old_task_holdout_retention_verified":False,
            "new_task_independent_generalization_verified":False,
            "original_V6_retention_blocker_closed":False,
            "production_authorized":False,"rows":results}

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--directory",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    output=Path(args.output)
    if output.exists():raise FileExistsError("create-only diagnostic")
    result=run(args.directory)
    with output.open('xb') as f:
        f.write(jbytes(result)+b"\n")
        f.flush()
        import os
        os.fsync(f.fileno())
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},sort_keys=True))

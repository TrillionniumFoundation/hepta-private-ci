#!/usr/bin/env python3
"""Actual CPU inference from the stage-1 parent Head, with NO stage-2 update.

Additive, research-only: do not rewrite the historical `no_change` arm, whose
real meaning is *no split + continued learning*. The frozen candidate is a
separate counterfactual sharing original source and immutable stage-1 bytes.
No independent source/model/worker authority or prospective efficacy claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from qualification.cell_meta_execution_af import physical_router_trial as trial
from qualification.cell_meta_execution_af import physical_router_audit as soft_audit
from qualification.cell_meta_execution_af import physical_router_hard_review as hard_audit
from qualification.cell_meta_execution_af import physical_router_top1_review as top1_audit

SCHEMA = "hepta.cell-meta-true-frozen-stage1.v1"
PARTS = ("old_retention", "future_1", "future_2", "ood")

class FrozenBaselineDenied(ValueError):
    """Invalid source, stage-1 provenance, prediction, or budget identity."""

def require(ok: bool, msg: str) -> None:
    if not ok:
        raise FrozenBaselineDenied(msg)

def stable_head(hard: dict[str, Any], width: int) -> tuple[list[float], bytes]:
    """All four old-parent observations must refer to the SAME stage-1 fit."""
    arms = hard["results"]
    require(type(arms) is list and len(arms) == 4,
            "expected four exact predecessor training arms")
    pinned = arms[0]["stage1_parent_fp32"]
    for arm in arms[1:]:
        require(arm["stage1_parent_fp32"] == pinned,
                "cannot define frozen no-change from divergent stage1 parents")
    weights = hard_audit.decode(pinned, [width+1])
    raw = bytes.fromhex(pinned["data_le_hex"])
    return weights, raw

def source_metrics(panel: dict[str, Any], predictions: dict[str, list[dict[str, Any]]]) -> dict[str, dict]:
    """Retrospective labels are consulted only after the prediction seal exists."""
    out = {}
    for part in PARTS:
        records = panel["partitions"][part]
        values = predictions[part]
        require(len(values) == len(records), "missing retrospective frozen rows")
        ps, ys = [], []
        for row, pred in zip(records, values, strict=True):
            require(pred["id"] == row["id"], "frozen source order changed")
            ps.append(pred["probability"])
            ys.append(row["label"])
        n = len(ps)
        out[part] = {
            "count": n,
            "accuracy": round(sum(int((p >= .5) == bool(y)) for p,y in zip(ps,ys,strict=True))/n, 7),
            "brier": round(sum((p-y)**2 for p,y in zip(ps,ys,strict=True))/n, 7),
            "nll": round(-sum(y*math.log(p)+(1-y)*math.log1p(-p)
                              for p,y in zip(ps,ys,strict=True))/n, 7),
        }
    return out

def produce(panel: dict[str, Any], soft: dict[str, Any],
            posthoc: dict[str, Any], hard: dict[str, Any]) -> dict[str, Any]:
    """Only infer from existing stage-1 parent; NEVER call optimizer or train."""
    import torch
    trial.validate(panel)
    # Independently re-run the complete four-arm legacy/numeric/route lineage.
    hard_audit.replay(panel, soft, posthoc, hard)
    width = panel["source"]["dim"]
    _, raw = stable_head(hard, width)
    torch.set_num_threads(1)
    tensor = torch.frombuffer(bytearray(raw), dtype=torch.float32).clone()
    require(tuple(tensor.shape) == (width+1,) and
            bool(torch.isfinite(tensor).all()), "invalid actual stage-1 tensor")
    predictions = {}
    head_rows = 0
    started = time.process_time()
    with torch.inference_mode():
        for part in PARTS:
            records = panel["partitions"][part]
            x = torch.tensor([r["features"] for r in records], dtype=torch.float32)
            x = torch.cat((x, torch.ones((len(records), 1),dtype=torch.float32)),dim=1)
            p = torch.sigmoid(x @ tensor).clamp(trial.EPS, 1-trial.EPS)
            require(bool(torch.isfinite(p).all()), "nonfinite frozen Head prediction")
            predictions[part] = [
                {"id":record["id"], "probability":round(float(prob),9)}
                for record,prob in zip(records,p.tolist(),strict=True)
            ]
            head_rows += len(records)
    cpu = time.process_time()-started
    seal = trial.digest(predictions)
    score = source_metrics(panel, predictions)
    # The historical 'no_change' arm DOES update on new_train; never silently
    # relabel it as a truly frozen policy or compare unequal work as matched.
    historical_continuation = hard["results"][0]["retrospective_evaluation"]
    diffs = {part: round(score[part]["brier"]-historical_continuation[part]["brier"],7)
             for part in PARTS}
    return {
        "schema":SCHEMA,
        "source_panel_sha256":trial.digest(panel),
        "hard_predecessor_sha256":trial.digest(hard),
        "control_identity":"frozen_stage1_no_second_phase_learning",
        "historical_no_change_semantics":"unsplit_continued_stage2_update",
        "stage1_parent_fp32":hard["results"][0]["stage1_parent_fp32"],
        "stage1_parent_domain_sha256":hashlib.sha256(b"hepta.true-frozen.stage1.v1\0"+raw).hexdigest(),
        "prediction_sha256":seal,
        "predictions":predictions,
        "retrospective_evaluation":score,
        "brier_minus_historical_unsplit_continued":diffs,
        "meters":{
            "reused_stage1_train_rows_reported":len(panel["partitions"]["old_train"])*hard["steps_each_stage"],
            "additional_stage2_train_head_rows":0,
            "additional_stage2_optimizer_updates":0,
            "additional_eval_head_rows":head_rows,
            "additional_eval_router_rows":0,
            "actual_inference_cpu_seconds":round(cpu,6),
            "frozen_head_payload_bytes_fp32":len(raw),
        },
        "new_independent_stage1_execution_attested":False,
        "original_stage1_model_origin_authenticated":False,
        "true_ood_verified":False,
        "future_window_prospective":False,
        "total_compute_matched":False,
        "independent_ndu_selection_authorized":False,
        "production_admission":"BLOCKED",
        "authority_posture":"DENY_ALL",
    }

def main(argv: list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("panel","soft_report","posthoc_report","hard_report","out"):
        parser.add_argument("--"+key.replace("_","-"),type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        panel=trial.read_panel(args.panel)
        soft=soft_audit.load(args.soft_report)
        posthoc=soft_audit.load(args.posthoc_report)
        hard=soft_audit.load(args.hard_report)
        out=produce(panel,soft,posthoc,hard)
        payload=trial.canonical(out)+b"\n"
        require(len(payload)<=trial.MAX_BYTES,"bounded frozen baseline output required")
        fd=os.open(args.out,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        print(json.dumps({"output":str(args.out),"sha256":hashlib.sha256(payload).hexdigest(),
                          "authority_posture":"DENY_ALL"}))
        return 0
    except (FrozenBaselineDenied,trial.InvalidPanel,soft_audit.AuditError,
            hard_audit.HardReplayDenied,top1_audit.Top1AuditError,
            TypeError,ValueError,KeyError,IndexError,OSError,OverflowError,
            RuntimeError,RecursionError) as exc:
        print(f"FROZEN-BASELINE DENIED: {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())

"""Read-only exact-byte V18 historical negative-evidence audit (stdlib only)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "hepta.stem.v18.source-first-uncertainty.research"
HOLD = "hepta.v18.future-source-intake.research"
METER = "hepta.stem.v18.original-readonly-replay-meter"
RECEIPT_SHA = "5c9cf67e1d91ca8ebc5adafd9963357a91ddb45361f43d0311c276150e29edb4"


def require(ok, why):
    if not ok:raise ValueError(why)


def pairs(items):
    result={}
    for k,v in items:
        require(k not in result,"duplicate JSON field")
        result[k]=v
    return result


def read(path, maximum=500_000):
    p=Path(path)
    require(p.is_file() and not p.is_symlink() and 0<p.stat().st_size<=maximum,
            "bounded ordinary evidence file required")
    raw=p.read_bytes()
    obj=json.loads(raw,object_pairs_hook=pairs)
    json.dumps(obj,allow_nan=False)
    return obj,hashlib.sha256(raw).hexdigest()


def review(result,hold,meter,actual_sha):
    require(actual_sha==RECEIPT_SHA, "different original receipt bytes; no self-certification")
    require(result["schema"]==SCHEMA and result["status"]=="RETROSPECTIVE_CLUSTERED_CALIBRATION_ONLY"
            and result["independent_model_bytes_verified"]==82
            and result["resampling_units"]==32
            and result["distinct_original_calibration_cases"]==32
            and result["candidate_arm_count"]==12
            and result["bootstrap_draws"]==4096
            and len(result["correlated_training_seeds"])==3
            and result["source_family_independence_authenticated"] is False
            and result["prospective_outcomes"]==0
            and result["production_authorized"] is False
            and result["scientific_promotion_authorized"] is False
            and result["no_change_reference_preserved"] is True,
            "false historical source/authority statement")
    require(len(result["arms"])==12
            and all(a["case_mean"]<0 for a in result["arms"].values()),
            "changed historical non-winning source-bound arm")
    require(abs(result["arms"]["geo_aligned_oof"]["case_mean"]+0.11147350919894386)<1e-10
            and abs(result["arms"]["v16_final_loss_gate"]["case_mean"]+0.027562292717530634)<1e-10
            and 0.016<result["infeasible_oracle"]["case_mean"]<0.017
            and result["infeasible_oracle"]["deployable"] is False
            and result["infeasible_oracle"]["uses_calibration_labels"] is True,
            "historical contrast/oracle changed")
    require(hold["schema"]==HOLD
            and hold["verdict"]=="HOLD_MISSING_NEW_INDEPENDENT_WINDOWS"
            and hold["new_signed_window_count"]==0
            and hold["new_source_roots"]==0
            and hold["prospective_future_utility"] is None
            and hold["scientific_promotion_authorized"] is False
            and hold["production_authorized"] is False
            and hold["no_change_preserved"] is True
            and hold["retrospective_roster_sha256"]==result["calibration_case_roster_sha256"],
            "false future source admission")
    require(meter["schema"]==METER
            and meter["receipt_digest_consistent_across_processes"] is True
            and len(meter["runs"])==2
            and all(r["receipt_sha256"]==RECEIPT_SHA and r["major_faults"]>=0
                    and r["peak_rss_kib_linux_wait4"]>0 for r in meter["runs"])
            and meter["actual_prospective_source_count"]==0
            and meter["production_authorized"] is False
            and meter["target_host_qualified"] is False,
            "false independent actual rerun or cost")
    return {"schema":"hepta.v18.public-source-recount.no-go",
            "verdict":"COUNTS_CONSISTENT_NOT_FUTURE_MODEL_SUPERIORITY",
            "original_actual_model_files_verified":82,
            "real_unique_calibration_cases":32,
            "repeated_training_seeds":3,
            "historical_candidate_arms":12,
            "genuine_new_source_roots":0,
            "production_authorized":False,
            "scientific_promotion_authorized":False,
            "future_utility":None,
            "independent_retention":None}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for x in ("result","hold","meter"):
        p.add_argument("--"+x,required=True)
    args=p.parse_args()
    result,sha=read(args.result)
    hold,_=read(args.hold)
    meter,_=read(args.meter)
    print(json.dumps(review(result,hold,meter,sha),sort_keys=True))


if __name__=="__main__":main()

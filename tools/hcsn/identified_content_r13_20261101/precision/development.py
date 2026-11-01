"""Replay all fixed R12 inputs against their independent 80-digit references."""

import gzip
import hashlib
import json
import time
from pathlib import Path

import numpy as np

import ds_kernel

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parents[1]/"unified_cell_r12_20261031"/"numerics"


def error(actual, expected):
    return float(np.max(np.abs(np.asarray(actual,dtype=np.float64)-expected)/np.maximum(1,np.abs(expected))))


def main():
    import sys
    tag=sys.argv[1] if len(sys.argv)>1 else "DEV01"
    output=ROOT/(tag+"_RESULTS.json")
    if output.exists():
        raise ValueError("Refusing to overwrite evidence")
    old=json.loads((OLD/"FINAL_RESULTS.json").read_text())
    joins=json.loads((OLD/"JOIN_RESULTS.json").read_text())
    fixtures=[dict(r,group="original48") for r in old["rows"] if r["mode"]=="candidate32"]
    fixtures += [dict(r,group="seams33") for r in joins["rows"] if r["mode"]=="float32"]
    sources={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ("ds_math.py","ds_kernel.py","CONSTANTS.json","green.py","GREEN_CONSTANTS.json")}
    for n in sources:
        (ROOT/(tag+"_"+n+".gz")).write_bytes(gzip.compress((ROOT/n).read_bytes(),mtime=0))
    results=[]
    start=time.perf_counter()
    for i,fix in enumerate(fixtures):
        theta=fix.get("represented_theta",fix["theta"])
        state=fix.get("represented_state",fix["state"])
        coordinate=fix.get("coordinate","log_distance")
        ref=np.asarray(fix["reference"])
        jac=np.asarray(fix["reference_jacobian"])
        row=dict(index=i,name=fix.get("name",fix.get("case")),group=fix["group"],theta=theta,state=state,
                 coordinate=coordinate,reference=ref.tolist(),reference_jacobian=jac.tolist(),
                 previous_value_error=fix["value_error"],previous_jacobian_error=fix["jacobian_error"])
        tick=time.perf_counter()
        try:
            v,j=ds_kernel.evaluate(theta,state,coordinate=coordinate,diagnostic_outside_box=True)
            if not np.isfinite(v).all() or not np.isfinite(j).all():
                raise ValueError("nonfinite result")
            ve,je=error(v,ref),error(j,jac)
            row.update(actual=v.tolist(),jacobian=j.tolist(),value_error=ve,jacobian_error=je,
                       passed=ve<=8e-7 and je<=2e-5)
        except (ValueError,ArithmeticError) as exc:
            row.update(passed=False,error=str(exc))
        row["seconds"]=time.perf_counter()-tick
        results.append(row)
        print(i,row["name"],row.get("value_error"),row.get("jacobian_error"),row["passed"],flush=True)
    summary={group:dict(rows=sum(r["group"]==group for r in results),
              passed=sum(r["group"]==group and r["passed"] for r in results),
              maximum_value_error=max((r.get("value_error",0) for r in results if r["group"]==group)),
              maximum_jacobian_error=max((r.get("jacobian_error",0) for r in results if r["group"]==group)))
              for group in ("original48","seams33")}
    payload=dict(sources=sources,reference_sources={n:hashlib.sha256((OLD/n).read_bytes()).hexdigest()
                   for n in ("FINAL_RESULTS.json","JOIN_RESULTS.json")},
                 rows=results,summary=summary,seconds=time.perf_counter()-start,
                 precision="two-FP32 double-single; final outputs/Jacobian FP32; no FP64 kernel fallback")
    output.write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()

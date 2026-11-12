"""Read-only replay of retained second-cycle arithmetic; no candidate/reference imports."""

import argparse
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close_digits(actual,expected):
    return abs(actual-expected)<=Decimal("1e-36")*max(abs(expected),Decimal("1e-2000"))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    root=Path(__file__).resolve().parent;repo=root.parents[1]
    kernels=root/"evidence/kernels-attempt001"
    references=root/"evidence/references-attempt001"
    ks=json.loads((kernels/"SUMMARY.json").read_text())
    rs=json.loads((references/"SUMMARY.json").read_text())
    assert ks["source_before"]==ks["source_after"]==rs["source_before"]==rs["source_after"]
    def mapped(old):
        if "/qualification/"in old:
            return repo/("qualification/"+old.split("/qualification/",1)[1])
        marker="/secondcycle/evidence/kernels-attempt001/"
        assert marker in old
        return kernels/old.split(marker,1)[1]
    for mapping in (ks["source_before"],ks["input_sha256"],rs["input_sha256"]):
        for old,expected in mapping.items():assert sha(mapped(old))==expected
    for summary,folder in ((ks,kernels),(rs,references)):
        for name,expected in summary["output_sha256"].items():assert sha(folder/name)==expected
    assert ks["source_commit"]==rs["source_commit"]=="c3a5b3d64693222dc44687c82079084860a01dd9"
    assert ks["new_serial_kernel_evaluations"]==72 and ks["positive_series_terms"]==2127264
    assert rs["candidate_kernel_reruns"]==0
    assert rs["analytic_reference_evaluations"]==192 and rs["finite_reference_expm_calls"]==1156
    call_count,term_count,query_count=0,0,0
    case_rows={}
    for name in ks["cases"]:
        payload=json.loads((kernels/(name+".json")).read_text())
        with np.load(kernels/(name+".npz"),allow_pickle=False)as archive:
            arrays={key:archive[key].copy()for key in archive.files}
        columns=arrays["columns"].tolist()
        for law in ("initial","reset"):
            assert np.min(arrays[law])>=0
            assert sum((Fraction.from_float(float(v))for v in arrays[law]),Fraction(0))==1
        for call in payload["calls"]:
            index=call["index"];call_count+=1;term_count+=call["terms"]
            assert call["terms"]==call["final_power_exponent"]+1
            active=arrays["call"+str(index)+"_final_power_active"]
            hit=arrays["call"+str(index)+"_final_power_hit"]
            escape=arrays["call"+str(index)+"_final_power_escape"]
            killed=arrays["call"+str(index)+"_final_power_killed"]
            assert np.min(np.r_[active.ravel(),hit,escape,killed])>=0
            finalmass=active.sum(axis=(1,2))+hit+escape+killed
            assert abs(finalmass-1).max()<=call["sampled_power_mass_drift"]+8*math.ulp(1.)
            assert not call["roundoff_certified"]
            with localcontext()as c:
                c.prec=90
                lam=Decimal.from_float(call["nu"])*Decimal.from_float(call["active_horizon"])
                threshold=Decimal(call["terms"])
                logbound=(Decimal.from_float(call["active_horizon"])/Decimal.from_float(.025)).ln()-lam+threshold*(1+(lam/threshold).ln())
                assert abs(Decimal(call["chernoff_log_expression"])-logbound)<Decimal("1e-65")*max(1,abs(logbound))
                expected=logbound.exp()*(1+Decimal("1e-30"))
                actual=Decimal(call["poisson_truncation_bound_M_and_H"])
                assert actual>0 and abs(actual-expected)<abs(expected)*Decimal("1e-65")
        for i,row in enumerate(payload["rows"]):
            query_count+=1
            assert row["time"]==float(.2+row["original_gap"])
            assert Fraction.from_float(row["active_offset"])==Fraction.from_float(row["time"])-Fraction.from_float(.2)
            expected=[row["time"],row["active_offset"],row["original_gap"],
                      *[row["values"][name]for name in columns[3:]]]
            np.testing.assert_array_equal(arrays["rows"][i],expected)
            first,back,second=[payload["calls"][j]for j in row["call_indices"]]
            assert row["values"]["M1"]==first["M"] and row["values"]["M2"]==second["M"]
            assert row["values"]["H1"]==first["H_phase"]
            assert math.isclose(row["values"]["H2"],math.exp(-.15*.2)*second["H_phase"],rel_tol=1e-14,abs_tol=0)
            assert row["values"]["returned_mass"]==back["M"]
            case_rows[(name,row["time"])]=row
    assert (call_count,term_count,query_count)==(72,2127264,24)
    rows=json.loads((references/"ROWS.json").read_text())
    assert len(rows)==24
    metrics,ineligible=0,0
    result={"read_only":True,"kernel_calls_replayed":0,"analytic_integrals_replayed":0,
        "expm_calls_replayed":0,"retained_kernel_calls":call_count,"retained_series_terms":term_count,
        "retained_query_rows":query_count,"status":"HOLD_NO_GO","all_closed":False,"case_metrics":{}}
    with localcontext()as c:
        c.prec=140
        for row in rows:
            observed=case_rows[(row["case"],row["time"])]["values"]
            for name,q in row["comparisons"].items():
                actual=Decimal.from_float(q["actual"])
                assert q["actual"]==observed[name]
                reference=Decimal(q["reference_value"])
                error=abs(actual-reference)
                assert close_digits(Decimal(q["absolute_error"]),error)
                eligible=abs(reference)>=Decimal.from_float(1e-12)
                assert q["relative_reference_floor"]==1e-12 and q["relative_diagnostic_eligible"]==eligible
                if eligible:assert close_digits(Decimal(q["relative_error"]),error/abs(reference))
                else:assert q["relative_error"]is None;ineligible+=1
                bound=Decimal(q["ideal_series_truncation_bound"])
                assert q["series_bound_exceeds_reference"]==(bound>=abs(reference))
                assert not q["roundoff_certified"]
                if row["kind"]=="matrix":
                    assert q["reference_precision_mode"]=="FP64-expm-quad"
                    assert q["precision80_vs120_relative"]is None
                else:assert q["reference_precision_mode"]=="independent80/120"
                if row["kind"]=="domain":
                    original=Decimal(q["unquantized_reference120"])
                    mapping=reference-original
                    assert close_digits(Decimal(q["reset_law_difference"]),mapping)
                    assert close_digits(Decimal(q["conservative_absolute_spatial_plus_mapping"]),error+abs(mapping))
                    upper=Decimal(q["continuum_upper_bound"])
                    assert close_digits(Decimal(q["spatial_vs_finite_continuum_bound"]),error+upper)
                    assert close_digits(Decimal(q["noncancelling_error_bound_via_upper_bracket"]),error+abs(mapping)+2*upper)
                    if eligible:
                        ratio=Decimal(q["noncancelling_error_bound_via_upper_bracket"])/abs(original)
                        slot=result["case_metrics"].setdefault(row["case"],{}).setdefault(name,{"eligible":0,"maximum_noncancelling_relative":0.})
                        slot["eligible"]+=1;slot["maximum_noncancelling_relative"]=max(slot["maximum_noncancelling_relative"],float(ratio))
                metrics+=1
    assert metrics==336
    result.update(quantity_error_rows=metrics,ineligible_relative_rows=ineligible)
    if args.output:args.output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items()if k!="case_metrics"}))


if __name__=="__main__":
    main()

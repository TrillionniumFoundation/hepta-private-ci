"""Independent standard-library arithmetic replay; no solver imports."""

import argparse
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path


def flat(value):
    if isinstance(value, list):
        for item in value:
            yield from flat(item)
    else:
        yield value


def close(a, b):
    assert abs(a-b) <= 1e-10 * (1+abs(a)), (a,b)


def check(output):
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
    for item in freeze["files"]:
        assert hashlib.sha256((root/item["path"]).read_bytes()).hexdigest() == item["sha256"]
    result = json.loads((output/"RESULTS.json").read_text())
    assert result["protocol"] == protocol and result["source_freeze"] == freeze
    assert result["old_r20_finite_step_gate"] is result["full_neural_gradient"] is result["production_activation"] is False
    count = 78 if result["phase"] == "diagnosis" else protocol["fresh_profiles"]*26 + len(protocol["tie_meshes"])*len(protocol["fee_ulps"])*2
    assert len(result["records"]) == len(result["archives"]) == count
    decisions, seen, scalar_checks, maxima = [], set(), 0, dict(local=0., decomposition=0., old=0.)
    for entry, row in zip(result["archives"],result["records"]):
        packed=(output/entry["path"]).read_bytes()
        assert len(packed)==entry["bytes"] and hashlib.sha256(packed).hexdigest()==entry["sha256"]
        raw=gzip.decompress(packed)
        assert hashlib.sha256(raw).hexdigest()==entry["raw_sha256"]
        payload=json.loads(raw)
        assert payload["record"]==row
        arrays={k:list(flat(v)) for k,v in payload["arrays"].items()}
        assert all(math.isfinite(value) for values in arrays.values() for value in values)
        cert=row["certificate"]
        assert cert["qualified"] == (cert["branch_certified"] and cert["derivative_error_bound_passed"] and not cert["policy_mismatches"])
        assert cert["derivative_error_bound_passed"] == (cert["maximum_derivative_enclosure_error"] <= protocol["local_tolerance"])
        if row.get("kind")=="binary_nonconstant_tie_control":
            dx,dt,sign=row["dx"],row["dt"],row["direction"]
            space,steps=round(8/dx)+1,round(.25/dt)+1
            gap=Fraction(float.fromhex(row["fee_hex"]))-Fraction(1,16)
            assert str(gap)==row["exact_gap"]
            oracle=[]
            for k in range(steps):
                for mode in range(2):
                    for i in range(space):
                        x=-4+i*dx
                        oracle.append(0. if k<steps-1 or mode==0 or x>0 else -sign if x<0 else 0. if gap>0 else -sign if gap<0 else max(0.,-sign))
            assert arrays["oracle"]==oracle and len(arrays["derivative"])==len(oracle)
            error=max(abs(a-b) for a,b in zip(arrays["derivative"],oracle))
            close(error,row["oracle_error"])
            passed=cert["qualified"] and error<=protocol["local_tolerance"]
            scalar_checks+=len(oracle)
            identity=("tie",dx,dt,row["fee_hex"],sign)
        else:
            diagnosis=result["phase"]=="diagnosis"
            dkey,lkey=("corrected_derivative","corrected_left_derivative") if diagnosis else ("derivative","left_derivative")
            if "analytic_derivative" not in arrays:
                assert row["analytic_reference_error"] is None and not row["passed"]
                passed=False
            else:
                assert all(len(arrays[k])==5002 for k in [dkey,lkey,"analytic_derivative","analytic_left_derivative"])
                error=max(max(abs(a-b) for a,b in zip(arrays[dkey],arrays["analytic_derivative"])),max(abs(a-b) for a,b in zip(arrays[lkey],arrays["analytic_left_derivative"])))
                close(error,row["analytic_reference_error"])
                passed=cert["qualified"] and error<=protocol["local_tolerance"]
                maxima["local"]=max(maxima["local"],error)
                scalar_checks+=10004
            if diagnosis:
                derivative,base=arrays["local_derivative"],arrays["base"]
                prior=max(abs(a-b) for a,b in zip(derivative,arrays["analytic_derivative"])) if "analytic_derivative" in arrays else None
                if prior is not None:close(prior,row["original_derivative_vs_analytic"])
                passed=passed and prior is not None and prior<=protocol["local_tolerance"]
                for j,step in enumerate(protocol["original_real_steps"]):
                    actual,fixed=arrays["actual_"+str(j)],arrays["frozen_"+str(j)]
                    observed=[(a-b)/step-d for a,b,d in zip(actual,base,derivative)]
                    truncation=[(a-b)/step-d for a,b,d in zip(fixed,base,derivative)]
                    switch=[(a-b)/step for a,b in zip(actual,fixed)]
                    residual=max(abs(a-b-c) for a,b,c in zip(observed,truncation,switch))
                    stored=row["decomposition"][j]
                    for number,field in [(max(map(abs,observed)),"original_error"),(max(map(abs,truncation)),"frozen_policy_error"),(max(map(abs,switch)),"switch_component"),(residual,"decomposition_residual")]:close(number,stored[field])
                    assert (max(map(abs,observed))<=protocol["original_finite_step_tolerance"])==stored["original_passed"]
                    passed=passed and residual<=protocol["decomposition_tolerance"]
                    maxima["decomposition"]=max(maxima["decomposition"],residual)
                    maxima["old"]=max(maxima["old"],max(map(abs,observed)))
                identity=("old",row["old_index"])
            else:identity=("fresh",row["profile"],row["coordinate"],row["sign"])
        assert identity not in seen
        seen.add(identity)
        assert passed==row["passed"]
        decisions.append(passed)
    if result["phase"]=="diagnosis":
        assert seen=={("old",index) for index in range(78)}
        assert not result["controls"]
    else:
        expected={("fresh",profile,coordinate,sign) for profile in range(protocol["fresh_profiles"]) for coordinate in range(13) for sign in (-1.,1.)}
        for dx,dt in protocol["tie_meshes"]:
            for ulps in protocol["fee_ulps"]:
                fee=.0625
                for _ in range(abs(ulps)):
                    fee=math.nextafter(fee,math.inf if ulps>0 else -math.inf)
                expected.update(("tie",dx,dt,fee.hex(),sign) for sign in (-1.,1.))
        assert seen==expected
        assert sorted(r["name"] for r in result["controls"])==sorted(protocol["controls"])
    decisions += [r["passed"] for r in result["controls"]]
    assert all(decisions)==result["passed"]
    return dict(schema="hcsn-r22-independent-array-replay-v1",integrity_passed=True,scientific_passed=result["passed"],phase=result["phase"],cases=count,scalar_derivative_positions=scalar_checks,maxima=maxima,
        scope="Complete saved arithmetic and rational oracle replay; not independent re-execution of interval enclosures/LAPACK or control summaries. Original finite-step gate remains failed.")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    with args.out.open("x") as stream:
        json.dump(check(args.run),stream,indent=2,allow_nan=False)
        stream.write("\n")

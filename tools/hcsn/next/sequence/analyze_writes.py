"""Inspect learned filler write coefficients; capability is not learned closure."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit,softmax


def main():
    folder=Path(__file__).parent
    main_record=json.loads((folder/"results.json").read_text())
    full_record=json.loads((folder/"full_results.json").read_text())
    assert main_record["complete"] and full_record["complete"]
    chosen=[r for r in main_record["runs"]+full_record["runs"]
            if r["task"]=="memory" and r["kind"] in ("hcsn","sigmoid","memory_only","full_hx")]
    filler=np.zeros((4,17),np.float64)
    filler[:4,:4]=np.eye(4)
    filler[:,-1]=np.log(2.)
    query=np.zeros(17,np.float64);query[5]=1.;query[-1]=np.log(2.)
    output=[]
    for row in chosen:
        path=folder/row["checkpoint_file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest()==row["checkpoint_sha256"]
        p={key:val.astype(np.float64) for key,val in np.load(path).items()}
        scores=(filler@p["write"]+p["write_bias"])[:,0]
        positive=np.maximum(scores,0.)
        writes=positive*positive/(1.+positive*positive)
        temp=1.+15.*expit(p["temperature"])
        address=softmax(temp*(filler@p["key"]+p["key_bias"]),axis=-1)
        query_address=softmax(temp*(query@p["key"]+p["key_bias"]))
        coefficients=writes[:,None]*address
        slot=int(np.argmax(query_address))
        largest=float(coefficients[:,slot].max())
        half=float(np.log(.5)/np.log1p(-largest)) if 0<largest<1 else None
        output.append(dict(kind=row["kind"],seed=row["seed"],filler_write_scores=scores.tolist(),
            all_filler_global_write_gates_closed=bool(np.all(scores<=0)),
            query_address=query_address.tolist(),highest_query_weight_slot=slot,
            per_filler_per_slot_write_coefficients=coefficients.tolist(),
            highest_query_slot_worst_direct_retention_half_life=half,
            checkpoint_sha256=row["checkpoint_sha256"]))
    result=dict(complete=True,checks=output,
        all_filler_global_gate_closed_count=sum(r["all_filler_global_write_gates_closed"] for r in output),
        interpretation="The C1 gate can close, but these trained weights need not use that capability. Positive softmax-weighted writes imply leakage of the old slot value's direct coefficient. This alone is not a proof of lost classification information because other slots and dynamic states also carry information.",
        numerical_analysis="Float64 evaluation of stored float32 weights, on the four exact filler symbols and final query of the declared memory task; no new training or test selection")
    (folder/"write_diagnostics.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"models_checked":len(output),"all_filler_global_gate_closed_count":result["all_filler_global_gate_closed_count"]}))


if __name__=="__main__":
    main()

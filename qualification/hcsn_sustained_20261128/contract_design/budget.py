"""Independent calibration and confirmation of minimum tested quote count."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

from contract_inverse import Surface
from design import (PILOT,OPTIONS,FIXED,TEST_SCALE,TEST_X,CENTER,Law,all_ids,
                    equity_basis,noise_scale,population,predictions,select_info)

FAMILIES=["fixed_spread","preplanned_medium_pilots","preplanned_wide_pilots"]
BUDGETS=[2,3,4,5,6]


def sources():
    return {name:sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("BUDGET_PROTOCOL.md","design.py","budget.py")}


def estimate(stage, reference_dir, path):
    sys.path.insert(0,str(reference_dir))
    from hx_reference import hit
    is_dev=stage=="calibrate"
    rng=np.random.default_rng(85202 if is_dev else 85203)
    contracts=population(rng,128 if is_dev else 256)
    reps=12
    data=np.zeros((len(contracts),len(FAMILIES),len(BUDGETS),reps,2))
    chosen_ids=np.zeros((len(contracts),len(FAMILIES),6),dtype=int)
    for i,row in enumerate(contracts):
        theta=row[None,:4]
        surface=Surface(*row[4:])
        law=Law(surface,PILOT+OPTIONS)
        eval_law=Law(surface,[(s,x) for s in TEST_SCALE for x in TEST_X])
        basis=equity_basis(surface,hit)
        desired=predictions(eval_law,theta,basis)
        possible=law.evaluate(theta,all_ids(1))[0]
        info=law.information(CENTER[None,:],all_ids(1))
        errors=rng.normal(size=(reps,6,2))
        for family in range(3):
            seq=[2,18] if family==2 else [0,1]
            for slot in range(2,6):
                add=(FIXED[slot-2]+2 if family==0 else
                     int(select_info(info,np.array(seq)[None,:])[0]))
                seq.append(add)
            chosen_ids[i,family]=seq
            vals=possible[seq]
            measured=vals+noise_scale(vals)*errors
            for j,cost in enumerate(BUDGETS):
                ids=np.tile(seq[:cost],(reps,1))
                z=law.fit(ids,measured[:,:cost],np.tile(CENTER,(reps,1)))
                gap=abs(predictions(eval_law,z,basis)-desired)
                data[i,family,j,:,0]=np.max(gap[:,:-1],axis=(1,2,3))/row[1]
                data[i,family,j,:,1]=np.max(gap[:,-1],axis=(1,2))/row[1]
    boot=np.random.default_rng(9200 if is_dev else 9201).integers(0,len(contracts),(2000,len(contracts)))
    summary,eligible={},{}
    for family,name in enumerate(FAMILIES):
        summary[name]=[]
        eligible[name]=None
        for j,cost in enumerate(BUDGETS):
            off,nom=data[:,family,j].transpose(2,0,1)
            pass_by_contract=np.mean(off<=.004,axis=1)
            lower=np.quantile(pass_by_contract[boot].mean(axis=1),.05)
            summary[name].append(dict(quote_count=cost,success=float(pass_by_contract.mean()),
                one_sided_lower95=float(lower),off_design_mean=float(off.mean()),
                retained_mean=float(nom.mean()),off_design_p95=float(np.quantile(off,.95))))
            if lower>=.95 and eligible[name] is None:
                eligible[name]=cost
    archive=path.with_name(stage+"_prefixes.npz")
    np.savez_compressed(archive,contract=contracts,score=data,sequence=chosen_ids)
    out=dict(stage=stage,sources=sources(),samples_per_contract=reps,n_contracts=len(contracts),
             archive_sha256=sha256(archive.read_bytes()).hexdigest(),by_cost=summary)
    if is_dev:
        out["selected"]=eligible
    return out


if __name__=="__main__":
    arg=argparse.ArgumentParser()
    arg.add_argument("stage",choices=["calibrate","held"])
    arg.add_argument("reference",type=Path)
    arg.add_argument("out",type=Path)
    arg.add_argument("--sealed",type=Path)
    opt=arg.parse_args()
    if opt.stage=="held":
        seal=json.loads(opt.sealed.read_text())
        if seal["sources"]!=sources():
            raise RuntimeError("budget design changed after calibration")
    result=estimate(opt.stage,opt.reference,opt.out)
    if opt.stage=="held":
        result["selected_before_test"]=seal["selected"]
        result["calibration_sha256"]=sha256(opt.sealed.read_bytes()).hexdigest()
    opt.out.write_text(json.dumps(result,indent=2)+"\n")
    print({name:[(r["quote_count"],round(r["success"],4),round(r["one_sided_lower95"],4))
                 for r in rows] for name,rows in result["by_cost"].items()})

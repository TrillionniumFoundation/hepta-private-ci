"""Rebuild budget success curves and selected cold outputs with independent equity ODEs."""
import argparse
import hashlib
from pathlib import Path
import json
import sys
import numpy as np
from design import PILOT,OPTIONS,CENTER,Law,Surface,population,all_ids,TEST_SCALE,TEST_X


def main(ref,root):
    sys.path.insert(0,str(ref.parent))
    from reference import solution
    seal=json.loads((root/"budget_seal.json").read_text())
    held=json.loads((root/"budget_held.json").read_text())
    if held["calibration_sha256"]!=hashlib.sha256((root/"budget_seal.json").read_bytes()).hexdigest():
        raise ValueError("development seal mismatch")
    diffs=[]
    worst=0.
    for stage,report,seed,n in [("calibrate",seal,85202,128),("held",held,85203,256)]:
        arch=root/(stage+"_prefixes.npz")
        if report["archive_sha256"]!=hashlib.sha256(arch.read_bytes()).hexdigest():
            raise ValueError("prefix archive mismatch")
        records=np.load(arch)
        rng=np.random.default_rng(seed)
        truth=population(rng,n)
        np.testing.assert_array_equal(truth,records["contract"])
        boots=np.random.default_rng(9200 if stage=="calibrate" else 9201).integers(0,n,(2000,n))
        for i,name in enumerate(("fixed_spread","preplanned_medium_pilots","preplanned_wide_pilots")):
            expected=None
            for j,k in enumerate(range(2,7)):
                off,nom=records["score"][:,i,j].transpose(2,0,1)
                rows=(off<=.004).mean(axis=1)
                lb=np.quantile(rows[boots].mean(axis=1),.05)
                vals=[rows.mean(),lb,off.mean(),nom.mean(),np.quantile(off,.95)]
                row=report["by_cost"][name][j]
                orig=[row[key] for key in ("success","one_sided_lower95","off_design_mean","retained_mean","off_design_p95")]
                np.testing.assert_allclose(vals,orig,rtol=1e-13,atol=1e-15)
                if expected is None and lb>=.95:
                    expected=k
            if stage=="calibrate" and expected!=seal["selected"][name]:
                raise ValueError("incorrect calibration selection")
        if stage!="held":
            continue
        for i,p in enumerate(truth):
            noise=rng.normal(size=(12,6,2))
            if i not in (2,25,79,133,181,251):
                continue
            law=Law(Surface(*p[4:]),PILOT+OPTIONS)
            r,d,s,m,prem=p[4:]
            all_data=law.evaluate(p[:4][None,:],all_ids(1))[0]
            def price(theta):
                c,par,alpha,tax=theta
                return np.array([solution(np.array([r,d,s,tax,alpha,c,scale*par,m,prem]),TEST_X)[:,[0,2,1]]
                                 for scale in TEST_SCALE])
            gold=price(p[:4])
            for f,name in enumerate(("fixed_spread","preplanned_medium_pilots","preplanned_wide_pilots")):
                k=seal["selected"][name]
                ids=records["sequence"][i,f,:k]
                raw=all_data[ids]+(.02+.002*abs(all_data[ids]))*noise[:,:k]
                z=law.fit(np.tile(ids,(12,1)),raw,np.tile(CENTER,(12,1)))
                for rep in (2,9):
                    err=abs(price(z[rep])-gold)
                    vals=np.array([err[:-1].max(),err[-1].max()])/p[1]
                    worst=max(worst,float(np.max(abs(vals-records["score"][i,f,k-2,rep]))))
                    diffs.append(worst)
    if worst>1e-8:
        raise ValueError("external ODE score mismatch")
    return dict(checked_calibration_and_test_curves=30,cold_trajectories_recomputed=len(diffs),
                independent_price_error_metrics_max_difference=worst,selected_before_test=seal["selected"])


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("reference",type=Path)
    ap.add_argument("root",type=Path)
    args=ap.parse_args()
    out=main(args.reference,args.root)
    (args.root/"budget_verified.json").write_text(json.dumps(out,indent=2)+"\n")
    print(out)

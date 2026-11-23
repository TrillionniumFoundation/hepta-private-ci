"""Verify scalar candidate identities and hard policy values with forward payoff propagation."""
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive_root",type=Path)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    root=args.archive_root.resolve()
    run=args.output
    sys.path.insert(0,str(root/"neuron"))
    from verify import independent_scores, forward_payoff
    from experiment import vg,canonical,digest,head,model_with_head,checked,context,read,save,pin,gen_items
    start=time.process_time()
    method=read(run/"METHOD.json")
    assert method["script_sha"]==pin(Path(__file__).with_name("stop_bias.py"))["sha256"]
    p=read(root/"neuron/pinned/PROTOCOL_FROZEN.json")
    ctx=context(p)
    fits=read(run/"FITS.json")
    cases=read(run/"WORLDS.json")
    records=read(run/"ROWS.json")
    historical=set(p["known_schedule_hashes"])
    for phase in ("selection","confirmation"):
        previous=read(root/"neuron/pinned/evidence/run"/f"{phase}_attempt001/output/WORLDS_FROZEN.json")
        historical.update(w["schedule_sha256"] for groups in previous["groups"].values()
                          for domain in groups.values() for w in domain["worlds"])
    historical.update(w["fingerprint"] for w in read(root/"neuron/run/WORLDS.json")["cases"])
    historical.update(w["schedule"] for w in read(root/"fullbp/run/WORLDS.json")["cases"])
    assert len(historical)==cases["excluded"]
    seen={r["schedule"] for r in records}
    assert len(records)==len(cases["cases"])==len(seen)==160 and not historical & seen
    assert digest(canonical({f:r["models"] for f,r in fits.items()}).encode())==cases["seal"]
    counts=0
    gen_checks=0
    largest=0.
    sweep_worst=0.
    for fit in p["fit_ids"]:
        base,items=gen_items(p,root/"neuron/inputs",fit)
        meta=fits[str(fit)]
        models={}
        for a,b in meta["shifts"].items():
            rows=head(base).copy()
            rows[:3,48]+=b
            model,norm=model_with_head(base,rows,"Q")
            assert (head(base)[:,:48]==head(model)[:,:48]).all()
            assert base["network"]["b2"][3]==model["network"]["b2"][3]
            assert norm["within_shared_ball"]
            assert np.count_nonzero(head(base)!=head(model))==(3 if b else 0)
            models[a]=model
        models["FULL_BP"]=read(root/"fullbp/run/models"/f"{fit}_full_bp.json.gz")
        assert {a:digest(canonical(m).encode()) for a,m in models.items()}==meta["models"]
        # Independent enumeration at 13 evenly spaced biases on the smallest GEN graph.
        from stop_bias import groups,curve
        item=min(items,key=lambda it:len(it["H"]))
        network_scores=vg.strict_scores(head(base),item["H"])[0]
        ws=groups(item["graph"],network_scores)
        cuts,vals=curve(ws,meta["bound"])
        for b in np.linspace(-.997*meta["bound"],.997*meta["bound"],13):
            rows=head(base).copy()
            rows[:3,48]+=b
            scores=vg.strict_scores(rows,item["H"])[0]
            value=forward_payoff(item["graph"],scores)
            err=abs(vals[np.searchsorted(cuts,b)]-value)
            assert err<1e-9
            sweep_worst=max(sweep_worst,err)
            gen_checks+=1
        for case,r in zip(cases["cases"],records,strict=True):
            assert (case["fit"],case["domain"],case["schedule"])==(r["fit"],r["domain"],r["schedule"])
            if r["fit"]!=fit:
                continue
            assert r["schedule"]==digest(canonical({k:case["public"][k] for k in p["schedule_fields"]}).encode())
            g=vg.build(ctx,case["public"],base,p["state_cap"],lambda:None)
            X,_=vg.semantic_inputs(ctx,case["public"],ctx.NumpyPolicy(base),g["states"],lambda:None)
            for a,m in models.items():
                actual=forward_payoff(g,independent_scores(m,X))
                reported=r["arms"][a]
                delta=abs(actual-reported["utility"])
                assert delta<1e-9 and abs(reported["PDI_residual"])<1e-9 and abs(reported["terminal_mass"]-1)<1e-9
                largest=max(largest,delta)
                counts+=1
    save(run/"VERIFIED.json",dict(values=counts,worlds=len(records),max_forward_difference=largest,
         sweep_checks=gen_checks,max_sweep_difference=sweep_worst,excluded=len(historical),
         scope="independent BLAS forward and payoff accumulation, shares original graph and feature builders",
         cpu_seconds=time.process_time()-start))

if __name__=="__main__":
    main()

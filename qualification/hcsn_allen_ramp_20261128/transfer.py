"""Fixed-parameter cross-stimulus forecast on eight jointly held specimens."""
from collections import defaultdict
import json
from pathlib import Path

import h5py
import numpy as np

from acquire import get, window
from forecast import DT, ROOT, Model, predict, put, score, sha, summarize
from hard_lif import OpenLoop, evaluate


def pack(path, arrays):
    if not path.exists():
        np.savez_compressed(path, **arrays)
    with np.load(path) as z:
        assert set(z.files)==set(arrays) and all(np.array_equal(z[k],v) for k,v in arrays.items())


def main():
    root=ROOT/"transfer"
    root.mkdir(exist_ok=True)
    held=json.loads((ROOT/"source/cohort.json").read_text())["held"]
    seal=json.loads((ROOT/"results/seal.json").read_text())["models"]
    hard=json.loads((ROOT/"hard-lif/seal.json").read_text())["selected"]
    model=Model(ROOT/"source",ROOT/"law4.npz")
    lif=OpenLoop()
    queries={};excluded={};roster={};records=[];scores={};post={};outputs={}
    for sid in held:
        qname=f"rma-{sid}.json"
        query=("model::EphysSweep,rma::criteria,[specimen_id$eq"+str(sid)+
               "],[stimulus_name$eq'Long Square'],rma::options[only$eq'id,specimen_id,sweep_number,stimulus_duration,stimulus_start_time,stimulus_name,stimulus_absolute_amplitude'][num_rows$eqall]")
        page=get(query,root/qname);assert len(page["msg"])==page["total_rows"]
        queries[qname]=sha(root/qname)
        groups=defaultdict(list)
        for v in page["msg"]:
            amp=v["stimulus_absolute_amplitude"]
            if amp is not None and amp>0:
                groups[amp].append(v)
        amplitudes=sorted(groups)
        if not amplitudes:
            excluded[str(sid)]=["no positive amplitude"];continue
        chosen=sorted(set(amplitudes[round(q*(len(amplitudes)-1))] for q in (.25,.5,.75)))
        rows=[min(groups[amp],key=lambda s:s["sweep_number"]) for amp in chosen]
        fpath=ROOT/"source"/str(sid)/"source.nwb"
        rec=json.loads((fpath.parent/"attempt-v2.json").read_text())
        assert sha(fpath)==rec["nwb_sha256"]
        roster[str(sid)]=dict(nwb_sha256=rec["nwb_sha256"],all_positive_amplitudes=amplitudes,selected=rows,source_url=rec["source_url"])
        with h5py.File(fpath) as f:
            for row in rows:
                try:
                    info,orig,times,y,x=window(f,row,"long square")
                    if np.median(x)<=0:raise ValueError("selected command lacks a positive median recorded current")
                except (OSError,ValueError,KeyError,IndexError,AssertionError) as exc:
                    excluded.setdefault(str(sid),[]).append([row["sweep_number"],str(exc)]);continue
                sw=row["sweep_number"];trace=(sid,sw,x.astype(float),y)
                pred={arm:predict(model,trace,b["selected"]) for arm,b in seal.items()}
                _,hard_outputs=evaluate(lif,[trace],hard);p,events=hard_outputs[f"{sid}-{sw}"];pred["hard"]=p
                i=np.flatnonzero(y);start=i[0]+1 if len(i) else len(y)
                for arm,p in pred.items():
                    s=score(p,y);scores.setdefault(arm,{}).setdefault(sid,np.zeros(6));scores[arm][sid]+=s
                    post.setdefault(arm,{}).setdefault(sid,np.zeros(6))
                    if start<len(y):post[arm][sid]+=score(p[start:],y[start:])
                arrays={"native_current":orig,"bin_current_pA":x,"official_spike_times_s":times,"counts":y,"hard_events":events,**pred}
                target=root/f"cell-{sid}-{sw}.npz";pack(target,arrays);outputs[target.name]=sha(target)
                records.append(info)
    if not scores:raise ValueError("no scored exposures "+repr(excluded))
    ids=[sid for sid in held if sid in scores["dual"]]
    draws=np.random.default_rng(950187).integers(0,len(ids),(10000,len(ids)))
    metrics={a:summarize(v) for a,v in scores.items()}
    paired={}
    def per(a):
        v=np.asarray([scores[a][sid] for sid in ids])
        return np.stack((v[:,0]/(v[:,3]*DT),v[:,1]/v[:,3],v[:,2]/v[:,5]),1)
    for arm in metrics:
        if arm=="dual":continue
        d=per("dual")-per(arm);paired[arm]=dict(delta=d.mean(axis=0).tolist(),specimen95=np.quantile(d[draws].mean(1),[.025,.975],axis=0).T.tolist())
    recurring={}
    for arm in metrics:
        arr=np.asarray(list(post[arm].values()));pool=arr.sum(0);active=arr[:,3]>0
        recurring[arm]=dict(occupied=int(pool[4]),seconds=pool[3]*DT,nll_per_second_pooled=pool[0]/(pool[3]*DT) if pool[3] else None,exposed_specimens=int(active.sum()),mean_exposed_specimen_nll_per_second=float(np.mean(arr[active,0]/(DT*arr[active,3]))) if active.any() else None)
    result=dict(held_roster=held,scored_specimens=ids,records=records,selected_sweeps=roster,failed=excluded,rma_pages=queries,
        probabilities_and_native_inputs=outputs,source_seals=[sha(ROOT/"results/seal.json"),sha(ROOT/"hard-lif/seal.json")],protocol_sha256=sha(ROOT/"TRANSFER.md"),
        metrics_order=["mean_specimen_nll_per_s","mean_specimen_brier","mean_specimen_censored_onset_nll"],metrics=metrics,paired_dual_minus=paired,
        sweeps=len(records),physiological_seconds=DT*sum(r["bins"] for r in records),spikes=sum(r["observed_spikes"] for r in records),occupied=sum(r["occupied_bins"] for r in records),
        silent_sweeps=sum(r["observed_spikes"]==0 for r in records),recurrent=recurring)
    put(root/"terminal.json",result);print(result["sweeps"],result["spikes"],metrics,flush=True)


if __name__=="__main__":
    main()

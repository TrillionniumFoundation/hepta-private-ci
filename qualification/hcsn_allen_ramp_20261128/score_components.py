"""Descriptive exposure, calibration and early-window diagnostics for recorded ramp truncation."""
import json
import numpy as np
from forecast import ROOT,DT,score,sha,put
def main():
    src=ROOT/"source";cohort=json.loads((src/"cohort.json").read_text());dest=ROOT/"results";end=json.loads((dest/"terminal.json").read_text())
    arms=list(end["metrics"]);result={};coverage={}
    for a in arms:
        components={};early={h:{} for h in (1.,2.)};num=den=pred_total=0.
        for sid in cohort["held"]:
            f=src/str(sid);rec=json.loads((f/"attempt-v2.json").read_text());terms=np.zeros(8)
            with np.load(f/"signals-v2.npz") as arrays:
                for i,row in enumerate(rec["sweeps"]):
                    sw=row["row"]["sweep_number"];y=arrays[f"occupied_counts_{i}"]>0
                    n=f"{a}-{sid}-{sw}.npz";assert sha(dest/n)==end["raw_probability_files"][n]
                    with np.load(dest/n) as arch:p=arch["probability"]
                    ev=np.flatnonzero(y);j=(int(ev[0])+1) if len(ev) else len(y)
                    event=-np.log(p[y]).sum();survival=-np.log1p(-p[~y]).sum()
                    post=score(p[j:],y[j:]) if j<len(y) else np.zeros(6)
                    terms+=np.array([event,survival,p.sum(),y.sum(),len(y),post[0],post[3],post[4]])
                    for h in early:
                        k=min(len(y),int(h/DT));v=score(p[:k],y[:k]);key=(a,h)
                        early[h][sid]=early[h].get(sid,np.zeros(6))+v
            components[str(sid)]=terms.tolist()
        vals=np.array(list(components.values()));total=vals.sum(0)
        result[a]=dict(raw_sums=components,event_nll_fraction=float(total[0]/(total[0]+total[1])),predicted_occupied_bins=float(total[2]),observed_occupied_bins=int(total[3]),
            predicted_observed_count_ratio=float(total[2]/total[3]),post_first_nll_per_at_risk_second=float(total[5]/(DT*total[6])) if total[6] else None,
            post_first_occupied_bins=int(total[7]),post_first_exposure_s=float(DT*total[6]),
            early_mean_specimen_nll_per_s={str(h):float(np.mean([v[0]/(v[3]*DT) for v in rows.values()])) for h,rows in early.items()})
    trial=end["records"];coverage={str(h):sum(r["bins"]*DT>=h for r in trial) for h in (1.,2.)}
    put(ROOT/"score_components.json",dict(terminal_sha256=sha(dest/"terminal.json"),fully_observed_early_window_trials=coverage,cell_sums_columns=["event_nll","silent_nll","predicted_occupied","observed_occupied","bins","postfirst_nll","postfirst_bins","postfirst_occupied"],models=result))
if __name__=="__main__":main()

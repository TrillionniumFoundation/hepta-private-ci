"""After the sealed score, compare official event locations with local voltage peaks in original NWBs."""
import json
from pathlib import Path
import h5py,numpy as np
from acquire import scalar,version
from forecast import ROOT,put,sha
def main():
    src=ROOT/"source";cohort=json.loads((src/"cohort.json").read_text());out={};overall=[]
    assert (ROOT/"results/seal.json").exists()
    for sid in cohort["train"]+cohort["dev"]+cohort["held"]:
        fold=src/str(sid);receipt=json.loads((fold/"attempt-v2.json").read_text());assert sha(fold/"source.nwb")==receipt["nwb_sha256"]
        hits=[]
        with h5py.File(fold/"source.nwb") as f,np.load(fold/"signals-v2.npz") as compact:
            for i,rec in enumerate(receipt["sweeps"]):
                sw=rec["row"]["sweep_number"];rate=rec["rates_hz"];orig=f[f"acquisition/timeseries/Sweep_{sw}/data"];scale=float(scalar(orig.attrs["conversion"])) if version(f)>=(1,1) else 1.
                peaks=[]
                for when in compact[f"spike_times_s_{i}"]:
                    idx=round((when+rec["start_s"])*rate);start=max(0,idx-round(rate*.001));stop=min(len(orig),idx+round(rate*.003)+1)
                    peaks.append(float(np.max(orig[start:stop])*scale*1e3))
                hits.extend(peaks);overall.extend(peaks)
        out[str(sid)]={"spikes":len(hits),"peaks_above_0_mV":sum(z>0 for z in hits),"median_local_peak_mV":float(np.median(hits)) if hits else None}
    put(ROOT/"voltage_alignment.json",dict(window_ms=[-1,3],specimens=out,total=len(overall),above_zero_mV=sum(z>0 for z in overall),median_mV=float(np.median(overall))))
if __name__=="__main__":main()

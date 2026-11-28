"""Acquire public Allen RMA provenance, native current samples and official spike times for disjoint ramps."""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import h5py
import numpy as np
ROOT=Path(__file__).resolve().parent
API="https://api.brain-map.org/api/v2/"
def digest(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def put(path,obj):
    b=(json.dumps(obj,sort_keys=True,indent=1,allow_nan=False)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=b:raise ValueError("existing bytes differ: "+str(path))
        return
    temp=path.with_suffix(path.suffix+".tmp");temp.write_bytes(b);temp.replace(path)
def get(q,path):
    if not path.exists():
        url=API+"data/query.json?criteria="+urllib.parse.quote(q)
        with urllib.request.urlopen(url,timeout=75) as response:raw=response.read()
        if not json.loads(raw)["success"]:raise ValueError("RMA unsuccessful")
        path.write_bytes(raw)
    return json.loads(path.read_bytes())
def label(value):return value.decode().lower() if isinstance(value,bytes) else str(value).lower()
def version(f):
    v=f.get("general/generated_by")
    if v is not None:
        for i in range(0,len(v)-1,2):
            if label(v[i])=="version":
                try:return tuple(map(int,label(v[i+1]).split(".")[:2]))
                except ValueError:pass
    return (0,0)
def window(f,row):
    n=row["sweep_number"];name="Sweep_"+str(n)
    current=f["stimulus/presentation/"+name];voltage=f["acquisition/timeseries/"+name]
    stim=current["data"];v=voltage["data"]
    if label(stim.attrs["unit"]) not in ("amps","ampere","amp","amperes","a"):raise ValueError("non-ampere current")
    if label(v.attrs["unit"]) not in ("volts","volt","v"):raise ValueError("non-volt response")
    if "ramp" not in label(voltage["aibs_stimulus_name"][()]):raise ValueError("not an NWB Ramp")
    dt=current["starting_time"];vr=voltage["starting_time"]
    rate=float(dt.attrs["rate"]);t0=float(dt[()]);assert abs(float(vr[()])-t0)<1e-7 and abs(rate-float(vr.attrs["rate"]))<1e-5
    width=round(rate*.002)
    if rate<10000 or abs(width-rate*.002)>1e-6:raise ValueError("sample rate")
    exp=f.get(f"epochs/Experiment_{n}/stimulus")
    if exp is None:raise ValueError("no experimental sampling interval")
    ra=int(exp["idx_start"][()]);rb=ra+int(exp["count"][()])
    start=max(ra,round((row["stimulus_start_time"]-t0)*rate))
    stop=min(rb,len(v),len(stim),round((row["stimulus_start_time"]-t0+row["stimulus_duration"])*rate),start+round(30*rate))
    bins=(stop-start)//width
    if bins<10:raise ValueError("insufficient complete observation")
    stop=start+bins*width
    sp=None;spikey=None
    for key in ("spike_times","aibs_spike_times"):
        path=f"analysis/{key}/{name}"
        if path in f:sp=np.asarray(f[path],dtype=np.float64);spikey=path;break
    if sp is None:raise ValueError("no explicit official spike-time dataset")
    if not np.all(np.isfinite(sp)) or not np.all(np.diff(sp)>0):raise ValueError("invalid official spikes")
    orig=np.asarray(stim[start:stop]);converted=version(f)>=(1,1);scale=(float(stim.attrs["conversion"]) if converted else 1.)*1e12
    x=np.mean(orig.astype(float).reshape(bins,width),axis=1)*scale
    if not np.isfinite(x).all() or np.ptp(x)<=0 or abs(x).max()>5000:raise ValueError("invalid sampled current")
    lo=t0+start/rate;hi=t0+stop/rate;times=sp[(sp>=lo)&(sp<hi)]-lo
    indices=np.floor(times/.002).astype(int)
    if np.any(indices<0) or np.any(indices>=bins):raise ValueError("time alignment at bin edge")
    counts=np.bincount(indices,minlength=bins).astype(np.uint16)
    info=dict(row=row,spike_dataset=spikey,rates_hz=rate,original_epoch=[ra,rb],native_samples=[start,stop],start_s=lo,end_s=hi,
              bin_seconds=.002,current_multiplier_pA=scale,version=version(f),current_min_max_pA=[float(x.min()),float(x.max())],
              original_dtype=str(orig.dtype),bins=bins,native_dtype_bytes=orig.nbytes,observed_spikes=len(times),occupied_bins=int((counts>0).sum()))
    return info,orig,times,counts,x.astype(np.float32)
def acquire_cell(sid,rows):
    folder=ROOT/"source"/str(sid);folder.mkdir(parents=True,exist_ok=True)
    result=folder/"attempt.json"
    if result.is_file():return json.loads(result.read_text())
    q=f"model::Specimen,rma::criteria,[id$eq{sid}],rma::include,ephys_result(well_known_files(well_known_file_type))"
    spec=get(q,folder/"specimen.json")["msg"][0];files=[x for x in spec["ephys_result"]["well_known_files"] if x["well_known_file_type"]["name"]=="NWBDownload"]
    if len(files)!=1:raise ValueError("NWB multiplicity")
    obj=files[0];url="https://api.brain-map.org"+obj["download_link"]
    nwb=folder/"source.nwb";partial=folder/"source.partial"
    if not nwb.exists():
        retry=None
        for attempt in range(3):
            try:
                expected=None
                with urllib.request.urlopen(url,timeout=100) as res,partial.open("wb") as f:
                    if "content-length" in res.headers:expected=int(res.headers["content-length"])
                    while v:=res.read(1048576):f.write(v)
                if expected is not None and partial.stat().st_size!=expected:raise IOError("incomplete NWB")
                with h5py.File(partial):pass
                partial.replace(nwb);break
            except (OSError,ValueError) as e:
                retry=e;time.sleep(1+attempt)
        if not nwb.exists():raise RuntimeError("transfer exhausted "+str(retry))
    payload={};kept=[];failed=[]
    with h5py.File(nwb) as f:
        for row in sorted(rows,key=lambda x:x["sweep_number"]):
            try:info,orig,times,counts,x=window(f,row)
            except (OSError,ValueError,KeyError,IndexError,AssertionError) as e:
                failed.append([row["sweep_number"],type(e).__name__+": "+str(e)]);continue
            i=len(kept);payload[f"stimulus_native_{i}"]=orig;payload[f"spike_times_s_{i}"]=times
            payload[f"occupied_counts_{i}"]=counts;payload[f"current_bin_pA_{i}"]=x
            kept.append(info)
            if len(kept)==3:break
    out=folder/"signals.npz"
    if len(kept)>=2:np.savez_compressed(out,**payload)
    summary=dict(specimen=sid,source_id=obj["id"],source_url=url,nwb_sha256=digest(nwb),nwb_bytes=nwb.stat().st_size,
                 accepted=len(kept)>=2,sweeps=kept,skips=failed,signals_sha256=digest(out) if out.exists() else None)
    put(result,summary);return summary
def main():
    src=ROOT/"source";src.mkdir(exist_ok=True)
    rows=[];total=1;offset=0
    while offset<total:
        q="model::EphysSweep,rma::criteria,[stimulus_name$eq'Ramp'],rma::options[only$eq'id,specimen_id,sweep_number,stimulus_duration,stimulus_start_time,stimulus_name,stimulus_absolute_amplitude'][order$eq'ephys_sweeps.specimen_id,ephys_sweeps.sweep_number,ephys_sweeps.id'][num_rows$eq1000][start_row$eq"+str(offset)+"]"
        page=get(q,src/f"page-{offset}.json");total=page["total_rows"];rows+=page["msg"];offset+=1000
    excluded=set(json.loads((ROOT/"excluded_specimens.json").read_text()))
    grouped=defaultdict(list)
    for row in rows:
        if row["specimen_id"] not in excluded and row["stimulus_duration"] is not None and row["stimulus_start_time"] is not None:grouped[row["specimen_id"]].append(row)
    order=sorted((sid for sid,v in grouped.items() if len(v)>=2),key=lambda n:hashlib.sha256(("hepta-9de7-ramp-v1/"+str(n)).encode()).hexdigest())
    put(src/"ranked_specimens.json",order)
    kept=[];attempts=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for step in range(0,len(order),4):
            jobs=[(sid,pool.submit(acquire_cell,sid,grouped[sid])) for sid in order[step:step+4]]
            for sid,job in jobs:
                r=job.result();attempts.append(sid)
                if r["accepted"] and len(kept)<24:kept.append(sid)
                print("source",sid,r["accepted"],len(r["sweeps"]),"eligible",len(kept),r["nwb_bytes"],r["skips"][:1],flush=True)
            if len(kept)==24:break
    assert len(kept)==24
    put(src/"cohort.json",dict(source_rows=len(rows),eligible_roster=len(order),excluded=len(excluded),attempts=attempts,train=kept[:12],dev=kept[12:16],held=kept[16:24],input_hashes={str(sid):digest(src/str(sid)/"signals.npz") for sid in kept},protocol_sha256=digest(ROOT/"PROTOCOL.md")))
if __name__=="__main__":main()

"""Independent longer observation window and never-screened intermediate gains."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.signal import find_peaks
from simulate import evolve,period

def run(out):
    cases=[(law,g,1.5*g,.05) for law in (0,1,2) for g in (0,64,80,96,112,128)]
    results={};signals={};stats={}
    for sign in (-1,1):
        lanes,data=evolve(cases,sign,8192,4096);stats[str(sign)]=data
        for case,v in zip(cases,lanes):
            law,g,_,_=case;label=['fixed','tangent','literal'][law]+'_'+str(g);key=label+'_sign'+str(sign)
            peaks,_=find_peaks(v,prominence=.01,distance=8)
            amps=np.array([np.ptp(q) for q in np.array_split(v,4)])
            sep=np.diff(peaks);cv=float(sep.std()/sep.mean()) if len(sep) else None
            ratio=float(amps.max()/amps.min()) if amps.min()>1e-15 else None
            qualify=bool(len(peaks)>=20 and cv<.05 and np.ptp(v)>.02 and ratio is not None and ratio<1.10)
            results.setdefault(label,{})[str(sign)]=dict(regular=qualify,integer_period=period(v),peaks=peaks.tolist(),
                  interpeak_mean=float(sep.mean()) if len(sep) else None,interpeak_cv=cv,amplitude=float(np.ptp(v)),quarter_amplitude_ratio=ratio,
                  mean_flux=float(v.mean()),min=float(v.min()),max=float(v.max()))
            signals[key]=v
    np.savez_compressed(out/'long_traces.npz',**signals)
    (out/'long_results.json').write_text(json.dumps({'both_signs_match':{k:all(m['regular'] for m in v.values()) for k,v in results.items()},
          'rows':results,'mass':stats},indent=1,allow_nan=False)+'\n')
    print('passed',sum(all(m['regular'] for m in v.values()) for v in results.values()),'of',len(cases))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();run(a.out)

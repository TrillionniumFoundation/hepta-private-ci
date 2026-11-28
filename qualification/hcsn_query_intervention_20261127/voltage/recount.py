"""Re-derive every event label from sparse source times and macro scores from FP32 messages."""
import argparse
import json
from pathlib import Path
import numpy as np

def run(data,predictions):
    scores=json.loads((predictions/'results.json').read_text())['by_waveform'];out={};largest=0.
    for typ in ('1','2'):
        by={};n=0;events=0
        for path in sorted(predictions.glob(f'*_{typ}_*.npz')):
            sid,protocol,rep,h=path.stem.split('_');h=int(h)
            if protocol != typ:continue
            with np.load(path) as z,np.load(data/(sid+'.npz')) as origin:
                i=z['anchors'];y=origin['y'+typ+'_'+rep]
                rebuilt=np.logical_or.reduce([y[i+j] for j in range(h)]);assert np.array_equal(rebuilt,z['y'])
                past=origin['v'+typ+'_'+rep][i]
                assert np.all(past < -25.) and not np.any(y[i-1]) and not np.any(y[i-2])
                for name in scores[typ]['averages']:
                    assert z[name].dtype==np.float32
                    f=np.clip(z[name].astype(np.float64),1e-7,1.-1e-7)
                    ll=-np.where(rebuilt,np.log(f),np.log1p(-f)).mean()
                    b=np.square(f-rebuilt).mean()
                    by.setdefault(name,{}).setdefault(sid,[]).append([ll,b])
                n+=len(i);events+=int(rebuilt.sum())
        for name,cells in by.items():
            for sid,val in cells.items():
                val=np.mean(val,axis=0);want=np.array(scores[typ]['individual'][name][sid])
                largest=max(largest,float(np.max(abs(val-want))))
        out[typ]=dict(queries=n,positive_queries=events)
    return {'scopes':out,'max_per_cell_absolute_NLL_or_Brier_difference':largest}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('predictions',type=Path);a=p.parse_args()
    print(json.dumps(run(a.data,a.predictions),indent=1))

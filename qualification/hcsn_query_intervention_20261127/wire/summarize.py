"""Aggregate independent socket measurements while preserving every raw run."""
import json
from pathlib import Path
import numpy as np

def summarize(root):
    data=json.loads((root/'raw.json').read_text());assert len(data)==120
    output={}
    for key in sorted({(r['mode'],r['parameter']) for r in data}):
        sub=[r for r in data if (r['mode'],r['parameter'])==key]
        assert len(sub)==6 and len({r['two_way_bytes'] for r in sub})==1 and all(r['source']['pid']!=r['sink']['pid'] for r in sub)
        one=sub[0];d={'two_way_bytes':one['two_way_bytes'],'source_tx':one['source']['tx'],'source_rx':one['source']['rx'],'source_application_sends':one['source']['application_sends']}
        for metric in ('queries','max_abs','p99_abs','rmse','mae','nll_brier','delta_nll_brier','event_counts_by_lane'):
            if metric in one:d[metric]=one[metric]
        d['transports']={}
        for transport in ('unix','tcp'):
            rows=[r for r in sub if r['transport']==transport]
            d['transports'][transport]={'wall_s_median_range':np.quantile([r['wall'] for r in rows],[.5,0,1]).tolist(),
                  'source_cpu_s_median_range':np.quantile([r['source']['cpu'] for r in rows],[.5,0,1]).tolist(),
                  'sink_cpu_s_median_range':np.quantile([r['sink']['cpu'] for r in rows],[.5,0,1]).tolist()}
            if 'per_rtt_us' in one:d['transports'][transport]['median_of_RTT_p50_p95_p99_microseconds']=np.median([r['per_rtt_us'] for r in rows],axis=0).tolist()
        output[key[0]+'_'+str(key[1])]=d
    return output
if __name__=='__main__':
    root=Path(__file__).resolve().parent
    (root/'summary.json').write_text(json.dumps(summarize(root),indent=1,allow_nan=False)+'\n')

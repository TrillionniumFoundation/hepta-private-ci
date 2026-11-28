"""Open the two sealed evaluation shards only after all parameter estimates and choices are bound."""
import argparse
import json
from pathlib import Path
import numpy as np

from isi_likelihood import ARMS,PANELS,RiskSet,contributions
from prepare_isi import sha,write_once


def cold(data_dir,selection_file,output):
    model=json.loads(selection_file.read_bytes())
    src=Path(__file__).resolve().parent
    for name,origin in model['source_sha256'].items():assert sha((src/name).read_bytes())==origin
    assert model['cohort_seal_sha256']==sha((data_dir/'cohort_seal.json').read_bytes())
    parts={}
    for group in ('new_cell','new_current'):
        raw=(data_dir/(group+'.json')).read_bytes()
        assert sha(raw)==model['external_shard_sha256_anticipated_from_cohort_seal'][group]
        rows=json.loads(raw);data=RiskSet.build(rows)
        outrows=[{'cell':r['cell'],'row_id':r['row_id'],'sweep':r['sweep'],'current_pA':r['current'],
                  'pulse_length_s':r['duration'],'first_spike_s':r['spikes_s'][0] if r['spikes_s'] else None,
                  'observed_spikes':len(r['spikes_s']),'renewals_scored':max(0,len(r['spikes_s'])-1),
                  'exposure_after_first_s':float(data.exposure[i]),'ll':{}} for i,r in enumerate(rows)]
        for panel,(dead,_) in PANELS.items():
            failed=set(data.row[data.event & (data.interval<=dead)].tolist())
            idx=[j for j in range(len(rows)) if j not in failed]
            sub=RiskSet.build([rows[j] for j in idx]) if failed else data
            for r in outrows:r['ll'][panel]={}
            for arm in ARMS:
                fit=model['panels'][panel]['arms'][arm]['refit']
                for r in outrows:r['ll'][panel][arm]=None
                if fit['status']!='finite':continue
                vals=contributions(sub,arm,fit['params'],panel)
                totals=np.bincount(sub.row,weights=vals,minlength=len(idx))
                for j,v in zip(idx,totals):outrows[j]['ll'][panel][arm]=float(v)
        parts[group]=outrows
    packet={'selection_seal_sha256':sha(selection_file.read_bytes()),
            'cohort_seal_sha256':model['cohort_seal_sha256'],'groups':parts}
    write_once(output,packet)
    print('cold receipts',sha(output.read_bytes()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('selection',type=Path)
    p.add_argument('output',type=Path);a=p.parse_args();cold(a.data,a.selection,a.output)

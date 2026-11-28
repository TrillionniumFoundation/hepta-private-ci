"""Independently aggregate the portable per-sweep cold scores, paired by specimen."""
import argparse,json,math
from pathlib import Path
import numpy as np
from prepare_isi import sha,write_once


def replay(weights,record):
    fitted=json.loads(weights.read_bytes());raw=json.loads(record.read_bytes())
    assert sha(weights.read_bytes())==raw['selection_seal_sha256']
    groups={}
    for group,rows in raw['groups'].items():
        ids=sorted({r['cell'] for r in rows})
        exps=np.array([sum(r['exposure_after_first_s'] for r in rows if r['cell']==s) for s in ids])
        live=np.flatnonzero(exps>0)
        counts=np.array([sum(r['renewals_scored'] for r in rows if r['cell']==s) for s in ids])
        assert len(live)>0
        draws=np.random.default_rng(534677).integers(len(live),size=(10000,len(live)))
        stats={}
        for panel,model in fitted['panels'].items():
            cell_ll={};means={};unsupported={}
            for arm,fit in model['arms'].items():
                absent=[(r['cell'],r['sweep']) for r in rows if r['ll'][panel][arm] is None]
                if absent:
                    unsupported[arm]=absent
                    continue
                ll=np.array([sum(r['ll'][panel][arm] for r in rows if r['cell']==s) for s in ids])
                cell_ll[arm]=ll
                means[arm]=float(np.mean(-ll[live]/exps[live]))
            chosen,comparator=model['chosen_multi'],model['chosen_control']
            def pair(a,b):
                delta=cell_ll[a][live]-cell_ll[b][live]
                per=delta/exps[live]
                bounds=np.quantile(per[draws].mean(axis=1),[.025,.975]).tolist()
                return {'gain_nats_per_second_cell_mean':float(per.mean()),
                        'paired_cell_95':bounds,
                        'pooled_bits_per_observed_subsequent_spike':float(delta.sum()/(counts[live].sum()*math.log(2))),
                        'specimen_wins_ties_losses':[int((per>0).sum()),int((per==0).sum()),int((per<0).sum())],
                        'cells':{str(ids[i]):float(x) for i,x in zip(live,per)}}
            primary=pair(chosen,comparator) if chosen in cell_ll and comparator in cell_ll else None
            stats[panel]={'chosen_multi':chosen,'chosen_conventional':comparator,'per_arm_loss_nats_per_second':means,
                          'unsupported_or_unfitted':unsupported,'selected_comparison':primary,
                          'versus_all_controls':{b:pair(chosen,b) for b in ('ig1','gamma','lognormal','exponential')
                                                 if chosen in cell_ll and b in cell_ll}}
        groups[group]={'cells_in_roster':len(ids),'cells_with_post_first_exposure':len(live),
                       'zero_exposure_cells':[s for s,v in zip(ids,exps) if v==0],
                       'sweeps':len(rows),'zero_spike_sweeps':sum(r['observed_spikes']==0 for r in rows),
                       'one_spike_sweeps':sum(r['observed_spikes']==1 for r in rows),
                       'observed_followup_spikes':int(counts.sum()),'total_exposure_s':float(exps.sum()),'panels':stats}
    ok=all(g['panels']['stationary']['selected_comparison'] is not None and
           g['panels']['stationary']['selected_comparison']['paired_cell_95'][0]>0 for g in groups.values())
    return {'selection_seal_sha256':sha(weights.read_bytes()),'cold_score_sha256':sha(record.read_bytes()),
            'random_seed':534677,'bootstrap_replicates':10000,
            'positive_lower_limits_for_both_primary_endpoints':ok,'groups':groups}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('selection',type=Path);p.add_argument('scores',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();r=replay(a.selection,a.scores);write_once(a.output,r)
    for g,record in r['groups'].items():
        for k,v in record['panels'].items():
            x=v['selected_comparison']
            print(g,k,v['chosen_multi'],v['chosen_conventional'],None if x is None else
                  [x['gain_nats_per_second_cell_mean'],x['paired_cell_95'],x['pooled_bits_per_observed_subsequent_spike']])

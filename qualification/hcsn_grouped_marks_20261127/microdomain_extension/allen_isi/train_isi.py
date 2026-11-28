"""Fit and select using two checksum-verified exposed shards, then seal every parameter group."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from isi_likelihood import ARMS,CONTROLS,MULTI,PANELS,RiskSet,score,starts_and_bounds
from prepare_isi import sha,write_once


def optimize(data,arm,panel):
    starts,bounds=starts_and_bounds(arm,panel)
    attempts=[]
    if np.any(data.event & (data.interval<=PANELS[panel][0])):
        return {'status':'training_support_violation','attempts':[]}
    for x in starts:
        begin=time.perf_counter()
        def fun(v):
            try:return score(data,arm,v,panel)
            except (ValueError,FloatingPointError,OverflowError):return 1e80
        result=minimize(fun,x,method='L-BFGS-B',bounds=bounds,
                        options={'maxiter':450,'ftol':1e-12,'gtol':1e-7,'maxls':40})
        value=float(result.fun);params=result.x.tolist()
        assert all(np.isfinite(params))
        attempts.append({'params':params,'objective':value,'success':bool(result.success),'status':int(result.status),
                         'message':str(result.message),'evaluations':int(result.nfev),'iterations':int(result.nit),
                         'wall_s':time.perf_counter()-begin})
    usable=[a for a in attempts if np.isfinite(a['objective']) and a['objective']<1e79]
    if not usable:return {'status':'no_finite_fit','attempts':attempts}
    winner=min(usable,key=lambda a:a['objective'])
    return {'status':'finite','params':winner['params'],'objective':winner['objective'],
            'successful_optimizer_termination':winner['success'],'attempts':attempts}


def main(data_dir,out):
    seal=json.loads((data_dir/'cohort_seal.json').read_bytes())
    sets={}
    for key in ('training','development'):
        raw=(data_dir/(key+'.json')).read_bytes()
        assert sha(raw)==seal['shards'][key]
        sets[key]=json.loads(raw)
    fitting=RiskSet.build(sets['training']);selection=RiskSet.build(sets['development'])
    refitting=RiskSet.build(sets['training']+sets['development'])
    panels={};start=time.perf_counter()
    for panel in PANELS:
        arms={};validation_supported=not np.any(selection.event & (selection.interval<=PANELS[panel][0]))
        for arm in ARMS:
            train=optimize(fitting,arm,panel)
            val=score(selection,arm,train['params'],panel) if train['status']=='finite' and validation_supported else None
            final=optimize(refitting,arm,panel)
            arms[arm]={'training':train,'development_loss':val,'refit':final}
        if all(a['refit']['status']=='finite' and a['development_loss'] is not None for a in arms.values()):
            chosen_multi=min(MULTI,key=lambda a:arms[a]['development_loss'])
            chosen_control=min(CONTROLS,key=lambda a:arms[a]['development_loss'])
        else:chosen_multi=chosen_control=None
        panels[panel]={'arms':arms,'chosen_multi':chosen_multi,'chosen_control':chosen_control,
                       'valid_on_development_support':bool(validation_supported)}
        print(panel,chosen_multi,chosen_control,flush=True)
    src=Path(__file__).resolve().parent
    record={'cohort_seal_sha256':sha((data_dir/'cohort_seal.json').read_bytes()),
            'input_training_and_development':{k:seal['shards'][k] for k in sets},
            'external_shard_sha256_anticipated_from_cohort_seal':{k:seal['shards'][k] for k in ('new_cell','new_current')},
            'source_sha256':{n:sha((src/n).read_bytes()) for n in
                ('PROTOCOL.md','prepare_isi.py','isi_likelihood.py','train_isi.py','score_isi.py','replay_isi.py')},
            'panels':panels,'training_wall_s':time.perf_counter()-start,
            'coverage_fitting':{key:{'sweeps':len(d.rows),'post_first_exposure_s':float(d.exposure.sum()),
                                      'observed_subsequent_spikes':int(d.event.sum())}
                                for key,d in [('train',fitting),('development',selection),('refit',refitting)]}}
    write_once(out,record)
    print('selection seal',sha(out.read_bytes()),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();main(a.data,a.output)

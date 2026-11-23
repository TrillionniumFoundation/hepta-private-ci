"""Replay the sealed 66 legacy heads on the new split and compare old decisions."""
import argparse
from pathlib import Path
import time
import numpy as np
import torch
from qualification.hcsn_intervention_value import independent, run
from .experiment import digest, panel, read, write


def evaluate(data, old, policies):
    run.init()
    seal=run.check_seal(policies)
    m=read(policies/'prepare/metadata.json')
    previous_table=independent.CausalChooser.from_state_dict(read(old/'chooser.json'))
    previous_choice=read(old/'frontend_seal.json')['immediate_baseline']
    out={}
    with torch.inference_mode():
        for avail in run.AVAIL:
            can_read=avail=='read'
            teacher=read(policies/'prepare'/(avail+'.json'))
            inputs=run.frontend(data.copy(),m,teacher)
            for seed in run.SEEDS:
                for mode, method in run.ARMS:
                    name=f'{avail}-{mode}-{method}-{seed}'
                    params=read(policies/'fit'/(name+'.json'))
                    model=run.representation(mode,seed,len(m['mu']))
                    get=run.features(model,mode,can_read)
                    theta=torch.as_tensor(params['theta'],dtype=torch.float64)
                    head=torch.as_tensor(params['head'],dtype=torch.float64)
                    q=run.predict(get(theta,inputs),head).numpy()
                    out[name]=run.score(q,inputs,can_read)
    return {'old_seal':seal,'old_table':independent.evaluate(previous_table,data,stage='confirmation',immediate_baseline=previous_choice),
            'opportunity':independent.opportunity(data),'old_heads':out}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path);p.add_argument('old',type=Path);p.add_argument('policies',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args()
    # The follow-up selection is complete and confirmation has already been allowed.
    signed=read(a.output/'test.json')
    t=time.perf_counter()
    data,h=panel(a.root,a.old,'test')
    if h!=signed['test_inputs'] or digest(a.output/'seal.json')!=signed['seal']:
        raise ValueError('new test panel differs')
    record=evaluate(data,a.old,a.policies)
    record['wall_seconds']=time.perf_counter()-t
    write(a.output/'incumbents.json',record)

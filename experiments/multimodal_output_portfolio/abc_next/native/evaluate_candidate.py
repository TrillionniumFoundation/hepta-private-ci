"""Measure generated head perturbations on already observed development data.

This is deliberately ineligible for independent acceptance. It supplies actual
evaluation bytes to the authority-free proposal record, never invented passing
evaluation facts to the authenticated product path.
"""

import argparse
import copy
import json
from pathlib import Path
import time

import numpy as np

from ...abc_recovery.training_run import file_sha,write_json
from .qualify import load_data,raw_prediction,metrics


def evaluate(candidates,model,data,output):
    started=time.perf_counter_ns()
    generation=json.loads(candidates.read_text());weights=json.loads((model/'weights.json').read_text())
    if generation['baseline_weights_sha256']!=file_sha(model/'weights.json'):raise ValueError('Different baseline')
    cal=json.loads((model/'calibration.json').read_text());x,y,group=load_data(data)
    x,y=x[group=='development'],y[group=='development'];base=raw_prediction(weights,x)
    rows=[]
    for candidate in generation['candidates']:
        updated=copy.deepcopy(weights)
        for delta in candidate['deltas']:
            field,index=delta['parameter'].split('.')
            if field!='w2':raise ValueError('Unregistered parameter mutation')
            updated[field][int(index)]+=delta['delta_q32']/2**32
        p=raw_prediction(updated,x)
        summary=metrics(updated,cal,x,y)
        summary.update({'candidate':candidate['id'],'kind':candidate['kind'],
            'raw_probability_change_max':float(np.max(np.abs(p-base))),
            'raw_probability_brier':float(np.mean((p-y)**2)),
            'number_of_parameter_updates':len(candidate['deltas'])})
        rows.append(summary)
    write_json(output,{'schema':'hepta.abc3.local-candidate-evaluation.v1','generator_digest':generation['generator_digest'],
        'candidates_file_sha256':file_sha(candidates),'weights_sha256':file_sha(model/'weights.json'),
        'development_data_sha256':file_sha(data/'features.npz'),'n_development_pairs':len(y),
        'eligible_for_independent_acceptance':False,'development_observed_before_candidate_construction':True,
        'reason':'Original head was selected on this same development set. No independent signed candidate qualification is supplied.',
        'same_local_process_security_domain':True,'rows':rows,'wall_ns':time.perf_counter_ns()-started})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('candidates','model','data','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();evaluate(a.candidates,a.model,a.data,a.output)

"""Measure serial generation and public-feature work omitted by resident-head scope.

This timing replay uses already observed train-development pairs, adds no new
qualification observations, and never changes the frozen predictor.
"""

import argparse
import json
from pathlib import Path
import resource
import time

from ...abc_recovery.training_run import file_sha, write_json


def measure(protocol,output):
    started=time.perf_counter_ns();cpu=time.process_time_ns()
    import numpy as np
    import torch
    from ...v7.sources import load_roles
    from ...v7.snapshot import Snapshot
    from ...v7.data import make_batch
    from ...abc_recovery.runtime import initialize,transition,public_frame
    from .features import features
    spec=json.loads(protocol.read_text());p=spec['paths']
    torch.set_num_threads(1)
    corpus=load_roles(p['cache'],p['manifest'],roles=('train',))
    snapshot=Snapshot.load(p['model'],expected_file_sha256=spec['input_sha256']['model']);model=snapshot._model
    loaded=time.perf_counter_ns();rows=[]
    for pair in range(4000,4128):
        a=time.perf_counter_ns()
        batch=make_batch(corpus,'train',1,spec['seed']+pair,view='clean',offset=pair)
        rng=torch.Generator().manual_seed(spec['seed']+pair+1000000)
        b=time.perf_counter_ns()
        with torch.inference_mode():
            run=initialize(model,batch.observation,generator=rng)
            for action in spec['continuation_actions']:run=transition(model,run,action,generator=rng)
            c=time.perf_counter_ns();x=features(model,public_frame(run),batch.observation);d=time.perf_counter_ns()
        rows.append({'pair':pair,'data_prep_ns':b-a,'generation_ns':c-b,'public_feature_ns':d-c,
                     'serial_generation_plus_features_ns':d-b,'including_input_prep_ns':d-a})
    result={'schema':'hepta.abc3.upstream-cost.v1','protocol_sha256':file_sha(protocol),
        'n_serial_requests':len(rows),'new_independent_qualification_samples':0,
        'source':'already observed train-development pairs4000..4127, clean view, serial new emissions for timing only',
        'startup_import_load_ns':loaded-started,'measured_total_wall_ns':time.perf_counter_ns()-started,
        'measured_cpu_ns':time.process_time_ns()-cpu,
        'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'native_head_and_journal_included':False,'raw_media_serialization_included':False,
        'scope_limit':'No end-to-end native owner claim: serial upstream wall is charged separately and must not be substituted with resident-head latency.',
        'rows':rows}
    for field in ('generation_ns','public_feature_ns','serial_generation_plus_features_ns','including_input_prep_ns'):
        v=[r[field] for r in rows];result[field]={'mean':float(np.mean(v)),'p50':float(np.quantile(v,.5)),
                                               'p95':float(np.quantile(v,.95)),'p99':float(np.quantile(v,.99)),'max':max(v)}
    output.parent.mkdir(parents=True,exist_ok=True);write_json(output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},sort_keys=True))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--protocol',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();measure(a.protocol,a.output)

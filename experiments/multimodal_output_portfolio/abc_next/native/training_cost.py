"""Time a deterministic training-only replay including fresh process startup.

The original qualified weights remain selected. This replay reads train only,
does not re-open either reserved role, and must reproduce the original weights.
"""

import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

from ...abc_recovery.training_run import file_sha,write_json


def measure(protocol,original,output):
    started=time.perf_counter_ns();cpu=time.process_time_ns();before=resource.getrusage(resource.RUSAGE_CHILDREN)
    output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[4]
    commands=[
        [sys.executable,'-B','-m','experiments.multimodal_output_portfolio.abc_next.native.collect',
         '--protocol',str(protocol.resolve()),'--role','train','--output',str(output/'data')],
        [sys.executable,'-B','-m','experiments.multimodal_output_portfolio.abc_next.native.qualify','fit',
         '--protocol',str(protocol.resolve()),'--data',str(output/'data'),'--model',str(output/'model')],
    ]
    results=[]
    for i,command in enumerate(commands):
        begin=time.perf_counter_ns()
        with (output/f'child-{i}.log').open('x') as log:
            result=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
        results.append({'command':command,'exit_code':result.returncode,'wall_ns':time.perf_counter_ns()-begin})
        if result.returncode:break
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    matched=(len(results)==2 and all(r['exit_code']==0 for r in results)
             and file_sha(output/'model/weights.json')==file_sha(original/'weights.json')
             and file_sha(output/'model/cuts.json')==file_sha(original/'cuts.json'))
    report={'schema':'hepta.abc3.whole-training-cost-replay.v1','protocol_sha256':file_sha(protocol),
        'whole_pipeline_wall_ns':time.perf_counter_ns()-started,'parent_cpu_ns':time.process_time_ns()-cpu,
        'child_cpu_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        'child_peak_rss_bytes':after.ru_maxrss*1024,'commands':results,
        'original_weights_sha256':file_sha(original/'weights.json'),'weights_and_cuts_reproduced_exactly':matched,
        'reserved_roles_read':[],'new_independent_qualification_samples':0,
        'cost_scope':'two fresh Python processes, imports, original-data verification/loading,6000 real generator+media+observer labels,2000 training updates and development selection,all writes and child exit',
        'not_included':'the previously completed generator training, frozen observer training, calibration/verification, toolchain setup; those are separate retained costs',
        'original_preverification_predictor_remains_selected':True}
    write_json(output/'result.json',report)
    if not matched:raise RuntimeError('Timing replay failed to reproduce the preverification predictor')
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('protocol','original','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();measure(a.protocol,a.original,a.output)

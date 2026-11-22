"""Freeze code, exact GEN prerequisites and all decisions before quality work."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
from data_contract import read,pin,save


def main():
    started=time.process_time()
    old=Path('/workspace/scratch/4b91365ace88/wsp_value_20261121/value')
    prior=Path('/workspace/scratch/267e347691df/advance_20261122/shared_head')
    previous=read(old/'PROTOCOL_FROZEN.json')
    old_main=read(old/'main_attempt001/output/RESULTS.json')
    prior_protocol=read(prior/'PROTOCOL_FROZEN.json')
    previous_worlds=read(prior/'confirmation_attempt001/output/WORLDS_FROZEN.json')
    bundle=ROOT/'input_bundle'
    bundle.mkdir(exist_ok=False)
    inputs=[]
    def retain(source,relative):
        source=Path(source);destination=bundle/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        os.link(source,destination)
        result=pin(destination);result['path']=relative
        result['original_source_pin']=pin(source)
        inputs.append(result)
        return result
    fits={}
    for fit in (11,23,37,53,71):
        source=old_main['fits'][str(fit)]
        model=retain(source['models']['KEEP']['model_pin']['path'],f'models/fit_{fit}.json.gz')
        hidden=retain(source['hidden_pin']['path'],f'hidden/fit_{fit}.npz')
        manifest=read(source['graph_manifest_pin']['path'])
        mapping={x['world_index']:x for x in manifest['graphs']}
        graphs=[]
        for i in previous['splits'][str(fit)]['GEN']:
            row=mapping[i]
            graph=retain(row['graph_pin']['path'],f'graphs/fit_{fit}/world_{i}.json.gz')
            graphs.append(dict(world_index=i,graph=graph,row_start=row['row_start'],row_end=row['row_end'],
                               state_order_sha256=row['state_order_sha256']))
        fits[str(fit)]=dict(model=model,hidden=hidden,graphs=graphs,
                            original_graph_manifest_pin=source['graph_manifest_pin'],
                            historical_shared_preparation_CPU_seconds=source['shared_preparation_CPU_seconds'])
    known=set(prior_protocol['known_schedule_hashes'])
    historical=len(known)
    known.update(w['schedule_sha256'] for fit in previous_worlds['fits'].values()
                 for domain in fit.values() for w in domain['worlds'])
    assert len(known)==historical+80
    mxcsr=retain(prior_protocol['primitive_binding']['mxcsr_library_pin']['path'],'numerical/mxcsr.so')
    result_primitive=retain(prior_protocol['primitive_binding']['primitive_result_pin']['path'],'numerical/primitive_results.json')
    assert read(bundle/result_primitive['path'])['status']=='PASS'
    source_pins=[]
    for path in sorted(ROOT.rglob('*.py')):
        if any(x in path.parts for x in ('input_bundle','run')):continue
        record=pin(path);record['path']=str(path.relative_to(ROOT));source_pins.append(record)
    for name in ('DESIGN.md','DEPENDENCY_PROVENANCE.json','math_attempt001/RESULTS.json'):
        record=pin(ROOT/name);record['path']=name;source_pins.append(record)
    semantic={key:next(x for x in source_pins if x['path']=='semantic/'+Path(value['path']).name)
              for key,value in previous['semantic_sources'].items()}
    math_result=read(ROOT/'math_attempt001/RESULTS.json')
    assert math_result['status']=='PASS'
    assert math_result['source_sha256']==pin(ROOT/'check_soft_math.py')['sha256']
    dispatch=np.lib.introspect.opt_func_info(func_name='^(exp|add|subtract|multiply|divide)$',signature='float64')
    protocol=dict(schema='hepta-value-sensitive-program-v1',namespace='hepta-value-sensitive-program-20261122/v1',
        created_utc=datetime.now(timezone.utc).isoformat(),fit_ids=[11,23,37,53,71],
        source_pins=source_pins,input_pins=inputs,fits=fits,semantic_sources=semantic,
        historical_protocol_pin=pin(old/'PROTOCOL_FROZEN.json'),previous_shared_protocol_pin=pin(prior/'PROTOCOL_FROZEN.json'),
        previous_confirmation_schedule_pin=pin(prior/'confirmation_attempt001/output/WORLDS_FROZEN.json'),
        previous_confirmation_use='schedule fingerprints only, no outcomes read for adaptation',
        known_schedule_hashes=sorted(known),historical_schedule_count=historical,
        prior_confirmation_schedule_count=80,
        public_domains=previous['public_domains'],schedule_fields=previous['schedule_fields'],
        numeric=dict(numpy_sha256=pin(np._core._multiarray_umath.__file__)['sha256'],
                     numpy_version=np.__version__,dispatch=dispatch,mxcsr=mxcsr,
                     primitive_result=result_primitive,python_executable=pin(sys.executable)),
        optimization=dict(temperature=.1,penalty=.001,family_cpu_seconds=20.,direct_rounds=8,
            states_per_round=8,proposal_doses=[.5,1.],bp_steps=128,bp_relative_step=.25,proposal_slots=128,
            family_objective_call_limit=129,information='identical complete GEN own-law graphs, terminal payoffs/posterior and hidden features',
            objective='mean complete soft-policy J_tau minus .001*delta_squared/(2*original_R_squared)'),
        selection_worlds_per_fit=16,confirmation_worlds_per_domain=8,
        mean_improvement_threshold=1e-8,maximum_selection_world_loss=.05,
        random_control_seeds=[11,23,37,53],state_cap=20000,address_space_bytes=2*1024**3,
        limits=dict(generation=dict(cpu_soft_seconds=240,cpu_hard_seconds=250,wall_seconds=500),
                    selection=dict(cpu_soft_seconds=120,cpu_hard_seconds=130,wall_seconds=260),
                    confirmation=dict(cpu_soft_seconds=120,cpu_hard_seconds=130,wall_seconds=260),
                    verification=dict(cpu_soft_seconds=180,cpu_hard_seconds=190,wall_seconds=380)),
        failed_family='KEEP, retain all cost and partial/rejected proposals; no new attempt or changed constants',
        confirmation_inference='6 Bonferroni-adjusted paired-t contrasts, checkpoint n=5; new confirmation cannot trigger retry',
        scope='Known own-law, original 196 head and radius; new public schedules, not future market labels. Diagnostic oracles are not weight edits. No production adoption.',
        metadata_preparation_CPU_seconds=time.process_time()-started)
    save(ROOT/'PROTOCOL_FROZEN.json',protocol)
    print(json.dumps(dict(protocol_pin=pin(ROOT/'PROTOCOL_FROZEN.json'),inputs=len(inputs),
                         input_bytes=sum(x['bytes'] for x in inputs),sources=len(source_pins),
                         known_schedules=len(known),metadata_CPU=protocol['metadata_preparation_CPU_seconds'])))


if __name__=='__main__':main()

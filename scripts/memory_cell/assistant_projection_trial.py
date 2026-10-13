"""Same-objective full/assistant projection qualification on pinned TRAIN data.

No new effectiveness study, target selection, generation change or activation.
Run two fresh one-epoch candidates using the existing trainer; retain all costs
and compare saved adapter tensors, observed LM-head shapes and training losses.
The dated cohort and targets are unchanged. SELECT/TEST outcomes are not read.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import gc
import json
from pathlib import Path
import torch
from safetensors.torch import load_file
from transformers import AutoTokenizer
import assistant_projection as projection
import five_causal_experiments as c
import five_reader_response_learning as learning
import five_reader_evidence_pairs as pairs
import five_reader_evidence_pair_trial as parent
import five_reader_response_trial as response
import source_time_evidence as metadata
from source_time_evidence_trial import project_examples
from five_native_historical_smoke import prepare_materials, snapshot, READER_INVENTORY, LOCOMO_SHA256, ARCHIVE_SHA256
from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
from native import load

PLAN = {'schema':'hepta.assistant-projection-qualification.v1',
        'profiles':[projection.FULL,projection.ASSISTANT], 'epochs':1,
        'archive_sha256':ARCHIVE_SHA256,'benchmark_sha256':LOCOMO_SHA256,
        'selection_plan_sha256':c.digest(parent.PLAN), 'training':deepcopy(learning.TRAINING),
        'loss_profile':pairs.MARGIN,'representation':metadata.SOURCE_TIME,
        'loss_atol':1e-5,'loss_rtol':1e-5,
        # Selecting LM-head rows changes CPU GEMM shape/order. The pinned run
        # observed one 2.5566842e-6 absolute adapter drift; retain a narrow,
        # fixed 3e-6 bound while leaving the relative bound unchanged.
        'adapter_atol':3e-6,'adapter_rtol':2e-4,
        'generation_or_evaluation':False,'automatic_selection':False,'production_accepted':False}


def run(archive, work, output):
    output.mkdir(parents=True,exist_ok=False)
    c.write_new(output/'plan.json',PLAN)
    c.write_new(output/'source.json',{n:c.file_sha(Path(__file__).with_name(n)) for n in (
        'assistant_projection.py','assistant_projection_trial.py','five_reader_response_learning.py',
        'five_reader_evidence_pairs.py','five_causal_native.py','source_time_evidence.py')})
    with measured() as acquisition:
        original,clean,staging=prepare_materials(archive,work/'staged')
    c.write_new(output/'staging.json',staging|{'cost':acquisition})
    matches=[p for p in original.rglob('*.json') if p.stat().st_size>50000 and c.file_sha(p)==LOCOMO_SHA256]
    c.require(len(matches)==1,'exact benchmark absent')
    benchmark=load(matches[0],'locomo',expected_sha256=LOCOMO_SHA256,allow_unresolved_evidence=True)
    chosen,excluded=parent.choose(benchmark)
    forbidden=sorted(set(excluded)|{benchmark.families[q.family] for q in chosen['select']})
    reader=clean/'reader'; snap=snapshot(reader,'causal_lm',READER_INVENTORY)
    tokenizer=AutoTokenizer.from_pretrained(reader,local_files_only=True,trust_remote_code=False)
    capacity=c.load(reader/'config.json')['max_position_embeddings']
    rows,census=response.training_examples(benchmark,chosen['train'],tokenizer,capacity)
    rows,projection_receipts=project_examples(rows,chosen['train'],benchmark.history,metadata.SOURCE_TIME)
    learning.validate_examples(rows,forbidden)
    compiled=pairs.prepare(tokenizer,rows,position_cap=capacity)
    c.write_new(output/'cohort.json',{'train_sha256':c.digest(rows),'examples':len(rows),
        'pairs':len(compiled),'census':census,'excluded_families':forbidden,'projection':projection_receipts})
    records={}; errors=[]
    for profile in PLAN['profiles']:
        backend=None; metric=None; trained=None
        with measured() as whole:
            try:
                with measured() as loading:
                    backend=LocalTextGenerator(reader,snap,768)
                with projection.projection_meter(backend.loaded) as metric:
                    trained=learning.fit_response_adapter(backend,rows,output/profile,
                        forbidden_families=forbidden,epochs=PLAN['epochs'],loss_profile=pairs.MARGIN,
                        projection_profile=profile)
                c.require(metric['head_calls']==trained['training_forwards'],'observed projection dispatch drift')
                expected=(trained['input_tokens_processed'] if profile==projection.FULL
                          else trained['scored_response_tokens_processed'])
                c.require(metric['projected_positions']==expected,'actual projected positions differ from compiled work')
                backend.close()
            except Exception as error:
                errors.append({'profile':profile,'error':type(error).__name__+': '+str(error),
                               'retry_permitted':False})
            finally:
                if backend is not None:
                    del backend
                    gc.collect()
        records[profile]={'training':trained,'lm_head_outputs':metric,'whole_fit_region':whole}
        c.write_new(output/(profile+'-result.json'),records[profile])
    parity=None
    if not errors:
        try:
            a,b=(records[x]['training'] for x in PLAN['profiles'])
            for key in ('base_tensor_sha256','initial_adapter_sha256','training_forwards',
                        'optimizer_steps','input_tokens_processed','supervised_tokens_processed',
                        'scored_response_tokens_processed'):
                c.require(a[key]==b[key],'fixed training identity/work differs: '+key)
            def finished(profile):
                events=[json.loads(x)['record'] for x in (output/profile/'optimizer-journal.jsonl').read_text().splitlines()]
                return [x for x in events if x['event']=='optimizer_finished']
            left,right=map(finished,PLAN['profiles'])
            c.require(len(left)==len(right)==len(compiled),'missing training events')
            for x,y in zip(left,right):
                c.require((x['epoch'],x['index'])==(y['epoch'],y['index']),'optimizer ordering drift')
                torch.testing.assert_close(torch.tensor(x['loss']),torch.tensor(y['loss']),
                    rtol=PLAN['loss_rtol'],atol=PLAN['loss_atol'])
            state_a,state_b=[load_file(str(output/x/'adapter/adapter_model.safetensors')) for x in PLAN['profiles']]
            c.require(state_a.keys()==state_b.keys(),'different adapter inventory')
            maximum=0.0
            for k in state_a:
                torch.testing.assert_close(state_a[k],state_b[k],rtol=PLAN['adapter_rtol'],atol=PLAN['adapter_atol'])
                maximum=max(maximum,float((state_a[k]-state_b[k]).abs().max()))
            full,short=(records[x]['lm_head_outputs'] for x in PLAN['profiles'])
            parity={'losses_within_registered_tolerance':True,'saved_adapter_tensors_within_tolerance':True,
                'maximum_adapter_abs_difference':maximum,'compared_training_steps':len(left),
                'projected_output_byte_fraction':short['produced_logit_bytes']/full['produced_logit_bytes'],
                'bitwise_equivalence':False,'whole_model_speedup_established':False}
        except Exception as error:
            errors.append({'phase':'parity','error':type(error).__name__+': '+str(error)})
    c.require(c.file_sha(matches[0])==LOCOMO_SHA256,'original data changed')
    report={'schema':'hepta.assistant-projection-qualification-result.v1','plan_sha256':c.digest(PLAN),
        'records':records,'parity':parity,'errors':errors,'physical_peak_and_energy_measured':False,
        'independent_capability':False,'production_accepted':False,'five_experiments_completed':False}
    c.write_new(output/'report.json',report)
    print('ASSISTANT_PROJECTION_RESULT',c.canonical(report).decode(),flush=True)
    c.require(not errors,'qualification has retained failures')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path);parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:run(args.archive,args.work,args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output/'failure.json').exists():
            c.write_new(args.output/'failure.json',{'error':str(error),'production_accepted':False})
        raise

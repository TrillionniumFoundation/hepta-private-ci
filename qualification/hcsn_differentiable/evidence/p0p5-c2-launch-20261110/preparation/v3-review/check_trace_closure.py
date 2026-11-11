"""Model-free independent closure of the frozen v3 actual-gradient trace gate."""
import ast
import copy
import hashlib
import json
from pathlib import Path

SOURCE=Path('/workspace/scratch/c385a7439f8e/c2-execution-candidate-v3/c2_recording.py')
OUT=Path(__file__).resolve().parent


def require(value,message):
    if not value:raise ValueError(message)


def main():
    raw=SOURCE.read_bytes()
    tree=ast.parse(raw)
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='validate_optimization_trace')
    scope={'require':require,'__builtins__':__builtins__}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(SOURCE),'exec'),scope)
    gate=scope['validate_optimization_trace']
    expected=dict(data_manifest_sha256='data',policy={'sha256':'policy'},trace_source_hashes={'source':'hash'},
        expected_positions=[0,1],expected_padded_sample_states=1,
        expected_batch_indices_by_position=[[0,1],[0]],expected_dt_by_position=[[0.1,0.2],[0.3]],
        network_model_sha256='network',logical_completed_updates_before_step=12,microbatch_episode_ids=['A','B'],
        probability_state_count=2,expected_valid_sample_states=3)
    header=dict(data_sha256='data',configuration_sha256='policy',sources={'source':'hash'})
    footer=dict(source_unchanged=True,sources_after={'source':'hash'},truncated=False,dropped_records=0,
        captures=1,seen_records=2,retained_records=2,padded_states_excluded=1)
    visits=[]
    for index,(indices,gaps) in enumerate(zip(expected['expected_batch_indices_by_position'],expected['expected_dt_by_position'])):
        visits.append(dict(position=index,index=index,capture=0,layer=0,batch_indices=indices,dt=gaps,
            model_sha256='network',update_index=12,episode_id='A+B',prior=[[0.6,0.4] for _ in indices],
            posterior=[[0.5,0.5] for _ in indices],expected_events=[0.1 for _ in indices]))
    patches={
        'valid_control':lambda h,v,f:None,
        'duplicate_position':lambda h,v,f:v[1].update(position=0),
        'wrong_valid_batch_indices':lambda h,v,f:v[0].update(batch_indices=[0]),
        'wrong_actual_dt':lambda h,v,f:v[0].update(dt=[9.0,9.0]),
        'wrong_network_digest':lambda h,v,f:v[0].update(model_sha256='wrong'),
        'wrong_source_footer':lambda h,v,f:f.update(sources_after={'source':'wrong'}),
        'wrong_padding_count':lambda h,v,f:f.update(padded_states_excluded=0),
        'wrong_probability_width':lambda h,v,f:v[0].update(prior=[[1.0],[1.0]]),
        'wrong_update':lambda h,v,f:v[1].update(update_index=13),
        'wrong_capture':lambda h,v,f:v[1].update(capture=1),
    }
    rows=[]
    for name,patch in patches.items():
        h,v,f=copy.deepcopy((header,visits,footer));patch(h,v,f)
        try:
            value=gate(expected,h,v,f)
            accepted=True;error=None
        except Exception as exc:
            value=None;accepted=False;error=str(exc)
        require(accepted==(name=='valid_control'),'unexpected gate result: '+name)
        rows.append(dict(case=name,accepted=accepted,error=error,result=value))
    require(SOURCE.read_bytes()==raw,'frozen source changed')
    result=dict(schema='C2-independent-model-free-trace-gate-closure-v1',passed_cases=len(rows),
        exact_source={'path':str(SOURCE),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
        cases=rows,model_reads=0,torch_imported=False,forward_calls=0,backward_calls=0,optimizer_operations=0,
        scope='Exact AST-extracted frozen validation function; positive control plus nine isolated corrupted metadata cases. No numerical or production-training admission.')
    with (OUT/'TRACE-GATE-CLOSURE.json').open('x') as stream:stream.write(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'passed_cases':len(rows),'source_sha256':result['exact_source']['sha256']}))


if __name__=='__main__':main()

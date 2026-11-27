"""Fresh process physical repeat of SHA-lowest original Reader requests; no labels."""
import argparse
import json
from pathlib import Path
import time
import source_first as s
from original_135m import BPE,Llama135M,verify,WEIGHTS


def repeat(requests_path,physical_path,model_root,output_path,n=12):
    request=s.read(requests_path);physical=s.read(physical_path)
    if (request.get('schema')!=s.SCHEMA+'.model-requests' or
        request.get('requests_sha256')!=s.digest(request.get('requests')) or
        physical.get('requests_sha256')!=request['requests_sha256'] or
        physical.get('model_sha256')!=WEIGHTS or
        physical.get('source_from_original_archive') is not True or
        physical.get('production_authorized') is not False or
        physical.get('decision')!='HOLD_NO_GO'):
        raise ValueError('new model trial disconnected from pinned original Reader')
    groups={}
    for rid,row in request['requests'].items():
        key=row['request_sha256']
        if key in groups and groups[key]['prompt']!=row['prompt']:
            raise ValueError('SHA source input collision')
        groups.setdefault(key,row)
    if set(groups)!=set(physical['physical_outputs']) or not 1<=n<=len(groups):
        raise ValueError('incomplete original Reader reference')
    # Selection is a function only of the sealed request SHA, not model answers.
    sample=sorted(groups)[:n]
    root=verify(model_root)
    from torch import set_num_threads
    set_num_threads(2)
    tok=BPE(root);reader=Llama135M(root)
    starts=Path(str(output_path)+'.starts.jsonl')
    if starts.exists() or Path(output_path).exists():raise FileExistsError('new trial must be create-only')
    stamp=time.perf_counter();rows=[]
    with starts.open('x') as f:
        for k in sample:
            ids=tok.encode(groups[k]['prompt'])
            if len(ids)>1000 or len(ids)+24>1024:raise ValueError('context overrun')
            f.write(json.dumps(dict(prompt_sha256=k,input_ids_sha256=s.digest(ids),
                original_weights_sha256=WEIGHTS),sort_keys=True)+'\n')
            f.flush()
            import os
            os.fsync(f.fileno())
            generated=reader.generate(ids,max_tokens=24)
            original=physical['physical_outputs'][k]
            if (generated!=original['output_ids'] or tok.decode(generated)!=original['original_answer']
                or len(ids)!=original['input_tokens'] or s.digest(ids)!=original['token_ids_sha256']):
                raise ValueError('fresh physical original inference did not reproduce')
            rows.append(dict(prompt_sha256=k,original_output_sha256=original['answer_sha256'],
                input_token_ids_sha256=s.digest(ids),model_output_token_count=len(generated)))
    verify(root)
    out=dict(schema=s.SCHEMA+'.fresh-physical-repeat',original_plan_sha256=physical['plan_sha256'],
        original_outputs_sha256=physical['outputs_sha256'],model_weight_sha256=WEIGHTS,
        original_started_journal_sha256=s.sha_file(starts),new_physical_forwards=reader.calls,
        actual_new_physical_model_requests=n,matching_original_requests=n,
        request_replay_rows_sha256=s.digest(rows),
        all_original_token_bytes_matched=True,
        original_model_hf_operator_parity=False,
        independent_semantic_evaluation=False,
        runtime_seconds=time.perf_counter()-stamp,authority='DENY_ALL',production_authorized=False,
        decision='HOLD_NO_GO')
    s.write_once(output_path,out)
    return out


def main():
    a=argparse.ArgumentParser()
    for key in ('requests','physical','reader-dir','output'):a.add_argument('--'+key,required=True)
    a.add_argument('--n',type=int,default=12)
    arg=a.parse_args()
    r=repeat(arg.requests,arg.physical,arg.reader_dir,arg.output,arg.n)
    print(json.dumps(r,sort_keys=True))

if __name__=='__main__':main()

"""Independent new-process original 135M Reader replay, 4 source-hash-lowest per arm.

No publisher labels or natural answer scoring. Complete output equality checks are
against private original token IDs after a genuinely new model/tensor load.
"""
import argparse
import os
import time
from pathlib import Path
import json

import source_first as spec
import v18_prompt_trial as producer

SCHEMA='hepta.v18.real-original-reader-independent-physical-repeat.v1'


def repeat_roster(proposal):
    if proposal.get('arms')!=list(producer.ARMS) or type(proposal.get('proposed')) is not dict:
        raise ValueError('wrong prespecified original new input population')
    roster=[]
    for arm in producer.ARMS:
        candidates=sorted((row['prompt_sha256'],cid+'|'+arm)
                          for cid in proposal['cases']
                          for row in [proposal['proposed'][cid+'|'+arm]])
        if len(candidates)!=30 or len({p for p,_ in candidates})!=30:
            raise ValueError('missing original prompt input for an arm')
        roster.extend(candidates[:4])
    if len(roster)!=12 or len(set(k for k,_ in roster))!=12:
        raise ValueError('repeat roster must contain twelve unique prompts')
    return sorted(roster)


def run(public,owner,plan,annotation,previous,proposal,physical,reader_dir,output):
    full=producer.validate(public,owner,plan,annotation,previous,proposal)
    orig=spec.read(physical)
    if (orig.get('schema')!=producer.SCHEMA+'.real-135m-private-output' or
        orig.get('proposal_sha256')!=full['proposal_sha256'] or
        orig.get('model_sha256')!=producer.WEIGHT_SHA or
        orig.get('responses_sha256')!=spec.digest(orig.get('responses')) or
        orig.get('physical_unique_requests')!=90 or
        orig.get('production_authorized') is not False or
        orig.get('decision')!='HOLD_NO_GO'):
        raise ValueError('original physical trial source changed')
    roster=repeat_roster(full)
    from original_135m import BPE,Llama135M,verify,WEIGHTS,TOKENIZER,CONFIG
    import torch
    modelroot=verify(reader_dir)
    torch.set_num_threads(2)
    tokenizer=BPE(modelroot)
    inputs=[]
    for key,rid in roster:
        entry=full['proposed'][rid]
        tid=tokenizer.encode(entry['prompt'])
        if not 1<=len(tid)<=1000 or len(tid)+24>1024:
            raise ValueError('original 135M context overflow')
        old=orig['responses'].get(key)
        if (type(old) is not dict or old.get('input_sha256')!=spec.digest(tid) or
            old.get('input_tokens')!=len(tid) or old.get('representative_id')!=rid or
            old.get('answer_sha256')!=spec.sha_text(old.get('answer','')) or
            old.get('output_tokens')!=len(old.get('generated_token_ids',[])) or
            old.get('answer')!=tokenizer.decode(old['generated_token_ids'])):
            raise ValueError('original comparator not a legitimate sealed token row')
        inputs.append((key,rid,tid,old))
    output=Path(output);journal=Path(str(output)+'.starts.jsonl')
    if output.exists() or output.is_symlink() or journal.exists() or journal.is_symlink():
        raise FileExistsError('no mutable original repeat receipt')
    physical_model=Llama135M(modelroot)
    verify(modelroot)
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY
    if hasattr(os,'O_NOFOLLOW'):flags |= os.O_NOFOLLOW
    t0=time.process_time();w0=time.perf_counter()
    matches=[]
    with os.fdopen(os.open(journal,flags,0o600),'w') as f:
        for key,rid,ids,old in inputs:
            event=dict(prompt_sha256=key,original_proposal_sha256=full['proposal_sha256'],
                token_ids_sha256=spec.digest(ids),model_sha256=WEIGHTS,
                real_model_call_started=True,authority='DENY_ALL')
            f.write(json.dumps(event,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
            tokens=physical_model.generate(ids,max_tokens=24)
            answer=tokenizer.decode(tokens)
            if tokens!=old['generated_token_ids'] or answer!=old['answer']:
                raise ValueError('fresh physical model did not reproduce original generated tokens')
            matches.append(dict(prompt_sha256=key,arm=rid.rsplit('|',1)[1],
                input_token_ids_sha256=spec.digest(ids),generated_token_ids_sha256=spec.digest(tokens),
                answer_text_sha256=spec.sha_text(answer),all_original_tokens_equal=True))
    verify(modelroot)
    report=dict(schema=SCHEMA,model_sha256=WEIGHTS,tokenizer_sha256=TOKENIZER,
        config_sha256=CONFIG,proposal_sha256=full['proposal_sha256'],
        original_physical_sha256=spec.sha_file(physical),
        repeated_requests=len(matches),
        per_arm_repeats={arm:sum(x['arm']==arm for x in matches) for arm in producer.ARMS},
        all_original_token_bytes_matched=True,
        fresh_original_model_forward_calls=physical_model.calls,
        fresh_model_cpu_ms=round(1000*(time.process_time()-t0)),
        fresh_model_wall_ms=round(1000*(time.perf_counter()-w0)),
        repeat_request_hashes=spec.digest(matches),
        start_journal_sha256=spec.sha_file(journal),
        original_publisher_labels_never_opened=True,
        stronger_reference_reader_executed=False,
        no_independent_human_semantic_adjudication=True,
        model_operator_hf_parity_not_verified=True,
        production_authorized=False,decision='HOLD_NO_GO',authority='DENY_ALL')
    spec.write_once(output,report)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('public','owner','plan','annotation','previous','proposal','physical','reader-dir','out'):
        ap.add_argument('--'+key,required=True)
    a=ap.parse_args()
    result=run(a.public,a.owner,a.plan,a.annotation,a.previous,a.proposal,a.physical,a.reader_dir,a.out)
    print(json.dumps({k:result[k] for k in ('schema','repeated_requests','all_original_token_bytes_matched',
                'fresh_original_model_forward_calls','decision')}))

if __name__=='__main__':main()

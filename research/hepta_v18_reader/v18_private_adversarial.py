"""Physical-material-only negative reviewer campaign (never a simulated efficacy run).

Only sanitized rejection totals may leave the private original-data workspace.
The original output/input packets and publisher labels are never uploaded.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

import v18_independent_review as reviewer


def write_private(path,obj):
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,'O_NOFOLLOW'):flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(path,flags,0o600),'w') as f:
        json.dump(obj,f,sort_keys=True,ensure_ascii=False,allow_nan=False)
        f.write('\n');f.flush();os.fsync(f.fileno())


def exercise(root,reader_dir,original,v17_dir,v18_dir,output):
    root=Path(root);v17_dir=Path(v17_dir);v18_dir=Path(v18_dir)
    normal_phy=reviewer.safe_read(v18_dir/'v18-physical.json')
    normal_plan=reviewer.safe_read(v18_dir/'proposal.json')
    normal_hidden=reviewer.safe_read(v17_dir/'hidden.json')
    original_journal=(v18_dir/'v18-physical.json.starts.jsonl').read_bytes()
    mutations=('alter_answer_resigned','false_forward_count','claimed_promotion',
        'resigned_source_id_change','shortened_journal_resigned','publisher_gold_mutation',
        'negative_cpu_cost_resigned','fake_model_source','injected_semantic_success')
    checks=[]
    for mode in mutations:
        with tempfile.TemporaryDirectory(prefix='hepta-v18-mutation-',dir=root) as temp:
            base=Path(temp);pr=None;phy=None;gold=None;journal=None;entry={}
            if mode in ('alter_answer_resigned','false_forward_count','claimed_promotion',
                        'shortened_journal_resigned','negative_cpu_cost_resigned',
                        'fake_model_source','injected_semantic_success'):
                phy=json.loads(json.dumps(normal_phy))
            if mode=='alter_answer_resigned':
                k=sorted(phy['responses'])[0]
                phy['responses'][k]['answer']='forged output not decoded from actual token IDs'
                phy['responses'][k]['answer_sha256']=reviewer.textsha(phy['responses'][k]['answer'])
                phy['responses_sha256']=reviewer.digest(phy['responses'])
            if mode=='false_forward_count':phy['model_forward_calls']+=1
            if mode=='claimed_promotion':phy['production_authorized']=True
            if mode=='resigned_source_id_change':
                pr=json.loads(json.dumps(normal_plan))
                k=next(z for z in pr['proposed'] if z.endswith('plain_annotated'))
                pr['proposed'][k]['source_ids']=[]
                pr['request_sha256']=reviewer.digest(pr['proposed'])
                pr['proposal_sha256']=reviewer.digest({k:v for k,v in pr.items() if k!='proposal_sha256'})
                phy=json.loads(json.dumps(normal_phy));phy['proposal_sha256']=pr['proposal_sha256']
            if mode=='shortened_journal_resigned':
                journal=b'\n'.join(original_journal.splitlines()[:-1])+b'\n'
                phy['journal_sha256']=reviewer.sha256(journal).hexdigest()
            if mode=='publisher_gold_mutation':
                gold=json.loads(json.dumps(normal_hidden))
                root_name=sorted(gold)[0];q=sorted(gold[root_name])[0]
                gold[root_name][q]['answer']='untrusted after-the-fact publisher rewrite'
            if mode=='negative_cpu_cost_resigned':
                k=sorted(phy['responses'])[0];phy['responses'][k]['cpu_ms']=-1
                phy['responses_sha256']=reviewer.digest(phy['responses'])
            if mode=='fake_model_source':phy['model_source_digest']='0'*64
            if mode=='injected_semantic_success':phy['semantic_correctness_certified']=True
            if pr is not None:
                write_private(base/'plan.json',pr);entry['proposal']=base/'plan.json'
            if phy is not None:
                write_private(base/'physical.json',phy);entry['physical']=base/'physical.json'
            if gold is not None:
                write_private(base/'hidden.json',gold);entry['hidden']=base/'hidden.json'
            if journal is not None:
                flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
                with os.fdopen(os.open(base/'journal.txt',flags,0o600),'wb') as f:
                    f.write(journal);f.flush();os.fsync(f.fileno())
                entry['journal']=base/'journal.txt'
            caught=False
            try:
                reviewer.run(
                    v17_dir/'public.json',v17_dir/'owner.json',original,
                    entry.get('hidden',v17_dir/'hidden.json'),v17_dir/'plan.json',
                    v17_dir/'annotation.json',v17_dir/'requests.json',
                    v17_dir/'physical.json',v17_dir/'physical.json.starts.jsonl',
                    entry.get('proposal',v18_dir/'proposal.json'),
                    entry.get('physical',v18_dir/'v18-physical.json'),
                    entry.get('journal',v18_dir/'v18-physical.json.starts.jsonl'),
                    reader_dir,base/'review.json')
            except (ValueError,KeyError,TypeError) as error:
                caught=True
            if not caught:
                raise ValueError('FAIL-OPEN physical reviewer accepted mutation '+mode)
            checks.append(mode)
    receipt=dict(schema='hepta.v18.private-original-adversarial-replay.v1',
        original_source_sha256=reviewer.file_sha(original),
        original_v17_physical_sha256=reviewer.file_sha(v17_dir/'physical.json'),
        new_v18_physical_sha256=reviewer.file_sha(v18_dir/'v18-physical.json'),
        rejected_all=True,mutation_count=len(checks),mutation_names=checks,
        task_success_inference=False,synthetic_score_claim=False,
        independent_human_semantic_review=False,production_authorized=False,
        decision='HOLD_NO_GO',authority='DENY_ALL')
    write_private(output,receipt)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('scratch-dir','reader-dir','original','v17-dir','v18-dir','out'):
        p.add_argument('--'+key,required=True)
    a=p.parse_args()
    result=exercise(a.scratch_dir,a.reader_dir,a.original,a.v17_dir,a.v18_dir,a.out)
    print(json.dumps({k:result[k] for k in ('schema','mutation_count','rejected_all','decision')}))

if __name__=='__main__':main()

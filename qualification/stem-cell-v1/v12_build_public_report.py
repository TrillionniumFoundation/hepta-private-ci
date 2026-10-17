"""Prepare sanitized V12 receipt from privately sealed originals; no dialogue/answers."""
from hashlib import sha256
import json
from pathlib import Path
from v12_public_audit import SCHEMA, EXPECTED, COUNTS, audit
from v12_reader_disagreement import hash_file, read_exact

def data_digest(a):
    selected={k:dict(tokens=v['output_ids'],text_sha=v['original_text_sha256']) for k,v in sorted(a['original_answers'].items())}
    return sha256(json.dumps(selected,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def build(plan_path,answer_path,replay_path,score_path,producer_path,out_path):
    p=read_exact(plan_path);a=read_exact(answer_path);b=read_exact(replay_path);s=read_exact(score_path)
    if set(a['original_answers'])!=set(b['original_answers']) or data_digest(a)!=data_digest(b):raise ValueError('second physical run changed model tokens')
    if (s['original_answers_sha256']!=hash_file(answer_path) or s['source_plan_sha256']!=hash_file(plan_path) or
       s['original_gold_sha256']!=EXPECTED['publisher_gold_original_sha256'] or
       s['any_publisher_weak_source_hit_rows']!=0 or s['residual_vs_cheap_changed_answers']!=3):raise ValueError('score did not bind originals')
    out={'schema':SCHEMA,**EXPECTED,'census':COUNTS,
         'original_plan_sha256':hash_file(plan_path),'sealed_answers_sha256':hash_file(answer_path),
         'rerun_token_text_sha256':data_digest(a),'experiment_source_sha256':hash_file(producer_path)}
    audit(out)
    with Path(out_path).open('x') as f:json.dump(out,f,sort_keys=True,indent=2);f.write('\n')
    return out
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    for n in ('plan','answers','replay','score','producer','out'):p.add_argument('--'+n,required=True)
    a=p.parse_args()
    build(a.plan,a.answers,a.replay,a.score,a.producer,a.out)

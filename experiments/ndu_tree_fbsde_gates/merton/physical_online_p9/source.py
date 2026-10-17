"""P9 original publisher selection: disjoint P5/P8 cohorts (historically public).

Publisher labels are seen only by the source-owner process for preregistered
stratification; model/selection jobs do not receive HELD labels.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from parent import load_p8
from portfolio import SCHEMA

SOURCE_SCHEMA=SCHEMA+'.original-publisher-fourth-fifth-train-third-held'
RULE='P9_train_fourth_and_fifth_held_third_class_length_parity'


def originals():return load_p8('source').original_module()


def select_publisher(train:list[dict],held:list[dict]):
    p5=originals()
    tables=(p5.validate_rows(train,'train'),p5.validate_rows(held,'held'))
    wanted={(label,bucket,parity) for label in range(4) for bucket in ('short','long') for parity in (0,1)}
    selected=[]
    for training,table in zip((True,False),tables):
        groups={k:[] for k in wanted}
        for row in table:
            idx=int(row['task_id'].rsplit('-',1)[1]);key=(row['label'],row['bucket'],idx%2)
            if key in groups and len(groups[key])<5:groups[key].append(row)
        required=5 if training else 3
        if any(len(group)<required for group in groups.values()):
            raise ValueError('unavailable: missing original publisher stratum at frozen occurrence')
        chosen=[row for key in sorted(groups) for row in (groups[key][3:5] if training else groups[key][2:3])]
        selected.append(sorted(chosen,key=lambda row:row['task_id']))
    training,testing=selected
    if len(training)!=32 or len(testing)!=16 or len({r['text_sha256'] for r in training+testing})!=48:
        raise ValueError('duplicate/census original publisher cohort')
    # Explicitly compare the first/second/third P5/P8 cohorts for the same split.
    for table,chosen,used in zip(tables,selected,('train','held')):
        already=set()
        older_text_digests=set()
        groups={k:[] for k in wanted}
        for row in table:
            key=(row['label'],row['bucket'],int(row['task_id'][-5:])%2)
            if key in groups and len(groups[key])<3:groups[key].append(row)
        for rs in groups.values():
            historical=rs[:3] if used=='train' else rs[:2]
            already.update(row['task_id'] for row in historical)
            older_text_digests.update(row['text_sha256'] for row in historical)
        if ({r['task_id'] for r in chosen}&already or
            {r['text_sha256'] for r in chosen}&older_text_digests):
            raise ValueError('P5/P8 original publisher row/content contamination')
    manifest={**p5.original_manifest(),
         'split_rule':RULE,'historical_publisher_not_future_source':True,
         'prior_p5_p8_cohort_disjoint':True}
    a={'schema':SOURCE_SCHEMA+'.train','source':manifest,'rows':[
       {k:r[k] for k in ('task_id','text','text_sha256','bucket','group','label')} for r in training]}
    b={'schema':SOURCE_SCHEMA+'.held-public','source':manifest,'rows':[
       {k:r[k] for k in ('task_id','text','text_sha256','bucket','group')} for r in testing]}
    c={'schema':SOURCE_SCHEMA+'.held-private-labels','source':manifest,'rows':[
       {k:r[k] for k in ('task_id','label','text_sha256')} for r in testing]}
    return a,b,c


def acquire():
    p5=originals()
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    parts=[]
    for rel,expected in p5.FILES.items():
        local=Path(hf_hub_download(repo_id=p5.REPO,repo_type='dataset',revision=p5.REV,filename=rel))
        if p5.sha(local.read_bytes())!=expected:
            raise ValueError('original publisher data byte substitution')
        parts.append(pq.read_table(local,columns=['text','label']).to_pylist())
    return select_publisher(*parts)


def main():
    from runner import write_new
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out
    out.mkdir(parents=True,exist_ok=False)
    for filename,data in zip(('train-public.json','held-public.json','held-private-labels.json'),acquire()):
        write_new(out/filename,data)
    print(json.dumps({'schema':SOURCE_SCHEMA,'train':32,'held':16,
                      'publisher_held_label_to_reader':False,'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()

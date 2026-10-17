"""P8 original AG News source owner; second/third publisher strata, never P5 first.

Historical public publisher labels are used by the source owner only; the real
model worker gets TRAIN with labels and HELD **without** held labels.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from policy import SCHEMA

SOURCE_SCHEMA = SCHEMA + '.original-publisher-second-occurrence'


def original_module():
    from pathlib import Path as P
    p=P(__file__).resolve().parents[1]/'physical_online_p2'/'public_source.py'
    spec=importlib.util.spec_from_file_location('p5_original_source_locked',p)
    if spec is None or spec.loader is None:raise ValueError('P5 source absent')
    import sys
    obj=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=obj
    spec.loader.exec_module(obj)
    return obj


def select_publisher(train:list[dict],held:list[dict]):
    """Split by original AG News publisher index, not model output or outcomes."""
    o=original_module()
    tables=(o.validate_rows(train,'train'),o.validate_rows(held,'held'))
    selected=[]
    expected={(k,b,p) for k in range(4) for b in ('short','long') for p in (0,1)}
    for is_train,table in zip((True,False),tables):
        groups={k:[] for k in expected}
        for row in table:
            key=(row['label'],row['bucket'],int(row['task_id'].rsplit('-',1)[1])%2)
            if key in groups and len(groups[key])<3:
                groups[key].append(row)
        if any(len(v)<(3 if is_train else 2) for v in groups.values()):
            raise ValueError('unavailable: missing second/third original publisher class/bucket/parity source')
        chosen=[r for k in sorted(groups) for r in (groups[k][1:3] if is_train else groups[k][1:2])]
        selected.append(sorted(chosen,key=lambda r:r['task_id']))
    training, held_rows=selected
    if len(training)!=32 or len(held_rows)!=16:
        raise ValueError('wrong P8 original source census')
    hashes=[r['text_sha256'] for r in training+held_rows]
    if len(set(hashes))!=48:raise ValueError('original source repeated text across P8 splits')
    # Reconstruct P5 first-occurrence IDs directly, prove no P5 source row reused.
    for table,chosen in zip(tables,selected):
        first={}
        for row in table:
            key=(row['label'],row['bucket'],int(row['task_id'].rsplit('-',1)[1])%2)
            first.setdefault(key,row['task_id'])
        if set(first)!=expected or set(first.values())&{r['task_id'] for r in chosen}:
            raise ValueError('P5 row contamination or missing strata')
    manifest={**o.original_manifest(),
              'split_rule':'P8_second_and_third_per_original_publisher_label_length_index_parity',
              'historical_publisher_not_future_source':True,
              'p5_first_cohort_disjoint':True}
    a={'schema':SOURCE_SCHEMA+'.train', 'source':manifest,
       'rows':[{k:r[k] for k in ('task_id','text','text_sha256','bucket','group','label')} for r in training]}
    b={'schema':SOURCE_SCHEMA+'.held-public','source':manifest,
       'rows':[{k:r[k] for k in ('task_id','text','text_sha256','bucket','group')} for r in held_rows]}
    c={'schema':SOURCE_SCHEMA+'.held-private-labels','source':manifest,
       'rows':[{k:r[k] for k in ('task_id','text_sha256','label')} for r in held_rows]}
    return a,b,c


def acquire():
    o=original_module()
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    tables=[]
    for relative,expected in o.FILES.items():
        file=Path(hf_hub_download(repo_id=o.REPO,repo_type='dataset',revision=o.REV,filename=relative))
        if o.sha(file.read_bytes())!=expected:
            raise ValueError('original publisher parquet digest mismatch: '+relative)
        tables.append(pq.read_table(file,columns=['text','label']).to_pylist())
    return select_publisher(*tables)


def main():
    from online import write_new
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    out=p.parse_args().out
    out.mkdir(parents=True,exist_ok=False)
    for name,doc in zip(('train-public.json','held-public.json','held-private-labels.json'),acquire()):
        write_new(out/name,doc)
    print(json.dumps({'schema':SOURCE_SCHEMA,'train':32,'held':16,'original_source':True,
                      'held_labels_to_reader':False,'posture':'RESEARCH_ONLY_DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()

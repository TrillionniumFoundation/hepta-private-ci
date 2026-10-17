"""P0.8 source-first cross-publisher cohort, no model/selection/effect authority.

The archive producer's label custody is *process/job separated*, not an independent
human issuer. The HuffPost source is historical, not a future time window.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

from agnews_crossfamily import ARCHIVE_SHA256, read_original
from original_replay import _no_duplicate_pairs, _no_nonfinite

SCHEMA = 'hepta.cell-fabric.p08.huff-transfer.v1'
HUFF_REPO = 'heegyu/news-category-dataset'
HUFF_REV = '304a05a55bc6abc0446d8fae0d0771716b6a271a'
HUFF_SHA = '2cfc51fa4a82a96ecbe251fa383737aa1dea2e0a517f61dece633fcc25a4a065'
MODEL_REPO = 'jhu-clsp/mmBERT-small'
MODEL_REV = '0eb3d056ec1d6333cf4e19b0966dfde342a41a3a'
MODEL_SAFETENSORS_SHA = '7ee7a6939b730a35e5d2a3e2263a1d1e992d10bc7f86b3470e9cb3cd482c590d'
MODEL_TOKENIZER_SHA = '197d4cc5406ee12cc50c8b5511f2393cc32d9db321545979ce041c1199178356'
ORIGINAL_MODEL_REV = 'abc32620dd4f6ab06f5fbe905dc25f310618e09f'
HUFF_LABEL = {'WORLD NEWS':0, 'SPORTS':1, 'BUSINESS':2, 'TECH':3}
PER_CLASS = 8
MAX_HUFF_SIZE = 105_000_000
MAX_ITEM_SIZE = 7000
MAX_TEXT = 768

class Denied(ValueError): pass

def require(x: bool, msg: str) -> None:
    if not x: raise Denied(msg)

def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()

def dump(o: object) -> bytes:
    return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def strict(raw: bytes):
    return json.loads(raw,object_pairs_hook=_no_duplicate_pairs,parse_constant=_no_nonfinite)

def read_regular(path: Path, limit: int) -> bytes:
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_size<=limit,'untrusted source inode')
        out=f.read(limit+1)
    require(len(out)<=limit,'oversized source')
    return out

def put_private(path: Path, content: bytes) -> None:
    require(path.parent.is_dir() and not path.parent.is_symlink(),'invalid output parent')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(content);f.flush();os.fsync(f.fileno())
    dfd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(dfd)
    finally:os.close(dfd)

def clean_text(text: str) -> str:
    require(type(text) is str and '\x00' not in text,'unsafe article text')
    out=' '.join(text.split())
    require(12<=len(out.encode('utf8'))<=MAX_TEXT,'bad article length')
    return out

def route(identifier: str) -> int:
    return hashlib.sha256(b'hepta.p08.no-target.route\0'+identifier.encode()).digest()[0]&1

def original_agnews(path: Path) -> tuple[list[dict],list[dict]]:
    original=read_original(path)
    rows=[strict(line) for line in original['dataset.jsonl'].splitlines()]
    require(len(rows)==128,'original AG News census changed')
    seen=set(); train=[];retention=[];cal=0
    for row in rows:
        require(type(row) is dict and set(row)=={'case_id','cell','group','label','observed_at','scope','split','text'},'original row schema changed')
        ident=row['case_id'];require(type(ident) is str and ident not in seen,'duplicate source identity')
        seen.add(ident)
        text=clean_text(row['text'])
        require(type(row['label']) is int and 0<=row['label']<4,'original label invalid')
        if row['split']=='train':train.append({'id':'ag:'+sha(ident.encode())[:40], 'text':text,'target':row['label']})
        elif row['split']=='holdout':retention.append({'id':'ag:'+sha(ident.encode())[:40],'text':text})
        elif row['split']=='calibration':cal+=1
        else:raise Denied('unrecognized original partition')
    require((len(train),cal,len(retention))==(64,32,32),'original train/cal/old-test count drift')
    return train,retention

def _parse_huff_rows(raw: bytes, *, require_full: bool) -> tuple[list[dict],str]:
    require(len(raw)<=MAX_HUFF_SIZE,'Huff original oversized')
    if require_full:require(sha(raw)==HUFF_SHA,'Huff original SHA256 drift')
    result=[];seen_links=set();seen_text=set();lines=raw.splitlines()
    if require_full:require(200000 <= len(lines) <= 220000,'Huff original count drift')
    for line in lines:
        require(0<len(line)<=MAX_ITEM_SIZE,'Huff source row oversized')
        item=strict(line)
        require(type(item) is dict,'Huff source item not object')
        category=item.get('category')
        if category not in HUFF_LABEL:continue
        timestamp=item.get('date')
        if type(timestamp) is not str or not ('2013-01-01'<=timestamp[:10]<='2022-12-31'):continue
        link=item.get('link');title=item.get('headline');description=item.get('short_description')
        if any(type(a) is not str for a in (link,title,description)):continue
        try:text=clean_text(title+' '+description)
        except Denied:continue
        id_='huff:'+sha((link+'\x00'+text).encode('utf8'))[:40]
        fingerprint=sha(text.casefold().encode('utf8'))
        if link in seen_links or fingerprint in seen_text:continue
        seen_links.add(link);seen_text.add(fingerprint)
        result.append({'id':id_,'text':text,'target':HUFF_LABEL[category],
                       'rank':sha(b'hepta.p08.freeze.publisher.v1\0'+id_.encode())})
    return result,sha(raw)

def choose_huff(raw: bytes, *, require_full: bool=True) -> list[dict]:
    rows,_=_parse_huff_rows(raw,require_full=require_full)
    by_class=defaultdict(list)
    for row in rows:by_class[row['target']].append(row)
    require(set(by_class)==set(range(4)),'Huff label mismatch')
    selected=[]
    for label in range(4):
        eligible=sorted(by_class[label],key=lambda x:(x['rank'],x['id']))
        require(len(eligible)>=PER_CLASS,'Huff category missing enough history')
        selected.extend(eligible[:PER_CLASS])
    selected.sort(key=lambda x:sha(b'hepta.p08.blind.order.v1\0'+x['id'].encode()))
    return [{k:r[k] for k in ('id','text','target')} for r in selected]

def make_panel(ag_zip: Path, huff_raw: bytes, *, production_source: bool=True) -> tuple[dict,str]:
    train,old=original_agnews(ag_zip)
    new=choose_huff(huff_raw,require_full=production_source)
    require(len(new)==4*PER_CLASS,'wrong transfer population')
    allrows=train+old+new
    ids=[r['id'] for r in allrows]
    require(len(ids)==len(set(ids)),'duplicate publisher identity')
    textshas=[sha(r['text'].casefold().encode('utf8')) for r in allrows]
    require(len(textshas)==len(set(textshas)),'cross-source exact text leakage')
    # Export only AGNews original training labels; both old/new outcome labels stay outside producer.
    public={'schema':SCHEMA,'agnews_archive_sha256':ARCHIVE_SHA256,
            'huff_source_sha256':HUFF_SHA if production_source else sha(huff_raw),
            'huff_revision':HUFF_REV,'model_revision':MODEL_REV,
            'model_weight_sha256':MODEL_SAFETENSORS_SHA,
            'model_tokenizer_sha256':MODEL_TOKENIZER_SHA,
            'train':train,'retention':old,
            'transfer':[{'id':r['id'],'text':r['text']} for r in new],
            'claims':{'label_source':'historically_public_publisher', 'publisher_independent':True,
                      'future_window_verified':False,'original_model_reused':False,
                      'production_authorized':False,'authority':'DENY_ALL'}}
    gold={'retention':{},'transfer':{r['id']:r['target'] for r in new}}
    ag=read_original(ag_zip)
    for line in ag['dataset.jsonl'].splitlines():
        r=strict(line)
        if r['split']=='holdout':gold['retention']['ag:'+sha(r['case_id'].encode())[:40]]=r['label']
    require(len(gold['retention'])==32 and len(gold['transfer'])==32,'gold population mismatch')
    commitment=sha(b'hepta.p08.gold.commit.v1\0'+dump(gold))
    public['gold_commitment']=commitment
    return public,commitment

def verify_panel(panel: dict) -> None:
    require(type(panel) is dict and set(panel)=={'schema','agnews_archive_sha256','huff_source_sha256','huff_revision','model_revision','model_weight_sha256','model_tokenizer_sha256','train','retention','transfer','claims','gold_commitment'},'panel schema drift')
    require(panel['schema']==SCHEMA and panel['agnews_archive_sha256']==ARCHIVE_SHA256 and panel['huff_source_sha256']==HUFF_SHA and panel['huff_revision']==HUFF_REV,'source identity not pinned')
    require(panel['model_revision']==MODEL_REV and panel['model_weight_sha256']==MODEL_SAFETENSORS_SHA and panel['model_tokenizer_sha256']==MODEL_TOKENIZER_SHA,'model identity not pinned')
    require(panel['claims']=={'label_source':'historically_public_publisher','publisher_independent':True,'future_window_verified':False,'original_model_reused':False,'production_authorized':False,'authority':'DENY_ALL'},'fake admission claim')
    for name,n,has_label in [('train',64,True),('retention',32,False),('transfer',32,False)]:
        part=panel[name];require(type(part) is list and len(part)==n,'missing cohort')
        for r in part:
            require(type(r) is dict and set(r)==({'id','text','target'} if has_label else {'id','text'}),'leaked held labels')
            require(type(r['id']) is str and r['id'].startswith('ag:' if name!='transfer' else 'huff:'),'wrong source identifier')
            clean_text(r['text'])
            if has_label:require(type(r['target']) is int and 0<=r['target']<4,'invalid training label')
    ids=[r['id'] for key in ('train','retention','transfer') for r in panel[key]]
    require(len(ids)==len(set(ids)),'duplicate identity')
    require(type(panel['gold_commitment']) is str and len(panel['gold_commitment'])==64,'missing hidden gold commitment')

def from_publisher(agnews: Path, huff: Path, dest: Path) -> dict:
    raw=read_regular(huff,MAX_HUFF_SIZE)
    panel,commitment=make_panel(agnews,raw)
    verify_panel(panel)
    put_private(dest,dump(panel))
    return {'schema':SCHEMA,'huff_sha256':HUFF_SHA,'panel_sha256':sha(dump(panel)),
            'gold_commitment':commitment,'new_source_count':32,'label_visibility':'curator_only',
            'future_window_verified':False,'production_authorized':False}

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--agnews',type=Path,required=True)
    ap.add_argument('--huff',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();print(json.dumps(from_publisher(a.agnews,a.huff,a.out),sort_keys=True))
if __name__=='__main__':main()

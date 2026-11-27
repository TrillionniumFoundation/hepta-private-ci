"""Independent archived real pretrained shared-Encoder/CellBank evaluation (no Torch).

Requires pinned original public train/test bytes for source-truth admission.
The separate numerical recount API deliberately labels its archived-roster-only
mode UNVERIFIED_SOURCE; it cannot qualify itself or auto-promote a model.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import unicodedata
import zipfile

ARCHIVE_SHA = 'fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a'
DATA_REV = '57ec275d8078af65b7731c2a98be812d844a6d6b'
DATA_SHA = {'train': 'b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b',
            'test': 'd12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d'}
DATA_BLOB = {'train': '98e2543cf482d0dca7bfb175ebe35d98efad95be',
             'test': '799687a8367359432985b8b13d85a2baf73f92dd'}
INTENTS = ('card_arrival', 'cash_withdrawal_not_recognised', 'exchange_rate', 'lost_or_stolen_phone')
ARMS = ('dense16', 'sparse16_top2')
BASE = 'public-cell-learning/'
EXPECTED = frozenset((
    'public-cell-learning.log', BASE+'pre-execution-plan.json', BASE+'selection.json',
    BASE+'scores.json', BASE+'data/SOURCE.json',BASE+'data/MATERIAL.json',
    BASE+'data/LICENSE', BASE+'trial/COMMITTED.json', BASE+'trial/plan.json',
    BASE+'trial/shared-encoder.json',
    *(BASE+f'trial/{arm}/{name}' for arm in ARMS for name in
      ('COMMITTED.json', 'bank.safetensors', 'execution.json', 'predictions.json'))))
MAX_ZIP = 8_000_000
MAX_MEMBER = 2_000_000

class EvidenceError(ValueError):
    pass

def need(c, message):
    if not c: raise EvidenceError(message)

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')

def json_no_duplicates(pairs):
    d={}
    for k,v in pairs:
        need(k not in d, 'duplicate JSON property');d[k]=v
    return d

def strict_json(raw: bytes):
    try: return json.loads(raw, object_pairs_hook=json_no_duplicates,
                           parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError('nonfinite JSON')))
    except (UnicodeError,json.JSONDecodeError) as e: raise EvidenceError('invalid JSON') from e

def original_text_key(text):
    return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())

def rows_from_original(raw: bytes, split: str):
    need(digest(raw)==DATA_SHA[split], 'original published dataset SHA mismatch')
    git_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    need(git_blob==DATA_BLOB[split],'immutable publisher blob differs')
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8',errors='strict')))
    need(reader.fieldnames==['text','category'],'unexpected publisher CSV schema')
    mapping={};duplicates=0
    for j,row in enumerate(reader):
        need(j<20_000 and set(row)=={'text','category'},'unbounded or malformed rows')
        text,label=row['text'],row['category']
        need(isinstance(text,str) and isinstance(label,str) and text and label and len(text.encode())<=4096,'invalid original row')
        key=original_text_key(text)
        need(bool(key),'empty normalized original')
        if key in mapping:
            need(mapping[key]==label,'conflicting publisher labels');duplicates+=1
        mapping[key]=label
    return mapping,duplicates

def original_source_selection(train: bytes, test: bytes):
    fit,dups_fit=rows_from_original(train,'train')
    held,dups_held=rows_from_original(test,'test')
    selected={'fit':[], 'heldout':[]};gold={};pools={'fit':{},'heldout':{}}
    for split,mapping in (('fit',fit),('heldout',held)):
        for label,intent in enumerate(INTENTS):
            keys=[k for k,l in mapping.items() if l==intent and (split=='fit' or k not in fit)]
            keys.sort(key=lambda k:digest(('hepta-banking77-subset-v1\0'+k).encode()))
            pools[split][intent]=len(keys)
            required=16 if split=='fit' else 8
            need(len(keys)>=required,'insufficient original dataset class')
            for k in keys[:required]:
                source_id=split+':'+digest(k.encode('utf-8'))
                selected[split].append(source_id)
                if split=='heldout':gold[source_id]=label
    need(len(gold)==32,'source group count')
    return {'selected':selected,'gold':gold,'pool_sizes':pools,
            'duplicate_rows':{'train':dups_fit,'test':dups_held},
            'excluded_test_overlap':len(set(fit)&set(held))}

def open_pinned_archive(path: Path, expected_digest=ARCHIVE_SHA):
    need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=MAX_ZIP,'unsafe research archive')
    data=path.read_bytes();need(digest(data)==expected_digest,'original Actions archive SHA mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos=z.infolist(); names=[x.filename for x in infos]
        need(len(names)==len(EXPECTED) and set(names)==EXPECTED,'closed original artifact member set mismatch')
        need(len(names)==len(set(names)),'duplicate ZIP members')
        for x in infos:
            need(0<x.file_size<=MAX_MEMBER and (x.external_attr>>16)&0o170000!=0o120000,'unsafe ZIP member')
        files={n:z.read(n) for n in names}
        need(all(len(files[n])<=MAX_MEMBER for n in names),'ZIP inflated beyond bound')
    return files

def binary_probs(logits):
    need(type(logits)==list and len(logits)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in logits),'invalid sealed logits')
    offset=max(logits); ex=[math.exp(x-offset) for x in logits];total=sum(ex)
    return [x/total for x in ex]

def evaluate(pred, gold, time_key):
    need(type(pred)==list and len(pred)==32,'missing complete sealed predictions')
    seen=set(); correct=0;brier=0.;nll=0.;binary={};per_class=[0]*4
    for row in pred:
        need(type(row)==dict and set(row)=={'id','before_logits','after_logits'},'unsealed prediction fields')
        name=row['id'];need(name in gold and name not in seen,'unknown or duplicate publisher case');seen.add(name)
        logits=row[time_key+'_logits'];p=binary_probs(logits);answer=gold[name]
        match=int(max(range(4),key=lambda k:logits[k])==answer)
        correct+=match;binary[name]=match;per_class[answer]+=match
        brier+=sum((p[k]-int(k==answer))**2 for k in range(4))
        nll-=math.log(p[answer])
    need(set(gold)==seen,'missing sealed case')
    return {'accuracy':correct/32,'correct':correct,'brier':brier/32,'mean_nll':nll/32,
            'per_class_accuracy':dict(zip(INTENTS,[n/8 for n in per_class]))},binary

def mcnemar(first,second):
    need(first.keys()==second.keys(),'unpaired original cases')
    first_only=sum(first[k] and not second[k] for k in first)
    second_only=sum(second[k] and not first[k] for k in first)
    n=first_only+second_only
    if n:
        smaller=min(first_only,second_only)
        p=min(1.,2*sum(math.comb(n,i) for i in range(smaller+1))/(2**n))
    else:p=1.
    return {'first_only':first_only,'second_only':second_only,
            'both_or_neither':len(first)-n,'discordant':n,'exact_two_sided_p':p}

def recount(files: dict, source_proof: dict | None):
    source_first = source_proof is not None
    selection=strict_json(files[BASE+'selection.json'])
    score=strict_json(files[BASE+'scores.json'])
    need(selection['schema']=='hepta.banking77-subset-selection.v1' and
         score['schema']=='hepta.public-cell-learning-scores.v1','unexpected historical evidence schema')
    need(selection['raw_sha256']==DATA_SHA and score['dataset_files_sha256']==DATA_SHA and
         score['dataset_revision']==DATA_REV,'publisher source hash/revision mismatch')
    if source_first:
        need(selection['selected_ids']==source_proof['selected'],'independent original source case roster mismatch')
        need(selection['pool_sizes']==source_proof['pool_sizes'],'source pool size changed')
        need(selection['duplicate_rows']==source_proof['duplicate_rows'] and
             selection['excluded_test_overlap']==source_proof['excluded_test_overlap'],'original source overlap/dedup mismatch')
        gold=source_proof['gold']
    else:
        # Precondition: only a historical inference from the unverified archive.
        ids=selection['selected_ids']['heldout']
        need(type(ids)==list and len(ids)==32 and len(set(ids))==32,'invalid unverified roster')
        gold={v:i//8 for i,v in enumerate(ids)}
    need(score['heldout_examples']==32 and score['fitting_examples']==64 and
         score['full_system_cost_measured'] is False and score['efficacy_established'] is False and
         score['observer_independence_established'] is False and
         score['production_authorized'] is False,'overclaimed original record')
    terminals=strict_json(files[BASE+'trial/COMMITTED.json'])
    need(terminals['run_id']==score['run_id'] and
         set(terminals['terminals'])==set(ARMS),'incomplete exact historical trial')
    need(digest(files[BASE+'trial/shared-encoder.json'])==terminals['shared_encoder_sha256'], 'shared original pretrained Encoder seal changed')
    result={};pairs={}
    for arm in ARMS:
        folder=BASE+'trial/'+arm+'/'
        seal=strict_json(files[folder+'COMMITTED.json'])
        execution=strict_json(files[folder+'execution.json'])
        pred=strict_json(files[folder+'predictions.json'])
        need(seal['schema']=='hepta.stem.prediction-seal.v1' and
             terminals['terminals'][arm]=={'id':seal['seal_id'],'kind':'completed'},'original terminal seal drift')
        need(set(seal['files'])=={'bank.safetensors','execution.json','predictions.json'},'original sealed file inventory drift')
        for name,expected in seal['files'].items():
            need(digest(files[folder+name])==expected, 'original model weight/forecast byte mismatch')
        need(execution['arm']==arm and execution['input_id']==selection['input_id'] and
             execution['heldout_labels_loaded'] is False and
             execution['production_authorized'] is False and
             execution['shared_encoder_sha256']==terminals['shared_encoder_sha256'], 'execution identity/authority mismatch')
        need(execution['initial_sha256']!=execution['trained_sha256'] and
             execution['training']['steps']==64,'original SGD updates not present')
        scores={};pairs[arm]={}
        for stage in ('before','after'):
            calc,binary=evaluate(pred,gold,stage);scores[stage]=calc;pairs[arm][stage]=binary
            public=score['scores'][arm][stage]
            for key in ('accuracy','brier','mean_nll'):
                need(abs(calc[key]-public[key])<1e-10,'published score does not recompute: '+arm+' '+key)
            for cat,val in calc['per_class_accuracy'].items():
                need(abs(val-public['per_class_accuracy'][cat])<1e-10,'per-class score mismatch')
        result[arm]={'scores':scores,'trainable_params':execution['inventory']['trainable_parameters'],
                     'active_cells_cap':execution['inventory']['active_cells_cap'],
                     'training_steps':execution['training']['steps'],
                     'before_after_paired_mcnemar':mcnemar(pairs[arm]['before'],pairs[arm]['after'])}
    compare=mcnemar(pairs['dense16']['after'],pairs['sparse16_top2']['after'])
    return {'schema':'hepta.stem.real-public-independent-v4','artifact_sha256':ARCHIVE_SHA,
            'source_bytes_independently_verified':source_first,
            'source_selection_sha256':{k:digest(canonical(selection['selected_ids'][k])) for k in ('fit','heldout')},
            'original_publisher_revision':DATA_REV,'fitting_cases':64,'heldout_cases':32,
            'arms':result,'dense_vs_sparse_after':compare,
            'source_disjoint_future_efficacy_established':False,
            'matched_total_lifecycle_cost_established':False,
            'pretraining_contamination_excluded':False,
            'model_selected':False,'production_authorized':False,
            'authority':'DENY_ALL','qualification':'HOLD_NO_GO'}

def main():
    p=argparse.ArgumentParser()
    for x in ('archive','train','test','output'):p.add_argument('--'+x,required=True)
    args=p.parse_args(); files=open_pinned_archive(Path(args.archive))
    for f in ('train','test'):
        file=Path(getattr(args,f));need(file.is_file() and not file.is_symlink() and 0<file.stat().st_size<=2_000_000,'unsafe publisher source')
    proof=original_source_selection(Path(args.train).read_bytes(),Path(args.test).read_bytes())
    report=recount(files,proof);out=Path(args.output)
    need(not out.exists() and not out.is_symlink(),'refuse to overwrite independent report')
    with out.open('xb') as stream:
        stream.write(canonical(report)+b'\n');stream.flush();os.fsync(stream.fileno())

if __name__=='__main__':main()

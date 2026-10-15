"""Actual ORIGINAL LoCoMo rank-head TRAIN -> physical reload -> blind score.

Use archived frozen MiniLM/BM25 source-only ranking; train cheap heads ONLY on
TRAIN family publisher weak-support labels, never touch SELECT/HELDOUT gold
until predictions are create-only persisted. SHADOW/DENY_ALL, not Reader QA.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import numpy as np
import torch
from safetensors.torch import save_file, load_file

PROFILE = 'hepta.amcn.original-locomo-physical-three-coordinate-rank-head.shadow.v1'
PRED_SCHEMA = PROFILE + '.sealed-predictions.v1'
ARMS = ('bm25', 'dense_original_minilm', 'rrf_60', 'frozen_shared',
        'untyped_equal_budget', 'typed_equal_budget', 'typed_swapped_negative',
        'train_label_shuffled_negative')
BANKS = ('untyped_equal_budget', 'typed_equal_budget', 'train_label_shuffled_negative')
TYPES = ('episodic', 'semantic')
VALID_SPLITS = ('train','select','retrospective_heldout_a','retrospective_heldout_b')
SOURCE_SHA = 'ac5f95085e5b223f81e888236e2c162f1ef45a3d1f52ad3e903fde48a629a633'
RANK_SHA = '25bd9754e1da4ee5ddf620e7f3c734f06650568278c6aab51916d55046baef99'
RANK_DECISION_SHA = 'bd63d0555a8e5b0cde444023d40da4570987226451fb97a2284d0bd285614a66'
GOLD_SHA = '758d951c2fb296c3ba23ef539e3f243fb8464d52ed0d42c8d0981943ac907a06'
MAX_BYTES = 12_000_000
TOP = 16
WIDTH = 32
# HNMF query type is preassigned solely from question syntax (not gold answer).
TEMPORAL = re.compile(r'^(when\b|how long\b|how old\b|what (?:date|time|year|month|day)\b|in what year\b)', re.I)
SOURCE_ID = re.compile(r'D(\d+):0*(\d+)$',re.I)


def digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),
                             allow_nan=False).encode()).hexdigest()


def stable_rank_digest(packet):
    """Full original model/source/per-question ranking identity, without wall time.

    The archive's `original_encoder_wall_seconds` changes every physical run;
    pinning its full original file SHA alone makes genuine replay impossible.
    All other metadata and every source ID in all 1,986 ranked lists are bound.
    This is a checksum, not an independent HF model/issuer endorsement.
    """
    require(isinstance(packet,dict) and
            'original_encoder_wall_seconds' in packet and
            type(packet['original_encoder_wall_seconds']) in (int,float),
            'missing original wall-clock observation')
    import math
    require(math.isfinite(packet['original_encoder_wall_seconds']) and
            packet['original_encoder_wall_seconds']>=0.,
            'invalid original runtime observation')
    return digest({k:v for k,v in packet.items()
                   if k!='original_encoder_wall_seconds'})


def file_sha(path):
    h=sha256()
    with Path(path).open('rb') as fd:
        for b in iter(lambda:fd.read(1<<20),b''):
            h.update(b)
    return h.hexdigest()


def require(ok, message):
    if not ok: raise ValueError(message)


def pinned(path,sha, max_bytes=MAX_BYTES):
    p=Path(path)
    require(p.is_file() and not p.is_symlink() and 0<p.stat().st_size<=max_bytes,
            'missing/unsafe/oversize pinned original file')
    require(len(sha)==64 and file_sha(p)==sha,'missing or mismatched EXTERNAL file SHA')
    def no_duplicates(pairs):
        d={}
        for k,v in pairs:
            require(k not in d,'duplicate JSON field')
            d[k]=v
        return d
    return json.loads(p.read_bytes(),object_pairs_hook=no_duplicates,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_new(path,obj):
    path=Path(path)
    require(not path.exists() and not path.is_symlink(),'never overwrite original result')
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                    allow_nan=False)+'\n').encode()
    with path.open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return file_sha(path)


def typename(question):
    require(type(question) is str and question,'empty source-only question')
    return TYPES[0] if TEMPORAL.match(question.strip()) else TYPES[1]


def normalize_source(value):
    m=SOURCE_ID.fullmatch(value)
    require(m is not None,'unregistered source identity')
    return f'D{int(m[1])}:{int(m[2])}'


def load_source_and_rank(pub_path,pub_sha,rank_path,rank_sha):
    pub=pinned(pub_path,pub_sha);rank=pinned(rank_path,rank_sha)
    require(pub_sha==SOURCE_SHA, 'original frozen source registry changed')
    require(stable_rank_digest(rank)==RANK_DECISION_SHA,
            'original pretrained full 1,986-question model rank changed')
    require(pub.get('publisher_targets_not_included') is True and
            pub.get('production_accepted') is False and
            rank.get('training_or_publisher_gold_accessed') is False and
            rank.get('real_original_pretrained_forward') is True and
            rank.get('official_hf_tokenizer_model_parity_proven') is False,
            'original source-first model origin or gold isolation drift')
    orig=pub['cases'];pred=rank['case_predictions']
    require(len(orig)==len(pred)==1986 and len(pub['source_families'])==10,
            'full original case or source-family count changed')
    by={x['case_id']:x for x in pred}
    require(len(by)==len(pred) and {x['case_id'] for x in orig}==set(by),
            'missing or duplicated ORIGINAL model prediction')
    full=[]
    for c in orig:
        require(c['split'] in VALID_SPLITS and
                sha256(c['question'].encode()).hexdigest()==c['question_sha256'],
                'original question changed')
        r=by[c['case_id']]
        require(r['family']==c['family'] and r['split']==c['split'] and
                r['question_sha256']==c['question_sha256'],
                'cross-family/future source binding changed')
        listing=r['ranked_source_ids']
        require(set(listing)=={'bm25','dense_original_minilm','bm25_dense_half','rrf_60'},
                'unregistered retrieval arm')
        roots={s['id'] for s in pub['source_families'][c['family']]}
        for a,ids in listing.items():
            require(len(ids)==TOP and len(set(ids))==TOP and set(ids)<=roots,
                    'reduced or substituted original candidate census')
        full.append((c,r))
    return full


def candidates(c,r):
    b=r['ranked_source_ids']['bm25'];d=r['ranked_source_ids']['dense_original_minilm']
    ids=list(dict.fromkeys(b+d))
    require(16<=len(ids)<=WIDTH,'wrong frozen common candidate budget')
    ib={s:i for i,s in enumerate(b)};idn={s:i for i,s in enumerate(d)}
    x=np.zeros((WIDTH,3),dtype=np.float32);mask=np.zeros(WIDTH,dtype=np.bool_)
    for i,sid in enumerate(ids):
        x[i,0]=(16-ib[sid])/16 if sid in ib else 0.
        x[i,1]=(16-idn[sid])/16 if sid in idn else 0.
        x[i,2]=float(sid in ib and sid in idn)
        mask[i]=True
    return ids,x,mask


def prepare_train(public,pub_sha,rank,rank_sha,gold,gold_sha,output):
    original=load_source_and_rank(public,pub_sha,rank,rank_sha)
    require(gold_sha==GOLD_SHA,'original weak-label immutable reference drift')
    targets=pinned(gold,gold_sha)
    by={x['case_id']:x for x in targets['cases']}
    require(len(by)==len(original),'not the complete ORIGINAL publisher annotation census')
    labels=[]
    for c,r in original:
        if c['split']!='train':continue
        target=by[c['case_id']]
        require(target['family']==c['family'],'source owner family changed')
        require(type(target['publisher_support']) is list,
                'invalid original publisher weak support')
        labels.append({'case_id':c['case_id'],'family':c['family'],
                       'split':'train','publisher_support':target['publisher_support']})
    require(len(labels)==1157 and len({x['family'] for x in labels})==6,
            'only six original TRAIN source families admissible')
    return write_new(output,{'schema':PROFILE+'.train-only-weak-labels.v1',
                             'source_sha256':pub_sha,'rank_sha256':rank_sha,
                             'public_heldout_labels_present':False,
                             'labels':labels,'production_accepted':False})


def build_features(full,train_label_by_case=None):
    rows=[]
    for c,r in full:
        ids,x,mask=candidates(c,r)
        rec={'case_id':c['case_id'],'family':c['family'],'split':c['split'],
             'memory_type':typename(c['question']),'ids':ids,'x':x,'mask':mask,
             'original':r['ranked_source_ids']}
        if train_label_by_case is not None and c['split']=='train':
            label=train_label_by_case[c['case_id']]
            support={normalize_source(k) for k in label['publisher_support']}
            y=np.zeros(WIDTH,dtype=np.float32)
            for i,sid in enumerate(ids):y[i]=float(normalize_source(sid) in support)
            rec['y']=y
            rec['train_has_positive_in_union']=bool(y.sum())
        rows.append(rec)
    return rows


def train_model(train_rows, *,kind, seed, steps, batch_size=24, lr=0.025,
                permute_labels=False):
    require(len(train_rows)>=24 and len({r['family'] for r in train_rows})>=3,
            'insufficient disjoint TRAIN family examples for Head')
    device='cpu'
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        head=torch.nn.Linear(3,1,bias=False).to(device)
        with torch.no_grad():head.weight.copy_(torch.tensor([[1.,0.,0.]]))
        before=head.weight.detach().clone()
        optimizer=torch.optim.AdamW(head.parameters(),lr=lr,weight_decay=0.0)
        gen=torch.Generator().manual_seed(seed+101)
        x=torch.tensor(np.stack([r['x'] for r in train_rows]),dtype=torch.float32)
        y=torch.tensor(np.stack([r['y'] for r in train_rows]),dtype=torch.float32)
        valid=torch.tensor(np.stack([r['mask'] for r in train_rows]),dtype=torch.bool)
        if permute_labels:
            for i in range(len(train_rows)):
                permutation=torch.randperm(int(valid[i].sum()),generator=gen)
                y[i,:int(valid[i].sum())]=y[i,permutation].clone()
        y=y/(y.sum(dim=1,keepdim=True).clamp_min(1.))
        for step in range(steps):
            idx=torch.randint(len(train_rows),(batch_size,),generator=gen)
            inp=x[idx]
            logits=head(inp).squeeze(-1).masked_fill(~valid[idx],-1e6)
            loss=-(torch.log_softmax(logits,dim=-1)*y[idx]).sum(dim=-1).mean()
            require(bool(torch.isfinite(loss)),'nonfinite original train loss')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step()
            with torch.no_grad():head.weight.clamp_(-6.,6.)
        require(not torch.equal(before,head.weight.detach()),'no physical weight update')
        head.eval()
        return head,{'steps':steps,'minibatch_examples':steps*batch_size,
                     'train_questions_with_available_positive':len(train_rows),
                     'trained_parameter_count':head.weight.numel(),
                     'seed':seed,'shuffle_train_only_labels':permute_labels,
                     'learned_fp32_weights':head.weight.detach().flatten().tolist()}


def fit_banks(pub_path,pub_sha,rank_path,rank_sha,label_path,label_sha,
              output_dir,*,steps=160,batch=24,seed=23):
    require(type(steps) is int and 1<=steps<=1000 and type(batch) is int and 1<=batch<=128,
            'non-equal physical training budget request')
    require(type(seed) is int and 0<=seed<2**31,'invalid frozen physical seed')
    full=load_source_and_rank(pub_path,pub_sha,rank_path,rank_sha)
    labels=pinned(label_path,label_sha)
    require(labels.get('schema')==PROFILE+'.train-only-weak-labels.v1' and
            labels.get('source_sha256')==pub_sha and
            labels.get('rank_sha256')==rank_sha and
            labels.get('public_heldout_labels_present') is False,
            'unqualified TRAIN-only label file')
    by={x['case_id']:x for x in labels['labels']}
    expected={c['case_id'] for c,r in full if c['split']=='train'}
    require(set(by)==expected and len(by)==len(labels['labels']),
            'future/SELECT/RETENTION gold leaked into physical training')
    for c,r in full:
        if c['split']=='train':
            require(by[c['case_id']]['split']=='train' and
                    by[c['case_id']]['family']==c['family'],
                    'TRAIN case crossed original source-family boundary')
    rows=build_features([(c,r) for c,r in full if c['split']=='train'],by)
    train=rows
    selected=[r for r in train if r['train_has_positive_in_union']]
    typed={kind:[r for r in selected if r['memory_type']==kind] for kind in TYPES}
    require(all(len(v)>=24 and len({r['family'] for r in v})>=3 for v in typed.values()),
            'specialization lacks sufficient independent TRAIN family coverage')
    directory=Path(output_dir)
    require(not directory.exists() and not directory.is_symlink(),
            'create-only physical Head bank')
    directory.mkdir(parents=True,mode=0o700)
    inventory={}
    for bank in BANKS:
        for i,kind in enumerate(TYPES):
            pool=typed[kind] if bank=='typed_equal_budget' else selected
            trained,receipt=train_model(pool,kind=kind,seed=seed+i,steps=steps,
                                        batch_size=batch,
                                        permute_labels=bank=='train_label_shuffled_negative')
            dest=directory/f'{bank}__{kind}.safetensors'
            tensor={k:v.detach().cpu().contiguous() for k,v in trained.state_dict().items()}
            save_file(tensor,str(dest))
            with dest.open('rb') as fd:os.fsync(fd.fileno())
            inventory[f'{bank}__{kind}']={'file':dest.name,'sha256':file_sha(dest),
                                          'train_receipt':receipt}
    for k in TYPES:
        for bank in BANKS:
            r=inventory[f'{bank}__{k}']['train_receipt']
            require(r['steps']==steps and r['minibatch_examples']==steps*batch and
                    r['trained_parameter_count']==3,'Head budgets unequal')
    record={'schema':PROFILE+'.physically-trained-two-head-banks.v1',
            'source_sha256':pub_sha,'rank_sha256':rank_sha,
            'train_labels_sha256':label_sha,'train_family_roots':sorted({r['family'] for r in train}),
            'train_positive_eligible':len(selected),'train_total':len(train),
            'by_type_positive_eligible':{k:len(typed[k]) for k in TYPES},
            'types':list(TYPES),'steps_per_head':steps,'batch_per_head':batch,
            'bank_trainable_parameters':6,'heads_per_bank':2,
            'max_forward_heads_per_question':1,'entries':inventory,
            'no_select_or_heldout_labels_available_to_train':True,
            'pretrained_encoder_forward_in_this_trial':False,
            'real_physical_cpu_torch_adamw_training':True,
            'production_accepted':False,'superiority_claim':False}
    sha=write_new(directory/'manifest.json',record)
    fd=os.open(directory,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return {'manifest_sha256':sha,'bank':str(directory),
            'training_examples':len(train),'effective_positive_examples':len(selected)}


def physically_reload(directory,expected_manifest_sha,pub_sha,rank_sha):
    directory=Path(directory)
    require(directory.is_dir() and not directory.is_symlink(),'unsafe original Head bank')
    record=pinned(directory/'manifest.json',expected_manifest_sha,max_bytes=200000)
    require(record.get('schema')==PROFILE+'.physically-trained-two-head-banks.v1' and
            record.get('source_sha256')==pub_sha and
            record.get('rank_sha256')==rank_sha and
            record.get('types')==list(TYPES) and
            record.get('production_accepted') is False and
            record.get('real_physical_cpu_torch_adamw_training') is True,
            'wrong detached physical Head/source identity')
    expected={bank+'__'+kind for bank in BANKS for kind in TYPES}
    require(set(record.get('entries',{}))==expected,'missing original physical Head')
    models={}
    for name in sorted(expected):
        ent=record['entries'][name]
        require(set(ent)=={'file','sha256','train_receipt'} and
                ent['file']==name+'.safetensors' and len(ent['sha256'])==64,
                'invalid Head inventory')
        file=directory/ent['file']
        require(file.is_file() and not file.is_symlink() and
                file.stat().st_size<1_000_000 and file_sha(file)==ent['sha256'],
                'tampered physical Head tensor')
        state=load_file(str(file),device='cpu')
        require(set(state)=={'weight'} and
                state['weight'].shape==(1,3) and
                state['weight'].dtype==torch.float32 and
                bool(torch.isfinite(state['weight']).all()),
                'unqualified actual original Head numeric tensor')
        h=torch.nn.Linear(3,1,bias=False).eval()
        h.load_state_dict(state,strict=True)
        models[name]=h
    return models,record


def infer(pub_path,pub_sha,rank_path,rank_sha,bank_dir,bank_manifest_sha,output):
    full=load_source_and_rank(pub_path,pub_sha,rank_path,rank_sha)
    models,meta=physically_reload(bank_dir,bank_manifest_sha,pub_sha,rank_sha)
    output_rows=[]
    for c,r in full:
        if c['split']=='train':continue
        ids,x,mask=candidates(c,r)
        kind=typename(c['question']);other=TYPES[1-TYPES.index(kind)]
        features=torch.from_numpy(x)
        common={bank:models[f'{bank}__{kind}'] for bank in BANKS}
        common['typed_swapped_negative']=models[f'typed_equal_budget__{other}']
        picked={'bm25':r['ranked_source_ids']['bm25'][:16],
                'dense_original_minilm':r['ranked_source_ids']['dense_original_minilm'][:16],
                'rrf_60':r['ranked_source_ids']['rrf_60'][:16],
                'frozen_shared':r['ranked_source_ids']['bm25'][:16]}
        with torch.no_grad():
            for arm,h in common.items():
                scores=h(features).squeeze(-1).tolist()
                picked[arm]=sorted(ids,key=lambda sid:(-scores[ids.index(sid)],sid))[:16]
        require(set(picked)==set(ARMS) and all(len(set(v))==16 for v in picked.values()),
                'unequal final candidate arm census')
        output_rows.append({'case_id':c['case_id'],'family':c['family'],
                            'split':c['split'],'question_sha256':c['question_sha256'],
                            'memory_type':kind,'ranked_source_ids':picked})
    require(len(output_rows)==429+196+204 and
            len({x['case_id'] for x in output_rows})==len(output_rows),
            'missing source-first original heldout prediction')
    return write_new(output,{'schema':PRED_SCHEMA,'source_sha256':pub_sha,
                             'rank_sha256':rank_sha,'bank_manifest_sha256':bank_manifest_sha,
                             'training_gold_never_opened_in_prediction_process':True,
                             'new_pretrained_encoder_forwards':0,
                             'new_reader_answers':0,
                             'original_physical_trained_head_forwards':len(output_rows)*4,
                             'independent_future_calendar_windows':0,
                             'production_accepted':False,
                             'complete_predictions':output_rows})


def verify_original_predictions(full, bank_dir, bank_sha, prediction_rows, pub_sha, rank_sha):
    """Recompute every sealed answer-independent ranking from physical tensors.

    No publisher gold or task answers are accepted. Calling this from the
    scorer BEFORE it opens weak targets forbids pasted prediction files.
    """
    models,_=physically_reload(bank_dir,bank_sha,pub_sha,rank_sha)
    cases={c['case_id']:(c,r) for c,r in full if c['split']!='train'}
    require(len(prediction_rows)==len(cases) and
            len({p['case_id'] for p in prediction_rows})==len(cases),
            'physical readback must include every SELECT and heldout source')
    verified=0
    for saved in prediction_rows:
        c,r=cases[saved['case_id']]
        ids,x,mask=candidates(c,r)
        kind=typename(c['question']);other=TYPES[1-TYPES.index(kind)]
        require(saved['family']==c['family'] and saved['split']==c['split'] and
                saved['memory_type']==kind and
                saved['question_sha256']==c['question_sha256'],
                'physical Head original query/source/type drift')
        expected={'bm25':r['ranked_source_ids']['bm25'][:16],
                  'dense_original_minilm':r['ranked_source_ids']['dense_original_minilm'][:16],
                  'rrf_60':r['ranked_source_ids']['rrf_60'][:16],
                  'frozen_shared':r['ranked_source_ids']['bm25'][:16]}
        wires={'untyped_equal_budget':models['untyped_equal_budget__'+kind],
               'typed_equal_budget':models['typed_equal_budget__'+kind],
               'typed_swapped_negative':models['typed_equal_budget__'+other],
               'train_label_shuffled_negative':models['train_label_shuffled_negative__'+kind]}
        for arm,head in wires.items():
            with torch.no_grad():
                score=head(torch.from_numpy(x)).squeeze(-1).tolist()
            expected[arm]=sorted(ids,key=lambda sid:(-score[ids.index(sid)],sid))[:16]
            verified+=1
        require(saved['ranked_source_ids']==expected,
                'saved probabilities do not match independently RELOADED original Head')
    require(verified==len(cases)*4 and verified==3316,
            'physical Head forward census incomplete')
    return verified


def score(pub_path,pub_sha,rank_path,rank_sha,answer_path,answer_sha,
          gold_path,gold_sha,output,*,bank_dir,bank_manifest_sha):
    full=load_source_and_rank(pub_path,pub_sha,rank_path,rank_sha)
    require(gold_sha==GOLD_SHA,'publisher weak labels changed')
    predictions=pinned(answer_path,answer_sha)
    require(predictions.get('schema')==PRED_SCHEMA and
            predictions.get('training_gold_never_opened_in_prediction_process') is True
            and predictions.get('source_sha256')==pub_sha and
            predictions.get('rank_sha256')==rank_sha and
            predictions.get('production_accepted') is False,
            'unqualified original physically reloaded Head predictions')
    require(predictions.get('bank_manifest_sha256')==bank_manifest_sha and
            predictions.get('original_physical_trained_head_forwards')==3316,
            'source/head budget original prediction receipt drift')
    verified_reloaded_forwards=verify_original_predictions(
        full,bank_dir,bank_manifest_sha,predictions['complete_predictions'],pub_sha,rank_sha)
    # Score-only stage may now open the separate original publisher weak support.
    gold=pinned(gold_path,gold_sha)
    expected={c['case_id']:c for c,r in full if c['split']!='train'}
    pred={x['case_id']:x for x in predictions['complete_predictions']}
    goldmap={x['case_id']:x for x in gold['cases']}
    require(set(pred)==set(expected) and len(pred)==len(expected) and
            set(goldmap)=={c['case_id'] for c,r in full},
            'complete original SELECT/HELDOUT question denominator missing')
    sources_by_family={f:{x['id'] for x in items}
                       for f,items in pinned(pub_path,pub_sha)['source_families'].items()}
    fam=defaultdict(lambda:defaultdict(Counter))
    by_type=defaultdict(lambda:defaultdict(Counter))
    splits=defaultdict(lambda: defaultdict(lambda: Counter()))
    paired=defaultdict(list);zero_support=Counter()
    for case_id,orig in expected.items():
        p=pred[case_id];w=goldmap[case_id]
        require(p['family']==orig['family'] and p['split']==orig['split'] and
                p['question_sha256']==orig['question_sha256'] and
                w['family']==orig['family'] and p['memory_type']==typename(orig['question']),
                'changed source/family/type after Head prediction sealed')
        idlist=next(r['ranked_source_ids'] for c,r in full if c['case_id']==case_id)
        support={normalize_source(x) for x in w['publisher_support']}
        source=sources_by_family[orig['family']]
        for arm,ids in p['ranked_source_ids'].items():
            require(arm in ARMS and len(ids)==16 and len(set(ids))==16
                    and set(ids)<=source,'unregistered or omitted Head inference candidates')
            normalized=[normalize_source(x) for x in ids]
            found=[i for i,z in enumerate(normalized) if z in support]
            any3=int(any(i<3 for i in found))
            all3=int(bool(support) and support<=set(normalized[:3]))
            any16=int(bool(found))
            measure={'questions':1,'hit3':any3,'hit16':any16,'all3':all3}
            splits[orig['split']][arm].update(measure)
            fam[orig['family']][arm].update(measure)
            by_type[p['memory_type']][arm].update(measure)
            paired[(orig['split'],orig['family'],case_id)].append((arm,any3,all3))
        zero_support[orig['split']]+=int(not support)
    for case in predictions['complete_predictions']:
        require(set(case['ranked_source_ids'])==set(ARMS),'missing negative or baseline arm')
    partition={split:{a:dict(v) for a,v in by_arm.items()}
               for split,by_arm in sorted(splits.items())}
    heldout=[(key,{arm:(hit3,all3) for arm,hit3,all3 in rows}) for key,rows in paired.items()
             if key[0].startswith('retrospective_heldout')]
    deltas={}
    for arm in ARMS:
        deltas[arm]={'hit3_vs_bm25':sum(row[arm][0]-row['bm25'][0] for key,row in heldout),
                     'all3_vs_bm25':sum(row[arm][1]-row['bm25'][1] for key,row in heldout)}
    paired_flips={}
    for arm in ARMS:
        paired_flips[arm]={'new_hit_vs_bm25':sum(row[arm][0]>row['bm25'][0] for k,row in heldout),
                           'lost_hit_vs_bm25':sum(row[arm][0]<row['bm25'][0] for k,row in heldout)}
    return write_new(output,{'schema':PROFILE+'.post-seal-publisher-weak-score.v1',
                             'original_source_sha256':pub_sha,
                             'original_rank_sha256':rank_sha,
                             'sealed_head_predictions_sha256':answer_sha,
                             'original_publisher_weak_gold_sha256':gold_sha,
                             'complete_questions':len(expected),
                             'heldout_questions':len(heldout),
                             'heldout_source_families':2,
                             'per_split':partition,
                             'per_family':{f:{a:dict(v) for a,v in arms.items()}
                                           for f,arms in sorted(fam.items())},
                             'per_query_type':{f:{a:dict(v) for a,v in arms.items()}
                                               for f,arms in sorted(by_type.items())},
                             'independent_physical_Head_forwards_replayed':verified_reloaded_forwards,
                             'paired_heldout_question_flips':paired_flips,
                             'retrospective_heldout_delta':deltas,
                             'zero_publisher_support_annotations':dict(zero_support),
                             'real_pytorch_head_training':True,
                             'real_reader_answers':0,
                             'independent_semantic_task_success':None,
                             'model_parameters_vs_fixed_BM25_matched_compute':False,
                             'official_hf_model_parity_verified':False,
                             'calendar_future_windows':0,
                             'production_accepted':False})


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    sub=cli.add_subparsers(dest='phase',required=True)
    a=sub.add_parser('prepare-train')
    a.add_argument('--public',required=True);a.add_argument('--public-sha',required=True)
    a.add_argument('--rank',required=True);a.add_argument('--rank-sha',required=True)
    a.add_argument('--publisher-gold',required=True);a.add_argument('--gold-sha',required=True)
    a.add_argument('--output',required=True)
    a=sub.add_parser('train')
    a.add_argument('--public',required=True);a.add_argument('--public-sha',required=True)
    a.add_argument('--rank',required=True);a.add_argument('--rank-sha',required=True)
    a.add_argument('--train-labels',required=True);a.add_argument('--train-labels-sha',required=True)
    a.add_argument('--bank-directory',required=True)
    a.add_argument('--steps',type=int,default=160)
    a=sub.add_parser('infer')
    a.add_argument('--public',required=True);a.add_argument('--public-sha',required=True)
    a.add_argument('--rank',required=True);a.add_argument('--rank-sha',required=True)
    a.add_argument('--bank-directory',required=True);a.add_argument('--manifest-sha',required=True)
    a.add_argument('--output',required=True)
    a=sub.add_parser('score')
    a.add_argument('--public',required=True);a.add_argument('--public-sha',required=True)
    a.add_argument('--rank',required=True);a.add_argument('--rank-sha',required=True)
    a.add_argument('--predictions',required=True);a.add_argument('--predictions-sha',required=True)
    a.add_argument('--publisher-gold',required=True);a.add_argument('--gold-sha',required=True)
    a.add_argument('--output',required=True)
    a.add_argument('--bank-directory',required=True)
    a.add_argument('--manifest-sha',required=True)
    x=cli.parse_args()
    kw={'pub_path':x.public,'pub_sha':x.public_sha,'rank_path':x.rank,'rank_sha':x.rank_sha}
    if x.phase=='prepare-train':r=prepare_train(x.public,x.public_sha,x.rank,x.rank_sha,x.publisher_gold,x.gold_sha,x.output)
    elif x.phase=='train':r=fit_banks(**kw,label_path=x.train_labels,label_sha=x.train_labels_sha,output_dir=x.bank_directory,steps=x.steps)
    elif x.phase=='infer':r=infer(**kw,bank_dir=x.bank_directory,bank_manifest_sha=x.manifest_sha,output=x.output)
    else:r=score(**kw,answer_path=x.predictions,answer_sha=x.predictions_sha,
                 gold_path=x.publisher_gold,gold_sha=x.gold_sha,output=x.output,
                 bank_dir=x.bank_directory,bank_manifest_sha=x.manifest_sha)
    print(json.dumps({'result':r},sort_keys=True))


if __name__=='__main__':main()

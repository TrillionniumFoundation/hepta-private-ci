"""Real mmBERT cached-feature, Cell0/Cell1 staged-learning diagnostic.

Only original 64 TRAIN items are ever staged for learning. Artificial two-stage
Cell0->Cell1 training is NOT time-travel/prospective learning or a real Cell split.
Source verification and learning/evaluation have separate execution entrypoints.
No incumbent Hepta worker, signer, authority, NDU or artifact owner is replaced.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import time
from zipfile import ZipFile

import numpy as np
from safetensors.numpy import load as load_numpy, save as save_numpy
import torch
from torch import nn
from torch.nn import functional as F

ARCHIVE_SHA = '0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
FEATURE_SHA = 'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
DATA_SHA = '50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c'
STAGED_SOURCE_SHA = '69bdb09bb235c9cf490da400e239c5d9fabe8e13327cb255721090ea47d2e096'
STAGED_TRAIN_FEATURE_SHA = '2530b62d48b593cebeeb783c3ee754f8229b924558340dd09fb7160c6d1e3cc3'
V14_INPUT_SHA = 'd029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a'
ORIGINAL_PRODUCER = '4133d6ac5bd3f8d4200c56fffb09e6aba004a084'
V14_SCHEMA = 'hepta.stem.counterfactual-split.v14.research'
SCHEMA = 'hepta.stem.v32.original-cell-prequential-trainonly.v1'
SEEDS = (41, 47, 53)
ARMS = ('nochange', 'continued', 'rehearsal', 'split', 'source_blind_ensemble')
WIDTH, CLASSES = 384, 4
CELL_COUNTS = (32, 32)
FOLDS, STEPS, BATCH = 4, 40, 16
LR = 0.07


def require(check: bool, why: str) -> None:
    if not check:
        raise ValueError(why)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def strict_json(raw: bytes):
    def distinct(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, 'duplicate JSON key')
            result[k] = v
        return result
    def reject(_):
        raise ValueError('nonfinite source JSON constant')
    d = json.loads(raw, object_pairs_hook=distinct, parse_constant=reject)
    canonical(d)
    return d


def write_only(path: Path, data: bytes):
    require(type(data) is bytes and 0 < len(data) <= 8_000_000, 'unsafe output length')
    require(path.parent.is_dir() and not path.parent.is_symlink() and not path.is_symlink(),
            'unsafe output destination')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush(); os.fsync(f.fileno())


def verified_file(path: Path, expected: str | None = None) -> bytes:
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 8_000_000,
            'source file absent, unsafe or overlarge')
    data = path.read_bytes()
    if expected is not None:
        require(sha(data) == expected, 'source file changed from immutable evidence')
    return data


def archive_source(archive: Path):
    """Read original publisher material only in the stage-only command."""
    require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size < 2_000_000,
            'missing/oversize original pretrained artifact')
    require(sha(archive.read_bytes()) == ARCHIVE_SHA, 'unverified original full ZIP')
    with ZipFile(archive) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) and len(names) < 160 and
                all(not n.startswith('/') and '..' not in Path(n).parts for n in names),
                'duplicate or unsafe archive roster')
        raw = z.read('hepta-public-study/dataset.jsonl')
        features = z.read('hepta-public-study/execution/frozen-features/features.safetensors')
        manifest = strict_json(z.read('hepta-public-study/execution/frozen-features/manifest.json'))
        require(z.read('hepta-pretrained-source.txt').decode().splitlines()[0] == ORIGINAL_PRODUCER,
                'unknown original pretrained source')
    require(sha(raw) == DATA_SHA and sha(features) == FEATURE_SHA and
            manifest.get('file_sha256') == FEATURE_SHA and
            manifest.get('contains_labels') is False and
            manifest.get('production_accepted') is False and
            manifest.get('simulated_encoder') is False,
            'source/weight/label provenance changed')
    rows = [strict_json(x) for x in raw.splitlines()]
    xx = load_numpy(features)
    require(set(xx) == {'features'}, 'original tensor roster altered')
    x = xx['features']
    require(x.shape == (128, WIDTH) and x.dtype == np.float32 and np.isfinite(x).all(),
            'not original real pretrained 128x384 FP32 material')
    require(len(rows) == len(manifest.get('rows', [])) == 128 and
            len({r.get('case_id') for r in rows}) == 128 and
            len({r.get('group') for r in rows}) == 128,
            'wrong independent source identities')
    for row, proof in zip(rows, manifest['rows']):
        require(type(row) is dict and row.get('split') in ('train','calibration','holdout') and
                type(row.get('label')) is int and 0 <= row['label'] < CLASSES and
                type(row.get('cell')) is int and row['cell'] in (0,1) and
                all(row.get(k) == proof.get(k) for k in ('case_id','group','scope','split','cell')),
                'source/label/feature pairing altered')
        digest = sha((json.dumps([row['scope'],row['text']],ensure_ascii=False,
                            separators=(',',':'))+'\n').encode())
        require(proof.get('input_sha256') == digest, 'original text-derived feature identity changed')
    part = {name:[i for i,r in enumerate(rows) if r['split'] == name]
            for name in ('train','calibration','holdout')}
    require([len(part[n]) for n in part] == [64,32,32], 'original source partitions changed')
    # Reconstruct the historical V14 manifest byte-for-byte BEFORE altering what
    # the trainer sees. V14 includes CAL labels, the V32 stage never does.
    v14 = {'schema': V14_SCHEMA, 'archive_sha256': ARCHIVE_SHA,
           'feature_sha256': FEATURE_SHA, 'dataset_sha256': DATA_SHA,
           'roster':[{'case_id':r['case_id'],'group':r['group'],'split':r['split']} for r in rows],
           'partitions':part,
           'labels':{str(i):rows[i]['label'] for i in part['train']+part['calibration']},
           'production_authorized':False}
    require(sha(canonical(v14)) == V14_INPUT_SHA,
            'actual original training/label manifest differs from V14 frozen source')
    tr = part['train']
    original = x[tr].copy()
    # Stage only original frozen feature bytes. Normalization occurs in both
    # independent producer/reviewer using only these same TRAIN rows; no
    # floating-point derived feature snapshot is falsely treated as original.
    trainer_roster = [{'case_id':rows[i]['case_id'], 'group':rows[i]['group'],
                       'cell':rows[i]['cell'], 'split':'train', 'label':rows[i]['label']}
                      for i in tr]
    require([sum(r['cell']==j for r in trainer_roster) for j in (0,1)] == list(CELL_COUNTS),
            'original Cell0/Cell1 not balanced')
    return original.astype('<f4'), trainer_roster


def stage(archive: Path, output: Path):
    x, roster = archive_source(archive)
    require(not output.exists() and not output.is_symlink(), 'stage must be exclusive-create')
    output.mkdir(mode=0o700, parents=False)
    tensor = save_numpy({'features':x})
    meta = {'schema':SCHEMA+'.train-only-source', 'archive_sha256':ARCHIVE_SHA,
            'original_producer_commit':ORIGINAL_PRODUCER,'original_full_feature_sha256':FEATURE_SHA,
            'original_v14_input_sha256':V14_INPUT_SHA,'original_data_sha256':DATA_SHA,
            'train_feature_sha256':sha(tensor),'train_count':64,'train_cell_counts':list(CELL_COUNTS),
            'rows':roster,'calibration_labels_exposed_to_trainer':False,
            'blind_labels_exposed_to_trainer':False,'independent_source_family_count':1,
            'independent_future_windows':0,'production_authorized':False}
    require(sha(tensor) == STAGED_TRAIN_FEATURE_SHA and
            sha(canonical(meta)) == STAGED_SOURCE_SHA,
            'TRAIN-only original byte identity changed; no substitute source')
    write_only(output/'train-features.safetensors', tensor)
    write_only(output/'train-source.json',canonical(meta))
    return meta


def load_train(folder: Path):
    raw = verified_file(folder/'train-source.json', STAGED_SOURCE_SHA)
    meta = strict_json(raw)
    require(type(meta) is dict and meta.get('schema') == SCHEMA+'.train-only-source' and
            meta.get('archive_sha256') == ARCHIVE_SHA and
            meta.get('original_producer_commit') == ORIGINAL_PRODUCER and
            meta.get('original_full_feature_sha256') == FEATURE_SHA and
            meta.get('original_v14_input_sha256') == V14_INPUT_SHA and
            meta.get('original_data_sha256') == DATA_SHA and
            meta.get('train_count') == 64 and meta.get('train_cell_counts') == [32,32] and
            meta.get('independent_source_family_count') == 1 and
            meta.get('independent_future_windows') == 0 and
            meta.get('calibration_labels_exposed_to_trainer') is False and
            meta.get('blind_labels_exposed_to_trainer') is False and
            meta.get('production_authorized') is False,
            'unapproved training source or future/authority claim')
    rows = meta['rows']
    require(type(rows) is list and len(rows) == 64 and
            len({x.get('case_id') for x in rows}) == 64 and
            len({x.get('group') for x in rows}) == 64,
            'missing/duplicate original TRAIN source')
    for r in rows:
        require(type(r) is dict and set(r) == {'case_id','group','cell','split','label'} and
                type(r['cell']) is int and r['cell'] in (0,1) and
                type(r['label']) is int and 0 <= r['label'] < CLASSES and
                r['split'] == 'train' and r['case_id'].startswith('ag-news:train:'),
                'CAL/BLIND or unapproved label exposed to trainer')
    require([sum(r['cell']==c for r in rows) for c in (0,1)] == [32,32],
            'lost Cell routing/census')
    require(meta['train_feature_sha256'] == STAGED_TRAIN_FEATURE_SHA,
            'wrong immutable original TRAIN-only frozen subset')
    tensor = verified_file(folder/'train-features.safetensors', STAGED_TRAIN_FEATURE_SHA)
    t = load_numpy(tensor)
    require(set(t) == {'features'}, 'feature tensor field drift')
    x = t['features']
    require(x.dtype == np.float32 and x.shape == (64, WIDTH) and np.isfinite(x).all(),
            'original TRAIN feature dimension/finite check')
    # The historical V19 exact TRAIN-only normalization, not a new Encoder.
    normalized=(x-x.mean(0))/np.maximum(x.std(0),np.float32(0.1))
    require(np.isfinite(normalized).all(), 'unbounded normalized original features')
    return normalized.astype('<f4'), rows, meta


def split_folds(rows):
    """Four non-leaking groups, 8 withheld old + 8 withheld new per fold."""
    require(len(rows)==64 and all(r['cell'] in (0,1) for r in rows), 'source split preflight')
    folds = []
    for cell in (0,1):
        pairs = sorted((sha(r['case_id'].encode()),i) for i,r in enumerate(rows) if r['cell']==cell)
        require(len(pairs)==32 and len(set(i for _,i in pairs))==32, 'source cell count')
        folds.append([[i for _,i in pairs[j::FOLDS]] for j in range(FOLDS)])
    return [folds[0][k]+folds[1][k] for k in range(FOLDS)]


def head():
    model = nn.Linear(WIDTH,CLASSES)
    with torch.no_grad():
        model.weight.zero_(); model.bias.zero_()
    return model


def state(model):
    return {'w':model.weight.detach().cpu().numpy().astype('<f4').tolist(),
            'b':model.bias.detach().cpu().numpy().astype('<f4').tolist()}


def fit(model, x, y, *, seed:int, cell: int|None, replay:tuple|None=None):
    """40 genuine AdamW updates; each batch exactly 16 observed examples."""
    require(x.shape[1] == WIDTH and y.dtype == torch.long and 0 < len(y) <= 48 and
            type(seed) is int and (cell is None or cell in (0,1)), 'invalid staged model input')
    torch.set_num_threads(1)
    g = torch.Generator().manual_seed(seed)
    optim = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.0)
    before=time.process_time_ns()
    for step in range(STEPS):
        if replay is None:
            select = torch.randint(0,len(x),(BATCH,),generator=g)
            xx,yy=x[select],y[select]
        else:
            xold,yold,xnew,ynew=replay
            require(len(xold)>0 and len(xnew)>0,'replay requires both original TRAIN Cells')
            a=torch.randint(0,len(xold),(BATCH//2,),generator=g)
            b=torch.randint(0,len(xnew),(BATCH//2,),generator=g)
            xx=torch.cat((xold[a],xnew[b]));yy=torch.cat((yold[a],ynew[b]))
        optim.zero_grad(set_to_none=True)
        loss=F.cross_entropy(model(xx),yy)
        require(bool(torch.isfinite(loss)),'unbounded real label-supervised SGD loss')
        loss.backward();optim.step()
    elapsed=time.process_time_ns()-before
    state_bytes=sum(t.numel()*t.element_size() for data in optim.state.values()
                    for t in data.values() if isinstance(t,torch.Tensor))
    require(elapsed>0 and state_bytes>0,'no executed optimizer state or CPU observation')
    return {'updates':STEPS,'batch':BATCH,'source_examples_seen':STEPS*BATCH,
            'cpu_ns':elapsed,'optimizer_state_bytes_observed':state_bytes,
            'source_cell':cell}


def forward_matrix(heads, held, cell_flags):
    """No extra optimizer: two Heads / same 3,080 physical weights for both variants."""
    old,new,continued,rehearsal=heads
    with torch.no_grad():
        old_out=old(held);new_out=new(held)
        mask=(cell_flags==1).unsqueeze(-1)
        return {
            'nochange':old_out,
            'continued':continued(held),
            'rehearsal':rehearsal(held),
            'split':torch.where(mask,new_out,old_out),
            'source_blind_ensemble':(old_out+new_out)/2,
        }


def score(logits, labels):
    p=F.softmax(logits,dim=-1)
    return {'correct':int((p.argmax(-1)==labels).sum().item()),
            'brier':round(float((p-F.one_hot(labels,CLASSES)).square().sum(-1).mean()),9)}


def evaluate(input_folder:Path):
    torch.use_deterministic_algorithms(True)
    x,rows,meta=load_train(input_folder)
    tx=torch.from_numpy(x.copy());labels=torch.tensor([r['label'] for r in rows],dtype=torch.long)
    cell=torch.tensor([r['cell'] for r in rows],dtype=torch.long)
    folds=split_folds(rows)
    per_seed={}
    private={'schema':SCHEMA+'.private-checkpoints', 'train_material_sha256':meta['train_feature_sha256'],
             'case_identity_sha256':sha(canonical(rows)),'research_only':True,
             'records':[],'cal_or_blind_labels_present':False}
    full_updates=0
    for seed in SEEDS:
        sums={arm:{c:[] for c in (0,1)} for arm in ARMS}
        fold_meters=[]
        for fold_index,held_indices in enumerate(folds):
            held=set(held_indices)
            oix=[i for i,r in enumerate(rows) if i not in held and r['cell']==0]
            nix=[i for i,r in enumerate(rows) if i not in held and r['cell']==1]
            require(len(oix)==len(nix)==24 and len(held_indices)==16 and
                    sum(rows[i]['cell']==0 for i in held_indices)==8,
                    'original TRAIN cross-fitting subset leakage')
            stage1=head()
            meter_old=fit(stage1,tx[oix],labels[oix],seed=seed*1000+fold_index*10,cell=0)
            keep=deepcopy(stage1)
            cont=deepcopy(stage1)
            rehearse=deepcopy(stage1)
            meter_cont=fit(cont,tx[nix],labels[nix],seed=seed*1000+fold_index*10+1,cell=1)
            meter_replay=fit(rehearse,tx[nix],labels[nix],seed=seed*1000+fold_index*10+1,
                             cell=None,replay=(tx[oix],labels[oix],tx[nix],labels[nix]))
            # Split directly borrows the SAME trained continuation state as its
            # second Cell. Re-training an identical copy wastes Head compute.
            new=cont
            full_updates+=sum(m['updates'] for m in (meter_old,meter_cont,meter_replay))
            predictions=forward_matrix((keep,new,cont,rehearse),tx[held_indices],cell[held_indices])
            for arm,logits in predictions.items():
                for c in (0,1):
                    index=[j for j,i in enumerate(held_indices) if rows[i]['cell']==c]
                    sums[arm][c].append((logits[index].detach().cpu(),labels[[held_indices[j] for j in index]]))
            private['records'].append({'seed':seed,'fold':fold_index,
                'train_old_case_ids':[rows[i]['case_id'] for i in oix],
                'train_new_case_ids':[rows[i]['case_id'] for i in nix],
                'held_case_ids':[rows[i]['case_id'] for i in held_indices],
                'held_source_cell':[rows[i]['cell'] for i in held_indices],
                'weights':{n:state(m) for n,m in [('old',keep),('new',new),('continued',cont),('rehearsal',rehearse)]},
                'weights_sha256':{n:sha(m.weight.detach().cpu().numpy().astype('<f4').tobytes()+
                                        m.bias.detach().cpu().numpy().astype('<f4').tobytes())
                                  for n,m in [('old',keep),('new',new),('continued',cont),('rehearsal',rehearse)]},
                'logits':{arm:pred.detach().cpu().numpy().astype('<f4').tolist()
                          for arm,pred in predictions.items()},
                'logits_sha256':{arm:sha(pred.detach().cpu().numpy().astype('<f4').tobytes())
                                 for arm,pred in predictions.items()},
                'cost':{'old':meter_old,'continued':meter_cont,
                        'rehearsal':meter_replay},
                'split_new_model_state_reuses_continued':True})
            fold_meters.append({key:{'cpu_ns':val['cpu_ns'],
                                      'optimizer_state_bytes':val['optimizer_state_bytes_observed']}
                                for key,val in private['records'][-1]['cost'].items()})
        seed_result={}
        for arm in ARMS:
            by_cell={}
            for c in (0,1):
                z=sums[arm][c]
                logits=torch.cat([l for l,_ in z]);gold=torch.cat([y for _,y in z])
                require(len(gold)==32,'source Cell not cross-fitted exactly once')
                by_cell[str(c)]=score(logits,gold)
            seed_result[arm]={'cell0_old_oof':by_cell['0'],
                              'cell1_new_oof':by_cell['1'],
                              'total_correct':by_cell['0']['correct']+by_cell['1']['correct'],
                              'total_cases':64}
        per_seed[str(seed)]={'folds':4,'arms':seed_result,'fold_cost':fold_meters}
    require(full_updates == len(SEEDS)*FOLDS*3*STEPS,
            'physical optimizer update budget not paid')
    return ({'schema':SCHEMA+'.sanitized', 'original_archive_sha256':ARCHIVE_SHA,
       'original_feature_sha256':FEATURE_SHA,'original_v14_source_sha256':V14_INPUT_SHA,
       'train_feature_sha256':meta['train_feature_sha256'],
       'train_rows':64,'original_old_cell0_rows':32,'original_new_cell1_rows':32,
       'train_only_oof_cases_per_seed':64,'fold_count':FOLDS,'seeds':list(SEEDS),
       'arms':list(ARMS),'stage1_steps':STEPS,'stage2_steps':STEPS,
       'total_physical_optimizer_updates_paid':full_updates,
       'shared_encoder_additional_forwards':0,'cell_head_parameters':1540,
       'two_head_parameters':3080,'two_head_model_weight_bytes_fp32':12320,
       'source_blind_ensemble_shares_exact_split_weights':True,
       'split_new_model_reuses_continued_head_without_duplicate_training':True,
       'observed_training_cpu_ns_included_per_fold':True,
       'per_seed':per_seed, 'source_family_count':1,'chronological_future_windows':0,
       'calibration_labels_used_for_selection':False,'blind_labels_used':False,
       'readout_is_out_of_fold_original_train_not_future':True,
       'independent_model_training_gradient_review':False,
       'independent_heldout_label_custody':False,
       'end_to_end_serving_benchmark_attested':False,
       'ndu_selection_authorized':False,'final_use_authorized':False,
       'model_or_cell_split_authorized':False,'production_authorized':False,
       'decision':'HOLD_ORIGINAL_TRAIN_OOF_NO_PROSPECTIVE_SELECTION',
       'authority':'DENY_ALL'},private)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='mode',required=True)
    st=sub.add_parser('stage');st.add_argument('--archive',type=Path,required=True)
    st.add_argument('--out',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('--source',type=Path,required=True)
    run.add_argument('--output',type=Path,required=True)
    run.add_argument('--private',type=Path,required=True)
    a=p.parse_args()
    if a.mode=='stage':
        m=stage(a.archive,a.out)
        print(json.dumps({'schema':m['schema'],'case_count':m['train_count'],
                          'future_windows':0,'production_authorized':False}))
    else:
        require(not a.output.exists() and not a.private.exists(),
                'research outcome must be create-only')
        report,private=evaluate(a.source)
        write_only(a.output,canonical(report))
        write_only(a.private,canonical(private))
        print(json.dumps({'decision':report['decision'],
                          'physical_training_updates':report['total_physical_optimizer_updates_paid'],
                          'new_encoder_forwards':0}))

if __name__=='__main__':main()

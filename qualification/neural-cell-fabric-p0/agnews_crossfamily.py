"""P0.5 independent historical AG News/mmBERT publisher-family context panel.

Original archive SHA256 and five inner digests are immutable. This retrospective
cross-task panel contrasts real learned original public model outputs against
cheap TRAIN-only route priors, but task/model/label-space and fitting budgets
DIFFER from ModernBERT BANKING77. Never pool their accuracy/p-values or treat
this as a prospective, source-independent specialization certification.

Crucially this original publisher study packs HOLDOUT gold in the same dataset
ZIP as the prelabel outputs: it CANNOT be claimed label-blind or prospective.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
from zipfile import ZipFile, BadZipFile

from fabric import Denied, sha
from original_replay import _no_duplicate_pairs, _no_nonfinite
from science_gate import exact_mcnemar

ARCHIVE_SHA256 = '0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
MEMBERS = {
    'hepta-public-study/dataset.jsonl': '50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c',
    'hepta-public-study/execution/predictions.json': '88c9bb484f7e178686a4314f3c234bc6f4fd080057b0a5e80abcb785bc03edb9',
    'hepta-public-study/execution/frozen-features/manifest.json': '39f3f5c52863147bdd8b21f24e32098867277505f66ff3385a2e454e84d92910',
    'hepta-public-study/execution/frozen-features/features.safetensors': 'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490',
    'hepta-public-study/execution/report.json': '0d9cfb537d9780bdccc3fab1607fe1e78bc9fa994c04280d3cf98eb89b44cbc4',
}
ARMS = ('gated', 'linear', 'low_rank', 'sparse_expert')


def _strict_json(blob: bytes):
    return json.loads(blob, object_pairs_hook=_no_duplicate_pairs, parse_constant=_no_nonfinite)


def read_original(path: Path) -> dict:
    if path.is_symlink():
        raise Denied('original artifact symlink')
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as reader:
            if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
                raise Denied('original archive must be regular')
            b = reader.read(2_000_001)
        if len(b)>2_000_000 or sha(b)!=ARCHIVE_SHA256:
            raise Denied('source-locked original archival SHA256 mismatch')
        with ZipFile(io.BytesIO(b)) as z:
            payload={}
            for name, digest in MEMBERS.items():
                info=z.getinfo(name)
                if info.is_dir() or not 0 < info.file_size < 1_000_000:
                    raise Denied('unsafe source member')
                original=z.read(name)
                if sha(original)!=digest:
                    raise Denied('historical original member changed')
                payload[name.split('hepta-public-study/',1)[1]]=original
            return payload
    except (OSError, KeyError, BadZipFile, UnicodeError, ValueError) as e:
        if isinstance(e,Denied):
            raise
        raise Denied('cannot independently verify archived original') from e


def _argmax(x):
    if type(x) is not list or len(x)!=4 or any(type(y) not in (int,float) or not math.isfinite(y) or not 0<=y<=1 for y in x):
        raise Denied('invalid published original probability vector')
    if abs(math.fsum(x)-1) > 1e-5:
        raise Denied('probabilities not normalized')
    return max(range(4),key=lambda j:x[j])


def evaluate(raw: dict[str,bytes]) -> dict:
    expected = {k.split('hepta-public-study/',1)[1] for k in MEMBERS}
    if set(raw)!=expected:
        raise Denied('incomplete original publisher packets')
    rows = [_strict_json(line) for line in raw['dataset.jsonl'].splitlines()]
    predictions=_strict_json(raw['execution/predictions.json'])['predictions']
    manifest=_strict_json(raw['execution/frozen-features/manifest.json'])
    receipt=_strict_json(raw['execution/report.json'])
    if (len(rows)!=128 or manifest['shape']!=[128,384] or manifest['simulated_encoder'] is not False
            or manifest['file_sha256']!=MEMBERS['hepta-public-study/execution/frozen-features/features.safetensors']
            or len(manifest['rows'])!=128 or receipt['encoding']['simulated_encoder'] is not False
            or receipt['encoding']['encoder_forward_calls'] != 16
            or receipt['production_accepted'] is not False or len(predictions)!=128):
        raise Denied('archived original pretrained corpus/inference lineage drift')
    seen=set(); splits={'train':[],'calibration':[],'holdout':[]}
    for source, feature in zip(rows,manifest['rows'],strict=True):
        if (type(source.get('case_id')) is not str or source['case_id'] in seen
                or source.get('split') not in splits or source.get('group')!=source['case_id']
                or source.get('cell') not in (0,1) or type(source.get('label')) is not int
                or source['label'] not in range(4) or source['case_id']!=feature.get('case_id')
                or source['split']!=feature.get('split') or source['cell']!=feature.get('cell')):
            raise Denied('source-root, label or Cell route drift')
        seen.add(source['case_id']);splits[source['split']].append(source)
    if {s:len(v) for s,v in splits.items()}!={'train':64,'calibration':32,'holdout':32}:
        raise Denied('original publisher source cohort mismatch')
    for sample in splits['calibration']:
        # Calibration is NOT used by any cheap baseline here, as a predeclared control.
        if sample['case_id'] in {x['case_id'] for x in splits['train']}:
            raise Denied('calibration train leakage')
    bycell={k:Counter() for k in (0,1)}
    global_count=Counter()
    for r in splits['train']:
        bycell[r['cell']][r['label']]+=1;global_count[r['label']]+=1
    priors={cell:[(c[k]+1)/(sum(c.values())+4) for k in range(4)] for cell,c in bycell.items()}
    overall=[(global_count[k]+1)/(len(splits['train'])+4) for k in range(4)]
    truth={r['case_id']:r['label'] for r in splits['holdout']}
    subtype={r['case_id']:r['cell'] for r in splits['holdout']}
    held_ids=[r['case_id'] for r in splits['holdout']]
    expected_keys={(arm,case_id) for arm in ARMS for case_id in held_ids}
    found={};
    for prediction in predictions:
        if (prediction.get('arm') not in ARMS or prediction.get('case_id') not in truth or
                prediction.get('cell')!=subtype.get(prediction.get('case_id')) or
                prediction.get('split')!='holdout' or prediction.get('group')!=prediction.get('case_id')):
            raise Denied('historical prediction lineage mismatch')
        key=(prediction['arm'],prediction['case_id'])
        if key in found:
            raise Denied('duplicate model forward output')
        _argmax(prediction.get('probabilities'))
        _argmax(prediction.get('frozen_probabilities'))
        found[key]=prediction
    if set(found)!=expected_keys:
        raise Denied('original model prediction set incomplete')
    decisions={name:{} for name in ('route_prior','global_prior',*ARMS)}
    outcomes={}
    briers={}
    for name in decisions:
        costs=[]
        for item in splits['holdout']:
            sample=item['case_id'];y=truth[sample]
            if name=='route_prior': p=priors[item['cell']]
            elif name=='global_prior': p=overall
            else:p=found[(name,sample)]['probabilities']
            decisions[name][sample]=_argmax(p)
            costs.append(math.fsum((v-int(k==y))**2 for k,v in enumerate(p)))
        outcomes[name]=sum(decisions[name][k]==truth[k] for k in held_ids)
        briers[name]=math.fsum(costs)/32
    comparisons={}
    for arm in ARMS:
        wins=sum(decisions[arm][key]==truth[key] and decisions['route_prior'][key]!=truth[key] for key in held_ids)
        losses=sum(decisions[arm][key]!=truth[key] and decisions['route_prior'][key]==truth[key] for key in held_ids)
        frozen=sum(_argmax(found[(arm,key)]['frozen_probabilities'])==truth[key] for key in held_ids)
        comparisons[arm]={'wins_vs_route_prior':wins,'losses_vs_route_prior':losses,
                          'nominal_posthoc_exact_p':exact_mcnemar(wins,losses),
                          'frozen_untrained_head_correct':frozen}
    return {
        'schema':'hepta.cell-fabric.p05.agnews-mmbert-original-posthoc.v1',
        'archive_sha256':ARCHIVE_SHA256,
        'inner_sha256':{k:MEMBERS[k] for k in sorted(MEMBERS)},
        'original_run_id':38546717991,
        'different_publisher_and_task_from_banking77':True,
        'original_pretrained_features_real':True,
        'original_feature_rows':128,
        'original_encoder_batch_forward_calls_from_receipt':16,
        'fresh_pretrained_forward_calls':0,
        'train_rows':64,'calibration_rows_unused':32,'held_rows':32,
        'four_class_route_prior_train_only_dirichlet_alpha':1,
        'train_cell_label_counts':{str(c):{str(k):bycell[c][k] for k in range(4)} for c in (0,1)},
        'correct':outcomes,'brier':briers,'paired':comparisons,
        'original_labels_co_resident_with_producer_material':True,
        'independent_blind_heldout_custody':False,
        'new_pretrained_training':False,
        'same_model_or_task_or_head_budget_as_modernbert_banking77':False,
        'cell_split_causal_gain_verified':False,
        'multi_publisher_prospective_generalization_verified':False,
        'system2_ndu_or_multimodal_generation_verified':False,
        'production_authorized':False,
        'disposition':'HOLD_NO_GO','authority':'DENY_ALL',
    }


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise Denied('create-only report required')
    report=evaluate(read_original(args.archive))
    raw=(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    fd=os.open(args.output, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
    print(json.dumps({'sha256':sha(raw),'authority':'DENY_ALL','held':32},sort_keys=True))


if __name__=='__main__':
    main()

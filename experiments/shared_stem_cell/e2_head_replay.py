"""Research-only independent E2 Q24 Token Matrix + Head safetensors replay.

This validates observed Head probabilities from *actual serialized Head tensors*
and from a complete, original-case-bound frozen feature bank, but does not
attest underlying pretrained model weights, future outcomes, or production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import torch
from torch.nn import functional as F
from safetensors.torch import load_file, save_file

from e2_token_query_ablation import (
    Head, _digest_module, _materialize, frozen_bank, Invalid as FeatureInvalid,
)

SCHEMA = 'hepta.stem.e2-head-replay-bundle.v1'
REVIEW_SCHEMA = 'hepta.stem.e2-head-replay-readonly-audit.v1'
ARMS = ('pooled_linear', 'pooled_gated', 'token_query')
SPLITS = ('calibration', 'test')
MAX_FEATURE_FILE = 450 * 1024 * 1024
MAX_HEAD_FILE = 1024 * 1024
MAX_JSON = 512 * 1024
MAX_ROWS = 224

class Invalid(ValueError):
    pass


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _checked(path: Path, max_bytes: int):
    if path.is_symlink() or not path.is_file():
        raise Invalid('missing or linked evidence file')
    size = path.stat().st_size
    if not 0 < size <= max_bytes:
        raise Invalid('empty or excessive replay bytes')
    return path.read_bytes()


def _load_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise Invalid('duplicate evidence field')
            out[k] = v
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(Invalid('nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise Invalid('invalid replay JSON') from exc


def _source_rows(cases):
    if type(cases) is not list or len(cases) != MAX_ROWS:
        raise Invalid('bounded original case count required')
    out = []
    for row in cases:
        if type(row) is not dict:
            raise Invalid('bad original source row')
        cid = row.get('case_id')
        split = row.get('split')
        digest = row.get('joint_input_digest')
        group = row.get('source_group', row.get('group_id'))
        if (type(cid) is not str or not cid or len(cid)>128 or
            split not in ('train', *SPLITS) or type(group) is not str or not group or
            type(digest) is not str or len(digest) != 64 or
            any(c not in '0123456789abcdef' for c in digest)):
            raise Invalid('missing source identity, split or original digest')
        out.append({'case_id': cid, 'split': split,
                    'source_group': group, 'joint_input_digest': digest})
    if len({r['case_id'] for r in out}) != MAX_ROWS:
        raise Invalid('duplicate source case')
    return out


def _head_inventory(head_states, width):
    if type(head_states) is not dict or set(head_states) != set(ARMS):
        raise Invalid('incomplete frozen/learned Head inventory')
    out = {}
    for kind in ARMS:
        for status in ('frozen', 'learned'):
            obj = head_states[kind].get(status)
            if type(obj) is not dict:
                raise Invalid('missing original Head state')
            h = Head(width, kind, torch.zeros(width, dtype=torch.float32))
            if set(obj) != set(h.state_dict()):
                raise Invalid('mismatched complete Head state names')
            for name, expected in h.state_dict().items():
                val = obj[name]
                if (not isinstance(val, torch.Tensor) or val.device.type != 'cpu' or
                        val.dtype != torch.float32 or tuple(val.shape) != tuple(expected.shape)
                        or not bool(torch.isfinite(val).all())):
                    raise Invalid('mismatched or nonfinite saved Head parameters')
                out[f'{kind}.{status}.{name}'] = val.detach().clone().contiguous()
    return out


def write_bundle(root: Path, cases: list, snapshots: dict, head_states: dict,
                 result: dict, report_sha256: str):
    """Create-only complete replay. Caller has already written sealed report."""
    if root.exists():
        raise FileExistsError('E2 evidence destination must be new')
    width = result.get('head_study', {}).get('width')
    if width not in (384,768) or len(report_sha256)!=64:
        raise Invalid('wrong original E2 report identity/width')
    original = frozen_bank(cases, snapshots, width=width)
    if result.get('feature_bank') != original or result['head_study'].get('feature_bank') != original:
        raise Invalid('E2 feature bank identity drift before serialization')
    groups = _source_rows(cases)
    if any(type(row.get('label')) is not int or row['label'] not in (0,1) for row in cases):
        raise Invalid('source panel labels not complete')
    lengths = [snapshots[row['case_id']]['tokens'].shape[0] for row in cases]
    offsets=[0]
    for n in lengths:
        offsets.append(offsets[-1]+n)
    contents={
        'tokens':torch.cat([snapshots[row['case_id']]['tokens'] for row in cases],dim=0).contiguous(),
        'pooled':torch.stack([snapshots[row['case_id']]['native_pooled'] for row in cases]).contiguous(),
        'offsets':torch.tensor(offsets, dtype=torch.int64),
    }
    heads=_head_inventory(head_states,width)
    root.mkdir(parents=True, exist_ok=False)
    save_file(contents, str(root/'features.safetensors'))
    save_file(heads, str(root/'heads.safetensors'))
    with (root/'case-identity.json').open('xb') as stream:
        stream.write(_canonical({'rows':groups}))
    hashes={name:_sha(_checked(root/name,limit)) for name,limit in (
        ('features.safetensors',MAX_FEATURE_FILE),
        ('heads.safetensors',MAX_HEAD_FILE),
        ('case-identity.json',MAX_JSON))}
    manifest={'schema':SCHEMA,'width':width,'case_count':MAX_ROWS,
              'source_report_sha256':report_sha256,
              'frozen_bank_sha256':original['frozen_token_and_native_pooled_sha256'],
              'files_sha256':hashes,
              'pretrained_origin_independently_authenticated':False,
              'production_promotion_permitted':False,'authority':'DENY_ALL'}
    with (root/'manifest.json').open('xb') as stream:
        stream.write(_canonical(manifest))
    return manifest


def review(root: Path, cases: list[dict], report: dict, report_sha256: str):
    """Recompute every frozen/learned probability from untrusted safe tensors."""
    if root.is_symlink() or not root.is_dir():
        raise Invalid('missing regular replay bundle directory')
    manifest=_load_json(_checked(root/'manifest.json',MAX_JSON))
    width=report.get('head_study',{}).get('width')
    if (type(manifest) is not dict or set(manifest)!={
        'schema','width','case_count','source_report_sha256','frozen_bank_sha256',
        'files_sha256','pretrained_origin_independently_authenticated',
        'production_promotion_permitted','authority'} or
            manifest['schema']!=SCHEMA or manifest['width']!=width or
            manifest['case_count']!=MAX_ROWS or
            manifest['source_report_sha256']!=report_sha256 or
            manifest['pretrained_origin_independently_authenticated'] is not False or
            manifest['production_promotion_permitted'] is not False or manifest['authority']!='DENY_ALL'):
        raise Invalid('E2 serialized research provenance/authority mismatch')
    files=manifest['files_sha256']
    if type(files) is not dict or set(files)!=set(('features.safetensors','heads.safetensors','case-identity.json')):
        raise Invalid('incomplete replay evidence')
    for name,limit in [('features.safetensors',MAX_FEATURE_FILE),('heads.safetensors',MAX_HEAD_FILE),('case-identity.json',MAX_JSON)]:
        if _sha(_checked(root/name,limit))!=files[name]:
            raise Invalid('changed replay weight/feature/source file')
    source=_load_json((root/'case-identity.json').read_bytes())
    if source!={'rows':_source_rows(cases)}:
        raise Invalid('original case group/input identity drift')
    tensors=load_file(str(root/'features.safetensors'),device='cpu')
    heads=load_file(str(root/'heads.safetensors'),device='cpu')
    if set(tensors)!=set(('tokens','pooled','offsets')):
        raise Invalid('wrong complete frozen feature tensor set')
    off=tensors['offsets'];tokens=tensors['tokens'];pooled=tensors['pooled']
    if (off.dtype!=torch.int64 or tuple(off.shape)!=(MAX_ROWS+1,) or
        tokens.dtype!=torch.float32 or pooled.dtype!=torch.float32 or
        tokens.ndim!=2 or tokens.shape[1]!=width or tuple(pooled.shape)!=(MAX_ROWS,width)):
        raise Invalid('unregistered replay tensor type/shape')
    boundaries=off.tolist()
    if (boundaries[0]!=0 or boundaries[-1]!=len(tokens) or
        any(not 1<=b-a<=512 for a,b in zip(boundaries,boundaries[1:]))):
        raise Invalid('overlapping/empty/unbounded token offsets')
    snapshots={}
    for i,row in enumerate(cases):
        snapshots[row['case_id']]={'tokens':tokens[boundaries[i]:boundaries[i+1]].contiguous(),
                                   'native_pooled':pooled[i].contiguous()}
    try:
        actual=frozen_bank(cases,snapshots,width=width)
    except FeatureInvalid as exc:
        raise Invalid('replay tensors differ from canonical Q24 frozen bank') from exc
    if (report.get('feature_bank')!=actual or
        report['head_study'].get('feature_bank')!=actual or
        manifest['frozen_bank_sha256']!=actual['frozen_token_and_native_pooled_sha256']):
        raise Invalid('replay is not the producer frozen feature bank')
    if set(heads)!=set(_head_inventory({kind:{status:{name:torch.zeros_like(t)
         for name,t in Head(width,kind,torch.zeros(width)).state_dict().items()}
         for status in ('frozen','learned')} for kind in ARMS},width)):
        raise Invalid('missing or injected Head checkpoint tensor')
    scored=[row for row in cases if row['split'] in SPLITS]
    data,mask,pool=_materialize(scored,snapshots,width)
    calibration=[row for row in scored if row['split']=='calibration']
    cal_data,cal_mask,cal_pool=_materialize(calibration,snapshots,width)
    cal_labels=torch.tensor([row['label'] for row in calibration],dtype=torch.long)
    complete=0;max_abs=0.0
    for kind in ARMS:
        obs=report['head_study']['arms'][kind]
        if obs['train_receipt']['initial_head_sha256']!=obs['frozen_initial_head_sha256']:
            raise Invalid('original frozen/learned initialization identity drift')
        for status,report_key,digest in (
            ('frozen','frozen_predictions',obs['frozen_initial_head_sha256']),
            ('learned','predictions',obs['train_receipt']['final_head_sha256'])):
            model=Head(width,kind,torch.zeros(width,dtype=torch.float32))
            payload={name:heads[f'{kind}.{status}.{name}'] for name in model.state_dict()}
            model.load_state_dict(payload,strict=True)
            if _digest_module(model)!=digest:
                raise Invalid('actual serialized Head tensors differ from report digest')
            temperature=obs['frozen_calibration_temperature'] if status=='frozen' else obs['calibration_temperature']
            if temperature not in (.5,.75,1.,1.5,2.,3.,4.):
                raise Invalid('unregistered Head temperature')
            predictions=obs.get(report_key)
            if type(predictions) is not list or len(predictions)!=96:
                raise Invalid('missing original E2 Head predictions')
            with torch.no_grad():
                logits=model(data,mask,pool)
                calibration_logits=model(cal_data,cal_mask,cal_pool)
                calibrations=(.5,.75,1.,1.5,2.,3.,4.)
                best=min(calibrations,key=lambda t:float(F.cross_entropy(calibration_logits/t,cal_labels)))
                if temperature!=best:
                    raise Invalid('calibration temperature differs from original checkpoint')
                if status=='frozen' and _sha(logits.cpu().contiguous().numpy().tobytes())!=obs['frozen_initial_predictions_sha256']:
                    raise Invalid('frozen original raw Head logits checksum drift')
                values=F.softmax(logits/temperature,dim=-1)[:,1].tolist()
            byid={x['case_id']:x for x in predictions}
            if len(byid)!=96 or set(byid)!={row['case_id'] for row in scored}:
                raise Invalid('duplicate/missing original prediction')
            for row,p in zip(scored,values):
                source=byid[row['case_id']]
                v=source.get('positive_probability')
                if (source.get('split')!=row['split'] or
                    source.get('joint_input_digest')!=row['joint_input_digest'] or
                    type(v) not in (int,float) or not math.isfinite(v)):
                    raise Invalid('source or probability drift')
                err=abs(float(v)-p)
                max_abs=max(max_abs,err)
                if err>1e-5:
                    raise Invalid('checkpoint fails independent probability replay')
                complete+=1
    return {'schema':REVIEW_SCHEMA,'original_case_count':MAX_ROWS,
            'heads_replayed':len(ARMS)*2,'predictions_replayed':complete,
            'max_probability_absolute_error':max_abs,
            'real_pretrained_execution_independently_verified':False,
            'independent_future_ndu_verified':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel',type=Path,required=True)
    parser.add_argument('--producer',type=Path,required=True)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    if a.output.exists():
        raise FileExistsError('replay evidence is create-only')
    from e1_public_triplet_real_cpu import load_panel
    panel,_=load_panel(a.panel)
    source=_checked(a.producer,MAX_JSON*8)
    report=_load_json(source)
    value=review(a.bundle,panel['cases'],report,_sha(source))
    with a.output.open('xb') as stream:
        stream.write(_canonical(value))


if __name__=='__main__':
    main()

"""Independent stdlib-only prelabel replay of original 64-FIT centroid LOO.

No torch, no pretrained encoder, no training implementation imports, no TEST
labels.  This independently verifies a FIT-only temperature selection from a
source-bound FP32 witness and makes no model-origin or efficacy assertion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct

SCHEMA = 'hepta.stem.fit-feature-witness-fp32.v7'
REVIEW_SCHEMA = 'hepta.stem.independent-fit-loo-review.v7'
TEMPERATURES = (1.0,0.5,0.25,0.125,0.0625,0.03125,0.015625)
MODEL_REPO = 'google/embeddinggemma-2'
MODEL_REVISION = '914f7f89142e33e77833254d9c9b90c3cef7303b'
MODEL_WEIGHT_SHA = '197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79'
PROJECTION = 'adjacent_pair_mean_l2_768_to_384_v1'
DOMAIN = b'hepta.stem.cal-fit-fp32.v5\0'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique_pairs(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate FIT proof JSON key')
        result[key]=value
    return result


def read(path, max_bytes=2_000_000):
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= max_bytes,
            'missing/unbounded/symlinked witness source')
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=_unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite FIT witness')))


def norm(row):
    norm=math.sqrt(math.fsum(v*v for v in row))
    require(norm > 1e-5 and math.isfinite(norm),'degenerate FIT centroid')
    return [v/norm for v in row]


def probability(logits, temperature):
    z=[x/temperature for x in logits]
    peak=max(z)
    scores=[math.exp(x-peak) for x in z]
    total=math.fsum(scores)
    return [v/total for v in scores]


def verify(source, witness, receipt):
    require(type(source) is dict and type(witness) is dict and type(receipt) is dict,
            'invalid FIT-only material')
    require(set(witness) == {'schema','source_plan_sha256','model_weights_sha256',
                            'feature_projection','rows','train_feature_digest',
                            'label_free_heldout','model_origin_independently_attested',
                            'production_authorized'},'unexpected FIT witness fields')
    require(witness['schema'] == SCHEMA and
            witness['source_plan_sha256'] == source.get('source_plan_sha256') == receipt.get('source_plan_sha256')
            and witness['model_weights_sha256'] == MODEL_WEIGHT_SHA == receipt.get('actual_weight_sha256')
            and witness['feature_projection'] == PROJECTION == receipt.get('projection')
            and receipt.get('model_repo') == MODEL_REPO and receipt.get('model_revision') == MODEL_REVISION
            and witness['label_free_heldout'] is True
            and witness['model_origin_independently_attested'] is False
            and witness['production_authorized'] is False
            and receipt.get('production_authorized') is False
            and receipt.get('authority') == 'DENY_ALL',
            'model, source or authority drift in FIT witness')
    fit=source.get('train')
    rows=witness['rows']
    require(type(fit) is list and len(fit) == 64 and
            type(rows) is list and len(rows) == 64,
            'FIT-only original roster incomplete')
    held=source.get('heldout')
    require(type(held) is list and len(held)==32 and
            all(type(row) is dict and set(row)=={'case_id','source_sha256','text'}
                for row in held), 'TEST gold leaked into FIT-only review')
    require(type(source.get('source_plan_sha256')) is str and
            source['source_plan_sha256']==_sha(json.dumps(
                {k:v for k,v in source.items() if k!='source_plan_sha256'},
                ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False
            ).encode('utf-8')), 'registered source plan digest mismatch')
    require(receipt.get('fit_feature_witness_sha256')==_sha(json.dumps(
                witness,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False
            ).encode('utf-8')), 'original sealed FIT witness not tied to model output')
    original_by_class=[0,0,0,0]
    digest=hashlib.sha256()
    digest.update(DOMAIN)
    features=[]
    fit_labels=[]
    seen=set()
    for actual, expected in zip(rows, fit):
        require(type(expected) is dict and set(expected)=={'case_id','source_sha256','text','label'}
                and type(actual) is dict and set(actual)=={'case_id','source_sha256','fp32'}
                and actual['case_id'] == expected['case_id']
                and actual['source_sha256'] == expected['source_sha256']
                and isinstance(actual['case_id'],str) and actual['case_id'].startswith('fit:')
                and actual['case_id'] not in seen,
                'FIT identity, order, duplicate or label leak')
        require(expected['case_id']=='fit:'+_sha(expected['text'].encode('utf-8'))
                and expected['source_sha256']==_sha(expected['text'].encode('utf-8')),
                'FIT publisher text/source identity not bound')
        seen.add(actual['case_id'])
        label=expected['label']
        require(type(label) is int and 0 <= label < 4,'invalid source FIT label')
        vec=actual['fp32']
        require(type(vec) is list and len(vec)==384 and all(type(x) in (float,int)
                and math.isfinite(x) and -1.01 <= x <= 1.01 for x in vec),
                'invalid original FIT vector')
        require(abs(math.fsum(x*x for x in vec)-1)<2e-3,
                'FIT vector not normalized as the original frozen projection')
        raw=struct.pack('<384f',*vec)
        require(all(float(v)==float(x) for v,x in zip(struct.unpack('<384f',raw),vec)),
                'witness is not an exact finite FP32 tensor vector')
        digest.update(raw)
        features.append(vec)
        fit_labels.append(label)
        original_by_class[label]+=1
        # Use math.fsum for each class/coordinate at the final reduction, not here.
    require(original_by_class == [16]*4, 'FIT class balance is not original')
    digest.update(bytes(fit_labels))
    ctr=receipt.get('train_only_centroid')
    require(type(ctr) is dict and
            digest.hexdigest()==witness['train_feature_digest']==ctr.get('train_feature_digest'),
            'FIT source tensor/label bytes mismatch')
    require(type(ctr.get('fit_only_loocv_multiclass_brier')) is list and
            ctr.get('registered_temperatures') == list(TEMPERATURES)
            and ctr.get('fit_per_class_counts') == [16]*4 and
            ctr.get('fit_examples') == 64 and
            ctr.get('heldout_labels_used_for_calibration') is False and
            ctr.get('new_head_sgd_steps') == 0 and
            ctr.get('new_model_forward_calls') == 0,
            'calibration source or budget substitution')
    # Independently reproduce the 64 leave-one-out predictions with full
    # double-precision accumulation; producer uses Torch CPU FP32.  We bound
    # their expected rounding differences, refusing a case where a close
    # argmin would be numerically ambiguous rather than inventing a winner.
    sums=[]
    for cl in range(4):
        group=[f for f,y in zip(features,fit_labels) if y==cl]
        sums.append([math.fsum(f[d] for f in group) for d in range(384)])
    losses=[0.0]*len(TEMPERATURES)
    for row,y in zip(features,fit_labels):
        cs=[]
        for cl in range(4):
            denominator=15 if cl==y else 16
            center=[(sums[cl][d]-(row[d] if cl==y else 0.0))/denominator for d in range(384)]
            cs.append(norm(center))
        logits=[math.fsum(x*z for x,z in zip(row,c)) for c in cs]
        for i,t in enumerate(TEMPERATURES):
            p=probability(logits,t)
            losses[i] += math.fsum((p[cl]-float(cl==y))**2 for cl in range(4))/64
    reported=ctr['fit_only_loocv_multiclass_brier']
    require(len(reported)==len(TEMPERATURES) and
            all(type(v) in (float,int) and math.isfinite(v) and 0<=v<=2 for v in reported)
            and all(abs(observed-original)<=5e-5 for observed,original in zip(reported,losses)),
            'independent FIT LOO loss is not the claimed source calculation')
    minimum=min(range(len(TEMPERATURES)), key=lambda i:(losses[i],i))
    select=ctr.get('selected_temperature')
    require(type(select) in (int,float) and select==TEMPERATURES[minimum],
            'FIT LOO selected temperature differs from independent replay')
    return {'schema':REVIEW_SCHEMA,'source_plan_sha256':source['source_plan_sha256'],
            'model_weights_sha256':MODEL_WEIGHT_SHA,'fit_feature_digest':digest.hexdigest(),
            'fit_examples_replayed':64,'temperatures_checked':list(TEMPERATURES),
            'fit_loo_brier_float64':losses,'max_loss_abs_error_vs_fp32':max(abs(a-b) for a,b in zip(reported,losses)),
            'independently_replayed_temperature':select,'heldout_gold_seen':False,
            'independent_model_origin_verified':False,'new_encoder_forwards':0,
            'production_authorized':False,'authority':'DENY_ALL',
            'disposition':'HOLD_NO_GO'}


def main():
    p=argparse.ArgumentParser()
    for name in ('source','witness','receipt','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    output=Path(args.output)
    require(output.parent.is_dir() and not output.parent.is_symlink() and not output.exists(),
            'unsafe FIT reviewer output')
    result=verify(read(args.source),read(args.witness),read(args.receipt))
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as fh:
        json.dump(result,fh,sort_keys=True,allow_nan=False,separators=(',',':'))
        fh.write('\n')
        fh.flush()
        os.fsync(fh.fileno())


if __name__=='__main__':main()

"""Independent NumPy/stdlib CPU replay of P2 trained 7,434p two-Cell scores.

Never imports Torch, trainer, or pretrained model loader. A report hash only
checks internal integrity, not external origin or any future-time efficacy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import p1_real_granite_review as p1check

SCHEMA='hepta.p2.equal-resident-cells.v1'
ARMS=('frozen_no_change','unrouted_equal_parameter','wide_single_equal_parameter','fixed_two_cell','adaptive_train_only')
SHAPES={
 'down':(2,384,8),'gate':(2,64,8),'g_bias':(2,8),
 'up':(2,8,384),'out':(2,384,2),'out_bias':(2,2),
}
WIDE_SHAPES={'down':(384,16),'gate':(64,16),'g_bias':(16,),
             'up':(16,384),'out':(384,2),'out_bias':(2,),
             'skip':(384,2),'skip_bias':(2,)}


def require(ok,why):
    if not ok: raise ValueError(why)


def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def digest(v):
    return hashlib.sha256(canonical(v)).hexdigest()


def decode_weights(weights,*,wide=False):
    shapes=WIDE_SHAPES if wide else SHAPES
    require(type(weights) is dict and set(weights)==set(shapes),'complete original tensor inventory required')
    d={}
    for name,shape in shapes.items():
        ob=weights[name]
        require(type(ob) is dict and set(ob)=={'shape','bytes_le_hex'}
                and ob['shape']==list(shape),'wrong tensor/shape')
        hx=ob['bytes_le_hex'];n=math.prod(shape)
        require(type(hx) is str and len(hx)==n*8
                and all(c in '0123456789abcdef' for c in hx),'untrusted FP32 byte payload')
        v=np.frombuffer(bytes.fromhex(hx),dtype='<f4').reshape(shape).copy()
        require(bool(np.isfinite(v).all()),'nonfinite original trained weight')
        d[name]=v
    return d


def np_logits(x,weights,arm,split,cutoff):
    # Fresh NumPy equations, not the Torch trainer. Float64 accumulation bounds
    # roundoff without silently reusing claimed logits or gradients.
    w=decode_weights(weights,wide=(arm=='wide_single_equal_parameter'))
    x=np.asarray(x,dtype=np.float32)
    require(x.ndim==2 and x.shape[1]==384 and bool(np.isfinite(x).all()),'invalid original Q24 input')
    z=x.astype(np.float64)
    if arm=='wide_single_equal_parameter':
        down=z@w['down'].astype(np.float64)
        gated=z[:,:64]@w['gate'].astype(np.float64)+w['g_bias'].astype(np.float64)
        sigmoid=1/(1+np.exp(-np.clip(gated,-50,50)))
        silu=down/(1+np.exp(-np.clip(down,-50,50)))
        delta=(silu*sigmoid)@w['up'].astype(np.float64)
        return ((z+delta)@w['out'].astype(np.float64)+w['out_bias'].astype(np.float64)
                + z@w['skip'].astype(np.float64)+w['skip_bias'].astype(np.float64))
    out=[]
    for i in range(2):
        down=z@w['down'][i].astype(np.float64)
        gated=z[:,:64]@w['gate'][i].astype(np.float64)+w['g_bias'][i].astype(np.float64)
        sigmoid=1/(1+np.exp(-np.clip(gated,-50,50)))
        silu=down/(1+np.exp(-np.clip(down,-50,50)))
        delta=(silu*sigmoid)@w['up'][i].astype(np.float64)
        out.append((z+delta)@w['out'][i].astype(np.float64)+w['out_bias'][i].astype(np.float64))
    a,b=out
    if arm in ('frozen_no_change','unrouted_equal_parameter'): return (a+b)/2
    if arm=='adaptive_train_only' and split is False: return a
    require(arm in ('fixed_two_cell','adaptive_train_only') and split is True,'unsupported router mode')
    return np.where(z[:,0:1]>=cutoff,b,a)


def review(original,train,blind,owner,record):
    labels=p1check.validate_original(original,train,blind,owner)
    require(type(record) is dict and record.get('schema')==SCHEMA
            and record.get('report_sha256')==digest({k:v for k,v in record.items() if k!='report_sha256'})
            and record.get('authority')=='DENY_ALL'
            and record.get('production_promotion_permitted') is False,
            'immutable nonauthorizing P2 research record required')
    expected_keys = {'schema','authority','production_promotion_permitted',
       'frozen_pretrained_source_execution_claimed','model_revision','public_panel_sha256',
       'original_source_is_cross_sectional_not_future','independent_model_origin_authenticated',
       'independent_publisher_label_origin_authenticated','reader_sufficiency_established',
       'ndu_system2_superiority_established','general_reasoning_equivalence_10t_100t_established',
       'physical_4096_active_pretrained_split_executed','model_parameter_count',
       'frozen_model_weights_sha256','original_source_model_api_calls','source_encode_cpu_ns',
       'source_encoder_wall_ns','original_train_count','original_calibration_count',
       'original_test_count','source_heldout_cases','source_features_q24',
       'cutoff_feature0_train_median','old_new_cohorts_are_temporal',
       'per_arm_parameter_budget','compared_arms','selection_authorized','report_sha256'}
    require(set(record)==expected_keys, 'extra or missing critical research outcome fields')
    for flag in ('independent_model_origin_authenticated',
          'independent_publisher_label_origin_authenticated','reader_sufficiency_established',
          'ndu_system2_superiority_established','general_reasoning_equivalence_10t_100t_established',
          'physical_4096_active_pretrained_split_executed','selection_authorized'):
        require(record.get(flag) is False,'unsupported model/authority/superiority claim')
    require(record.get('public_panel_sha256')==p1check.PANEL_SHA
            and record.get('model_revision')==p1check.REVISION
            and record.get('original_source_is_cross_sectional_not_future') is True
            and record.get('old_new_cohorts_are_temporal') is False
            and record.get('original_train_count')==128
            and record.get('original_calibration_count')==32
            and record.get('original_test_count')==64
            and record.get('original_source_model_api_calls')==224
            and type(record.get('model_parameter_count')) is int and record['model_parameter_count']>0
            and record.get('per_arm_parameter_budget')==14868
            and isinstance(record.get('frozen_model_weights_sha256'),str)
            and len(record['frozen_model_weights_sha256'])==64
            and type(record.get('source_encode_cpu_ns')) is int
            and record['source_encode_cpu_ns']>0
            and type(record.get('source_encoder_wall_ns')) is int
            and record['source_encoder_wall_ns']>0,
            'P2 source, model or equal-parameter geometry drift')
    if record.get('frozen_pretrained_source_execution_claimed'):
        require(record['model_parameter_count']>=90_000_000,'fake public pretrained 97M source')
    expected=[dict(case_id=c['case_id'],group_id=c['group_id'],split=c['split'],
                   joint_input_digest=c['joint_input_digest']) for c in blind['rows']]
    require(record.get('source_heldout_cases')==expected,
            'source/answer identity or blind question inventory altered')
    source=record.get('source_features_q24')
    require(type(source) is dict and set(source)=={c['case_id'] for c in blind['rows']},
            'full 96 source-scoped Q24 vector inventory required')
    vectors=[]
    for row in expected:
        a=source[row['case_id']]
        require(type(a) is list and len(a)==384
                and all(type(v) is int and abs(v)<=(8<<24) for v in a),
                'not a complete finite Q24 original Encoder vector')
        vectors.append([v/(1<<24) for v in a])
    x=np.asarray(vectors,dtype=np.float32)
    cutoff=record.get('cutoff_feature0_train_median')
    require(type(cutoff) is float and math.isfinite(cutoff) and abs(cutoff)<=8,
            'predeclared train-only router threshold required')
    arms=record.get('compared_arms')
    require(type(arms) is dict and set(arms)==set(ARMS),'complete matched four-arm comparison required')
    detailed={};wins={};raw={}
    initial_digests=set()
    for key in ARMS:
        a=arms[key]
        require(type(a) is dict and set(a)=={
            'arm','parameter_count','private_head_parameter_count',
            'initial_weights_sha256','final_weights_sha256','weights',
            'split_proposed','train_only_split_excess_brier','split_threshold',
            'parent_to_child_max_abs_error','optimization_steps',
            'training_example_exposures','train_cpu_ns','train_loss_history',
            'training_uses_test_labels','heldout_original_labels_opened','logits'},
            'unknown critical trained-Head evidence field')
        require(a.get('arm')==key
                and a.get('parameter_count')==14868
                and a.get('private_head_parameter_count')==(14868 if key=='wide_single_equal_parameter' else 7434)
                and type(a.get('split_proposed')) is bool
                and type(a.get('train_only_split_excess_brier')) is float
                and math.isfinite(a['train_only_split_excess_brier'])
                and a.get('split_threshold')==0.03
                and a.get('parent_to_child_max_abs_error')==0.0
                and type(a.get('train_cpu_ns')) is int and a['train_cpu_ns']>0
                and a.get('training_uses_test_labels') is False
                and a.get('heldout_original_labels_opened') is False,
                'invalid registered P2 Head/Router or blinding claim')
        initial=a.get('initial_weights_sha256');final=a.get('final_weights_sha256')
        require(type(initial) is str and len(initial)==64 and
                type(final) is str and len(final)==64,
                'invalid initial/final actual Head bytes identifier')
        if key!='wide_single_equal_parameter':
            initial_digests.add(initial)
        weights=decode_weights(a['weights'],wide=(key=='wide_single_equal_parameter'))
        saved=hashlib.sha256()
        for name in sorted(weights):
            saved.update(name.encode()+b'\0'+weights[name].astype('<f4',copy=False).tobytes())
        require(saved.hexdigest()==final,'published trained FP32 weight digest differs from content')
        losses=a.get('train_loss_history')
        require(type(losses) is list and len(losses)==a.get('optimization_steps')
                and all(type(q) is float and math.isfinite(q) and q>=0 for q in losses),
                'optimizer loss census missing or nonfinite')
        if key=='frozen_no_change':
            require(a.get('optimization_steps')==0 and a.get('training_example_exposures')==0
                    and a.get('initial_weights_sha256')==a.get('final_weights_sha256')
                    and a.get('split_proposed') is False, 'fake frozen Head/no-change')
        else:
            require(a.get('optimization_steps')==40 and a.get('training_example_exposures')==3840
                    and a.get('initial_weights_sha256')!=a.get('final_weights_sha256'),
                    'wrong fixed SGD updates or exposure')
        if key=='fixed_two_cell':require(a['split_proposed'] is True,'fixed router was not active')
        if key in ('unrouted_equal_parameter','wide_single_equal_parameter'):
            require(a['split_proposed'] is False,'unsplit control drift')
        if key=='adaptive_train_only':
            require(a['split_proposed']==(a['train_only_split_excess_brier']>0.03),
                    'post-eval adaptive split was retrofitted')
        stored=a.get('logits')
        require(type(stored) is list and len(stored)==96
                and all(type(row) is list and len(row)==2 and
                        all(type(v) is float and math.isfinite(v) for v in row) for row in stored),
                'incomplete original score-independent model predictions')
        actual=np_logits(x,a['weights'],key,a['split_proposed'],cutoff)
        delta=float(np.max(np.abs(actual-np.asarray(stored,dtype=np.float64))))
        require(delta<=4e-5,'independent NumPy cannot reproduce trained Head logits')
        positive=np.exp(actual[:,1]-np.max(actual,axis=1))/np.exp(actual-np.max(actual,axis=1,keepdims=True)).sum(axis=1)
        y=np.asarray([row['label'] for row in labels],dtype=np.float64)
        good=(positive>=.5)==(y==1)
        counts={s:int(sum(z['split']==s for z in expected)) for s in ('calibration','test')}
        require(counts=={'calibration':32,'test':64},'original validation/test census changed')
        stats={}
        for split in ('calibration','test'):
            idx=np.array([i for i,z in enumerate(expected) if z['split']==split])
            stats[split]=dict(n=int(len(idx)),accuracy=float(np.mean(good[idx])),
                         brier=float(np.mean((positive[idx]-y[idx])**2)),
                         mean_positive_probability=float(np.mean(positive[idx])))
        raw[key]=good
        detailed[key]=dict(sealed_logits_max_abs_replay_error=delta,
                          registered_resident_params=14868,training_updates=a['optimization_steps'],
                          training_example_exposures=a['training_example_exposures'],
                          train_cpu_ns=a['train_cpu_ns'],split=a['split_proposed'],**stats)
    require(len(initial_digests)==1,'matched source/seed initial Head weights differ across arms')
    for arm in ARMS[1:]:
        recovered=int(np.sum(raw[arm]&~raw['unrouted_equal_parameter']))
        lost=int(np.sum(raw['unrouted_equal_parameter']&~raw[arm]))
        wins[arm]=dict(recovered_vs_unrouted=recovered,lost_vs_unrouted=lost,
                       paired_correct_delta=(recovered-lost)/96)
    return dict(schema='hepta.p2.equal-cell-independent-review.v1',
        authority='DENY_ALL',source_panel_sha256=record['public_panel_sha256'],
        model_pretrained_origin_independently_authenticated=False,
        independent_future_task_utility_established=False,
        source_group_effective_independent_n=0,
        all_four_model_arms_replayed=True,descriptive_only=True,
        exactly_equal_active_flops_verified=False,
        equal_parameter_residency_matched=True,
        eligible_model_selection=False,production_promotion_permitted=False,
        results=detailed,paired_to_unrouted=wins)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for p in ('original-panel','train-material','blind-material','owner-labels','report','output'):
        ap.add_argument('--'+p,required=True)
    args=ap.parse_args()
    owner=p1check.read_strict(args.owner_labels)
    out=review(p1check.read_strict(args.original_panel),
      p1check.read_strict(args.train_material),p1check.read_strict(args.blind_material),
      owner,p1check.read_strict(args.report,limit=8*1024*1024))
    with Path(args.output).open('x',encoding='utf8') as handle:
        json.dump(out,handle,sort_keys=True,indent=2,allow_nan=False);handle.write('\n')

if __name__=='__main__':main()

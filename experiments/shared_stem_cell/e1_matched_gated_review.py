#!/usr/bin/env python3
"""Independent NumPy-only replay of matched E1 Heads; never imports their trainer.

Checks original TRAIN-label SGD, calibration and blind predictions. It does NOT
score held quality or authenticate a model publisher, physical CPU time or NDU.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

ARMS = ('frozen_additive', 'trained_additive', 'frozen_gated', 'trained_gated')
SHAPES = {'a.weight': (16, 128), 'a.bias': (16,), 'b.weight': (16, 128),
          'b.bias': (16,), 'out.weight': (1, 16), 'out.bias': (1,)}
TOL = 3e-5


def sha_state(state):
    return hashlib.sha256(b''.join(k.encode()+b'\0'+v.tobytes(order='C')
                                  for k, v in sorted(state.items()))).hexdigest()


def forward(x, state, kind):
    a = np.tanh(x @ state['a.weight'].T + state['a.bias'])
    b_raw = x @ state['b.weight'].T + state['b.bias']
    b = (np.exp(-np.logaddexp(np.float32(0), -b_raw)) if kind == 'gated'
         else np.tanh(b_raw))
    h = a*b if kind == 'gated' else (a+b)/np.float32(2**0.5)
    return (h @ state['out.weight'].T + state['out.bias']).ravel(), (a, b, h)


def retrain(x, y, state, kind):
    state = {k: v.copy() for k, v in state.items()}
    for _ in range(40):
        logits, (a, b, h) = forward(x, state, kind)
        delta = ((np.exp(-np.logaddexp(np.float32(0), -logits))-y)/len(y))[:, None]
        dh = delta @ state['out.weight']
        da = dh*b*(1-a*a) if kind == 'gated' else dh*(1-a*a)/np.float32(2**0.5)
        db = dh*a*b*(1-b) if kind == 'gated' else dh*(1-b*b)/np.float32(2**0.5)
        grad = {'out.weight': delta.T @ h, 'out.bias': delta.sum(0),
                'a.weight': da.T @ x, 'a.bias': da.sum(0),
                'b.weight': db.T @ x, 'b.bias': db.sum(0)}
        state = {k: v-np.float32(0.1)*grad[k] for k, v in state.items()}
    return state


def verify_probe(report, tensors, features, train_idx, train_y, cal_idx, cal_y, blind_idx):
    """Numerical consistency only; source-authentication is NOT supplied by hashes."""
    if (report.get('schema') != 'hepta.e1.matched-projected-gated-head.v1'
            or report.get('authority') != 'DENY_ALL'):
        raise ValueError('wrong experiment or claimed authority')
    for key in ('held_labels_accessed', 'quality_scored', 'model_selection_permitted',
                'production_promotion_permitted', 'end_to_end_cost_equal',
                'native_representation_preserved', 'timing_is_counterbalanced'):
        if report.get(key) is not False:
            raise ValueError('unsupported acceptance/cost/quality claim')
    for key in ('additional_pretrained_loads', 'additional_encoder_forwards'):
        if type(report.get(key)) is not int or report[key] != 0:
            raise ValueError('unregistered extra model work')
    for key in ('physical_model_origin_independently_authenticated', 'genuine_deployed_nochange_baseline'):
        if key in report and report[key] is not False:
            raise ValueError('false model/deployed baseline authority')
    for name, indices in (('train_indices', train_idx), ('calibration_indices', cal_idx), ('blind_indices', blind_idx)):
        if report.get(name) != indices:
            raise ValueError('wrong original source row assignment')
    if (features.dtype != np.float32 or features.ndim != 2 or features.shape[1] not in (256,384,768)
            or not np.isfinite(features).all() or report.get('source_width') != features.shape[1]
            or report.get('input_features_sha256') != hashlib.sha256(features.tobytes(order='C')).hexdigest()):
        raise ValueError('changed or unbounded original feature source')
    expected = {'shared_projection'} | {f'seed{s}.{arm}.{key}' for s in (41,47,53) for arm in ARMS for key in SHAPES}
    if set(tensors) != expected:
        raise ValueError('incomplete or extra parameter tensors')
    proj = tensors['shared_projection']
    reference = (np.random.Generator(np.random.PCG64(20261015)).standard_normal((features.shape[1],128))/np.sqrt(128)).astype(np.float32)
    if proj.dtype != np.float32 or not np.array_equal(proj, reference):
        raise ValueError('unregistered or task-fitted projection')
    if report.get('projected_width') != 128 or report.get('head_hidden_width') != 16:
        raise ValueError('false Head geometry')
    cost = report.get('shared_projection', {})
    for key, val in {'kind':'fixed-PCG64-Gaussian-not-fitted', 'seed':20261015,
                     'coefficient_count':int(proj.size), 'fp32_bytes':int(proj.nbytes),
                     'linear_forward_macs':int(len(features)*proj.size),
                     'projected_bank_bytes':int(len(features)*128*4),
                     'split_buffer_bytes':int((len(train_idx)+len(cal_idx)+len(blind_idx))*128*4)}.items():
        if cost.get(key) != val:
            raise ValueError('false shared projection work/bytes')
    z = features @ proj
    states = {}
    for seed in (41,47,53):
        for arm in ARMS:
            st = {k:tensors[f'seed{seed}.{arm}.{k}'] for k in SHAPES}
            if any(v.dtype != np.float32 or v.shape != SHAPES[k] or not np.isfinite(v).all() for k,v in st.items()):
                raise ValueError('wrong finite physical FP32 Head')
            states[seed,arm] = st
        if sha_state(states[seed,'frozen_additive']) != sha_state(states[seed,'frozen_gated']):
            raise ValueError('different initial Head tensor budgets')
    records = report.get('arms')
    if type(records) is not list or [(r.get('seed'),r.get('arm')) for r in records] != [(s,a) for s in (41,47,53) for a in ARMS]:
        raise ValueError('missing, duplicated, reordered or unexpected trial')
    max_weight, max_probability = 0., 0.
    for r in records:
        seed, arm = r['seed'], r['arm']
        kind = arm.split('_',1)[1]
        trained = arm.startswith('trained_')
        st, initial = states[seed,arm], states[seed,'frozen_'+kind]
        if (r.get('parameter_count') != 4145 or r.get('optimizer_steps') != (40 if trained else 0)
                or r.get('training_row_exposures') != (40*len(train_idx) if trained else 0)
                or r.get('initial_sha256') != sha_state(initial) or r.get('final_sha256') != sha_state(st)):
            raise ValueError('wrong complete parameter/optimizer/weight accounting')
        replay = retrain(z[train_idx], np.asarray(train_y,dtype=np.float32), initial, kind) if trained else initial
        err = max(float(np.abs(replay[k]-st[k]).max()) for k in SHAPES)
        if err > TOL:
            raise ValueError('original TRAIN-label SGD replay disagrees')
        max_weight = max(max_weight, err)
        temp = r.get('temperature')
        temps = (0.5,0.75,1.,1.5,2.,3.)
        if type(temp) not in (int,float) or temp not in temps:
            raise ValueError('unregistered calibration')
        cl, _ = forward(z[cal_idx], st, kind)
        losses = [float(np.mean(np.logaddexp(0,cl/t)-np.asarray(cal_y)*cl/t)) for t in temps]
        if losses[temps.index(temp)] > min(losses)+TOL:
            raise ValueError('calibration not from original CAL labels')
        logits, _ = forward(z[blind_idx], st, kind)
        p = np.exp(-np.logaddexp(np.float32(0), -logits/temp))
        for key, expected_vector in (('blind_logits',logits),('blind_probabilities',p)):
            actual = np.asarray(r.get(key), dtype=np.float64)
            if actual.shape != expected_vector.shape or not np.isfinite(actual).all():
                raise ValueError('incomplete finite held forecasts')
            err = float(np.abs(actual-expected_vector).max())
            if err > TOL:
                raise ValueError('independent blind numerical replay disagrees')
            if key == 'blind_probabilities': max_probability = max(max_probability,err)
    return {'schema':'hepta.e1.matched-gated-independent-replay.v1', 'trial_count':12,
            'parameter_count_each':4145, 'max_weight_disagreement':max_weight,
            'max_probability_disagreement':max_probability, 'tolerance':TOL,
            'numeric_consistency_only':True, 'held_quality_scored':False,
            'physical_model_origin_authenticated':False,
            'production_promotion_permitted':False, 'authority':'DENY_ALL'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('fit','blind','original-report','replay-dir','probe-dir','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--model', choices=('granite_97m_r2','mmbert_small','embeddinggemma_2_text'), required=True)
    a = parser.parse_args()
    from p0_multirc_semantic_material import read, canonical, validate
    from p0_physical_replay_v5 import independent_numeric_replay, _safe_tensor_bytes
    from safetensors.numpy import load
    fit, blind, old = read(a.fit), read(a.blind), read(a.original_report)
    rows, held = validate(fit,blind)
    prior = independent_numeric_replay(a.replay_dir,fit,blind,old,model=a.model)
    report = read(a.probe_dir/'COMMITTED.json')
    for name, doc in (('original_fit_sha256',fit),('original_blind_sha256',blind),('original_report_sha256',old)):
        if report.get(name) != hashlib.sha256(canonical(doc)).hexdigest():
            raise ValueError('unmatched original source seal')
    if (report.get('model') != a.model or report.get('original_numeric_replay') != prior
            or report.get('blind_case_ids') != [row['case_id'] for row in held]):
        raise ValueError('wrong original model/case lineage')
    payload = _safe_tensor_bytes(a.probe_dir,'probe.safetensors')
    if report.get('probe_safetensors_sha256') != hashlib.sha256(payload).hexdigest():
        raise ValueError('changed sealed probe tensors')
    x = load(_safe_tensor_bytes(a.replay_dir,'features.safetensors'))['features_q24_fp32']
    tr = [i for i,r in enumerate(rows) if r['split']=='train' and r['condition']=='original']
    ca = [i for i,r in enumerate(rows) if r['split']=='calibration' and r['condition']=='original']
    out = verify_probe(report,load(payload),x,tr,[rows[i]['label'] for i in tr],ca,
                       [rows[i]['label'] for i in ca],list(range(len(rows),len(rows)+len(held))))
    # These identities are emitted ONLY after the independent TRAIN-gradient,
    # CAL-temperature and blind-prediction numeric verification succeeds.
    # They bind the later human scorer to the exact reviewed producer report.
    out.update({'reviewed_probe_report_sha256':hashlib.sha256(canonical(report)).hexdigest(),
                'reviewed_probe_weights_sha256':hashlib.sha256(payload).hexdigest(),
                'reviewed_original_p0_report_sha256':hashlib.sha256(canonical(old)).hexdigest(),
                'reviewed_blind_material_sha256':hashlib.sha256(canonical(blind)).hexdigest(),
                'reviewed_model':a.model})
    with a.output.open('xb') as stream:
        stream.write(canonical(out)+b'\n')


if __name__ == '__main__': main()

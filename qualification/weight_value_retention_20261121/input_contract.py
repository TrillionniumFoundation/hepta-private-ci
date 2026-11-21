"""Authenticated exposed TRAIN inputs; no imports of earlier experiment code."""
from pathlib import Path
import numpy as np
from data_contract import read, verify, pin, digest, canonical, exact_radius, head


def original_specs(input_root, previous_root, fit):
    work, previous = Path(input_root), Path(previous_root)
    old = work / 'neuron_margin_experiment'
    full = work / 'neuron_full_mlp_experiment' / 'attempt001'
    causal = work / 'neuron_causal_rescue_20261120' / 'attempt001'
    paths = dict(model=previous / 'attempt001/models' / f'fit_{fit}_C.json.gz',
                 data=full / 'data' / f'fit_{fit}_TRAIN.npz',
                 teacher=causal / 'TRAIN' / f'fit_{fit}_teacher.npz',
                 reconstruction=full / f'fit_{fit}_CANDIDATE.json.gz',
                 family=causal / f'fit_{fit}_FAMILY.json.gz',
                 publics=old / 'inputs' / f'fit_{fit}_TRAIN_PUBLICS.json.gz')
    return {key: pin(path) for key, path in paths.items()}


def load_fit(spec):
    for item in spec.values():
        verify(item)
    model = read(spec['model']['path'])
    rec, fam, publics = (read(spec[k]['path']) for k in ('reconstruction', 'family', 'publics'))
    if model['schema'] != 'joint-policy-v1' or model['family'] != 'renewal' or model['head_dimensions'] != [85, 48, 4]:
        raise ValueError('original model contract differs')
    exact_radius(head(model))
    for actual, old in ((spec['model'], fam['source_C']), (spec['data'], rec['dataset']),
                        (spec['teacher'], fam['teacher'])):
        if any(actual[key] != old[key] for key in ('bytes', 'sha256')):
            raise ValueError('prior source/data/own-teacher identity')
    if not fam['program']['own_law_labels_only']:
        raise ValueError('teacher must be source-bound checkpoint own law')
    with np.load(spec['data']['path'], allow_pickle=False) as archive:
        data = {key: archive[key] for key in ('X', 'legal_masks', 'C_scores')}
    with np.load(spec['teacher']['path'], allow_pickle=False) as archive:
        teacher = {key: archive[key] for key in ('own_optimal_targets', 'own_posterior', 'sample_weights')}
    X, masks, scores = data['X'], data['legal_masks'], data['C_scores']
    if X.shape != (rec['train_rows'], 85) or masks.shape != (len(X), 6) or scores.shape != masks.shape:
        raise ValueError('original cached shape')
    if any(a.dtype != np.float64 for a in (X, scores, teacher['own_optimal_targets'], teacher['own_posterior'])):
        raise ValueError('declared F64 cache changed')
    if masks.dtype != np.bool_ or any(not np.isfinite(a).all() for a in (X, scores, teacher['own_optimal_targets'], teacher['own_posterior'])):
        raise ValueError('nonfinite data or nonboolean mask')
    world_rows, teacher_rows = rec['reconstructed_worlds'], fam['program']['TRAIN']
    if len(publics) != 64 or len(world_rows) != 64 or len(teacher_rows) != 64:
        raise ValueError('all64 TRAIN worlds required')
    offsets, offset = [], 0
    for index, (public, row, target) in enumerate(zip(publics, world_rows, teacher_rows)):
        n = row['rows']
        if n != target['rows'] or public['id'] != row['world_id'] or row['world_id'] != target['world_id']:
            raise ValueError('world row alignment')
        if row['state_order_sha256'] != target['state_order_sha256']:
            raise ValueError('state-order alignment')
        section = slice(offset, offset + n)
        if digest(teacher['own_optimal_targets'][section].tobytes()) != target['teacher_sha256']:
            raise ValueError('per-world own teacher bytes')
        if digest(teacher['sample_weights'][section].tobytes()) != target['sample_weight_sha256']:
            raise ValueError('per-world teacher weight provenance')
        offsets.append(dict(index=index, start=offset, end=offset + n,
                            state_order_sha256=row['state_order_sha256']))
        offset += n
    if offset != len(X):
        raise ValueError('trailing/missing cached rows')
    return dict(base=model, X=X, masks=masks, original_scores=scores,
                teacher=teacher, publics=publics, offsets=offsets)


def authenticate_graph(graph, data, index):
    bounds = data['offsets'][index]
    section = slice(bounds['start'], bounds['end'])
    if graph['state_order_sha256'] != bounds['state_order_sha256']:
        raise ArithmeticError('rebuilt complete state order differs')
    if np.asarray(graph['masks']).tobytes() != data['masks'][section].tobytes():
        raise ArithmeticError('rebuilt legal masks differ')
    if np.asarray(graph['posterior']).tobytes() != data['teacher']['own_posterior'][section].tobytes():
        raise ArithmeticError('rebuilt own deadline posterior differs')
    if np.asarray(graph['qstar'])[:, 1:4].tobytes() != data['teacher']['own_optimal_targets'][section, :3].tobytes():
        raise ArithmeticError('rebuilt own optimal Q differs')
    return dict(state_order_exact=True, masks_bits_exact=True, posterior_bits_exact=True,
                continuation_Q_bits_exact=True, continuation_Q_max_abs_error=0.0,
                source='causal_core.construct_program uses its full-state enumerate_graph, not Oracle.q recursion',
                illegal_continuation_slots='original positive F64 zero')


def schedule_hash(public, fields):
    return digest(canonical({key: public[key] for key in fields}).encode())


def split_worlds(fit, publics, fields):
    namespace = 'hepta-value-retention-20261121/train-split/v1'
    keys = [schedule_hash(public, fields) for public in publics]
    order = sorted(range(len(keys)), key=lambda i: (digest(canonical([namespace, fit, keys[i]]).encode()), i))
    return dict(GEN=order[:32], SELECT=order[32:48], TRAIN_AUDIT=order[48:],
                schedule_hashes=keys, rule='sha256(canonical([namespace,fit,schedule_hash])), original-index tie')

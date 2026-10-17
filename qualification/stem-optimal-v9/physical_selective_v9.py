"""Research-only physical selective execution; no label access and no effects.

Original V3 Granite47 model, weights, tokenizer, data, and gated-Head recipe
are reused without changing their production API. Each mode is a fresh process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for name in ('stem-optimal-v1', 'stem-optimal-v4'):
    sys.path.insert(0, str(ROOT / name))

MODEL = 'granite47'
SOURCE_SHA = '3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900'
SCHEMA = 'hepta.stem.physical-selective.v9'
ARM = 'char_345_tfidf_centroid'
ROUTE_K = 8
TRIAL_MODES = {'selective': 8, 'full': 32}
AUTHORITY = 'DENY_ALL'


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def probabilities(data, cases, arm):
    require(type(data) is dict and type(data.get('rows')) is list and
            len(data['rows']) == len(cases), 'wrong probability roster')
    expected = {x['case_id']: x['source_sha256'] for x in cases}
    result = {}
    for row in data['rows']:
        require(type(row) is dict and set(row) == {'case_id', 'source_sha256', 'scores'} and
                row['case_id'] in expected and row['case_id'] not in result and
                row['source_sha256'] == expected[row['case_id']],
                'stale, duplicated or substituted case')
        scores = row['scores']
        require(type(scores) is dict and arm in scores, 'missing original scores')
        p = scores[arm]
        require(type(p) is list and len(p) == 4 and
                all(type(x) in (float, int) and math.isfinite(x) and 0 <= x <= 1 for x in p) and
                abs(sum(p) - 1) < 1e-5, 'nonfinite or invalid probability')
        result[row['case_id']] = p
    require(set(result) == set(expected), 'original case coverage incomplete')
    return result


def preflight(source, cheap, old, material, mode):
    require(mode in TRIAL_MODES, 'not a declared physical trial')
    require(type(source) is dict and source.get('schema') == 'hepta.stem.charge-stress.source.v3' and
            source.get('source_plan_sha256') == SOURCE_SHA and
            source.get('cohort') == 'hard-charge-four-intents-v3' and
            source.get('heldout_labels_excluded') is True and
            source.get('production_authorized') is False and
            len(source.get('train', [])) == 64 and len(source.get('heldout', [])) == 32 and
            all(set(x) == {'case_id', 'source_sha256', 'text'} for x in source['heldout']),
            'untrusted original source or heldout labels')
    require(digest(canonical({k: v for k, v in source.items()
                              if k != 'source_plan_sha256'})) == SOURCE_SHA,
            'original source bytes changed')
    require(type(cheap) is dict and cheap.get('schema') ==
            'hepta.stem.hard-charge.lexical-control.v4' and
            cheap.get('source_plan_sha256') == SOURCE_SHA and
            cheap.get('authority') == AUTHORITY and
            cheap.get('production_authorized') is False and
            cheap.get('cost', {}).get('neural_encoder_forward_count') == 0,
            'not original cheap prelabel predictions')
    require(type(old) is dict and old.get('schema') ==
            'hepta.stem.charge-stress.physical-unattested.v3' and
            old.get('source_plan_sha256') == SOURCE_SHA and old.get('candidate') == MODEL and
            old.get('authority') == AUTHORITY and old.get('production_authorized') is False and
            old.get('optimizer_steps') == 100 and old.get('head_parameters') == 27656,
            'not original learned-Head lineage')
    require(type(material) is dict and material.get('schema') ==
            'hepta.stem.original-candidate-model-material.v1' and
            material.get('research_only') is True and material.get('production_authorized') is False and
            material.get('training') == {'seed': 17, 'steps': 100, 'learning_rate': 0.006,
                                         'per_cell_parameters': 6914, 'cells': 4},
            'unfrozen original material or training recipe')
    spec = material['candidates'][MODEL]
    require((old.get('model_repo'), old.get('model_revision'), old.get('actual_weight_sha256')) ==
            (spec['repo'], spec['revision'], spec['weight_sha256']) and
            old.get('material_manifest_sha256') == digest(canonical(material)),
            'original pretrained checkpoint mismatch')
    lookup = probabilities(cheap, source['heldout'], ARM)
    original = probabilities(old, source['heldout'], 'learned')
    require(len(original) == 32, 'old original model baseline incomplete')
    ranking = []
    for cid, p in lookup.items():
        high, next_high = sorted(p, reverse=True)[:2]
        ranking.append((high - next_high, cid))
    ranking.sort()
    selected = [cid for _, cid in ranking[:ROUTE_K]]
    require(len(selected) == ROUTE_K and len(set(selected)) == ROUTE_K,
            'duplicated or invalid original selective route')
    return selected, lookup, original


def run(mode, source, cheap, old, materials, *, loader=None, encode=None,
        train=None, cheap_compute=None):
    """Physically execute only this mode's admitted test rows; no test labels.

    Injection ports permit numerical synthetic tests without downloading models.
    A real job uses the original byte-verified pretrained loader and Torch Head.
    """
    selected, original_cheap, original_learned = preflight(source, cheap, old, materials, mode)
    import stem_candidate_v1 as first
    import cheap_lexical_stem_v4 as cheap_backend
    loader = loader or first._material_model
    encode = encode or first._encode
    train = train or first._torch_head_training
    cheap_compute = cheap_compute or cheap_backend.compute
    started, cpu_started = time.perf_counter(), time.process_time()
    cheap_start = time.perf_counter()
    fresh_cheap = cheap_compute(source)
    cheap_seconds = time.perf_counter() - cheap_start
    observed_cheap = probabilities(fresh_cheap, source['heldout'], ARM)
    require(all(all(abs(a-b) <= 1e-12 for a,b in zip(observed_cheap[cid], original_cheap[cid]))
                for cid in original_cheap), 'new cheap routing scores drift from original ZIP')
    # Recompute the route from new physically computed cheap predictions, before Encoder loading.
    fresh_ranking = sorted((sorted(p, reverse=True)[0]-sorted(p, reverse=True)[1], cid)
                           for cid,p in observed_cheap.items())
    require([cid for _, cid in fresh_ranking[:ROUTE_K]] == selected,
            'fresh cheap routing changed the original no-gold policy')
    active = [case for case in source['heldout'] if
              mode == 'full' or case['case_id'] in selected]
    require(len(active) == TRIAL_MODES[mode], 'physical active rows not admission bounded')
    load_begin = time.perf_counter()
    tokenizer, model = loader(materials['candidates'][MODEL])
    load_wall = time.perf_counter() - load_begin
    # Original model hook fires only for true model.forward; no claimed count from len(inputs).
    forward = [0]
    hook = model.register_forward_hook(lambda *_: forward.__setitem__(0, forward[0] + 1))
    encode_start = time.perf_counter()
    try:
        train_features, fit_batches = encode([r['text'] for r in source['train']], tokenizer, model)
        input_features, active_batches = encode([r['text'] for r in active], tokenizer, model)
    finally:
        hook.remove()
    encode_wall = time.perf_counter() - encode_start
    require(fit_batches == 4 and active_batches == (1 if mode == 'selective' else 2) and
            forward[0] == fit_batches + active_batches, 'actual pretrained forward hook mismatch')
    require(tuple(train_features.shape) == (64, 384) and
            tuple(input_features.shape) == (len(active), 384), 'wrong physically computed feature width')
    result = train(train_features, [r['label'] for r in source['train']], input_features,
                   config=materials['training'])
    require(result['total_head_parameters'] == 27656 and result['steps'] == 100 and
            result['initial_head_sha256'] == old['initial_head_sha256'],
            'different original gated-Head initialization')
    prediction_rows = []
    old_probs = probabilities(old, source['heldout'], 'learned')
    for case, new in zip(active, result['learned']):
        previous = old_probs[case['case_id']]
        require(len(new) == 4 and all(abs(a-b) <= 5e-4 for a,b in zip(new,previous)),
                'real newly paid model diverged from original V3 predictions')
        prediction_rows.append({'case_id':case['case_id'],
                                'source_sha256':case['source_sha256'], 'probabilities':new})
    return {'schema': SCHEMA, 'mode':mode, 'candidate': MODEL,
            'source_plan_sha256':SOURCE_SHA, 'model_repo':old['model_repo'],
            'model_revision':old['model_revision'], 'actual_weight_sha256':old['actual_weight_sha256'],
            'material_sha256':digest(canonical(materials)),
            'source_sha256':digest(canonical(source)), 'cheap_receipt_sha256':digest(canonical(cheap)),
            'original_receipt_sha256':digest(canonical(old)),
            'selected_case_ids':selected, 'active_case_ids':[r['case_id'] for r in active],
            'rows':prediction_rows,
            'head_parameters':result['total_head_parameters'], 'optimizer_steps':result['steps'],
            'initial_head_sha256':result['initial_head_sha256'],
            'trained_head_sha256':result['trained_head_sha256'],
            'trained_head_byte_identical_to_original':result['trained_head_sha256'] == old['trained_head_sha256'],
            'cost': {'model_load_wall_seconds':load_wall, 'cheap_wall_seconds':cheap_seconds,
                     'full_encoder_frozen_train_rows':64, 'physically_encoded_heldout_rows':len(active),
                     'physically_executed_encoder_sequences':64+len(active),
                     'actual_model_forward_hook_calls':forward[0],
                     'frozen_train_forward_batches':fit_batches,
                     'heldout_forward_batches':active_batches,
                     'feature_encode_wall_seconds':encode_wall,
                     'head_training_wall_seconds':result['training_wall_seconds'],
                     'elapsed_cpu_seconds':time.process_time()-cpu_started,
                     'elapsed_wall_seconds':time.perf_counter()-started,
                     'process_peak_rss_bytes':first._peak_rss_bytes(),
                     'energy_joules':None, 'p99_latency_ms':None},
            'trial_separate_fresh_process':True,
            'original_v3_label_exposure_prior_to_design':True,
            'full_lifecycle_savings_qualified':False,
            'hardware_meter_independently_attested':False,
            'source_independent_families':1, 'future_windows':0,
            'production_authorized':False, 'stem_winner_verified':False,
            'cell_split_authorized':False, 'disposition':'HOLD_NO_GO', 'authority':AUTHORITY}


def main():
    p=argparse.ArgumentParser()
    for name in ('source','cheap','original','materials','mode','output'):
        p.add_argument('--'+name, required=True)
    args=p.parse_args()
    require(args.mode in TRIAL_MODES, 'unsupported trial mode')
    read=lambda path: json.loads(Path(path).read_text(encoding='utf-8'))
    output=Path(args.output)
    require(not output.exists(), 'create-once producer output required')
    material_path=Path(args.materials)
    import stem_candidate_v1 as first
    materials=first.load_materials(material_path)
    outcome=run(args.mode,read(args.source),read(args.cheap),read(args.original),materials)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as f:
        f.write(canonical(outcome)+b'\n');f.flush()
    print(json.dumps({'receipt_sha256':digest(output.read_bytes()),
                      'physical_sequences':outcome['cost']['physically_executed_encoder_sequences'],
                      'actual_model_forwards':outcome['cost']['actual_model_forward_hook_calls'],
                      'authority':'DENY_ALL'},sort_keys=True))


if __name__=='__main__':
    main()

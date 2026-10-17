"""V27 label-late retrospective route replay of ORIGINAL ScienceQA model outputs.

This does not run a model, claim physical skipped forwards, or grant authority.
The sealed per-case route stays ephemeral; only aggregate diagnostics are exportable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = 'hepta.stem.v27.scienceqa-conditional-replay.v1'
PLAN_SCHEMA = SCHEMA + '.prelabel-plan'
REVIEW_SCHEMA = SCHEMA + '.late-label-review'
PRED_SHA = 'c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4'
SOURCE_SHA = 'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
ARCHIVE_SHA = '7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30'
THRESHOLD = 0.005
ARMS = frozenset({'text_only', 'image_masked', 'calibrated_fusion', 'bridge_image_only',
                  'bridge_equal_fusion', 'rotated_equal_fusion', 'train_gate',
                  'unaligned_equal_fusion'})


class Rejected(ValueError):
    pass


def need(value, message):
    if not value:
        raise Rejected(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                       allow_nan=False) + '\n').encode('utf-8')


def read_jsonl(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            need(k not in result, 'duplicate JSON field')
            result[k] = v
        return result
    def invalid(x):
        raise Rejected('invalid numeric constant')
    need(type(raw) is bytes and 0 < len(raw) < 32*1024*1024 and raw.endswith(b'\n'),
         'unbounded/noncanonical JSONL source')
    out = [json.loads(row, object_pairs_hook=unique, parse_constant=invalid)
           for row in raw.splitlines()]
    need(all(type(row) is dict and canonical(row) == line + b'\n'
             for row, line in zip(out, raw.splitlines())), 'noncanonical source JSONL')
    return out


def check_prob(x):
    need(type(x) is list and len(x) == 4 and
         all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in x) and
         abs(math.fsum(x)-1.0) <= 1e-5, 'invalid original probability')
    return x


def pick(x):
    return max(range(4), key=lambda k: x[k])


def exact_p(a, b):
    n = a+b
    return min(1.0, 2*sum(math.comb(n, i) for i in range(min(a, b)+1))/2**n) if n else 1.0


def _validate_original(pred, published):
    need(type(pred) is dict and type(published) is dict and
         pred.get('source_sha256') == published.get('source_sha256') == SOURCE_SHA,
         'original source mismatch')
    need(pred.get('held_labels_visible_to_inference') is False and
         pred.get('production_accepted') is False and
         published.get('authority') == 'DENY_ALL' and
         published.get('production_accepted') is False,
         'model authority/held label leak')
    need(type(pred.get('predictions')) is list and len(pred['predictions']) == 64 and
         set(pred.get('arms', ())) == ARMS and len(pred.get('arms', ())) == 8,
         'complete original arms/cases required')
    need(set(published.get('arms', {})) == ARMS and
         set(published.get('paired_vs_text_only', {})) == ARMS-{'text_only', 'image_masked'},
         'published full controls required')
    need(published.get('sealed_predictions_sha256') == PRED_SHA and
         published.get('original_heldout_cases') == 64, 'wrong sealed prediction identity')
    ids = set()
    for case in pred['predictions']:
        need(type(case) is dict and case.get('split') == 'test' and
             type(case.get('id')) is str and len(case['id']) == 64 and
             type(case.get('group')) is str and len(case['group']) == 64 and
             case['id'] not in ids and set(case.get('arms', {})) == ARMS,
             'invalid/duplicate case, group, or arm')
        need(all(c in '0123456789abcdef' for c in case['id']+case['group']),
             'noncanonical case or group SHA')
        ids.add(case['id'])
        for vals in case['arms'].values():
            check_prob(vals)
        need(case['arms']['text_only'] == case['arms']['image_masked'] ==
             case['arms']['calibrated_fusion'], 'masked/frozen negative changed')
    need(published.get('statistical_selection_authorized') is False and
         published.get('stem_winner') is None, 'unauthorized scientific selection')


def make_plan(pred, published):
    """Pure, label-free route; must be sealed before original TEST labels are read."""
    _validate_original(pred, published)
    rows = []
    for case in pred['predictions']:
        t = check_prob(case['arms']['text_only'])
        v = check_prob(case['arms']['bridge_image_only'])
        margin = sorted(t, reverse=True)[0]-sorted(t, reverse=True)[1]
        trigger = margin < THRESHOLD
        rows.append({'id':case['id'], 'group':case['group'], 'trigger_vision':trigger,
                     'selected_class':pick(v) if trigger else pick(t),
                     'text_class':pick(t), 'image_class':pick(v)})
    return {'schema':PLAN_SCHEMA, 'archived_prediction_sha256':PRED_SHA,
            'source_sha256':SOURCE_SHA, 'threshold':THRESHOLD,
            'policy':'text_margin_lt_threshold_else_text',
            'rows':rows, 'prelabel_only':True, 'physical_conditional_forwards':False,
            'training_updates':0, 'production_authorized':False}


def check_plan(plan, pred, published):
    need(type(plan) is dict and plan == make_plan(pred, published),
         'prelabel plan changed after outcome read')


def verify_label_material(source_bytes, label_bytes, published_seals):
    """Only use after a create-only prelabel plan exists; exact original bytes."""
    need(type(published_seals) is dict and
         published_seals.get('source_sha256') == SOURCE_SHA and
         sha(source_bytes) == SOURCE_SHA, 'original publisher source SHA mismatch')
    held = published_seals.get('private_test_labels_sha256')
    need(type(held) is str and len(held) == 64 and sha(label_bytes) == held,
         'original TEST target bytes differ from archived original seal')
    source_rows, labels = read_jsonl(source_bytes), read_jsonl(label_bytes)
    need(len(source_rows) == 192 and len(labels) == 64, 'original 96/32/64 census altered')
    seen_src, seen_group, roster = set(), {}, {'train':0, 'validation':0, 'test':0}
    for row in source_rows:
        need(set(row) == {'id','group','split','image','question','hint','choices','scope'} and
             row['scope'] == 'public-scienceqa-e3-research' and
             row['split'] in roster and type(row['id']) is str and len(row['id']) == 64 and
             row['id'] not in seen_src and type(row['group']) is str and len(row['group']) == 64,
             'source row/scope/identity invalid')
        seen_src.add(row['id'])
        need(row['group'] not in seen_group, 'original group duplicated')
        seen_group[row['group']] = row
        roster[row['split']] += 1
    need(roster == {'train':96,'validation':32,'test':64}, 'original split changed')
    sources = {r['id']:r for r in source_rows if r['split'] == 'test'}
    targets = {}
    for row in labels:
        need(type(row) is dict and set(row) == {'id','group','split','label'} and
             row['split'] == 'test' and type(row['label']) is int and 0 <= row['label'] < 4 and
             row['id'] in sources and row['id'] not in targets and
             row['group'] == sources[row['id']]['group'], 'label owner/source join invalid')
        targets[row['id']] = row['label']
    need(set(targets) == set(sources), 'missing original TEST labels')
    return sources, targets


def review_plan(plan, pred, published, published_seals, sources, targets):
    """Recompute ALL archived-arm exact-label outcomes, not only the selected route."""
    check_plan(plan, pred, published)
    ids = {case['id'] for case in pred['predictions']}
    need(type(sources) is dict and type(targets) is dict and
         set(sources) == set(targets) == ids, 'unverified original label roster')
    cases = {c['id']:c for c in pred['predictions']}
    replay = {r['id']:r for r in plan['rows']}
    need(len(replay) == 64, 'duplicate route ID')
    counters = {name:0 for name in ARMS}
    rescue = {name:0 for name in ARMS-{'text_only'}}
    harm = {name:0 for name in ARMS-{'text_only'}}
    route_correct = route_rescue = route_harm = changed = invoked = 0
    for cid in ids:
        c, route, gold = cases[cid], replay[cid], targets[cid]
        need(type(gold) is int and 0 <= gold < 4 and
             sources[cid]['group'] == c['group'], 'source or label mutated')
        text_good = pick(c['arms']['text_only']) == gold
        for arm in ARMS:
            arm_good = pick(c['arms'][arm]) == gold
            counters[arm] += int(arm_good)
            if arm != 'text_only':
                rescue[arm] += int(arm_good and not text_good)
                harm[arm] += int(text_good and not arm_good)
        invoked += int(route['trigger_vision'])
        changed += int(route['selected_class'] != route['text_class'])
        chosen_good = route['selected_class'] == gold
        route_correct += int(chosen_good)
        route_rescue += int(chosen_good and not text_good)
        route_harm += int(text_good and not chosen_good)
    for arm in ARMS:
        reported = published['arms'][arm]
        need(type(reported) is dict and type(reported.get('correct')) is int and
             reported['correct'] == counters[arm] and
             reported.get('accuracy') == counters[arm]/64 and
             reported.get('cases') == 64, 'published original heldout score not independently reproduced')
        if arm != 'text_only' and arm != 'image_masked':
            pair = published['paired_vs_text_only'][arm]
            need(type(pair.get('rescued_errors_vs_text')) is int and
                 type(pair.get('new_errors_vs_text')) is int and
                 rescue[arm] == pair['rescued_errors_vs_text'] and
                 harm[arm] == pair['new_errors_vs_text'] and
                 pair.get('discordant_cases') == rescue[arm]+harm[arm] and
                 abs(pair.get('mcnemar_unadjusted_exact_p', -1)-exact_p(rescue[arm],harm[arm]))<1e-12,
                 'original pairwise TEST reviewer could not be independently reproduced')
    need(changed <= invoked and invoked == 21 and changed == 19,
         'frozen 0.005 original label-free route census changed')
    need(5 <= route_correct <= 33, 'violates mathematical aggregate identification bound')
    return {'schema':REVIEW_SCHEMA, 'original_archive_sha256':ARCHIVE_SHA,
            'original_prediction_sha256':PRED_SHA, 'original_source_sha256':SOURCE_SHA,
            'original_test_label_sha256':published_seals['private_test_labels_sha256'],
            'cases':64, 'original_arm_correct_recount':dict(sorted(counters.items())),
            'source_and_label_sha256_verified':True, 'archived_prediction_sha256_verified':True,
            'archived_reviewer_all_arms_recomputed':True,
            'conditional_text_margin_threshold':THRESHOLD,
            'counterfactual_image_lookups':invoked, 'counterfactual_changed_decisions':changed,
            'counterfactual_correct':route_correct, 'counterfactual_rescues':route_rescue,
            'counterfactual_harms':route_harm,
            'counterfactual_unadjusted_mcnemar_p':exact_p(route_rescue,route_harm),
            'origin':'retrospective_same_original_model_outputs_not_physically_conditional',
            'physical_conditional_encoder_forwards':None, 'physical_savings_established':False,
            'new_encoder_forwards':0, 'new_training_updates':0,
            'visual_necessity_causally_established':False,
            'independent_future_windows':0, 'outside_publisher_source_independence':False,
            'production_authorized':False, 'stem_winner_verified':False,
            'disposition':'HOLD_NO_GO', 'authority':'DENY_ALL'}


def safe_write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    # refuse overwrites, symlink hops at the destination, and group-readable outputs
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(canonical(data));f.flush();os.fsync(f.fileno())


def main():
    import v24_multimodal_causal_bounds as v24
    arg = argparse.ArgumentParser(description=__doc__)
    subs = arg.add_subparsers(dest='mode', required=True)
    seal = subs.add_parser('seal');seal.add_argument('--archive',type=Path,required=True)
    seal.add_argument('--plan',type=Path,required=True)
    check = subs.add_parser('review');check.add_argument('--archive',type=Path,required=True)
    check.add_argument('--plan',type=Path,required=True)
    check.add_argument('--sources',type=Path,required=True)
    check.add_argument('--labels',type=Path,required=True)
    check.add_argument('--output',type=Path,required=True)
    args = arg.parse_args()
    pred, published, seals = v24.verify_archive(args.archive)
    v24.analyze(pred, published, seals)  # strict original 11-member archive and aggregate control gate
    if args.mode == 'seal':
        safe_write(args.plan, make_plan(pred, published))
        print(json.dumps({'plan_sha256':sha(args.plan.read_bytes()),'policy':'fixed_prelabel',
                          'labels_reopened':False,'authority':'DENY_ALL'},sort_keys=True))
    else:
        need(args.plan.is_file() and not args.plan.is_symlink(), 'sealed plan missing')
        plan = json.loads(args.plan.read_bytes())
        check_plan(plan, pred, published)
        need(not args.sources.is_symlink() and not args.labels.is_symlink(), 'unsafe original input path')
        sources, targets = verify_label_material(args.sources.read_bytes(),args.labels.read_bytes(),seals)
        result = review_plan(plan,pred,published,seals,sources,targets)
        safe_write(args.output,result)
        print(json.dumps({'sanitized_review_sha256':sha(args.output.read_bytes()),
                          'counterfactual_correct':result['counterfactual_correct'],
                          'physical_model_executed':False,'authority':'DENY_ALL'},sort_keys=True))


if __name__=='__main__':
    main()

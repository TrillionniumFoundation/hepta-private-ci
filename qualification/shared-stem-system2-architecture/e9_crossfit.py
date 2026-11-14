"""Label-isolated, same-family 4-fold REAL archived-Stem route crossfit.

No new Encoder invocation, actual online routing, future-time measurement,
authentication, FBSDE solver or production artifact admission. DENY_ALL.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import re

from e7_archive import ARMS, HISTORICAL_SHA, PHYSICAL_SHA, canonical, digest, physical_rows, read_zip
from e7_route_seal import seal
from e7_second_opinion import group_labels

SCHEMA = 'hepta.e9.prelabel-4fold-physical-v1'
HASH = re.compile(r'[a-f0-9]{64}\Z')
N = 128
FOLDS = 4


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def load(path, sha=None):
    raw = Path(path).read_bytes()
    require(0 < len(raw) <= 2_000_000, 'bounded JSON evidence required')
    if sha is not None:
        require(type(sha) is str and HASH.fullmatch(sha) and digest(raw) == sha,
                'sealed source byte identity mismatch')
    def pairs(value):
        record = {}
        for k, v in value:
            require(k not in record, 'duplicate JSON key')
            record[k] = v
        return record
    obj = json.loads(raw, object_pairs_hook=pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    return obj, digest(raw)


def write_once(path, obj):
    raw = canonical(obj)
    with Path(path).open('xb') as out:
        out.write(raw)
    return digest(raw)


def fold_mapping(rows):
    """Frozen group-hash split; all 128 groups distinct, exactly 32 per fold."""
    require(type(rows) is list and len(rows) == N, 'complete cohort required')
    groups = [r['group_id'] for r in rows]
    require(len(set(groups)) == N, 'group leakage')
    ordering = sorted(groups, key=lambda g: sha256(('hepta-e9-folds-20261015-v1:'+g).encode()).digest())
    return {gid: i // (N // FOLDS) for i, gid in enumerate(ordering)}


def validate_prelabel(data):
    require(type(data) is dict and data.get('schema') == SCHEMA
            and data.get('authority') == 'DENY_ALL'
            and data.get('physical_archive_sha256') == PHYSICAL_SHA
            and data.get('labels_seen_during_prelabel') is False
            and data.get('actual_new_encoder_forwards') == 0
            and data.get('production_accepted') is False,
            'not original untrusted research source profile')
    require(set(data) == {'schema','authority','physical_archive_sha256',
            'labels_seen_during_prelabel','actual_new_encoder_forwards','registered_arms',
            'production_accepted','rows'}
            and data['registered_arms'] == list(ARMS),
            'unknown or postlabel fields in prelabel artifact')
    rows = data.get('rows')
    require(type(rows) is list and len(rows) == N, '128 original physical rows required')
    fold = fold_mapping(rows)
    ids = set()
    for row in rows:
        require(type(row) is dict and set(row) == {
            'case_id','group_id','joint_input_digest','fold','routing',
            'granite_prob','mmbert_prob','granite_encoder_forward_ns',
            'mmbert_encoder_forward_ns','granite_head_ns','mmbert_head_ns',
        }, 'noncanonical prelabel row')
        require(type(row['case_id']) is str and row['case_id'] not in ids
                and type(row['group_id']) is str and HASH.fullmatch(row['group_id'])
                and type(row['joint_input_digest']) is str and HASH.fullmatch(row['joint_input_digest'])
                and type(row['fold']) is int and row['fold'] == fold[row['group_id']],
                'prelabel source/stratum mismatch')
        ids.add(row['case_id'])
        for p in ('granite_prob','mmbert_prob'):
            require(type(row[p]) in (float, int) and 0 <= row[p] <= 1,
                    'invalid physical prediction')
        for t in ('granite_encoder_forward_ns','mmbert_encoder_forward_ns',
                  'granite_head_ns','mmbert_head_ns'):
            require(type(row[t]) is int and row[t] > 0, 'invalid archive time')
        require(type(row['routing']) is dict and set(row['routing']) == set(ARMS),
                'missing registered action')
        from e7_route_seal import routing_prob
        for arm in ARMS:
            routed = row['routing'][arm]
            expected_prob, secondary = routing_prob(arm,row['granite_prob'],row['mmbert_prob'])
            require(type(routed) is dict and set(routed) == {'probability','secondary_used'}
                    and routed['probability'] == expected_prob and routed['secondary_used'] is secondary,
                    'source-only action prediction tampered')
    require(Counter(r['fold'] for r in rows) == {0:32,1:32,2:32,3:32},
            'unbalanced fold assignment')
    return {r['case_id']:r for r in rows}


def prelabel(physical, output):
    base = seal(physical_rows(read_zip(physical, PHYSICAL_SHA)))
    folds = fold_mapping(base['cases'])
    rows = [dict(r, fold=folds[r['group_id']]) for r in base['cases']]
    data = {'schema':SCHEMA,'authority':'DENY_ALL','physical_archive_sha256':PHYSICAL_SHA,
            'labels_seen_during_prelabel':False,'actual_new_encoder_forwards':0,
            'registered_arms':list(ARMS),'production_accepted':False,'rows':rows}
    validate_prelabel(data)
    sha = write_once(output, data)
    return {'prelabel_sha256':sha,'case_count':N,'source_labels_seen':False}


def source_labels_train_only(historical, prelabel_path, prelabel_sha, output_prefix):
    """TRUST BOUNDARY: only emitted per-fold training truths go to fit_fold.

    This extraction process necessarily sees the historical ZIP; fit_fold does
    NOT accept a historical archive argument. It is a research-level logical
    split, not cryptographic confidentiality among adversarial processes.
    """
    pre, sha = load(prelabel_path, prelabel_sha)
    rows = validate_prelabel(pre)
    original = group_labels(read_zip(historical, HISTORICAL_SHA))
    require(set(original) == set(rows), 'original labels/source panel changed')
    for cid, item in original.items():
        require((rows[cid]['group_id'], rows[cid]['joint_input_digest']) == item[:2],
                'original label not source aligned')
    output = {}
    for fold in range(FOLDS):
        train = [dict(case_id=cid, group_id=rows[cid]['group_id'],label=original[cid][2])
                 for cid in sorted(rows) if rows[cid]['fold'] != fold]
        require(len(train) == 96, 'training split size incorrect')
        blob = {'schema':'hepta.e9.train-only-fold-v1','authority':'DENY_ALL',
                'fold':fold,'prelabel_sha256':sha,'historical_archive_sha256':HISTORICAL_SHA,
                'holdout_labels_included':False,'rows':train}
        path = f'{output_prefix}-fold{fold}.json'
        output[path] = write_once(path, blob)
    return output


def parse_train(pre, sha, fold, train):
    rows = validate_prelabel(pre)
    require(type(fold) is int and 0 <= fold < FOLDS,'invalid fold')
    require(type(train) is dict and train.get('schema') == 'hepta.e9.train-only-fold-v1'
            and train.get('authority') == 'DENY_ALL'
            and train.get('fold') == fold and train.get('prelabel_sha256') == sha
            and train.get('historical_archive_sha256') == HISTORICAL_SHA
            and train.get('holdout_labels_included') is False,
            'wrong training-only source')
    require(set(train) == {'schema','authority','fold','prelabel_sha256',
            'historical_archive_sha256','holdout_labels_included','rows'},
            'additional label-bearing train field')
    items = train.get('rows')
    require(type(items) is list and len(items) == 96, 'train-only rows required')
    truth = {}
    for item in items:
        require(type(item) is dict and set(item) == {'case_id','group_id','label'},
                'training label row contains disallowed fields')
        cid = item['case_id']
        require(type(cid) is str and cid in rows and cid not in truth
                and item['group_id'] == rows[cid]['group_id']
                and rows[cid]['fold'] != fold and type(item['label']) is int
                and item['label'] in (0,1), 'label leak, missing, or inconsistent group')
        truth[cid] = item['label']
    require(set(truth) == {cid for cid,r in rows.items() if r['fold'] != fold},
            'training must cover exactly 96 non-heldout rows')
    return rows, truth


def probability_and_cost(row, arm):
    probability = row['routing'][arm]['probability']
    used = row['routing'][arm]['secondary_used']
    g = row['granite_encoder_forward_ns'] + row['granite_head_ns']
    m = row['mmbert_encoder_forward_ns'] + row['mmbert_head_ns']
    if arm == 'granite_only':
        return probability, g, 0
    if arm == 'mmbert_only':
        return probability, m, 0
    return probability, g + (m if used else 0), int(used)


def arm_score(rows, labels, arm):
    total_cost, correct, extra = 0, 0, 0
    brier = Fraction(0)
    for cid, label in labels.items():
        probability, cost, second = probability_and_cost(rows[cid],arm)
        correct += int((probability >= .5) == bool(label))
        brier += (Fraction(str(probability)) - label) ** 2
        total_cost += cost
        extra += second
    return {'correct':correct,'n':len(labels),'brier':float(brier/len(labels)),
            'time_proxy_ns':total_cost,'hypothetical_secondary_calls':extra}


def fit_fold(prelabel_path, prelabel_sha, train_path, train_sha, fold, output):
    pre, actual_pre_sha = load(prelabel_path, prelabel_sha)
    train, actual_train_sha = load(train_path, train_sha)
    rows, truth = parse_train(pre, actual_pre_sha, fold, train)
    scores = {arm:arm_score(rows,truth,arm) for arm in ARMS}
    # Preregistered total ordering: training accuracy, Brier, cost, then
    # original fixed arm order. No heldout labels or test scoring touched.
    selected = min(ARMS, key=lambda arm:(-scores[arm]['correct'],
                  scores[arm]['brier'], scores[arm]['time_proxy_ns'], ARMS.index(arm)))
    data = {'schema':'hepta.e9.train-only-selected-fold-v1','authority':'DENY_ALL',
            'fold':fold,'prelabel_sha256':actual_pre_sha,
            'train_source_sha256':actual_train_sha,'selected_arm':selected,
            'train_scores':scores,'holdout_labels_seen':False,
            'selection_is_retrospective_same_family':True,
            'production_accepted':False}
    return {'fold':fold,'selected_arm':selected,'seal_sha256':write_once(output,data)}


def evaluate(prelabel_path, prelabel_sha, fit_paths, historical, output):
    pre, actual_sha = load(prelabel_path, prelabel_sha)
    rows = validate_prelabel(pre)
    require(type(fit_paths) in (tuple,list) and len(fit_paths)==4,'four sealed folds required')
    choices = {}
    selection_rows = {}
    for path in fit_paths:
        fit,_ = load(path)
        require(type(fit) is dict and fit.get('schema')=='hepta.e9.train-only-selected-fold-v1'
                and fit.get('authority')=='DENY_ALL'
                and fit.get('prelabel_sha256')==actual_sha
                and fit.get('holdout_labels_seen') is False
                and fit.get('production_accepted') is False,
                'unqualified train-only selection')
        fold = fit['fold']; arm = fit['selected_arm']
        require(type(fold) is int and 0 <= fold < FOLDS and fold not in choices
                and arm in ARMS,'duplicate or undeclared fold selection')
        choices[fold] = arm
        selection_rows[fold] = fit
    require(set(choices)==set(range(FOLDS)),'incomplete fold selection')
    original = group_labels(read_zip(historical,HISTORICAL_SHA))
    require(set(original)==set(rows),'source label case drift')
    truth = {}
    for cid, (group,digest_value,label) in original.items():
        require((rows[cid]['group_id'],rows[cid]['joint_input_digest'])==(group,digest_value),
                'original raw source mismatched')
        truth[cid] = label
    # Source-verified train-only reconstructability prevents a forged selected
    # arm from being accepted as if it won the original 96-group training fold.
    for fold in range(FOLDS):
        train_truth = {cid:label for cid,label in truth.items() if rows[cid]['fold']!=fold}
        expected_train = {'schema':'hepta.e9.train-only-fold-v1','authority':'DENY_ALL',
            'fold':fold,'prelabel_sha256':actual_sha,
            'historical_archive_sha256':HISTORICAL_SHA,
            'holdout_labels_included':False,
            'rows':[{'case_id':cid,'group_id':rows[cid]['group_id'],'label':train_truth[cid]}
                    for cid in sorted(train_truth)]}
        # Re-read the sealed file for complete, not self-reported, selection proof.
        expected_sha = digest(canonical(expected_train))
        selected_file = selection_rows[fold]
        require(selected_file.get('train_source_sha256')==expected_sha,
                'fold training source identity not the original 96 labeled groups')
        scores = {arm:arm_score(rows,train_truth,arm) for arm in ARMS}
        expected = min(ARMS,key=lambda arm:(-scores[arm]['correct'],
                       scores[arm]['brier'],scores[arm]['time_proxy_ns'],ARMS.index(arm)))
        require(selected_file.get('train_scores')==scores and choices[fold]==expected,
                'training policy ranking not independently reconstructable')
    correct = extra = cost = baseline_correct = baseline_cost = 0
    brier = baseline_brier = Fraction(0)
    improved = worsened = 0
    for cid,label in truth.items():
        row = rows[cid]; arm = choices[row['fold']]
        p,c,sec = probability_and_cost(row,arm)
        gp,gc,_ = probability_and_cost(row,'granite_only')
        y = (p >= .5)==bool(label); by = (gp >= .5)==bool(label)
        improved += int(y and not by); worsened += int(by and not y)
        correct += int(y); baseline_correct += int(by)
        brier += (Fraction(str(p))-label)**2
        baseline_brier += (Fraction(str(gp))-label)**2
        cost += c; baseline_cost += gc; extra += sec
    output_data = {
        'schema':'hepta.e9.fourfold-source-group-crossfit-retrospective.v1',
        'authority':'DENY_ALL','prelabel_sha256':actual_sha,
        'physical_archive_sha256':PHYSICAL_SHA,'source_archive_sha256':HISTORICAL_SHA,
        'n':N,'fold_sizes':[32,32,32,32],
        'selected_per_fold':{str(k):choices[k] for k in sorted(choices)},
        'trained_route':{'correct':correct,'accuracy':correct/N,'brier':float(brier/N),
                         'archived_per_case_wall_proxy_ns_sum':cost,
                         'hypothetical_extra_mmbert_calls':extra,
                         'paired_improvements_from_granite':improved,
                         'paired_regressions_from_granite':worsened},
        'granite_baseline':{'correct':baseline_correct,'accuracy':baseline_correct/N,
                            'brier':float(baseline_brier/N),
                            'archived_per_case_wall_proxy_ns_sum':baseline_cost},
        'source_group_disjoint_within_each_fold':True,
        'cross_validation_not_real_future_observation_time':True,
        'same_AGNews_source_family':True,
        'real_new_pretrained_encoder_forwards':0,
        'physical_serving_routing_measured':False,
        'source_origin_independently_signed':False,
        'full_lifecycle_cost_equalized':False,
        'prospective_utility_accepted':False,
        'model_selection_allowed':False,
        'production_accepted':False,
    }
    return {'report_sha256':write_once(output,output_data), 'result':output_data}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='cmd',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--physical',required=True);prep.add_argument('--output',required=True)
    ex=sub.add_parser('train-labels');ex.add_argument('--historical',required=True);ex.add_argument('--prelabel',required=True)
    ex.add_argument('--prelabel-sha256',required=True);ex.add_argument('--output-prefix',required=True)
    fit=sub.add_parser('fit');fit.add_argument('--prelabel',required=True);fit.add_argument('--prelabel-sha256',required=True)
    fit.add_argument('--train',required=True);fit.add_argument('--train-sha256',required=True)
    fit.add_argument('--fold',required=True,type=int);fit.add_argument('--output',required=True)
    ev=sub.add_parser('evaluate');ev.add_argument('--prelabel',required=True);ev.add_argument('--prelabel-sha256',required=True)
    ev.add_argument('--fits',required=True,nargs=4);ev.add_argument('--historical',required=True)
    ev.add_argument('--output',required=True)
    args=ap.parse_args()
    if args.cmd=='prepare':result=prelabel(args.physical,args.output)
    elif args.cmd=='train-labels':result=source_labels_train_only(args.historical,args.prelabel,args.prelabel_sha256,args.output_prefix)
    elif args.cmd=='fit':result=fit_fold(args.prelabel,args.prelabel_sha256,args.train,args.train_sha256,args.fold,args.output)
    else:result=evaluate(args.prelabel,args.prelabel_sha256,args.fits,args.historical,args.output)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()

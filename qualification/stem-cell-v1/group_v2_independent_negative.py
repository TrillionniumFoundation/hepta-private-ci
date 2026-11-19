#!/usr/bin/env python3
"""Read-only, source-locked P1/P4 real-Granite97 Group summary arithmetic audit.

This is a *second implementation* over committed original summary bytes, not a
replay of uncommitted raw tensors / issuer signatures / human task results.
All outcomes retain DENY_ALL and original non-admission decisions.
"""
from __future__ import annotations
import argparse
from hashlib import sha1, sha256
import json
import math
from pathlib import Path

ORIGINAL_HEAD = '16fbbf2b5ab2d29b03eb605e8a797e1f16402ae0'
ORIGINAL_GIT_BLOB = 'e2913669e502238c82c7f8982ead99d7998e99c7'
ORIGINAL_EVIDENCE_ZIP_SHA = '692283c5bd54793348c701fbb115e6dc33e2625109ad0da0bee7fa9576641d96'
SEEDS = ('41','47','53')
ARMS = ('static','wide','fixed','adaptive','ndu','no_verifier','reset_state','split')
ROLES = {'static':(3152,12608), 'wide':(19265,77060),
         'core':(19112,76448), 'split':(22474,89896)}
SUM_FIELDS = ('correct','n','cpu_ns','wall_ns','steps')
REVIEW = 'hepta.group-v2-original-three-seed-independent-summary.v1'

class Denied(ValueError):
    """Missing or forged original research summary data."""


def require(ok, why):
    if not ok:
        raise Denied(why)


def reject_pairs(items):
    r = {}
    for k,v in items:
        require(k not in r, 'duplicate source JSON key')
        r[k] = v
    return r


def read_original(path: Path):
    require(path.is_file() and not path.is_symlink() and
            1 <= path.stat().st_size <= 150000, 'missing/oversized original summary')
    b = path.read_bytes()
    digest = sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    require(digest == ORIGINAL_GIT_BLOB, 'original Git blob has been changed')
    return json.loads(b, object_pairs_hook=reject_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(Denied('nonfinite JSON')))


def positive_int(x, name, zero=False):
    require(type(x) is int and x >= (0 if zero else 1), 'invalid '+name)


def review(candidate):
    require(type(candidate) is dict and candidate.get('schema') ==
            'hepta.group.corrected-three-seed-summary.v1' and
            candidate.get('seeds') == [41,47,53] and
            candidate.get('source_prs') == list(range(2263,2270)),
            'unqualified three-seed Group research lineage')
    require(candidate.get('entry_pr') == 2271 and
            candidate.get('hosted_ci') == 'queued_not_counted_as_passed' and
            candidate.get('equal_compute') is False and
            candidate.get('learned_reasoning_emergence_established') is False and
            candidate.get('natural_future_efficacy') is False and
            candidate.get('all_split_candidates_rejected') is True and
            candidate.get('native_scope') == 'offline_Q32_replay_not_production_owner' and
            candidate.get('multimodal_scope') == 'versioned_interface_only',
            'unqualified model/cost/authority claims')
    archive = candidate.get('archive',{})
    require(archive.get('sha256') == ORIGINAL_EVIDENCE_ZIP_SHA and
            archive.get('bytes') == 2666151, 'original raw-archive reference changed')
    runs = candidate.get('runs')
    require(type(runs) is dict and set(runs) == set(SEEDS),
            'missing/extra original independent training seed')
    aggregate = {k:{field:0 for field in SUM_FIELDS} for k in ARMS}
    train_sum = {role:{'cpu_ns':0,'steps':0,'parameters':p,'parameter_bytes':n}
                 for role,(p,n) in ROLES.items()}
    encoder = {'physical_forwards':0,'logical_requests':0,
               'encoder_load_cpu_ns':0,'canonical_feature_bytes':0}
    seeds = []
    initial_source = None
    for seed in SEEDS:
        r = runs[seed]
        require(type(r) is dict and r.get('native_reference_match') is True and
                r.get('split_decision')=='reject_candidate' and
                r.get('selected_model')=='core' and
                r.get('encoder_complete_formula_flops') is None and
                r.get('critic_params')==14, 'invalid original split/native/group result')
        source = r.get('source_sha256')
        require(type(source) is dict and len(source)==10 and
                all(type(x) is str and len(x)==64 and
                    x!='0'*64 and all(c in '0123456789abcdef' for c in x)
                    for x in source.values()), 'missing original source blobs')
        if initial_source is None:
            initial_source=source
        require(source==initial_source, 'source changed between original seeds')
        test = r.get('test')
        require(type(test) is dict and set(test)==set(ARMS),
                'incomplete original 8-arm model comparison')
        for arm in ARMS:
            t = test[arm]
            require(type(t) is dict and t.get('tail_quantiles_are_target_host_certification') is False,
                    'false full-device tail-quantile certification')
            for field in SUM_FIELDS:
                positive_int(t.get(field),field,zero=field=='correct')
                aggregate[arm][field]+=t[field]
            require(t['n']==96 and t['correct']<=t['n'] and
                    t['cpu_ns']>0 and t['wall_ns']>0 and
                    t.get('verifier_calls') == t['steps'], 'incomplete task/callback meter')
            for p in ('observed_p50_ns','observed_p95_ns'):
                positive_int(t.get(p),p)
            require(t['observed_p95_ns']>=t['observed_p50_ns'],
                    'incorrect observed duration quantiles')
            status=t.get('statuses')
            require(type(status) is dict and all(type(v) is int and v>=0 for v in status.values()) and
                    sum(status.values())==96, 'missing 96 original outcome statuses')
        training = r.get('training')
        require(type(training) is dict and set(training)==set(ROLES),
                'unregistered training comparison')
        for role,(p,bytes_) in ROLES.items():
            one=training[role]
            require(one.get('status')=='completed' and one.get('completed_steps')==120 and
                    one.get('parameter_count')==p and
                    one.get('parameter_bytes')==bytes_, 'incorrect trained Head inventory')
            positive_int(one.get('cpu_ns'),role+' train cpu')
            positive_int(one.get('wall_ns'),role+' train wall')
            train_sum[role]['steps']+=one['completed_steps']
            train_sum[role]['cpu_ns']+=one['cpu_ns']
        e=r.get('encoder')
        require(type(e) is dict and e.get('logical_feature_requests') == 832,
                'unexpected registered original group input panel')
        for k in ('actual_forward_calls','load_and_encode_cpu_ns','cache_canonical_bytes'):
            positive_int(e.get(k),k)
        require(e['actual_forward_calls']<=832 and
                r.get('encoder_unknown_operators',{}).get('aten.silu.default',0)>0,
                'bad missing-FLOPs/real-forward boundary')
        encoder['physical_forwards']+=e['actual_forward_calls']
        encoder['logical_requests']+=e['logical_feature_requests']
        encoder['encoder_load_cpu_ns']+=e['load_and_encode_cpu_ns']
        encoder['canonical_feature_bytes']+=e['cache_canonical_bytes']
        seeds.append({'seed':int(seed),'train_steps_each_arm':120,
                      'actual_encoder_forwards':e['actual_forward_calls'],
                      'split_candidate_admitted':False,
                      'future_pretrained_natural_efficacy':False})
    declared=candidate.get('aggregate_test')
    require(type(declared) is dict and set(declared)==set(ARMS),
            'missing original declared aggregate')
    for arm in ARMS:
        require(type(declared[arm]) is dict and
                all(declared[arm].get(k)==v for k,v in aggregate[arm].items()),
                'independent exact 3-seed aggregation disagreement')
        require(aggregate[arm]['n']==288 and
                aggregate[arm]['correct']<=288, 'invalid aggregate denominator')
    static, ndu, split = aggregate['static'],aggregate['ndu'],aggregate['split']
    require(split['correct']<=static['correct'] and
            ndu['correct']<=static['correct'] and
            split['cpu_ns']>static['cpu_ns'] and
            ndu['cpu_ns']>static['cpu_ns'] and
            all(train_sum[r]['steps']==360 for r in ROLES) and
            encoder['physical_forwards']>0 and
            encoder['logical_requests']>=encoder['physical_forwards'],
            'the original negative comparison/complete training was changed')
    return {
        'schema':REVIEW,'authority_posture':'DENY_ALL','production_accepted':False,
        'original_pr':2271,'original_commit':ORIGINAL_HEAD,
        'original_blob_sha':ORIGINAL_GIT_BLOB,
        'original_raw_evidence_zip_sha256':ORIGINAL_EVIDENCE_ZIP_SHA,
        'original_archive_zip_independently_replayed_here':False,
        'actual_three_seed_training_summary_rechecked':True,
        'run_seeds':seeds,'task_observations_per_arm':288,
        'original_encoder':{**encoder,
            'logical_minus_physical_forwards':encoder['logical_requests']-
                                               encoder['physical_forwards'],
            'complete_flops_known':False,
            'cache_bytes_are_peak_rss':False},
        'original_arms':aggregate,'original_training':train_sum,
        'split_test_correct_delta_vs_static':split['correct']-static['correct'],
        'ndu_test_correct_delta_vs_static':ndu['correct']-static['correct'],
        'split_online_cpu_ratio_vs_static':round(split['cpu_ns']/static['cpu_ns'],9),
        'ndu_online_cpu_ratio_vs_static':round(ndu['cpu_ns']/static['cpu_ns'],9),
        'split_candidates_all_rejected':True,
        'inference_online_cpu_excludes_encoder_training_critic':True,
        'original_source_families_independent':False,
        'equal_full_lifecycle_compute':False,
        'unobserved_model_10t_100t_equivalence':False,
        'general_reasoning_emergence_established':False,
        'learning_or_split_winner_certified':False,
        'model_or_NDU_promotion_permitted':False
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-summary',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    x=p.parse_args()
    require(not x.output.exists() and not x.output.is_symlink(),
            'no overwrite or fake original report')
    result=review(read_original(x.original_summary))
    x.output.write_text(json.dumps(result,sort_keys=True,separators=(',',':'),
                    allow_nan=False)+'\n',encoding='utf-8')
    print('ORIGINAL_REAL_GRANITE_GROUP_NEGATIVE_ONLY / DENY_ALL')


if __name__=='__main__': main()

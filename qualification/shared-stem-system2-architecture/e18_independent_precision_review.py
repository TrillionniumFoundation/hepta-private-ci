"""E18 source-independent numeric precision replay and original human-only audit.

Does NOT import the E18 producer; uses frexp/ldexp exponent quantizers rather
than the producer's struct binary-format conversion. Historical human scores
are read only AFTER the prior blind source bytes are sealed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
from itertools import combinations
from math import frexp, ldexp, isfinite
from pathlib import Path
from zipfile import ZipFile

from e14_multirc_route import ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel, strict_json, write_once

SCHEMA = 'hepta.e18.independent-original-reader-precision.v1'
BLIND_SCHEMA = 'hepta.e18.real-reader-postlogit-precision.v1'
PROFILES = ('original_fp32', 'q24_rne', 'fp16_rne', 'bf16_rne')
HUMAN_SCORE_PATH = 'multirc-native-candidate-scores/scores.json'
HUMAN_SCORE_SHA = '3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4'


def independent_quantize(v: float, profile: str) -> float:
    if type(v) not in (float, int) or not isfinite(v) or abs(v) > 8:
        raise ValueError('invalid independent source value')
    v = float(v)
    if profile == PROFILES[0]:
        return v
    if profile == PROFILES[1]:
        # Powers of two are exact. round() is ties-even on exact fp32->double.
        return float(round(v * (1<<24))) / (1<<24)
    if profile in PROFILES[2:]:
        fraction_bits = 10 if profile == 'fp16_rne' else 7
        least_step_exponent = -24 if profile == 'fp16_rne' else -133
        if not v:
            return v
        e = frexp(abs(v))[1]
        step = ldexp(1.0, max(e - fraction_bits - 1, least_step_exponent))
        return float(round(v / step) * step)
    raise ValueError('unknown independent precision')


def audit_original(obs, blind: dict):
    if (type(blind) is not dict or set(blind) != {
        'schema','authority','archive_sha256','original_pretrained_observation_id',
        'original_passages','original_questions','original_candidates','precision_profiles',
        'operation','post_logit_projection_not_reexecuted_bf16_fp16_encoder',
        'human_labels_opened_in_blind_stage','existing_scored_archive_member_opened_in_blind_stage',
        'pretrained_model_new_forward_count','actual_serving_low_precision_efficacy_measured',
        'negative_group_bottleneck_does_not_prove_semantic_inability',
        'question_rows','summary','model_selected','production_accepted'
    } or blind['schema'] != BLIND_SCHEMA or blind['authority'] != 'DENY_ALL'
            or blind['archive_sha256'] != ARCHIVE_SHA or blind['original_pretrained_observation_id'] != OBS_ID
            or (blind['original_passages'], blind['original_questions'], blind['original_candidates']) != (4,8,33)
            or blind['precision_profiles'] != list(PROFILES)
            or blind['operation'] != 'independently_round_each_archived_fp32_logit_BEFORE_binary_margin'
            or any(blind[k] is not flag for k, flag in {
                'post_logit_projection_not_reexecuted_bf16_fp16_encoder': True,
                'human_labels_opened_in_blind_stage': False,
                'existing_scored_archive_member_opened_in_blind_stage': False,
                'actual_serving_low_precision_efficacy_measured': False,
                'negative_group_bottleneck_does_not_prove_semantic_inability': True,
                'model_selected': False,'production_accepted': False}.items())
            or type(blind['pretrained_model_new_forward_count']) is not int
            or blind['pretrained_model_new_forward_count'] != 0):
        raise ValueError('unqualified precision projection claim')
    groups = defaultdict(list)
    for i,r in enumerate(obs['rows']):
        groups[(r['source_group'],r['question_slot'])].append(i)
    if len(groups) != 8 or sum(map(len,groups.values())) != 33:
        raise ValueError('original human-question census missing')
    if type(blind['question_rows']) is not list or len(blind['question_rows']) != 8:
        raise ValueError('blind question count')
    stats = {arm:{p:{'invariant':0,'one_label':0,'pairs':0,'pairs_total':0,'maxspan':0.0}
             for p in PROFILES} for arm in ARMS}
    for stored,(key,indices) in zip(blind['question_rows'],sorted(groups.items()),strict=True):
        if (type(stored) is not dict or set(stored) != {'source_group','question_slot','candidate_count','arms'}
                or (stored['source_group'],stored['question_slot']) != key
                or stored['candidate_count'] != len(indices)
                or type(stored['arms']) is not dict or set(stored['arms']) != set(ARMS)):
            raise ValueError('altered passage/question/candidate binding')
        for arm in ARMS:
            predictions = obs['predictions'][arm]
            report = stored['arms'][arm]
            if type(report) is not dict or set(report) != set(PROFILES):
                raise ValueError('missing full precision/profile axes')
            for p in PROFILES:
                margins = []
                for i in indices:
                    source = predictions[i]
                    if source['task_id'] != obs['rows'][i]['task_id']:
                        raise ValueError('changed original model task identity')
                    a,b = source['logits']
                    margins.append(independent_quantize(b,p)-independent_quantize(a,p))
                expected = {
                    'distinct_signed_margins':len(set(margins)),
                    'equal_margin_candidate_pairs':sum(a==b for a,b in combinations(margins,2)),
                    'candidate_pairs':len(indices)*(len(indices)-1)//2,
                    'max_signed_margin_span':max(margins)-min(margins),
                    'distinct_hard_predictions':len({v>=0 for v in margins}),
                }
                observed = report[p]
                if type(observed) is not dict or set(observed) != set(expected):
                    raise ValueError('forged precision row shape')
                for name,v in expected.items():
                    # All observed float spans here are exact dyadics in Python.
                    if type(observed[name]) is not type(v) or observed[name] != v:
                        raise ValueError('forged post-quantization precision evidence')
                s=stats[arm][p]
                s['invariant'] += int(len(set(margins))==1)
                s['one_label'] += int(expected['distinct_hard_predictions']==1)
                s['pairs'] += expected['equal_margin_candidate_pairs']
                s['pairs_total'] += expected['candidate_pairs']
                s['maxspan']=max(s['maxspan'],expected['max_signed_margin_span'])
    if type(blind['summary']) is not dict or set(blind['summary']) != set(ARMS):
        raise ValueError('incomplete overall precision report')
    for arm in ARMS:
        if type(blind['summary'][arm]) is not dict or set(blind['summary'][arm]) != set(PROFILES):
            raise ValueError('missing summary profile')
        for p in PROFILES:
            s = stats[arm][p]; report = blind['summary'][arm][p]
            expected = {
                'questions_exactly_candidate_invariant': s['invariant'],
                'questions_with_distinguishable_candidate_margins': 8-s['invariant'],
                'questions_single_hard_prediction':s['one_label'],
                'equal_margin_candidate_pairs':s['pairs'],
                'candidate_pairs':s['pairs_total'],
                'max_question_margin_span':s['maxspan'],
            }
            if type(report) is not dict or set(report) != set(expected):
                raise ValueError('incomplete summary')
            if any(type(report[name]) is not type(v) or report[name] != v for name,v in expected.items()):
                raise ValueError('numeric precision review mismatch')
    return stats


def review(archive: str, blind_path: str, sealed_sha256: str, output: str) -> str:
    data=Path(blind_path).read_bytes()
    if not 0 < len(data) < 200_000 or type(sealed_sha256) is not str or sha256(data).hexdigest()!=sealed_sha256:
        raise ValueError('unsealed original blind source')
    blind=strict_json(data)
    original=read_prelabel(archive)
    stats=audit_original(original,blind)
    with ZipFile(archive) as zipped:
        # Historical human score must not be read by the preceding blind producer.
        score_bytes=zipped.read(HUMAN_SCORE_PATH)
    if sha256(score_bytes).hexdigest() != HUMAN_SCORE_SHA:
        raise ValueError('original human score bytes changed')
    human=strict_json(score_bytes)
    if (human.get('schema') != 'hepta.multirc.genuine-answer-slate-evaluation.v1'
            or human.get('observation_id') != OBS_ID or human.get('candidate_count') != 33
            or human.get('question_count') != 8 or human.get('production_authorized') is not False
            or any(human.get('results',{}).get(arm,{}).get('mixed_label_question_count') != 8 for arm in ARMS)):
        raise ValueError('missing historical eight mixed-label questions')
    conditioned={name:stats['conditioned'][name]['invariant'] for name in PROFILES}
    if conditioned != {'original_fp32':4,'q24_rne':4,'fp16_rne':6,'bf16_rne':8}:
        raise ValueError('source-invariant numeric negative controls drifted')
    if stats['no_query']['bf16_rne']['invariant'] != 8:
        raise ValueError('full no-query invariance not reproduced')
    return write_once(output, {
        'schema':SCHEMA,'authority':'DENY_ALL','blind_source_sha256':sealed_sha256,
        'original_pretrained_archive_sha256':ARCHIVE_SHA,
        'original_human_score_sha256':HUMAN_SCORE_SHA,
        'original_questions_with_mixed_human_labels':8,
        'original_candidate_count':33,'original_passage_count':4,
        'conditioned_exactly_invariant_question_counts':conditioned,
        'bf16_postlogit_conditioned_deterministic_margin_only_cannot_finish_eight_mixed_questions':True,
        'original_reader_unquantized_conditioned_cannot_finish_four_mixed_questions_if_using_only_same_question_constant_margins':True,
        'bf16_postlogit_not_equal_actual_bf16_weight_execution':True,
        'original_q24_profile_not_actual_worker_q24_receipt':True,
        'no_new_pretrained_forwards':True,'original_human_label_signer_authenticated':False,
        'prospective_learning_improvement':False,'online_FBSDE_net_gain_established':False,
        'model_selected':False,'production_accepted':False,
    })


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('archive','blind','blind-sha256','output'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    print(review(args.archive,args.blind,args.blind_sha256,args.output),'DENY_ALL')

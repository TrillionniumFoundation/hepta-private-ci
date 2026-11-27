"""E18: exact-source, label-blind ORIGINAL pretrained Reader logit-projection study.

Project EACH of the two archived FP32 logits to Q24, IEEE FP16, or BF16
before subtraction. This is NOT reduced-precision foundation-model inference,
a safe serving selection, or a trained Head. Only the original pre-score
Reader ZIP is decompressed by the existing exact-source reader.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
from math import isfinite
from pathlib import Path
from struct import pack, unpack

from e14_multirc_route import ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel, write_once

SCHEMA = 'hepta.e18.real-reader-postlogit-precision.v1'
PROFILES = ('original_fp32', 'q24_rne', 'fp16_rne', 'bf16_rne')


def projected(value: float, profile: str) -> float:
    """Hardware-format rounding of one original FP32 logit, RNE ties-to-even.

    The original archive claims source FP32 and is validated upstream; this
    function checks that the supplied value is representable in original FP32.
    """
    if type(value) not in (float, int) or not isfinite(value) or abs(value) > 8:
        raise ValueError('invalid original signed logit domain')
    v = float(value)
    try:
        exact_fp32 = unpack('>f', pack('>f', v))[0]
    except (OverflowError, ValueError) as e:
        raise ValueError('non FP32 logit') from e
    if exact_fp32 != v:
        raise ValueError('only exact original physical FP32 values are supported')
    if profile == PROFILES[0]:
        return v
    if profile == PROFILES[1]:
        return round(v * 2**24) / 2**24
    if profile == PROFILES[2]:
        return unpack('>e', pack('>e', v))[0]
    if profile == PROFILES[3]:
        bits = unpack('>I', pack('>f', v))[0]
        high, low = bits >> 16, bits & 0xFFFF
        if low > 0x8000 or (low == 0x8000 and high & 1):
            high += 1
        return unpack('>f', pack('>I', high << 16))[0]
    raise ValueError('unregistered precision profile')


def analyze(obs: dict) -> dict:
    if (type(obs) is not dict or obs.get('observation_id') != OBS_ID
            or obs.get('actual_candidate_count') != 33 or obs.get('question_count') != 8
            or type(obs.get('rows')) is not list or len(obs['rows']) != 33
            or type(obs.get('predictions')) is not dict or set(obs['predictions']) != set(ARMS)):
        raise ValueError('only original complete real pretrained model evidence')
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    for i, row in enumerate(obs['rows']):
        if (type(row) is not dict or type(row.get('source_group')) is not str
                or type(row.get('question_slot')) is not int or row['question_slot'] not in (0, 1)
                or type(row.get('task_id')) is not str):
            raise ValueError('incomplete exact original source identity')
        groups[(row['source_group'], row['question_slot'])].append(i)
    if (len(groups) != 8 or len({group for group, _ in groups}) != 4
            or sum(len(x) for x in groups.values()) != 33
            or any(not 2 <= len(x) <= 8 for x in groups.values())):
        raise ValueError('missing complete original human-question slate')
    questions = []
    for (group, slot), indices in sorted(groups.items()):
        per_arm = {}
        for arm in ARMS:
            preds = obs['predictions'][arm]
            if type(preds) is not list or len(preds) != 33:
                raise ValueError('missing original frozen Reader')
            results = {}
            for profile in PROFILES:
                margins = []
                for i in indices:
                    item = preds[i]
                    if (type(item) is not dict or item.get('task_id') != obs['rows'][i]['task_id']
                            or item.get('source_group') != group or item.get('question_slot') != slot
                            or type(item.get('logits')) is not list or len(item['logits']) != 2):
                        raise ValueError('mismatched original query/candidate/weights')
                    left = projected(item['logits'][0], profile)
                    right = projected(item['logits'][1], profile)
                    margins.append(right-left)
                results[profile] = {
                    'distinct_signed_margins': len(set(margins)),
                    'equal_margin_candidate_pairs': sum(a == b for a, b in combinations(margins, 2)),
                    'candidate_pairs': len(indices)*(len(indices)-1)//2,
                    'max_signed_margin_span': max(margins)-min(margins),
                    'distinct_hard_predictions': len({margin >= 0 for margin in margins}),
                }
            per_arm[arm] = results
        questions.append({'source_group': group, 'question_slot': slot,
                          'candidate_count': len(indices), 'arms': per_arm})
    summary = {}
    for arm in ARMS:
        summary[arm] = {}
        for profile in PROFILES:
            measures = [q['arms'][arm][profile] for q in questions]
            summary[arm][profile] = {
                'questions_exactly_candidate_invariant': sum(r['distinct_signed_margins'] == 1 for r in measures),
                'questions_with_distinguishable_candidate_margins': sum(r['distinct_signed_margins'] > 1 for r in measures),
                'questions_single_hard_prediction': sum(r['distinct_hard_predictions'] == 1 for r in measures),
                'equal_margin_candidate_pairs': sum(r['equal_margin_candidate_pairs'] for r in measures),
                'candidate_pairs': sum(r['candidate_pairs'] for r in measures),
                'max_question_margin_span': max(r['max_signed_margin_span'] for r in measures),
            }
    return {
        'schema': SCHEMA, 'authority': 'DENY_ALL', 'archive_sha256': ARCHIVE_SHA,
        'original_pretrained_observation_id': OBS_ID,
        'original_passages': 4, 'original_questions': 8, 'original_candidates': 33,
        'precision_profiles': list(PROFILES),
        'operation': 'independently_round_each_archived_fp32_logit_BEFORE_binary_margin',
        'post_logit_projection_not_reexecuted_bf16_fp16_encoder': True,
        'human_labels_opened_in_blind_stage': False,
        'existing_scored_archive_member_opened_in_blind_stage': False,
        'pretrained_model_new_forward_count': 0,
        'actual_serving_low_precision_efficacy_measured': False,
        'negative_group_bottleneck_does_not_prove_semantic_inability': True,
        'question_rows': questions, 'summary': summary,
        'model_selected': False, 'production_accepted': False,
    }


def produce(archive: str, output: str) -> str:
    return write_once(output, analyze(read_prelabel(archive)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(produce(args.archive, args.output), 'DENY_ALL')

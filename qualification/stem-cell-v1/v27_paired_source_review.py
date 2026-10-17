"""V27 independent model-output / paired weak-gold denominator publication gate.

This runs only after the separate original 135M and pinned Qwen original-128
producers and independent token-level reviewers all *successfully seal*. It is
not a human judge and may not issue any FinalUse, FBSDE or Stem capability gain.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from v21_original_plan_rebuilder import V16_PLAN_SHA, digest
V16_SCHEMA = 'hepta.stem.v16.original-literal-answer-witness.shadow.v1'
V17_SCHEMA = 'hepta.stem.v17.physical-reference-reader.shadow.v1'

SCHEMA = 'hepta.stem.v27.original-paired-qwen-host.shadow.v1'
ARMS = ('none', 'retrieved', 'witness', 'lesion')
GROUPS = ('literal_in_annotated_source', 'not_literal_in_annotated_source')


def review(plan, original_candidate, original_recount, qwen_result, qwen_review,
           weak, original_source):
    if (digest(plan) != V16_PLAN_SHA or len(plan['requests']) != 128
        or original_candidate.get('schema') != V16_SCHEMA + '.actual-original-reader-results'
        or original_candidate.get('requests') != 128
        or original_candidate.get('model_forwards') != 2951
        or qwen_result.get('schema') != V17_SCHEMA + '.sealed-model-output'
        or qwen_result.get('reference_request_count') != 128
        or qwen_review.get('schema') != V17_SCHEMA + '.independent-byte-review'
        or qwen_review.get('verified_reference_requests') != 128
        or qwen_review.get('decision') != 'RECEIPT_BYTES_ONLY_HOLD_NO_GO'):
        raise ValueError('unsealed original physical comparator or full Qwen reference')
    if (original_recount.get('verified_requests') != 128
        or original_recount.get('model_forward_calls') != 2951
        or original_recount.get('token_input_total') != 16264
        or original_recount.get('token_output_total') != 2855
        or original_recount.get('semantic_accuracy') is not None
        or original_recount.get('production_authorized') is not False):
        raise ValueError('original candidate physical receipt not independently authenticated')
    if (qwen_result.get('production_authorized') is not False
        or qwen_result.get('independent_human_evidence_sufficiency') is not False
        or qwen_result.get('semantic_accuracy') is not None
        or qwen_review.get('production_authorized') is not False):
        raise ValueError('reference physical output falsely promoted')
    from v17_reference_independent_review import weak_gold_compare
    expected = weak_gold_compare(plan, original_candidate['raw_answers'],
                                 qwen_result['raw_answers'], original_source)
    if weak != expected or weak.get('decision') != 'HOLD_NO_GO':
        raise ValueError('gold was scored independently incorrectly')
    counts = weak['per_cohort_arm']
    if type(counts) is not dict or set(counts) != set(GROUPS):
        raise ValueError('missing grouped original 128 task census')
    for group,arms in counts.items():
        if type(arms) is not dict or set(arms) != set(ARMS):
            raise ValueError('missing evidence arm in paired study')
        for arm,totals in arms.items():
            if totals['cases'] != 16 or (totals['publisher_answer_known']
                                        + totals['publisher_answer_unknown']) != 16:
                raise ValueError('original source labels incorrectly censored')
    if (counts[GROUPS[0]]['witness']['candidate_substring'] != 8
        or counts[GROUPS[0]]['retrieved']['candidate_substring'] != 0
        or counts[GROUPS[0]]['none']['candidate_substring'] != 0
        or counts[GROUPS[0]]['lesion']['candidate_substring'] != 0
        or counts[GROUPS[1]]['retrieved']['candidate_substring'] != 1
        or counts[GROUPS[1]]['lesion']['candidate_substring'] != 1
        or counts[GROUPS[1]]['witness']['candidate_substring'] != 0):
        raise ValueError('original physical candidate historical outcomes drifted')
    if any(counts[GROUPS[1]][a]['publisher_answer_unknown'] != 5 for a in ARMS):
        raise ValueError('five missing publisher answers not censored correctly')
    ref_input = qwen_review['verified_reference_input_tokens']
    ref_output = qwen_review['verified_reference_output_tokens']
    if (type(ref_input) is not int or type(ref_output) is not int
        or ref_input <= 0 or not 128 <= ref_output <= 128*24):
        raise ValueError('missing actual reference token usage')
    def sane_time(x):
        return type(x) in (float, int) and math.isfinite(x) and 0 < x < 24*3600
    if not all(map(sane_time, (
         original_candidate['execution_cpu_seconds'],
         original_candidate['execution_wall_seconds'],
         qwen_result['execution_cpu_seconds'],
         qwen_result['execution_wall_seconds']))):
        raise ValueError('missing non-synthetic physical CPU or wall samples')
    # Entire returned object is deliberately aggregate-only; never emit
    # original questions, source IDs, prompts, labels, raw answers or token IDs.
    return {
        'schema': SCHEMA + '.paired-original-physical-sanitized',
        'original_plan_sha256': V16_PLAN_SHA,
        'original_135m_requests': 128,
        'original_135m_model_forwards': 2951,
        'qwen_reference_requests': 128,
        'qwen_reference_input_tokens': ref_input,
        'qwen_reference_output_tokens': ref_output,
        'original_135m_cpu_seconds': original_candidate['execution_cpu_seconds'],
        'qwen_cpu_seconds': qwen_result['execution_cpu_seconds'],
        'per_cohort_arm_weak_literal_only': counts,
        'historical_root_count': 4,
        'publisher_answers_missing_case_count': 5,
        'independently_reviewed_semantic_accuracy': None,
        'human_evidence_sufficiency_verified': False,
        'matched_full_lifecycle_cost': False,
        'stem_gain_attributed': False,
        'ndu_gain_attributed': False,
        'cell_split_gain_attributed': False,
        'production_authorized': False,
        'decision': 'PAIRED_PRETRAINED_BYTES_ONLY_HOLD_NO_GO',
    }


def cli():
    a=argparse.ArgumentParser()
    for f in ('plan','candidate','original-recount','reference','reference-recount',
              'weak-gold','original-gold'):
        a.add_argument('--'+f,required=True)
    args=a.parse_args()
    from v16_literal_witness_reader import read
    paths=lambda attr: read(getattr(args,attr.replace('-','_')))
    result=review(paths('plan'),paths('candidate'),paths('original-recount'),
                  paths('reference'),paths('reference-recount'),
                  paths('weak-gold'),paths('original-gold'))
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':cli()

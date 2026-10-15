#!/usr/bin/env python3
"""E22: original-human MultiRC answer-information obstruction (RESEARCH ONLY).

A blind pass consumes E21's six original pretrained/frozen or held-fold learned
Reader predictions, WITHOUT original human labels. An independent post-seal pass
opens pinned human labels and the independently reconciled E21 score, not a
new/fitted predictor. Pair rankings and complete-question truth are kept apart
from the producer. No NDU solver may override the Reader sufficiency gate.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

SOURCE_SHA = '1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
VAL_SHA = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
E15_HEAD = 'd4d71baa8c00821fe385c1a47ed7b68b4255ad6e'
BLIND_INPUT = 'hepta.e21.real-reader-whole-question-blind.v1'
E21_SCORE = 'hepta.e21.original-human-question-level-review.v1'
BLIND_SCHEMA = 'hepta.e22.multirc-answer-information-blind.v1'
SCORE_SCHEMA = 'hepta.e22.multirc-answer-information-human-review.v1'
FROZEN = ('conditioned', 'mean_pool_query_fused', 'no_evidence', 'no_query')
LEARNED = ('learned_linear_5', 'learned_gated_3')
ALL = FROZEN + LEARNED


class EvidenceDenied(ValueError):
    """The bounded original-source research evidence has failed closed."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise EvidenceDenied(reason)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes) -> Any:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out = {}
        for key, value in pairs:
            require(key not in out, 'duplicate JSON member')
            out[key] = value
        return out
    try:
        return json.loads(data, object_pairs_hook=pairs_hook,
                          parse_constant=lambda x: (_ for _ in ()).throw(
                              EvidenceDenied('nonfinite JSON literal: ' + x)))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceDenied('malformed JSON') from exc


def load(path: Path, max_bytes: int = 1_000_000) -> tuple[bytes, Any]:
    require(path.is_file() and not path.is_symlink() and
            path.stat().st_size <= max_bytes, 'missing or unbounded regular input')
    raw = path.read_bytes()
    return raw, strict_json(raw)


def emit_once(path: Path, value: Any) -> str:
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False) + '\n').encode('utf-8')
    require(len(raw) <= 1_000_000 and not path.is_symlink(), 'bounded regular output required')
    with path.open('xb') as out:
        out.write(raw)
    return sha256(raw)


def hard_class(arm: str, p: float) -> int:
    return int(p >= 0.5) if arm in LEARNED else int(p > 0.5)


def check_original_blind(blind: Any) -> dict[tuple[Any, Any], list[dict[str, Any]]]:
    require(type(blind) is dict and set(blind) == {
        'schema', 'authority', 'production_accepted', 'source_archive_sha256',
        'e15_head', 'real_pretrained_forwards_new', 'held_human_labels_opened',
        'source_group_count', 'question_count', 'candidate_count', 'rows'},
        'not the complete sealed original E21 blind schema')
    require(blind['schema'] == BLIND_INPUT and blind['authority'] == 'DENY_ALL' and
            blind['production_accepted'] is False and
            blind['source_archive_sha256'] == SOURCE_SHA and
            blind['e15_head'] == E15_HEAD and
            type(blind['real_pretrained_forwards_new']) is int and
            blind['real_pretrained_forwards_new'] == 0 and
            blind['held_human_labels_opened'] is False and
            tuple(blind[x] for x in ('source_group_count', 'question_count', 'candidate_count'))
            == (4, 8, 33), 'original provenance or authority mismatch')
    rows = blind['rows']
    require(type(rows) is list and len(rows) == 33, '33 original candidates required')
    questions: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    seen: set[Any] = set()
    v1_count = 0
    for row in rows:
        require(type(row) is dict and set(row) == {
            'task_id', 'source_group', 'question_slot', 'candidate_id',
            'original_v1_candidate', 'probs'}, 'original candidate field mismatch')
        tid = row['task_id']
        require(type(tid) is str and len(tid) > 0 and tid not in seen,
                'duplicate or invalid task id')
        seen.add(tid)
        require(type(row['source_group']) is str and row['source_group'] and
                type(row['question_slot']) in (int, str) and
                type(row['candidate_id']) in (int, str) and
                type(row['original_v1_candidate']) is bool,
                'invalid original candidate identity')
        require(type(row['probs']) is dict and set(row['probs']) == set(ALL),
                'six original predictors are mandatory')
        for p in row['probs'].values():
            require(type(p) is float and math.isfinite(p) and 0 < p < 1,
                    'invalid original floating score')
        v1_count += int(row['original_v1_candidate'])
        questions[(row['source_group'], row['question_slot'])].append(row)
    require(len(questions) == 8 and len({q[0] for q in questions}) == 4 and
            all(len(v) >= 2 for v in questions.values()) and v1_count == 8,
            'original question/passage or V1 anchor census changed')
    return questions


def blind_audit(blind: Any, raw: bytes) -> dict[str, Any]:
    groups = check_original_blind(blind)
    per_question = []
    for (passage, slot), rows in sorted(groups.items(), key=lambda t: str(t[0])):
        arms = {}
        for arm in ALL:
            values = [r['probs'][arm] for r in rows]
            classes = {hard_class(arm, p) for p in values}
            arms[arm] = {
                'distinct_hard_labels': len(classes),
                'constant_hard_label': len(classes) == 1,
                'exact_constant_score': len(set(values)) == 1,
                'max_minus_min_probability': round(max(values)-min(values), 15),
                'probability_span_at_most_0p001_diagnostic': max(values)-min(values) <= .001,
            }
        per_question.append({'source_group': passage, 'question_slot': slot,
                             'candidate_count': len(rows), 'arms': arms})
    return {
        'schema': BLIND_SCHEMA, 'e21_blind_sha256': sha256(raw),
        'source_archive_sha256': SOURCE_SHA, 'original_reader_arms': list(ALL),
        'original_passage_count': 4, 'original_question_count': 8,
        'original_candidate_count': 33, 'question_information': per_question,
        'human_labels_opened': False, 'new_pretrained_model_forwards': 0,
        'reader_sufficiency_certified': False, 'ndu_system2_admitted': False,
        'production_accepted': False, 'authority_posture': 'DENY_ALL',
    }


def adjudicate(blind: Any, blind_raw: bytes, sealed: Any,
               labels: Any, prior_review: Any) -> dict[str, Any]:
    # The independent scorer rederives the entire unlabeled report, not just its
    # self-reported digest. The caller must verify its SHA from the blind job.
    require(type(sealed) is dict and sealed == blind_audit(blind, blind_raw),
            'blind geometry does not replay under original sealed source')
    groups = check_original_blind(blind)
    require(type(labels) is dict and set(labels) == {r['task_id'] for r in blind['rows']}
            and all(type(v) is int and v in (0, 1) for v in labels.values()),
            'original binary human label set mismatch')
    require(type(prior_review) is dict and prior_review.get('schema') == E21_SCORE and
            prior_review.get('authority') == 'DENY_ALL' and
            prior_review.get('production_accepted') is False and
            prior_review.get('human_score_source_head_and_synthetic_merge_reconciled') is True and
            prior_review.get('original_source_and_merge_scores_reconciled') is True and
            prior_review.get('source_original_human_labels_sha256') == VAL_SHA and
            prior_review.get('model_selected') is False and
            prior_review.get('fbsde_reactivation_allowed') is False and
            prior_review.get('original_human_passage_groups') == 4 and
            prior_review.get('candidate_count') == 33 and
            prior_review.get('original_question_count') == 8,
            'independently reconciled E21 score prerequisite missing')
    methods = prior_review.get('method_results')
    require(type(methods) is dict and set(methods) == set(ALL),
            'incomplete independent six-arm prior review')
    results: dict[str, dict[str, Any]] = {}
    for arm in ALL:
        correct = 0
        brier_sum = 0.0
        passage_correct: dict[str, int] = defaultdict(int)
        passage_total: dict[str, int] = defaultdict(int)
        full_question_count = 0
        full_passage_hits: dict[str, bool] = {}
        rank_concordant = rank_discordant = rank_tied = 0
        structurally_constant_questions = 0
        hard_constant_questions = 0
        question_results = []
        for (group, slot), rows in sorted(groups.items(), key=lambda kv: str(kv[0])):
            truth = [labels[r['task_id']] for r in rows]
            require(set(truth) == {0, 1}, 'original mixed-answer question missing')
            ps = [r['probs'][arm] for r in rows]
            preds = [hard_class(arm, v) for v in ps]
            hits = [int(x == y) for x, y in zip(preds, truth)]
            correct += sum(hits)
            passage_correct[group] += sum(hits)
            passage_total[group] += len(rows)
            brier_sum += sum(2 * (p-y)**2 for p, y in zip(ps, truth))
            complete = all(hits)
            full_question_count += int(complete)
            full_passage_hits[group] = full_passage_hits.get(group, True) and complete
            constant_score = len(set(ps)) == 1
            constant_class = len(set(preds)) == 1
            structurally_constant_questions += int(constant_score)
            hard_constant_questions += int(constant_class)
            pos = [p for p, y in zip(ps, truth) if y == 1]
            neg = [p for p, y in zip(ps, truth) if y == 0]
            counts = [0, 0, 0]
            for positive, negative in itertools.product(pos, neg):
                counts[(0 if positive > negative else 1 if positive < negative else 2)] += 1
            rank_concordant += counts[0]
            rank_discordant += counts[1]
            rank_tied += counts[2]
            # If model output is constant across different true alternatives,
            # *no deterministic function of this score alone* can classify both.
            require(not (constant_class and complete),
                    'constant binary output cannot solve a mixed-label question')
            question_results.append({
                'source_group': group, 'question_slot': slot,
                'candidate_count': len(rows), 'complete_question': complete,
                'positive_count': len(pos), 'negative_count': len(neg),
                'constant_score': constant_score, 'constant_hard_class': constant_class,
                'concordant_pos_negative_pairs': counts[0],
                'discordant_pos_negative_pairs': counts[1],
                'exact_tied_pos_negative_pairs': counts[2],
            })
        expected = methods[arm]
        require(type(expected) is dict and expected.get('correct') == correct and
                expected.get('total') == 33 and
                abs(expected.get('brier', float('inf'))-brier_sum/33) <= 2e-12 and
                expected.get('passage_correct') == dict(sorted(passage_correct.items())) and
                expected.get('passage_total') == dict(sorted(passage_total.items())) and
                expected.get('complete_question_count') == full_question_count and
                expected.get('complete_passage_count') == sum(full_passage_hits.values()),
                'original-human detailed score differs from independently reconciled E21')
        results[arm] = {
            'candidate_correct': correct, 'complete_question_count': full_question_count,
            'complete_passage_count': sum(full_passage_hits.values()),
            'constant_score_question_count': structurally_constant_questions,
            'constant_hard_class_question_count': hard_constant_questions,
            'positive_negative_pair_concordant': rank_concordant,
            'positive_negative_pair_discordant': rank_discordant,
            'positive_negative_pair_exact_tied': rank_tied,
            'positive_negative_pair_total': rank_concordant+rank_discordant+rank_tied,
            'per_question': question_results,
        }
    require(results['no_query']['constant_score_question_count'] == 8,
            'original real no-query negative-control must remain constant')
    return {
        'schema': SCORE_SCHEMA, 'source_archive_sha256': SOURCE_SHA,
        'human_labels_sha256': VAL_SHA, 'e21_blind_sha256': sha256(blind_raw),
        'human_truth_reopened_in_independent_postseal_job': True,
        'original_source_and_merge_e21_scores_reconciled': True,
        'original_passages': 4, 'original_questions': 8, 'candidate_answers': 33,
        'rankings_are_descriptive_and_cluster_dependent': True,
        'answer_information_support_for_full_ndu_system2': False,
        'no_query_mixed_question_complete_success_upper_bound': 0,
        'new_pretrained_forward_calls': 0, 'new_trained_parameters': 0,
        'new_future_source_families': 0, 'model_selected': False,
        'production_accepted': False, 'authority_posture': 'DENY_ALL',
        'arm_results': results,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='mode', required=True)
    a = sub.add_parser('blind')
    a.add_argument('--e21-blind', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True)
    b = sub.add_parser('score')
    b.add_argument('--e21-blind', type=Path, required=True)
    b.add_argument('--blind-summary', type=Path, required=True)
    b.add_argument('--validation', type=Path, required=True)
    b.add_argument('--e21-reviewed-score', type=Path, required=True)
    b.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    raw, blind = load(args.e21_blind)
    if args.mode == 'blind':
        answer = blind_audit(blind, raw)
    else:
        _, sealed = load(args.blind_summary)
        label_bytes = args.validation.read_bytes()
        require(sha256(label_bytes) == VAL_SHA, 'human label parquet SHA mismatch')
        import pyarrow.parquet as pq
        from e14_multirc_score import original_labels
        frame = pq.read_table(args.validation,
                              columns=['paragraph','question','answer','label','idx']).to_pylist()
        ids = [{k:r[k] for k in ('task_id','source_group','question_slot',
                                'candidate_id','original_v1_candidate')}
               for r in blind['rows']]
        labels = original_labels(frame, ids)
        _, reviewed = load(args.e21_reviewed_score)
        answer = adjudicate(blind, raw, sealed, labels, reviewed)
    print(emit_once(args.output, answer))


if __name__ == '__main__':
    main()

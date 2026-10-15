"""14-case ORIGINAL typed-vs-untyped Head disagreement Reader diagnostic.

Uses 10 exact source-changing + 4 source-order-changing cases from two
historical LoCoMo source families. True archived CPU model weights only.
Not official Hugging Face parity, equal-token/total-compute causality, an
independent semantic judge, future evidence, or production permission.

Phases: plan (NO GOLD) -> generate (NO GOLD) -> score (POST SEAL ONLY).
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

from amcn_original_trained_rank_heads import (
    SOURCE_SHA, RANK_DECISION_SHA, RANK_SHA, GOLD_SHA,
    pinned, file_sha, load_source_and_rank, verify_original_predictions,
    stable_rank_digest, require,
)
from amcn_original_text_reader import (
    ArchivedLlama, ArchivedByteLevelBPE, format_archived_chat, WEIGHT_SHA256,
)

PROFILE = 'hepta.amcn.original-two-family-14-typed-untyped-physical-reader.shadow.v1'
ARMS = ('bm25', 'untyped_equal_budget', 'typed_equal_budget')
FAMILIES = {'conv-49': 'retrospective_heldout_a',
            'conv-50': 'retrospective_heldout_b'}
TOKENIZER_SHA = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
PRED_SHA = 'a937d4fd91e0c75cf4ddd265760c0b6c4cf1ed0947ad0c5be323686aca7391a3'
BANK_SHA = '88dbb2c9feffea97058c455f9a1292d21601a39449b6fee47169b540d6759fb6'
DATASET_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
PUBLISHER_PUBLIC_PAYLOAD_SHA = '0cb3b98eb0ff066703a0a5f7d1d2964abb1409b42f6f42c862ffb3f619de97e3'
MAX_NEW = 32
CONTEXT_MAX = 1024
CASES = 14
EXPECTED_SOURCE_CHANGES = 10
EXPECTED_ORDER_ONLY = 4
MAX_JSON = 16 * 1024 * 1024


def sha_bytes(data):
    return sha256(data).hexdigest()


def sha_text(text):
    return sha_bytes(text.encode('utf-8'))


def canonical(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def pair_unique(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, 'duplicate JSON field in original evidence')
        result[k] = v
    return result


def read_pinned(path, expected, *, limit=MAX_JSON):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
            'missing/unsafe bounded research source')
    raw = path.read_bytes()
    require(sha_bytes(raw) == expected, 'externally pinned original bytes changed')
    return json.loads(raw, object_pairs_hook=pair_unique)


def create_once(path, obj):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), 'no overwriting original evidence')
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(obj)
    with path.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return sha_bytes(raw)


def append_attempt(path, item):
    with Path(path).open('ab') as f:
        f.write(canonical(item)); f.flush(); os.fsync(f.fileno())


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_JSON,
            'unsafe original Reader attempts')
    raw = path.read_bytes()
    require(raw.endswith(b'\n'), 'torn original Reader journal')
    return [json.loads(line, object_pairs_hook=pair_unique) for line in raw.splitlines()]


def validate_plan(plan):
    require(isinstance(plan, dict) and plan.get('schema') == PROFILE and
            plan.get('source_sha256') == SOURCE_SHA and
            plan.get('original_rank_sha256') == RANK_SHA and
            plan.get('rank_decision_sha256') == RANK_DECISION_SHA and
            plan.get('original_predictions_sha256') == PRED_SHA and
            plan.get('original_bank_sha256') == BANK_SHA and
            plan.get('reader_sha256') == WEIGHT_SHA256 and
            plan.get('tokenizer_sha256') == TOKENIZER_SHA and
            plan.get('max_output_tokens') == MAX_NEW and
            plan.get('final_evidence_slots') == 3 and
            plan.get('arms') == list(ARMS) and len(plan.get('cases', [])) == CASES and
            plan.get('case_selection_from_publisher_gold') is False and
            plan.get('official_hf_parity_verified') is False and
            plan.get('production_accepted') is False,
            'foreign original pinned E2 cohort')
    seen = set()
    kinds = Counter()
    for case in plan['cases']:
        require(case['family'] in FAMILIES and
                case['split'] == FAMILIES[case['family']] and
                case['case_id'] not in seen and
                isinstance(case['question_sha256'], str) and
                set(case['requests']) == set(ARMS),
                'missing or changed original heldout query')
        seen.add(case['case_id']); kinds[case['divergence_kind']] += 1
        for arm in ARMS:
            q = case['requests'][arm]
            require(type(q['input_tokens']) is int and q['input_tokens'] > 0 and
                    q['input_tokens'] + MAX_NEW <= CONTEXT_MAX and
                    len(q['source_ids']) == 3 and len(set(q['source_ids'])) == 3 and
                    q['prompt_sha256'] == sha_text(q['prompt']) and
                    'publisher_support' not in q and 'answer' not in q,
                    'mutated original Reader source/prompt/token bound')
        ids = case['requests']
        require(ids['typed_equal_budget']['source_ids'] !=
                ids['untyped_equal_budget']['source_ids'],
                'not an actual Head-disagreement case')
        kind = ('source_replacement' if set(ids['typed_equal_budget']['source_ids']) !=
                set(ids['untyped_equal_budget']['source_ids']) else 'order_only')
        require(kind == case['divergence_kind'], 'Head divergence relabelled')
    require(kinds['source_replacement'] == EXPECTED_SOURCE_CHANGES and
            kinds['order_only'] == EXPECTED_ORDER_ONLY and
            len({v['case_id'] for v in plan['cases']}) == CASES and
            Counter(x['family'] for x in plan['cases']) == {'conv-49': 6, 'conv-50': 8},
            'incomplete 400-case original typed-vs-untyped divergence census')
    return [(c, arm) for c in plan['cases'] for arm in ARMS]


def build_plan(public, original_rank, preds, *, original_rank_sha, reader_dir,
               physical_head_bank=None):
    """No publisher gold argument or import. Source + original physical Head only."""
    require(public.get('publisher_targets_not_included') is True and
            public.get('production_accepted') is False and
            len(public.get('cases', [])) == 1986 and
            len(public.get('source_families', {})) == 10 and
            stable_rank_digest(original_rank) == RANK_DECISION_SHA and
            original_rank.get('training_or_publisher_gold_accessed') is False and
            original_rank_sha == RANK_SHA and
            preds.get('source_sha256') == SOURCE_SHA and
            preds.get('rank_sha256') == RANK_SHA and
            preds.get('bank_manifest_sha256') == BANK_SHA and
            preds.get('training_gold_never_opened_in_prediction_process') is True and
            preds.get('original_physical_trained_head_forwards') == 3316 and
            preds.get('production_accepted') is False and
            len(preds.get('complete_predictions', [])) == 829,
            'original source/physical Head/readback provenance missing')
    if physical_head_bank is not None:
        require(file_sha(Path(physical_head_bank) / 'manifest.json') == BANK_SHA,
                'physical source tensor bank manifest mismatch')
        original = load_source_and_rank(physical_head_bank.parent / 'public-sources-only.json',
                 SOURCE_SHA, physical_head_bank.parent / 'ten-family-real-original-minilm-rank.json', RANK_SHA)
        require(verify_original_predictions(original, physical_head_bank, BANK_SHA,
                       preds['complete_predictions'], SOURCE_SHA, RANK_SHA) == 3316,
                'original physical Head forwards did not replay')
    tokenizer = ArchivedByteLevelBPE(Path(reader_dir), expected_tokenizer_sha256=TOKENIZER_SHA)
    by_q = {c['case_id']: c for c in public['cases']}
    require(len(by_q) == 1986 and all(set(c) ==
        {'case_id', 'family', 'split', 'question', 'question_sha256'}
        for c in public['cases']), 'benchmark labels in original question records')
    require(len({x['case_id'] for x in preds['complete_predictions']}) == 829,
            'duplicate original physical Head question')
    cases = []
    for p in preds['complete_predictions']:
        if p['family'] not in FAMILIES:
            continue
        question = by_q[p['case_id']]
        require(question['family'] == p['family'] and
                question['split'] == p['split'] == FAMILIES[p['family']] and
                question['question_sha256'] == p['question_sha256'] ==
                sha_text(question['question']), 'original source/question changed')
        ranks = p['ranked_source_ids']
        selected = {arm: ranks[arm][:3] for arm in ARMS}
        if selected['typed_equal_budget'] == selected['untyped_equal_budget']:
            continue
        inventory = {x['id']: x['text'] for x in public['source_families'][p['family']]}
        require(all(sid in inventory for ids in selected.values() for sid in ids),
                'unknown source injected into registered 3-Head result')
        requests = {}
        for arm in ARMS:
            texts = [inventory[sid] for sid in selected[arm]]
            prompt = format_archived_chat(question['question'], texts)
            tokens = tokenizer.encode(prompt)
            require(0 < len(tokens) <= CONTEXT_MAX - MAX_NEW,
                    'actual original Reader prompt exceeds maximum context')
            requests[arm] = {'source_ids': selected[arm], 'prompt': prompt,
                             'prompt_sha256': sha_text(prompt),
                             'input_tokens': len(tokens)}
        cases.append({'case_id': p['case_id'], 'family': p['family'],
                      'split': p['split'], 'question_sha256': p['question_sha256'],
                      'memory_type': p['memory_type'],
                      'divergence_kind': ('source_replacement' if
                          set(selected['typed_equal_budget']) !=
                          set(selected['untyped_equal_budget']) else 'order_only'),
                      'requests': requests})
    cases.sort(key=lambda c: (c['family'], int(c['case_id'].split(':')[-1])))
    plan = {'schema': PROFILE, 'source_sha256': SOURCE_SHA,
            'original_rank_sha256': RANK_SHA,
            'rank_decision_sha256': RANK_DECISION_SHA,
            'original_predictions_sha256': PRED_SHA,
            'original_bank_sha256': BANK_SHA,
            'reader_sha256': WEIGHT_SHA256,
            'tokenizer_sha256': TOKENIZER_SHA,
            'max_output_tokens': MAX_NEW, 'final_evidence_slots': 3,
            'arms': list(ARMS), 'cases': cases,
            'case_selection_rule': 'ALL source/order Top3 divergences of original two heldout families from 400 original questions; never gold',
            'case_selection_from_publisher_gold': False,
            'official_hf_parity_verified': False,
            'independent_future_calendar_windows': 0,
            'production_accepted': False}
    validate_plan(plan)
    return plan


def _audit_attempts(plan, folder, tokenizer):
    ordered = validate_plan(plan)
    starts = read_jsonl(Path(folder) / 'starts.jsonl')
    answers = read_jsonl(Path(folder) / 'raw_answers.jsonl')
    require(len(answers) <= len(starts) <= len(answers) + 1,
            'lost or unmatched original inference starts')
    completed = {}
    cursor = 0
    active = None
    failure = 0
    for i, row in enumerate(answers):
        st = starts[i]
        require(st.get('case_id') == row.get('case_id') and
                st.get('arm') == row.get('arm') and
                st.get('prompt_sha256') == row.get('prompt_sha256') and
                st.get('reader_sha256') == row.get('reader_sha256') == WEIGHT_SHA256,
                'start and original response disagree')
        key = (st['case_id'], st['arm'])
        require(cursor < len(ordered), 'unexpected model attempt beyond 42 originals')
        expected = ordered[cursor]
        require(key == (expected[0]['case_id'], expected[1]),
                'Reader attempt order or original candidate cohort changed')
        q = expected[0]['requests'][expected[1]]
        require(st['prompt_sha256'] == q['prompt_sha256'], 'original prompt altered')
        if row.get('status') == 'failed':
            require(row.get('not_completed') is True and set(row) ==
                    set(st) | {'status', 'not_completed'},
                    'invalid failed model attempt')
            failure += 1
            continue  # preserves target for next retry
        require(row.get('status') == 'ok' and key not in completed and
                row.get('source_ids') == q['source_ids'] and
                row.get('input_tokens') == q['input_tokens'] and
                type(row.get('output_tokens')) is int and
                1 <= row['output_tokens'] <= MAX_NEW and
                type(row.get('generated_token_ids')) is list and
                len(row['generated_token_ids']) == row['output_tokens'] and
                all(type(z) is int and 0 <= z < 49152 for z in row['generated_token_ids']) and
                row.get('raw_model_text') == tokenizer.decode(row['generated_token_ids']) and
                row.get('raw_model_text_sha256') == sha_text(row['raw_model_text']),
                'original model result altered / inconsistent token budget')
        completed[key] = row
        cursor += 1
    if len(starts) > len(answers):
        last = starts[-1]
        require(cursor < len(ordered) and
                (last.get('case_id'), last.get('arm')) ==
                (ordered[cursor][0]['case_id'], ordered[cursor][1]) and
                last.get('prompt_sha256') == ordered[cursor][0]['requests'][ordered[cursor][1]]['prompt_sha256'] and
                last.get('reader_sha256') == WEIGHT_SHA256,
                'dangling original Reader attempt is unregistered')
        active = last
    return ordered, completed, active, failure


def run(plan, reader_dir, outdir):
    """Resume only incomplete candidate; retain all previously logged attempts."""
    validate_plan(plan)
    outdir = Path(outdir)
    if not outdir.exists():
        outdir.mkdir(parents=True)
    require(outdir.is_dir() and not outdir.is_symlink() and
            not (outdir / 'seal.json').exists(), 'sealed or unsafe Reader output')
    tok = ArchivedByteLevelBPE(Path(reader_dir), expected_tokenizer_sha256=TOKENIZER_SHA)
    starts_file = outdir / 'starts.jsonl'
    answers_file = outdir / 'raw_answers.jsonl'
    ordered, completed, active, failures = _audit_attempts(plan, outdir, tok)
    import torch
    torch.set_num_threads(2)
    model = ArchivedLlama(Path(reader_dir))
    for case, arm in ordered:
        key = (case['case_id'], arm)
        if key in completed:
            continue
        req = case['requests'][arm]
        if active is not None:
            append_attempt(answers_file, {**active, 'status': 'failed', 'not_completed': True})
            failures += 1
            active = None
        tokens = tok.encode(req['prompt'])
        require(len(tokens) == req['input_tokens'] and len(tokens)+MAX_NEW<=CONTEXT_MAX,
                'original tokenizer exact input drift')
        st = {'case_id': case['case_id'], 'arm': arm,
              'prompt_sha256': req['prompt_sha256'], 'reader_sha256': WEIGHT_SHA256}
        append_attempt(starts_file, st)
        try:
            t0 = perf_counter()
            output_ids = model.generate(tokens, max_new_tokens=MAX_NEW)
            elapsed = perf_counter() - t0
            output = tok.decode(output_ids)
            rec = {**st, 'status': 'ok', 'source_ids': req['source_ids'],
                   'input_tokens': len(tokens), 'output_tokens': len(output_ids),
                   'generated_token_ids': output_ids,
                   'raw_model_text': output, 'raw_model_text_sha256': sha_text(output),
                   'wall_seconds': elapsed}
        except Exception:
            append_attempt(answers_file, {**st, 'status': 'failed', 'not_completed': True})
            raise
        append_attempt(answers_file, rec)
        print(f'original_reader_completed {len(completed)+1}/{len(ordered)} case={case["case_id"]} arm={arm} tokens={len(output_ids)}', flush=True)
        completed[key] = rec
    ordered, complete, active, failures = _audit_attempts(plan, outdir, tok)
    require(len(complete) == CASES * len(ARMS) and active is None,
            'not all original Reader calls completed')
    sealed = {'schema': PROFILE + '.original-answer-seal.v1',
              'original_plan_sha256': sha_bytes(canonical(plan)),
              'source_sha256': SOURCE_SHA, 'head_predictions_sha256': PRED_SHA,
              'reader_sha256': WEIGHT_SHA256, 'tokenizer_sha256': TOKENIZER_SHA,
              'start_journal_sha256': file_sha(starts_file),
              'answer_journal_sha256': file_sha(answers_file),
              'actual_attempts': len(read_jsonl(starts_file)),
              'successful_original_reader_calls': len(complete),
              'failed_attempts_preserved': failures,
              'all_original_calls_completed': True,
              'gold_accessed_before_seal': False,
              'official_hf_parity_verified': False,
              'production_accepted': False}
    create_once(outdir / 'seal.json', sealed)
    return sealed



def verify_original_seal(plan, folder, seal, tokenizer):
    """Recount original answer/token bytes BEFORE any postseal targets open."""
    original = Path(folder)
    validate_plan(plan)
    require(seal.get('schema') == PROFILE + '.original-answer-seal.v1' and
            seal.get('original_plan_sha256') == sha_bytes(canonical(plan)) and
            seal.get('source_sha256') == SOURCE_SHA and
            seal.get('head_predictions_sha256') == PRED_SHA and
            seal.get('reader_sha256') == WEIGHT_SHA256 and
            seal.get('tokenizer_sha256') == TOKENIZER_SHA and
            seal.get('all_original_calls_completed') is True and
            seal.get('gold_accessed_before_seal') is False and
            seal.get('official_hf_parity_verified') is False and
            seal.get('production_accepted') is False,
            'original sealed Reader identity/negative authority missing')
    require(file_sha(original / 'starts.jsonl') == seal.get('start_journal_sha256')
            and file_sha(original / 'raw_answers.jsonl') == seal.get('answer_journal_sha256'),
            'raw Reader journal bytes differ from original seal')
    ordered, completed, dangling, failures = _audit_attempts(plan, folder, tokenizer)
    require(dangling is None and len(ordered) == len(completed) == 42 and
            seal.get('successful_original_reader_calls') == len(completed) and
            seal.get('actual_attempts') == len(read_jsonl(original / 'starts.jsonl')) and
            seal.get('failed_attempts_preserved') == failures,
            'failed or omitted original Reader attempts in sealed result')
    return completed, failures


def score(plan, folder, seal, gold, raw_locomo, *, reader_dir):
    """POST-SEAL publisher weak evidence + literal QA, no inferred entailment."""
    tok = ArchivedByteLevelBPE(Path(reader_dir), expected_tokenizer_sha256=TOKENIZER_SHA)
    completed, failed = verify_original_seal(plan, folder, seal, tok)
    require(gold.get('public_payload_sha256') == PUBLISHER_PUBLIC_PAYLOAD_SHA and
            gold.get('independent_human_entailment') is False and
            gold.get('calendar_future_windows') == 0 and
            raw_locomo is not None, 'publisher weak label/original source identity drift')
    weak = {c['case_id']: c for c in gold['cases']}
    require(len(weak) == 1986, 'original weak publisher labels incomplete')
    original = {c['sample_id']: c for c in raw_locomo}
    require(len(original) == 10, 'original LoCoMo families unavailable')
    metrics = ('questions', 'weak_any_at3', 'weak_all_at3',
               'strict_literal_answer_match', 'ordinary_questions',
               'adversarial_questions', 'ordinary_exact', 'adversarial_exact',
               'missing_publisher_answer', 'input_tokens', 'output_tokens',
               'output_hit_max32')
    totals = {arm: dict.fromkeys(metrics, 0) for arm in ARMS}
    by_root = {root: {arm: dict.fromkeys(metrics, 0) for arm in ARMS}
               for root in FAMILIES}
    by_kind = {kind: {arm: dict.fromkeys(metrics, 0) for arm in ARMS}
               for kind in ('source_replacement', 'order_only')}
    per_q = []
    type_diff_answer_text = 0
    for case in plan['cases']:
        cid, family = case['case_id'], case['family']
        require(cid in weak and weak[cid]['family'] == family and
                isinstance(weak[cid].get('publisher_support'), list),
                'publisher support not original source-bound')
        f, idx = cid.rsplit(':', 1)
        require(f == family and idx.isdigit() and len(original[family]['qa']) > int(idx),
                'unknown original 10-family LoCoMo question')
        label = original[family]['qa'][int(idx)]
        require(sha_text(label['question']) == case['question_sha256'],
                'postseal gold question identity changed')
        normal = label.get('answer')
        adversarial = label.get('adversarial_answer')
        if isinstance(normal, (str, int, float)) and str(normal).strip():
            gold_text, label_kind = str(normal), 'ordinary'
        elif isinstance(adversarial, (str, int, float)) and str(adversarial).strip():
            gold_text, label_kind = str(adversarial), 'adversarial'
        else:
            gold_text, label_kind = None, 'missing'
        support = set(weak[cid]['publisher_support'])
        if any(type(sid) is not str or len(sid) >= 128 for sid in support):
            raise ValueError('malformed original publisher support references')
        measured = {}
        outputs = {}
        for arm in ARMS:
            rec = completed[cid, arm]
            req = case['requests'][arm]
            refs = set(req['source_ids'])
            actual_text = rec['raw_model_text'].strip().casefold()
            strictly_equal = bool(gold_text and actual_text and actual_text == gold_text.strip().casefold())
            m = {'questions': 1, 'weak_any_at3': int(bool(support & refs)),
                 'weak_all_at3': int(bool(support) and support <= refs),
                 'strict_literal_answer_match': int(strictly_equal),
                 'ordinary_questions': int(label_kind == 'ordinary'),
                 'adversarial_questions': int(label_kind == 'adversarial'),
                 'ordinary_exact': int(strictly_equal and label_kind == 'ordinary'),
                 'adversarial_exact': int(strictly_equal and label_kind == 'adversarial'),
                 'missing_publisher_answer': int(label_kind == 'missing'),
                 'input_tokens': rec['input_tokens'], 'output_tokens': rec['output_tokens'],
                 'output_hit_max32': int(rec['output_tokens'] == MAX_NEW)}
            for group in (totals[arm], by_root[family][arm],
                          by_kind[case['divergence_kind']][arm]):
                for k, v in m.items(): group[k] += v
            measured[arm] = m
            outputs[arm] = rec['raw_model_text']
        type_diff_answer_text += int(outputs['typed_equal_budget'] !=
                                     outputs['untyped_equal_budget'])
        per_q.append({'case_id_sha256': sha_text(cid), 'family': family,
                      'divergence_kind': case['divergence_kind'],
                      'paired': measured,
                      'typed_untyped_exact_raw_answer_agree':
                          outputs['typed_equal_budget'] == outputs['untyped_equal_budget']})
    require(all(r['questions'] == CASES for r in totals.values()),
            'original Reader outcome denominator incomplete')
    changes = {}
    for arm in ARMS:
        changes[arm] = {'new_weak_hit_vs_bm25': sum(int(p['paired'][arm]['weak_any_at3'] >
                                   p['paired']['bm25']['weak_any_at3']) for p in per_q),
                        'lost_weak_hit_vs_bm25': sum(int(p['paired'][arm]['weak_any_at3'] <
                                   p['paired']['bm25']['weak_any_at3']) for p in per_q)}
    return {'schema': PROFILE + '.postseal-publisher-weak-diagnostic.v1',
            'original_reader_plan_sha256': sha_bytes(canonical(plan)),
            'original_answer_seal_sha256': file_sha(Path(folder) / 'seal.json'),
            'original_question_count': CASES, 'original_reader_calls': 42,
            'original_reader_failed_attempts_preserved': failed,
            'source_replacement_questions': EXPECTED_SOURCE_CHANGES,
            'evidence_order_only_questions': EXPECTED_ORDER_ONLY,
            'independent_original_source_family_roots': 2,
            'arm_totals': totals, 'per_family': by_root,
            'per_divergence_kind': by_kind,
            'type_different_raw_text_question_count': type_diff_answer_text,
            'paired_weak_support_flips_vs_bm25': changes,
            'matched_final_evidence_slots': True,
            'same_reader_weights_tokenizer_prompt_template': True,
            'same_max_generation_tokens': True,
            'identical_observed_input_tokens': len({v['input_tokens'] for v in totals.values()}) == 1,
            'equal_total_cost_including_encoder_and_training': False,
            'selection_cohort_representative_of_400_questions': False,
            'independent_semantic_entailment_verified': False,
            'official_hf_parity_verified': False,
            'independent_future_calendar_windows': 0,
            'learned_graph_vs_fixed_graph_whole_task_qualified': False,
            'type_specialization_whole_task_qualified': False,
            'production_accepted': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='phase', required=True)
    for phase in ('plan', 'generate', 'score'):
        a = sub.add_parser(phase)
        a.add_argument('--output', required=True)
        if phase == 'plan':
            a.add_argument('--public', required=True)
            a.add_argument('--rank', required=True)
            a.add_argument('--predictions', required=True)
            a.add_argument('--bank-directory', required=True)
            a.add_argument('--reader-directory', required=True)
        else:
            a.add_argument('--plan', required=True)
            a.add_argument('--plan-sha256', required=True)
            a.add_argument('--reader-directory', required=True)
            if phase == 'score':
                a.add_argument('--original-run', required=True)
                a.add_argument('--seal-sha256', required=True)
                a.add_argument('--publisher-weak-gold', required=True)
                a.add_argument('--raw-original-locomo', required=True)
    x = p.parse_args(argv)
    if x.phase == 'plan':
        public = read_pinned(x.public, SOURCE_SHA)
        original_rank = read_pinned(x.rank, RANK_SHA)
        predictions = read_pinned(x.predictions, PRED_SHA)
        out = build_plan(public, original_rank, predictions, original_rank_sha=RANK_SHA,
                         reader_dir=x.reader_directory, physical_head_bank=Path(x.bank_directory))
        record_sha = create_once(x.output, out)
        print(json.dumps({'original_plan_sha256': record_sha,
                          'disagreement_cases': len(out['cases']),
                          'raw_gold_accessed': False, 'production_accepted': False}))
    elif x.phase == 'generate':
        plan = read_pinned(x.plan, x.plan_sha256)
        out = run(plan, x.reader_directory, x.output)
        print(json.dumps(out, sort_keys=True))
    else:
        plan = read_pinned(x.plan, x.plan_sha256)
        seal = read_pinned(Path(x.original_run)/'seal.json', x.seal_sha256)
        # Verify all ORIGINAL journal/model/answer bytes first. The gold files
        # are not even opened when a source, response or attempt has drifted.
        verifier_tokenizer = ArchivedByteLevelBPE(Path(x.reader_directory),
                                                   expected_tokenizer_sha256=TOKENIZER_SHA)
        verify_original_seal(plan, x.original_run, seal, verifier_tokenizer)
        original_weak = read_pinned(x.publisher_weak_gold, GOLD_SHA)
        locomo = read_pinned(x.raw_original_locomo, DATASET_SHA, limit=3_000_000)
        out = score(plan, x.original_run, seal, original_weak, locomo,
                    reader_dir=x.reader_directory)
        result_sha = create_once(x.output, out)
        print(json.dumps({'score_sha256': result_sha,
                          'original_question_count': out['original_question_count'],
                          'production_accepted': False}, sort_keys=True))

if __name__ == '__main__':
    main()

"""Independently inspect original LoCoMo/MiniLM tensor and Head-bank bytes.

Local historical SHADOW audit only: manual WordPiece/BERT parity is unverified,
original Reader was not called, publisher weak labels are not human entailment.
Hash checks authenticate *bytes against supplied pins*, never issuer identity.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from amcn_core import digest, is_sha, require, shadow_disposition

ARCHIVE_SHA = '07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
LOCOMO_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
MODEL_SHA = '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
SOURCE_PLAN_SHA = 'ec478977b3f1e5b5b1e654a946df7acb405239745be6f4b4e84a82a6dc848f46'
PROFILE = 'hepta.amcn.original-minilm-offline-material-audit.shadow.v1'
SPLITS = ('select', 'future_a', 'future_b', 'retention')
TYPES = ('episodic', 'semantic')
ARMS = ('lexical_top1', 'frozen', 'single_shared', 'untyped_equal_budget',
        'typed_equal_budget', 'typed_swapped_negative')


def _check_file(path, expected, max_bytes):
    require(is_sha(expected), 'missing exact independent expected SHA256')
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= max_bytes, 'missing/linked/oversized physical input')
    digest_hasher = sha256()
    with path.open('rb') as reader:
        for block in iter(lambda: reader.read(1048576), b''):
            digest_hasher.update(block)
    require(digest_hasher.hexdigest() == expected, 'original physical bytes changed')
    return path.stat().st_size


def audit_receipts(feature_manifest, original_seal, query_score):
    """Audit original manifest/answer shape before any positive inference claim."""
    require(all(isinstance(x, dict) for x in
                (feature_manifest, original_seal, query_score)), 'original material receipts required')
    f, s = feature_manifest, original_seal
    q = query_score.get('metrics')
    require(isinstance(q, dict) and query_score.get('production_accepted') is False,
            'original read-only question score required')
    require(f.get('schema') == 'hepta.amcn.custom-minilm-real-weights-forward.nonqualifying.v1'
            and s.get('schema') == 'hepta.amcn.original-minilm-manual-forward-typed.head-train.shadow.v1'
            and q.get('profile') == 'hepta.amcn.typed-question-recall.shadow.v1',
            'unregistered native historical profile')
    require(f.get('source_original_zip_sha256') == ARCHIVE_SHA and
            f.get('source_original_locomo_sha256') == LOCOMO_SHA and
            s.get('original_locomo_sha256') == LOCOMO_SHA,
            'original source/ZIP cohort drift')
    require(f.get('original_source_first_sha256') == SOURCE_PLAN_SHA and
            s.get('original_source_first_sha256') == SOURCE_PLAN_SHA,
            'label-blind candidate plan drift')
    require(f.get('model_safetensors_sha256') == MODEL_SHA and
            s.get('model_safetensors_sha256') == MODEL_SHA,
            'incompatible pretrained Encoder revision')
    require(f.get('features_shape') == [1472, 384]
            and f.get('fp32_tensor_bytes') == 1472 * 384 * 4
            and f.get('original_model_forward_calls') == 92,
            'incomplete original pretrained feature census')
    require(f.get('tensor_file_sha256') == s.get('input_feature_safetensors_sha256'),
            'original frozen features changed before Head training')
    require(s.get('actual_pretrained_weight_forward_performed') is True
            and s.get('training_sampling') == 'balanced_binary'
            and s.get('actual_optimizer_steps_per_head') == 48
            and s.get('training_parameters_paired') == 9272
            and s.get('train_only_original_publisher_weak_support') is True,
            'physical Head training identity/budget drift')
    require(f.get('hf_tokenizer_parity_verified') is False
            and f.get('hf_bert_operator_parity_verified') is False
            and s.get('hf_tokenizer_parity_verified') is False
            and s.get('hf_bert_operator_parity_verified') is False
            and s.get('real_pretrained_source_claim_qualified') is False,
            'manual-forward cannot be silently promoted to qualified HF parity')
    require(f.get('train_labels_opened_during_encoding') is False
            and f.get('future_labels_opened_during_encoding') is False
            and s.get('independent_future_calendar_windows') is False
            and s.get('production_accepted') is False,
            'unsupported true-future / training-contamination claim')
    predictions = s.get('predictions')
    require(isinstance(predictions, list) and len(predictions) == 704
            and digest(predictions) == s.get('original_prediction_digest')
            and s.get('original_prediction_digest') == q.get('original_predictions_sha256'),
            'incomplete or substituted original trained prediction census')
    check = s.get('physical_reloaded_prediction_check')
    require(isinstance(check, dict) and
            check.get('verified_predictions') == 704
            and check.get('no_label_scores_opened') is True
            and check.get('original_predictions_sha256') == q['original_predictions_sha256'],
            'original Head readback is not bound to sealed predictions')
    require(q.get('complete_question_count') == 44
            and q.get('complete_candidate_count') == 704
            and q.get('zero_support_or_zero_hit_questions') == 15
            and q.get('future_family_pairs') == 2
            and q.get('family_wins') == {'win': 0, 'loss': 1, 'tie': 1}
            and q.get('independent_future_calendar_windows') == 0
            and q.get('pretrained_feature_origin_independently_authenticated') is False
            and q.get('physical_head_bank_independently_replayed') is False
            and q.get('original_reader_answers') is None
            and q.get('strong_hybrid_rag_comparison') is None,
            'original question scoring or negative acceptance limits drift')
    totals = q.get('source_first_weak_support')
    require(isinstance(totals, list) and len(totals) == len(SPLITS)*len(TYPES)*len(ARMS),
            'incomplete original all-split type/arm census')
    rows = {}
    for row in totals:
        require(isinstance(row, dict)
                and set(row) == {'arm', 'hit1', 'hitk', 'memory_type', 'mrr_at_k',
                                 'no_support_shortlist', 'questions', 'split'},
                'original per-type source scoring envelope mismatch')
        key = (row['split'], row['memory_type'], row['arm'])
        require(row['split'] in SPLITS and row['memory_type'] in TYPES
                and row['arm'] in ARMS and key not in rows
                and all(type(row[k]) is int for k in ('questions', 'hit1', 'hitk', 'no_support_shortlist'))
                and 1 <= row['questions'] <= 16
                and 0 <= row['hit1'] <= row['hitk'] <= row['questions']
                and 0 <= row['no_support_shortlist'] <= row['questions']
                and type(row['mrr_at_k']) in (int, float)
                and 0 <= row['mrr_at_k'] <= 1,
                'invalid original weak-support score')
        rows[key] = row
    expected = {(split, kind, arm) for split in SPLITS for kind in TYPES for arm in ARMS}
    require(set(rows) == expected, 'incomplete original 48-stratum evidence')
    aggregated = {}
    for split in SPLITS:
        expected_q = {'select': 16, 'future_a': 8, 'future_b': 8, 'retention': 12}[split]
        counts = {arm: sum(rows[(split, kind, arm)]['questions'] for kind in TYPES)
                  for arm in ARMS}
        require(set(counts.values()) == {expected_q}, 'unpaired query-level arms')
        for kind in TYPES:
            ceiling = rows[(split, kind, ARMS[0])]
            for arm in ARMS:
                r = rows[(split, kind, arm)]
                require(r['hitk'] == ceiling['hitk']
                        and r['no_support_shortlist'] == ceiling['no_support_shortlist']
                        and r['questions'] == ceiling['questions'],
                        'model must not change the source-first candidate/weak-support ceiling')
        aggregated[split] = {arm: sum(rows[(split, kind, arm)]['hit1'] for kind in TYPES)
                             for arm in ARMS}
    require(sum(x['lexical_top1'] for x in aggregated.values()) == 14,
            'historical lexical baseline changed')
    require(sum(x['typed_equal_budget'] for x in aggregated.values()) == 4,
            'original typed model selected-support changed')
    return shadow_disposition(
        profile=PROFILE, original_locomo_sha256=LOCOMO_SHA,
        original_archive_sha256=ARCHIVE_SHA, original_model_sha256=MODEL_SHA,
        original_source_first_sha256=SOURCE_PLAN_SHA,
        original_model_prediction_sha256=s['original_prediction_digest'],
        original_question_count=44, original_candidate_count=704,
        zero_publisher_support_shortlist_questions=15,
        retrospective_per_split_top1=aggregated,
        future_family_wins=q['family_wins'], historical_family_count_upper_bound=10,
        independent_future_calendar_windows=0,
        original_reader_answers=0, strong_hybrid_rag_comparison=False,
        hf_auto_tokenizer_model_parity_qualified=False,
        source_issuer_authenticated=False,
        independent_semantic_evidence_verdicts=False,
        independent_model_replay_executed_by_auditor=False,
        production_accepted=False,
    )


def audit_local_materials(archive, corpus, encoder_weights, vocab, features,
                          feature_manifest, seal, bank_directory, question_score):
    """Verify original bytes physically, then recompute the strict negative census."""
    def load(path, maximum):
        path = Path(path)
        require(path.is_file() and not path.is_symlink() and
                0 < path.stat().st_size <= maximum, 'bounded receipt file required')
        raw = path.read_bytes()
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(
            ValueError('nonfinite json')))
        return value

    f = load(feature_manifest, 1048576)
    s = load(seal, 2 * 1024 * 1024)
    q = load(question_score, 1048576)
    result = audit_receipts(f, s, q)
    _check_file(archive, ARCHIVE_SHA, 600 * 1024 * 1024)
    _check_file(corpus, LOCOMO_SHA, 8 * 1024 * 1024)
    _check_file(encoder_weights, MODEL_SHA, 150 * 1024 * 1024)
    _check_file(vocab, f['vocab_sha256'], 1048576)
    _check_file(features, f['tensor_file_sha256'], 5 * 1024 * 1024)
    bank_directory = Path(bank_directory)
    manifest_path = bank_directory / 'manifest.json'
    _check_file(manifest_path, s['head_bank_sha256'], 1048576)
    bank = load(manifest_path, 1048576)
    required = {'frozen', 'single_shared', *(f'{arm}__{kind}' for arm in
                  ('typed_equal_budget', 'untyped_equal_budget') for kind in TYPES)}
    require(bank.get('schema') == 'hepta.amcn.typed-bank.safetensors.shadow.v1'
            and bank.get('types') == list(TYPES) and bank.get('feature_width') == 384
            and bank.get('stem_sha256') == MODEL_SHA
            and bank.get('source_binding_sha256') == s['source_binding_sha256_not_signed']
            and bank.get('trained_sampling') == s['training_sampling']
            and bank.get('production_accepted') is False,
            'original immutable Head inventory identity drift')
    entries = bank.get('entries')
    require(isinstance(entries, dict) and set(entries) == required,
            'missing original physically trained Heads')
    total_weight_bytes = 0
    for head, record in entries.items():
        require(record['file'] == head + '.safetensors'
                and type(record['bytes']) is int and 0 < record['bytes'] < 65536,
                'unsafe original bank entry')
        total_weight_bytes += _check_file(bank_directory / record['file'],
                                          record['sha256'], 65536)
        require(record['parameters']['parameters'] == 4636
                and record['parameters']['parameter_bytes'] == 18544,
                'unexpected FP32 Head count')
    require(total_weight_bytes == 6 * 19040 and s['training_parameters_paired'] == 2 * 4636,
            'incorrect equal-budget original Head bank')
    return {**result, 'audited_local_head_file_bytes': total_weight_bytes,
            'physical_bytes_checked': True}

"""Research E27 original-source material owner and frozen public Transformer runner.

Original publisher train labels are released to the trainer; validation truth is
retained only for independent post-seal scoring. All outputs DENY_ALL.
"""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import time

from e27_material_contract import (
    AUTHORITY, SCHEMA, MAX_TOKENS, validate_material, canonical_sha,
)

MODEL_ID = 'answerdotai/ModernBERT-base'
MODEL_REV = '8949b909ec900327062f0ebf497f51aef5e6f0c8'
TRAIN_SHA = 'ced6d731a335a0e4fbd29f6f382f291518952c0f449448361d294000c39e6728'
VAL_SHA = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
DATA_REV = '4e14482c58d790d467ecfb29b6790e1917bf8756'
MODEL_FILES = {
    'config.json': '1609d59e627c33eaed524b4f01e546d42e84190a079a5a5ded84b212c41c324f',
    'model.safetensors': '340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9',
    'special_tokens_map.json': 'ea97ecdbcc73713039d8d64dbb05e3689495c96657fbd9a18f5bed381be81049',
    'tokenizer.json': '9fd55248d51d33976b324fc11592e28071da7d41e0e9401dfb7082e30574b7b1',
    'tokenizer_config.json': '3cd2017ff46d0a527e5d39cae39272eccfa1f19bb9f89b05d166aab2e38354e2',
}
TRAIN_PASSAGES = 48
VAL_PASSAGES = 8


def strict_read(path, max_bytes=12_000_000):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= max_bytes:
        raise ValueError('missing or oversized original data')
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError('duplicate data key')
            out[k] = v
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_once(path, value):
    b = (json.dumps(value, sort_keys=True, separators=(',', ':'),
                    ensure_ascii=False, allow_nan=False) + '\n').encode()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('xb') as f:
        f.write(b); f.flush()
        import os
        os.fsync(f.fileno())
    return sha256(b).hexdigest()


def _text_hash(text):
    return sha256(text.encode()).hexdigest()


def select_groups(rows, *, split, limit):
    """Complete paragraph/question/candidate selection BEFORE inspecting labels.

    Selection is a lexical/source-identity operation, never a model/utility/
    held-truth-dependent filter. No source questions are mixed across groups.
    """
    if split not in ('train', 'validation') or type(rows) is not list:
        raise ValueError('invalid original MultiRC split')
    grouped = {}
    excluded = set()
    seen_native_ids = set()
    for row in rows:
        if type(row) is not dict or set(row) != {'paragraph', 'question', 'answer', 'label', 'idx'}:
            raise ValueError('wrong original MultiRC Parquet schema')
        idx = row['idx']
        if (type(idx) is not dict or set(idx) != {'paragraph', 'question', 'answer'} or
            any(type(i) is not int or not 0 <= i <= 100_000_000 for i in idx.values())):
            raise ValueError('bad original paragraph/question/answer ID')
        pid, qid, aid = idx['paragraph'], idx['question'], idx['answer']
        if type(row['label']) is not int or row['label'] not in (0, 1):
            raise ValueError('malformed original 0/1 publisher label')
        key=(pid,qid,aid)
        if key in seen_native_ids:
            raise ValueError('duplicate original native answer ID')
        seen_native_ids.add(key)
        evidence = row['paragraph']
        texts=(evidence,row['question'],row['answer'])
        if any(x is not None and type(x) is not str for x in texts):
            raise ValueError('unsupported source text type')
        if any(isinstance(x,str) and len(x.encode())>1_048_576 for x in texts):
            raise ValueError('unbounded original input')
        if (any(x is None or not x.strip() for x in texts) or
            not 0 < len(evidence.encode()) <= 32000 or
            not 0 < len(row['question'].encode()) <= 4096 or
            not 0 < len(row['answer'].encode()) <= 4096):
            excluded.add(pid)
            continue
        if pid in excluded:
            continue
        group = grouped.setdefault(pid, {'evidence': evidence, 'questions': {}})
        if group['evidence'] != evidence:
            raise ValueError('source paragraph identity collision')
        q = group['questions'].setdefault(qid, {'text': row['question'], 'answers': {}})
        if q['text'] != row['question'] or aid in q['answers']:
            raise ValueError('duplicate or conflicting genuine candidate')
        q['answers'][aid] = (row['answer'], row['label'])
    records = []
    for pid, info in grouped.items():
        if pid in excluded:
            continue
        groups = []
        root = sha256(f'{split}:{pid}:{_text_hash(info["evidence"])}'.encode()).hexdigest()
        for qid, q in sorted(info['questions'].items()):
            # Predeclared native-slate sizes. Never select using true labels.
            if not 2 <= len(q['answers']) <= 8:
                continue
            questions = []
            for aid, (answer, label) in sorted(q['answers'].items()):
                candidate_id = sha256(f'{root}:{qid}:{aid}:{_text_hash(answer)}'.encode()).hexdigest()
                questions.append({'candidate_id': candidate_id, 'text': answer, 'label': label})
            groups.append({'question_id': sha256(f'{root}:{qid}:{_text_hash(q["text"])}'.encode()).hexdigest(),
                           'text': q['text'], 'candidates': questions})
        if not 1 <= len(groups) <= 16:
            continue
        records.append({'group_id': root, 'evidence': info['evidence'], 'questions': groups})
    records.sort(key=lambda g: g['group_id'])
    if len(records) < limit:
        raise ValueError('insufficient complete original publisher paragraphs')
    return records[:limit], len(records)


def material_owner(train_rows, validation_rows):
    train, train_eligible = select_groups(train_rows, split='train', limit=TRAIN_PASSAGES)
    held, val_eligible = select_groups(validation_rows, split='validation', limit=VAL_PASSAGES)
    for t in train:
        if any(_text_hash(t['evidence']) == _text_hash(v['evidence']) for v in held):
            raise ValueError('original train/validation source alias')
    common = {'schema': SCHEMA + '.material', 'source_revision': DATA_REV,
              'selection_uses_labels': False, 'production_accepted': False,
              'authority': AUTHORITY}
    train_material = {**common, 'role': 'train', 'source_sha256': TRAIN_SHA, 'groups': train}
    held_material = {**common, 'role': 'held', 'source_sha256': VAL_SHA,
                     'groups': [{**g, 'questions': [{**q, 'candidates': [
                         {'candidate_id': c['candidate_id'], 'text': c['text']} for c in q['candidates']
                     ]} for q in g['questions']]} for g in held]}
    validate_material(train_material, mode='train')
    validate_material(held_material, mode='held')
    gold = {'schema': SCHEMA + '.original-held-gold', 'authority': AUTHORITY,
            'source_revision': DATA_REV, 'source_sha256': VAL_SHA,
            'held_material_sha256': canonical_sha(held_material),
            'cases': [{ 'source_group': g['group_id'], 'question_id': q['question_id'],
                        'candidate_id': c['candidate_id'], 'label': c['label']}
                      for g in held for q in g['questions'] for c in q['candidates']],
            'production_accepted': False}
    descriptor = {'schema': SCHEMA + '.selection', 'authority': AUTHORITY,
                  'train_available_passages': train_eligible, 'held_available_passages': val_eligible,
                  'train_selected_passages': len(train), 'held_selected_passages': len(held),
                  'source_disjoint_by_paragraph_bytes': True,
                  'prospective_future_family_or_time': False,
                  'selection_before_label_scoring': True, 'model_promoted': False}
    return train_material, held_material, gold, descriptor


class OriginalModernBERT:
    """Actual pinned public model, explicitly shared and physically counted."""
    def __init__(self, snapshot):
        root = Path(snapshot)
        for path, digest in MODEL_FILES.items():
            p = root / path
            if not p.is_file() or p.is_symlink() or sha256(p.read_bytes()).hexdigest() != digest:
                raise ValueError('wrong original public pretrained checkpoint bytes')
        from transformers import AutoTokenizer, AutoModel
        self.tok = AutoTokenizer.from_pretrained(root, local_files_only=True,
                                                  trust_remote_code=False)
        self.model = AutoModel.from_pretrained(root, local_files_only=True,
                                                trust_remote_code=False).eval()
        self.model.requires_grad_(False)
        self.forward_calls = 0
        self.total_tokens = 0
        self.cpu_ns = 0
        self.wall_ns = 0
        self.shared_model_id = MODEL_REV
        self.truncated_sequences = 0
        self.d_model = self.model.config.hidden_size
        if not 4 <= self.d_model <= 2048:
            raise ValueError('unsupported public model shape')

    def __call__(self, text, *, token_sequence):
        import torch
        raw_tokens = self.tok(text, return_tensors='pt', padding=False, truncation=False)
        raw_length = raw_tokens['input_ids'].numel()
        tokens = self.tok(text, return_tensors='pt', padding=False, truncation=True,
                          max_length=MAX_TOKENS)
        self.truncated_sequences += int(raw_length > MAX_TOKENS)
        duration_cpu, duration_wall = time.process_time_ns(), time.perf_counter_ns()
        with torch.inference_mode():
            embedding = self.model(**tokens).last_hidden_state[0].float()
        self.cpu_ns += time.process_time_ns() - duration_cpu
        self.wall_ns += time.perf_counter_ns() - duration_wall
        self.forward_calls += 1
        self.total_tokens += tokens['input_ids'].numel()
        return embedding.detach() if token_sequence else embedding.mean(dim=0).detach()


def execute(train_material, held_material, *, embedder):
    # Material-owner imports must stay Torch-free. Only the registered blind
    # computation path loads physical trainable Cell operations.
    from e27_token_interaction import make_feature_bank, train_head, blind_predict
    train_ids, train_questions, train_cases = validate_material(train_material, mode='train')
    held_ids, held_questions, held_cases = validate_material(held_material, mode='held')
    if train_ids & held_ids or train_material['source_revision'] != held_material['source_revision']:
        raise ValueError('train/held source overlap or version drift')
    start = time.process_time_ns()
    before = getattr(embedder, 'forward_calls', 0)
    train_bank, train_calls = make_feature_bank(train_material, embedder=embedder)
    held_bank, held_calls = make_feature_bank(held_material, embedder=embedder)
    features_cpu = time.process_time_ns() - start
    aware, aw_meter = train_head(train_bank, answer_visible=True)
    muted, mu_meter = train_head(train_bank, answer_visible=False)
    if aw_meter['parameter_count'] != mu_meter['parameter_count'] or aw_meter['optimizer_steps'] != mu_meter['optimizer_steps']:
        raise ValueError('unmatched Head budgets')
    before_infer = time.process_time_ns()
    predictions = blind_predict(held_bank, aware, muted)
    inference_cpu = time.process_time_ns() - before_infer
    recorded_model_calls = getattr(embedder, 'forward_calls', before + train_calls + held_calls) - before
    if recorded_model_calls != train_calls + held_calls:
        raise ValueError('physical shared Encoder event count mismatch')
    return {
        'schema': SCHEMA + '.blind', 'authority': AUTHORITY,
        'train_material_sha256': canonical_sha(train_material),
        'held_material_sha256': canonical_sha(held_material),
        'model_revision': MODEL_REV,
        'encoder_checkpoint_digest_profile': MODEL_FILES['model.safetensors'],
        'shared_encoder_calls': recorded_model_calls,
        'train_shared_encoder_calls': train_calls,
        'held_shared_encoder_calls': held_calls,
        'train_question_count': train_questions, 'held_question_count': held_questions,
        'train_candidate_count': train_cases, 'held_candidate_count': held_cases,
        'head_budgets': {'aware': aw_meter, 'answer_muted': mu_meter},
        'physical_meter': {'feature_generation_cpu_ns': features_cpu,
                           'head_inference_cpu_ns': inference_cpu,
                           'model_encoder_cpu_ns': getattr(embedder, 'cpu_ns', None),
                           'model_encoder_wall_ns': getattr(embedder, 'wall_ns', None),
                           'model_tokens': getattr(embedder, 'total_tokens', None),
                           'truncated_sequences': getattr(embedder, 'truncated_sequences', None)},
        'predictions': predictions,
        'real_pretrained_encoder': isinstance(embedder, OriginalModernBERT),
        'held_labels_loaded_during_fit_or_blind': False,
        'task_gain_established': False, 'ndu_fbsde_activation': False,
        'production_accepted': False,
    }


def main():
    p = argparse.ArgumentParser()
    modes = p.add_subparsers(dest='mode', required=True)
    a = modes.add_parser('material')
    for key in ('train-parquet', 'val-parquet', 'train-out', 'held-out', 'gold-out', 'selection-out'):
        a.add_argument('--' + key, required=True)
    b = modes.add_parser('blind')
    for key in ('train', 'held', 'snapshot', 'output'):
        b.add_argument('--' + key, required=True)
    args = p.parse_args()
    if args.mode == 'material':
        from multirc_materials import load_parquet
        train_rows = load_parquet(args.train_parquet, expected_sha256=TRAIN_SHA)
        val_rows = load_parquet(args.val_parquet, expected_sha256=VAL_SHA)
        train, held, gold, descriptor = material_owner(train_rows, val_rows)
        for destination, value in zip((args.train_out, args.held_out, args.gold_out, args.selection_out),
                                      (train, held, gold, descriptor)):
            write_once(destination, value)
        print(json.dumps({'authority': AUTHORITY, 'train_passages': TRAIN_PASSAGES,
                          'held_passages': VAL_PASSAGES}))
    else:
        torch_local = __import__('torch')
        torch_local.set_num_threads(2)
        train = strict_read(args.train)
        held = strict_read(args.held)
        encoder = OriginalModernBERT(args.snapshot)
        out = execute(train, held, embedder=encoder)
        if not out['real_pretrained_encoder']:
            raise ValueError('original checkpoint was not physically executed')
        print(json.dumps({'authority': AUTHORITY, 'sha256': write_once(args.output, out),
                          'pretrained_forwards': out['shared_encoder_calls']}))

if __name__ == '__main__':
    main()

"""Run authentic archived MiniLM/HF weights on label-blind original LoCoMo cues.

Strict research smoke, not a strong-RAG/Reader result or a reproduction of the
separate manual WordPiece/BERT diagnostic. No remote code, model download,
training labels or production path. Missing HF packages fail, never synthesize.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

MODEL_SHA = '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
VOCAB_SHA = '07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3'
TOKENIZER_SHA = 'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037'
CONFIG_SHA = '953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41'
LOCOMO_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
SCHEMA = 'hepta.amcn.native-hf-minilm-original-source-smoke.shadow.v1'


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(raw):
    return sha256(raw).hexdigest()


def _checked(path, expected, maximum):
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or
            not 0 < path.stat().st_size <= maximum):
        raise ValueError('missing/linked/oversized original byte input')
    data = path.read_bytes()
    if _sha(data) != expected:
        raise ValueError('original source/model/tokenizer SHA mismatch')
    return data


def freeze_cues(samples):
    """Use only question text and real source turn, never QA answer/evidence."""
    if not isinstance(samples, list) or len(samples) != 10:
        raise ValueError('ten original independent LoCoMo conversations required')
    ids, result = set(), []
    for sample in sorted(samples, key=lambda x: x['sample_id']):
        sid = sample['sample_id']
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError('ambiguous sample identity')
        ids.add(sid)
        questions = [(qa['question'], i) for i, qa in enumerate(sample['qa'])
                     if isinstance(qa.get('question'), str) and qa['question'].strip()]
        if not questions:
            raise ValueError('sample has no original question')
        question, _ = sorted(questions, key=lambda v: (_sha(v[0].encode()), v[1]))[0]
        first = sample['conversation'].get('session_1')
        if not isinstance(first, list) or not first:
            raise ValueError('no original first-session source')
        turn = first[0]
        if not isinstance(turn.get('speaker'), str) or not isinstance(turn.get('text'), str):
            raise ValueError('malformed original source turn')
        source = turn['speaker'] + ': ' + turn['text']
        if not 1 <= len(source.encode()) <= 1200:
            raise ValueError('source exceeds bounded first-session cue')
        payload = {'question': question, 'source': source}
        text = _bytes(payload).decode()
        result.append({'case_sha256': _sha(_bytes([sid, question, source])),
                       'source_sha256': _sha(source.encode()), 'input_sha256': _sha(text.encode()),
                       'source_family_sha256': _sha(sid.encode()), 'text': text})
    if len(result) != 10 or len({r['case_sha256'] for r in result}) != 10:
        raise ValueError('incomplete source-family census')
    return result


def run_original_hf(archive_encoder_dir, original_locomo, output_dir):
    """Physically load pinned HF AutoTokenizer/AutoModel-compatible BERT weights."""
    # All sources and snapshots must be pre-staged from pinned archive externally.
    root = Path(archive_encoder_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('original immutable model directory required')
    from safetensors.torch import load_file, save_file
    import torch
    from transformers import BertConfig, BertModel, BertTokenizer, BertTokenizerFast
    for name, expected, ceiling in (
            ('model.safetensors', MODEL_SHA, 120_000_000),
            ('vocab.txt', VOCAB_SHA, 1_000_000),
            ('tokenizer.json', TOKENIZER_SHA, 1_000_000),
            ('config.json', CONFIG_SHA, 1_000_000)):
        _checked(root / name, expected, ceiling)
    samples = json.loads(_checked(original_locomo, LOCOMO_SHA, 8_000_000))
    inputs = freeze_cues(samples)
    config = BertConfig.from_json_file(str(root / 'config.json'))
    if (config.hidden_size != 384 or config.num_hidden_layers != 6 or
            config.num_attention_heads != 12 or config.vocab_size != 30522):
        raise ValueError('original BERT model geometry changed')
    model = BertModel(config).eval()
    saved = load_file(str(root / 'model.safetensors'), device='cpu')
    legacy = saved.pop('embeddings.position_ids', None)
    expected = torch.arange(config.max_position_embeddings, dtype=torch.long)[None]
    if legacy is None or not torch.equal(legacy.cpu(), expected):
        raise ValueError('unreviewed old positional buffer removed or altered')
    check = model.load_state_dict(saved, strict=False)
    if check.missing_keys or check.unexpected_keys:
        raise ValueError('unexpected original BERT parameter geometry')
    fast = BertTokenizerFast.from_pretrained(str(root), local_files_only=True)
    slow = BertTokenizer.from_pretrained(str(root), local_files_only=True)
    texts = [r['text'] for r in inputs]
    enc = fast(texts, padding=True, truncation=False, return_tensors='pt')
    ref = slow(texts, padding=True, truncation=False, return_tensors='pt')
    if not torch.equal(enc['input_ids'], ref['input_ids']) or not torch.equal(
            enc['attention_mask'], ref['attention_mask']):
        raise ValueError('HF fast vs slow original WordPiece parity failed')
    if enc['input_ids'].shape[1] > 512:
        raise ValueError('original pretrained positional budget exceeded without truncation')
    with torch.inference_mode():
        state = model(input_ids=enc['input_ids'], attention_mask=enc['attention_mask'])
        mask = enc['attention_mask'].unsqueeze(-1)
        features = (state.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1)
        features = torch.nn.functional.normalize(features.float(), p=2, dim=-1).contiguous()
    if features.shape != (10, 384) or not bool(torch.isfinite(features).all()):
        raise ValueError('no actual finite HF pretrained feature rows')
    output = Path(output_dir)
    if output.exists() or output.is_symlink():
        raise ValueError('original audit output is create-only')
    output.mkdir(mode=0o700, parents=False)
    tensor_path = output / 'features.safetensors'
    save_file({'features': features}, str(tensor_path))
    with tensor_path.open('rb') as fd:
        os.fsync(fd.fileno())
    payload = {
        'schema': SCHEMA,
        'source_locomo_sha256': LOCOMO_SHA, 'encoder_weights_sha256': MODEL_SHA,
        'tokenizer_json_sha256': TOKENIZER_SHA, 'vocab_sha256': VOCAB_SHA,
        'frozen_case_identities': [{k: r[k] for k in r if k != 'text'} for r in inputs],
        'original_source_family_count': 10,
        'physical_pretrained_encoder_forward_count': 1,
        'feature_count': 10, 'feature_width': 384,
        'pooled_vector_strategy': 'last_hidden_mean_masked_l2_normalized',
        'hf_fast_slow_tokenization_parity_verified': True,
        'parity_with_historical_manual_forward_verified': False,
        'original_reader_answers': 0, 'training_or_heldout_gold_used': False,
        'future_calendar_windows': 0, 'production_accepted': False,
        'features_file_sha256': _sha(tensor_path.read_bytes()),
    }
    raw = _bytes(payload) + b'\n'
    with (output / 'receipt.json').open('xb') as fd:
        fd.write(raw); fd.flush(); os.fsync(fd.fileno())
    return payload


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('original_encoder_dir')
    parser.add_argument('original_locomo_json')
    parser.add_argument('create_only_output_dir')
    args=parser.parse_args()
    print(json.dumps(run_original_hf(args.original_encoder_dir,
                                     args.original_locomo_json,
                                     args.create_only_output_dir), sort_keys=True))

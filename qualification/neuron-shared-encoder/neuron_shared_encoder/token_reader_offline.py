"""Pinned local pretrained token capture and paired Cell Head shadow study.

No downloads, remote code, pickle feature files, cached authorization or
production final-use. A local SHA-256 match is not an independent attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from collections.abc import Mapping
import time
from typing import Any

import torch
from torch import Tensor

from .token_reader_v1 import _audit, _hex_digest, paired_token_reader_trial, snapshot_sha256

KINDS = ('mmbert-joint', 'granite-joint', 'modernbert-joint')
INPUT_ENCODING = b'hepta.token-reader.ordered-json-question-options-state.v1'
NORMALIZATION = b'hepta.token-reader.train-only-valid-token-zscore-clamp8.v1'
MAX_INPUT_BYTES = 32_768


def _digest_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _joint_text(row: dict[str, Any]) -> tuple[str, str]:
    """Bind all decision inputs with unambiguous ordered JSON, not pipe joins."""
    if type(row.get('question')) is not str or not row['question']:
        raise ValueError('nonempty question required')
    if not isinstance(row.get('options'), list) or not 2 <= len(row['options']) <= 16:
        raise ValueError('ordered options required')
    try:
        payload = json.dumps({'question': row['question'], 'options': row['options'],
                              'state': row['state']}, ensure_ascii=False,
                             sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError('invalid canonical question/options/state') from exc
    if not 0 < len(payload) <= MAX_INPUT_BYTES:
        raise ValueError('bounded canonical input required')
    return payload.decode('utf-8'), _digest_bytes(INPUT_ENCODING + b'\0' + payload)


def _prepare_rows(raw_rows: list[dict], purpose: str, pins: dict) -> tuple[list[str], list[dict], Tensor]:
    if not isinstance(purpose, str) or not 0 < len(purpose) <= 128:
        raise ValueError('bounded declared study purpose required')
    texts: list[str] = []
    rows: list[dict] = []
    labels: list[int] = []
    allowed = ('row_id', 'principal', 'organ_id', 'cell_id', 'source_group',
               'event_time', 'split', 'label', 'options')
    for row in raw_rows:
        if not isinstance(row, dict) or ('purpose' in row and row['purpose'] != purpose):
            raise ValueError('dataset scope/purpose conflict')
        text, digest = _joint_text(row)
        texts.append(text)
        fields = {name: row.get(name) for name in allowed}
        rows.append({**fields, 'purpose': purpose, 'input_sha256': digest})
        labels.append(row.get('label'))
    # Validate BEFORE any expensive Encoder model load or forward. The dummy
    # tensor is strictly schema preflight, not a source/feature evidence claim.
    if len(rows) < 8 or any(type(value) is not int for value in labels):
        raise ValueError('bounded integer labels required')
    y = torch.tensor(labels, dtype=torch.long)
    probe = torch.zeros((len(rows), 1, 1), dtype=torch.float32)
    probe_mask = torch.ones((len(rows), 1), dtype=torch.bool)
    _audit(probe, probe_mask, y, rows, pins, snapshot_sha256(probe, probe_mask, rows, pins))
    return texts, rows, y


def _tokenize_and_capture(backend: Any, texts: list[str], *, max_length: int,
                          batch: int) -> tuple[Tensor, Tensor, dict]:
    from .encoder_meter import EncoderModuleForwardMeter

    if not 8 <= max_length <= 256 or not 1 <= batch <= 32:
        raise ValueError('bounded token length and Encoder batch required')
    dimension = backend.dimension
    if (type(dimension) is not int or not 1 <= dimension <= 768 or not texts
            or len(texts) * max_length * dimension > 8_388_608):
        raise ValueError('real token snapshot exceeds dimension/byte bound')
    features = torch.empty((len(texts), max_length, dimension), dtype=torch.float32)
    masks = torch.empty((len(texts), max_length), dtype=torch.bool)
    tokenize_ns = 0
    model_ns = 0
    with EncoderModuleForwardMeter(backend.model) as meter:
        with torch.inference_mode():
            for start in range(0, len(texts), batch):
                end = min(start + batch, len(texts))
                t0 = time.perf_counter_ns()
                encoded = backend.tok(texts[start:end], padding='max_length',
                                      truncation=False, max_length=max_length,
                                      return_tensors='pt')
                tokenize_ns += time.perf_counter_ns() - t0
                if (not isinstance(encoded, Mapping)
                        or not {'input_ids', 'attention_mask'} <= set(encoded)
                        or not set(encoded) <= {'input_ids', 'attention_mask', 'token_type_ids'}):
                    raise ValueError('unsupported tokenizer output / required attention mask missing')
                ids, attn = encoded['input_ids'], encoded['attention_mask']
                if (not isinstance(ids, Tensor) or ids.dtype != torch.long
                        or not isinstance(attn, Tensor) or attn.dtype not in (torch.long, torch.int64)
                        or tuple(ids.shape) != (end - start, max_length)
                        or tuple(attn.shape) != tuple(ids.shape)
                        or not bool(((attn == 0) | (attn == 1)).all())
                        or not bool(attn.any(dim=1).all())):
                    # A tokenizer producing >max_length is rejected: NEVER
                    # silently truncate the condition/options/state.
                    raise ValueError('tokenizer exceeded max_length or malformed padding mask')
                if any(not isinstance(value, Tensor) or value.device.type != 'cpu'
                       or tuple(value.shape) != tuple(ids.shape)
                       for value in encoded.values()):
                    raise ValueError('tokenizer must return aligned CPU tensors')
                t0 = time.perf_counter_ns()
                actual = backend.model(**encoded).last_hidden_state
                model_ns += time.perf_counter_ns() - t0
                if (not isinstance(actual, Tensor) or actual.ndim != 3
                        or tuple(actual.shape) != (end - start, max_length, dimension)
                        or not torch.isfinite(actual).all()):
                    raise ValueError('real model returned malformed/nonfinite token output')
                features[start:end].copy_(actual.detach().to('cpu', dtype=torch.float32))
                masks[start:end].copy_(attn.bool())
    if (meter.attempts != meter.completions or meter.completed_rows != len(texts)
            or meter.attempted_rows != len(texts)):
        raise ValueError('incomplete observed physical model calls')
    meter_report = meter.receipt()
    return features.contiguous(), masks.contiguous(), {
        'model_forward_observation': meter_report,
        'observed_tokenizer_wall_seconds': tokenize_ns / 1e9,
        'observed_model_forward_wall_seconds': model_ns / 1e9,
        'total_encoder_batches': meter.completions,
        'observed_masked_tokens': int(masks.sum()),
        'padded_token_slots': masks.numel(),
    }


def run_pinned_offline(*, dataset: str, dataset_sha256: str,
                       checkpoint_dir: str, kind: str,
                       weights_sha256: str, bundle_sha256: str,
                       tokenizer_sha256: str, purpose: str,
                       generation: int, authority_epoch: int,
                       max_length: int = 64, encoder_batch: int = 8,
                       rank: int = 8, head_budget: int = 16384,
                       steps: int = 20, head_batch: int = 16,
                       seeds: tuple[int, ...] = (11, 23, 47)) -> dict:
    """Physically invoke an offline local model; return only nonauthorizing metrics.

    No model/data discovery or download is performed; all assets must already
    be present and pinned. Local hashes cannot substitute independent evidence.
    """
    from .contracts import load_dataset, sha256_file
    from .models import OfflineEncoder

    if kind not in KINDS:
        raise ValueError('only qualified non-Laya bidirectional token controls supported')
    if any(not _hex_digest(x) for x in (dataset_sha256, weights_sha256,
                                       bundle_sha256, tokenizer_sha256)):
        raise ValueError('exact pinned model, dataset and tokenizer SHA256 required')
    if (type(generation) is not int or generation <= 0 or type(authority_epoch) is not int
            or authority_epoch <= 0):
        raise ValueError('positive experiment generation/epoch required')
    if not 8 <= max_length <= 256 or not 1 <= encoder_batch <= 32:
        raise ValueError('bounded token length and Encoder batch required')
    directory = Path(checkpoint_dir)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError('physical checkpoint directory required')
    tokenizer_file = directory / 'tokenizer.json'
    if tokenizer_file.is_symlink() or not tokenizer_file.is_file():
        raise ValueError('regular local tokenizer required')
    if sha256_file(tokenizer_file) != tokenizer_sha256:
        raise ValueError('tokenizer file hash mismatch')
    raw_rows, _ = load_dataset(dataset, expected_sha256=dataset_sha256)
    pins = {'encoder_sha256': bundle_sha256, 'tokenizer_sha256': tokenizer_sha256,
            'preprocessor_sha256': _digest_bytes(INPUT_ENCODING),
            'normalizer_sha256': _digest_bytes(NORMALIZATION),
            'dataset_sha256': dataset_sha256,
            'generation': generation, 'authority_epoch': authority_epoch}
    texts, rows, labels = _prepare_rows(raw_rows, purpose, pins)
    backend = OfflineEncoder(kind, str(directory), weights_sha256,
                             device='cpu', max_length=max_length,
                             expected_bundle_sha256=bundle_sha256)
    start = time.perf_counter_ns()
    tokens, mask, capture = _tokenize_and_capture(backend, texts, max_length=max_length,
                                                  batch=encoder_batch)
    backend._check_bundle_unchanged()
    frozen = snapshot_sha256(tokens, mask, rows, pins)
    head_start = time.perf_counter_ns()
    comparison = paired_token_reader_trial(tokens, mask, labels, rows, pins, frozen,
                                           rank=rank, budget=head_budget,
                                           seeds=seeds, steps=steps, batch=head_batch)
    head_seconds = (time.perf_counter_ns() - head_start) / 1e9
    backend._check_bundle_unchanged()
    if sha256_file(dataset) != dataset_sha256 or sha256_file(tokenizer_file) != tokenizer_sha256:
        raise ValueError('source/tokenizer mutated during model/Head execution')
    if snapshot_sha256(tokens, mask, rows, pins) != frozen:
        raise ValueError('frozen real token snapshot drift')
    # This excludes process startup and checkpoint loading: each segment is
    # labeled separately rather than presented as end-to-end service latency.
    return {
        **comparison, 'experiment': 'E2_REAL_PINNED_TOKEN_READER_SHADOW',
        'evidence_class': 'SELF_ATTESTED_REAL_PRETRAINED_OFFLINE_ONLY',
        'kind': kind, 'original_weights_sha256': weights_sha256,
        'bundle_sha256': bundle_sha256, 'tokenizer_sha256': tokenizer_sha256,
        'dataset_sha256': dataset_sha256,
        'observed_capture_and_head_wall_seconds': (time.perf_counter_ns() - start) / 1e9,
        'observed_head_fit_and_evaluation_wall_seconds': head_seconds,
        'observed_encoding': capture,
        'pooled_feature_cache_minimum_bytes': len(rows) * tokens.shape[2] * 4,
        'whole_token_snapshot_bytes': comparison['snapshot_tensor_bytes_once'],
        'real_model_loaded_and_called_locally': True,
        'real_model_independently_attested': False,
        'source_and_final_use_independently_authorized': False,
        'independent_frozen_nochange_verified': False,
        'trusted_future_causal_NDU_verified': False,
        'production_admission': 'BLOCKED', 'selection_authorized': False,
        'warning': ('Model forward rows are observed at the module boundary, not GPU kernel or'
                    ' physical cross-request deduplication. This is not a production run.'),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for required in ('dataset', 'dataset-sha256', 'checkpoint-dir', 'weights-sha256',
                     'bundle-sha256', 'tokenizer-sha256', 'purpose', 'output'):
        parser.add_argument('--' + required, required=True)
    parser.add_argument('--kind', choices=KINDS, required=True)
    parser.add_argument('--generation', type=int, required=True)
    parser.add_argument('--authority-epoch', type=int, required=True)
    parser.add_argument('--max-length', type=int, default=64)
    parser.add_argument('--encoder-batch', type=int, default=8)
    parser.add_argument('--rank', type=int, default=8)
    parser.add_argument('--head-budget', type=int, default=16384)
    parser.add_argument('--steps', type=int, default=20)
    parser.add_argument('--head-batch', type=int, default=16)
    parser.add_argument('--seeds', type=int, nargs='+', default=[11, 23, 47])
    args = parser.parse_args(argv)
    if Path(args.output).exists():
        parser.error('refuse overwriting an evidence record')
    report = run_pinned_offline(**{key: value for key, value in vars(args).items()
                                  if key != 'output' and key != 'seeds'},
                                seeds=tuple(args.seeds))
    # Output contains only hashed identities, shapes and numeric results;
    # it must still remain in an operator-approved private evidence directory.
    destination = Path(args.output)
    blob = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    import os
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd = os.open(destination, flags, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(blob)
        output.flush()
        os.fsync(output.fileno())


if __name__ == '__main__':
    main()

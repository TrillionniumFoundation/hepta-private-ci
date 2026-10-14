"""Pretrained tokenizer-only length preflight BEFORE large model acquisition.

Research-only. The original public source and publisher tokenizer are immutable
and hash pinned. Checks use the same no-truncation, ordered full joint inputs as
the real Producer and Reviewer; no model weights, forward or authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from collections.abc import Mapping
import shutil
from typing import Any, Callable

from .physical_pooled_replay_v1 import MODEL, read_public_physical_features
from .physical_token_pair_v1 import _public_rows
from .stage_modernbert_public_v1 import source_model_files
from .token_reader_v1 import MAX_ELEMENTS
from .trained_head_artifacts_v1 import _canonical

SCHEMA = 'hepta.neuron.tokenizer-only-length-preflight.shadow.v1'
TOKENIZER_FILES = frozenset({'config.json', 'special_tokens_map.json',
                             'tokenizer.json', 'tokenizer_config.json'})
MAX_PARTIAL_BYTES = 16 * 1024 * 1024
MAX_TOKENS = 256
WIDTH = 768


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as reader:
        for chunk in iter(lambda: reader.read(1 << 20), b''):
            result.update(chunk)
    return result.hexdigest()


def audit_full_joint_token_lengths(tokenizer: Callable[..., Any], by_cell: dict[int, list[dict]],
                                   *, max_length: int, batch: int,
                                   model_id: str, revision: str,
                                   source_sha256: str, tokenizer_sha256: str) -> dict:
    """Read all original strings, without truncation, without a model forward.

    Returned IDs are used only for an internal canonical digest and are never
    persisted as raw token IDs. Refuse any untrusted tokenizer geometry or
    partial computation; a report cannot turn the pass into model evidence.
    """
    if (type(max_length) is not int or not 8 <= max_length <= MAX_TOKENS
            or type(batch) is not int or not 1 <= batch <= 32
            or 64 * max_length * WIDTH > MAX_ELEMENTS):
        raise ValueError('bounded full-token model profile required')
    if (not isinstance(by_cell, dict) or set(by_cell) != {0, 1}
            or any(not isinstance(by_cell[i], list) or len(by_cell[i]) != 64 for i in (0, 1))):
        raise ValueError('original two-Cell public source required')
    if model_id != MODEL['modernbert'][1] or revision != MODEL['modernbert'][2]:
        raise ValueError('pinned original ModernBERT revision required')
    if any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
           for v in (source_sha256, tokenizer_sha256)):
        raise ValueError('exact original source/tokenizer SHA256 required')
    digest = hashlib.sha256(b'hepta.neuron.tokenizer-only-ordered-inputs.v1\0')
    counters = []
    for cell in (0, 1):
        rows = by_cell[cell]
        lengths = []
        seen = set()
        batches = 0
        for start in range(0, len(rows), batch):
            selected = rows[start:start + batch]
            texts = []
            for row in selected:
                if (not isinstance(row, dict) or type(row.get('cell')) is not int
                        or row['cell'] != cell or row.get('case_id') in seen
                        or not isinstance(row.get('case_id'), str)
                        or not isinstance(row.get('joint_text'), str)
                        or not isinstance(row.get('input_sha256'), str)
                        or len(row['input_sha256']) != 64):
                    raise ValueError('complete isolated source/input lineage required')
                seen.add(row['case_id'])
                texts.append(row['joint_text'])
            encoded = tokenizer(texts, truncation=False, padding=False,
                                return_attention_mask=True, add_special_tokens=True)
            if (not isinstance(encoded, Mapping) or 'input_ids' not in encoded
                    or 'attention_mask' not in encoded):
                raise ValueError('tokenizer returned incomplete untruncated inputs')
            ids = encoded['input_ids']
            masks = encoded['attention_mask']
            if (not isinstance(ids, list) or not isinstance(masks, list)
                    or len(ids) != len(selected) or len(masks) != len(selected)):
                raise ValueError('tokenizer batch has incompatible row count')
            for offset, row in enumerate(selected):
                words, active = ids[offset], masks[offset]
                if (not isinstance(words, list) or not isinstance(active, list)
                        or not 1 <= len(words) <= max_length or len(active) != len(words)
                        or any(type(x) is not int or not 0 <= x < 2**31 for x in words)
                        or any(type(x) is not int or x != 1 for x in active)):
                    raise ValueError('full joint tokenizer exceeded model budget or malformed mask')
                lengths.append(len(words))
                payload = json.dumps([cell, start + offset, row['input_sha256'], words],
                                     separators=(',', ':'), ensure_ascii=False).encode()
                digest.update(len(payload).to_bytes(8, 'big'))
                digest.update(payload)
            batches += 1
        if len(lengths) != 64 or len(seen) != 64:
            raise ValueError('incomplete original Cell tokenizer census')
        counters.append({'cell': cell, 'input_rows': 64, 'tokenizer_batches': batches,
                         'minimum_untruncated_tokens': min(lengths),
                         'maximum_untruncated_tokens': max(lengths),
                         'total_active_token_slots': sum(lengths),
                         'padded_token_slots_after_model_collate': 64 * max_length})
    return {'schema': SCHEMA, 'model_id': model_id, 'model_revision': revision,
            'source_zip_sha256': source_sha256,
            'tokenizer_json_sha256': tokenizer_sha256,
            'input_encoding': 'ordered-json-question-options-state.v1',
            'capture_max_length': max_length, 'capture_batch': batch,
            'two_cell_original_source_complete': True,
            'full_joint_untruncated_row_count': 128,
            'ordered_real_token_id_stream_sha256': digest.hexdigest(),
            'per_cell': counters,
            'model_weights_downloaded_by_this_step': False,
            'pretrained_encoder_forward_verified': False,
            'tokenizer_result_independently_signed': False,
            'prospective_learning_NDU_verified': False,
            'selection_authorized': False,
            'production_admission': 'BLOCKED'}


def execute_pinned_length_preflight(*, source_zip: Path, source_sha256: str,
                                    tokenizer_destination: Path, receipt_file: Path,
                                    max_length: int = 168, batch: int = 8,
                                    download_fn=None, tokenizer_loader=None) -> dict:
    """Fetch ONLY pinned small tokenizer/config files, not model.safetensors."""
    publisher = source_model_files(source_zip, source_sha256)
    _, source, identity = read_public_physical_features(source_zip, source_sha256, arm='modernbert')
    if not identity['physical_source_verified_locally']:
        raise ValueError('original pinned pretrained public dataset required')
    original = _public_rows(source)
    target = Path(tokenizer_destination)
    receipt = Path(receipt_file)
    if (target.exists() or target.is_symlink() or receipt.exists()
            or receipt.is_symlink() or not target.parent.is_dir() or not receipt.parent.is_dir()):
        raise ValueError('refuse pre-existing tokenizer staging or receipt')
    # The expensive full model is never requested in this step.
    if download_fn is None:
        from huggingface_hub import snapshot_download
        download_fn = snapshot_download
    archive = Path(download_fn(repo_id=MODEL['modernbert'][1],
                               revision=MODEL['modernbert'][2],
                               allow_patterns=sorted(TOKENIZER_FILES)))
    if not archive.is_dir():
        raise ValueError('pinned original tokenizer snapshot missing')
    total = 0
    for name in sorted(TOKENIZER_FILES):
        item = archive / name
        if not item.is_file():
            raise ValueError('required pinned tokenizer file missing')
        size = item.stat().st_size
        if not 0 < size <= MAX_PARTIAL_BYTES - total or _digest(item) != publisher[name]:
            raise ValueError('pinned tokenizer file budget or publisher SHA mismatch')
        total += size
    target.mkdir(mode=0o700)
    for name in sorted(TOKENIZER_FILES):
        dst = target / name
        handle = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(handle, 'wb') as sink, (archive / name).open('rb') as src:
            shutil.copyfileobj(src, sink, 1 << 20)
            sink.flush()
            os.fsync(sink.fileno())
        if _digest(dst) != publisher[name]:
            raise ValueError('pinned tokenizer changed while creating private snapshot')
    if tokenizer_loader is None:
        from transformers import AutoTokenizer
        tokenizer_loader = lambda directory: AutoTokenizer.from_pretrained(
            str(directory), local_files_only=True, trust_remote_code=False, use_fast=True)
    tokenizer = tokenizer_loader(target)
    result = audit_full_joint_token_lengths(
        tokenizer, original, max_length=max_length, batch=batch,
        model_id=MODEL['modernbert'][1], revision=MODEL['modernbert'][2],
        source_sha256=source_sha256, tokenizer_sha256=publisher['tokenizer.json'])
    result['publisher_tokenizer_files_sha256'] = {name: publisher[name] for name in sorted(TOKENIZER_FILES)}
    result['publisher_tokenizer_total_bytes'] = total
    payload = _canonical(result)
    descriptor = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'wb') as writer:
        writer.write(payload)
        writer.flush()
        os.fsync(writer.fileno())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', required=True, type=Path)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--tokenizer-destination', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--max-length', type=int, default=168)
    parser.add_argument('--batch', type=int, default=8)
    args = parser.parse_args()
    execute_pinned_length_preflight(source_zip=args.source_zip,
        source_sha256=args.source_sha256,
        tokenizer_destination=args.tokenizer_destination, receipt_file=args.receipt,
        max_length=args.max_length, batch=args.batch)


if __name__ == '__main__':
    main()

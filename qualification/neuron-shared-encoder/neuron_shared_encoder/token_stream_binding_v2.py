"""Research-only canonical token identity across preflight/Producer/Reviewer.

Hash-only receipts and local byte checks grant NO model-use authority. A
completed independent physical forward is still required for replay evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DOMAIN = b'hepta.neuron.tokenizer-only-ordered-inputs.v1\0'
CELL_DOMAIN = b'hepta.neuron.tokenizer-ordered-cell.v1\0'
PREFLIGHT_SCHEMA = 'hepta.neuron.tokenizer-only-length-preflight.shadow.v2'
MAX_RECEIPT_BYTES = 16 * 1024


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def new_cell_stream(cell: int):
    if type(cell) is not int or cell not in (0, 1):
        raise ValueError('invalid bounded Cell stream identity')
    return hashlib.sha256(CELL_DOMAIN + bytes([cell]))


def add_token_row(cell_hasher, global_hasher, *, cell: int, index: int,
                  input_sha256: str, token_ids: list[int]) -> None:
    if (type(cell) is not int or cell not in (0, 1)
            or type(index) is not int or not 0 <= index < 64
            or not _digest(input_sha256) or not isinstance(token_ids, list)
            or not 1 <= len(token_ids) <= 256
            or any(type(q) is not int or not 0 <= q < 2**31 for q in token_ids)):
        raise ValueError('incomplete bounded canonical token row identity')
    blob = json.dumps([cell, index, input_sha256, token_ids],
                      ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    framed = len(blob).to_bytes(8, 'big') + blob
    cell_hasher.update(framed)
    if global_hasher is not None:
        global_hasher.update(framed)


def read_checked_preflight(path: Path, *, source_sha256: str, tokenizer_sha256: str,
                           model_id: str, revision: str, max_length: int,
                           batch: int) -> dict[str, Any]:
    """Validate a previous hash-bound self-reported preflight, never an external signature."""
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_RECEIPT_BYTES):
        raise ValueError('bounded regular tokenizer preflight receipt required')
    raw = path.read_bytes()
    if len(raw) != path.stat().st_size:
        raise ValueError('preflight receipt changed during read')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate preflight critical JSON key')
            result[key] = value
        return result
    try:
        receipt = json.loads(raw, object_pairs_hook=pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite preflight JSON')))
        exact = (json.dumps(receipt, sort_keys=True, ensure_ascii=False,
                            separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('invalid canonical tokenizer preflight JSON') from exc
    if raw != exact or type(receipt) is not dict:
        raise ValueError('noncanonical tokenizer preflight receipt')
    expected = {'schema': PREFLIGHT_SCHEMA, 'source_zip_sha256': source_sha256,
                'tokenizer_json_sha256': tokenizer_sha256, 'model_id': model_id,
                'model_revision': revision, 'capture_max_length': max_length,
                'capture_batch': batch, 'input_encoding': 'ordered-json-question-options-state.v1',
                'full_joint_untruncated_row_count': 128,
                'two_cell_original_source_complete': True,
                'model_weights_downloaded_by_this_step': False,
                'pretrained_encoder_forward_verified': False,
                'tokenizer_result_independently_signed': False,
                'prospective_learning_NDU_verified': False,
                'selection_authorized': False, 'production_admission': 'BLOCKED'}
    for key, value in expected.items():
        if type(receipt.get(key)) is not type(value) or receipt[key] != value:
            raise ValueError(f'pinned tokenizer preflight binding mismatch: {key}')
    base_keys = set(expected) | {'ordered_real_token_id_stream_sha256', 'per_cell'}
    publisher_keys = {'publisher_tokenizer_files_sha256', 'publisher_tokenizer_total_bytes'}
    if set(receipt) not in (base_keys, base_keys | publisher_keys):
        raise ValueError('unexpected or incomplete critical tokenizer preflight fields')
    if set(receipt) == base_keys | publisher_keys:
        expected_names = {'config.json', 'special_tokens_map.json',
                          'tokenizer.json', 'tokenizer_config.json'}
        files = receipt['publisher_tokenizer_files_sha256']
        if (type(files) is not dict or set(files) != expected_names
                or files['tokenizer.json'] != tokenizer_sha256
                or any(not _digest(value) for value in files.values())
                or type(receipt['publisher_tokenizer_total_bytes']) is not int
                or not 0 < receipt['publisher_tokenizer_total_bytes'] <= 16 * 1024 * 1024):
            raise ValueError('invalid original publisher tokenizer bundle identity')
    if (type(max_length) is not int or type(batch) is not int
            or not 8 <= max_length <= 256 or not 1 <= batch <= 32
            or not _digest(source_sha256) or not _digest(tokenizer_sha256)
            or not _digest(receipt.get('ordered_real_token_id_stream_sha256'))):
        raise ValueError('invalid pinned preflight dimensions or digest')
    counters = receipt.get('per_cell')
    if not isinstance(counters, list) or len(counters) != 2:
        raise ValueError('incomplete per-Cell preflight census')
    digests = []
    for cell, row in enumerate(counters):
        if (type(row) is not dict or set(row) != {
                'cell', 'input_rows', 'tokenizer_batches', 'minimum_untruncated_tokens',
                'maximum_untruncated_tokens', 'total_active_token_slots',
                'padded_token_slots_after_model_collate', 'ordered_active_token_ids_sha256'}
                or type(row['cell']) is not int or row['cell'] != cell
                or type(row['input_rows']) is not int or row['input_rows'] != 64
                or type(row['tokenizer_batches']) is not int
                or row['tokenizer_batches'] != (64 + batch - 1) // batch
                or any(type(row[v]) is not int for v in (
                    'minimum_untruncated_tokens', 'maximum_untruncated_tokens',
                    'total_active_token_slots', 'padded_token_slots_after_model_collate'))
                or not 1 <= row['minimum_untruncated_tokens'] <= row['maximum_untruncated_tokens'] <= max_length
                or not 64 * row['minimum_untruncated_tokens'] <= row['total_active_token_slots'] <= 64 * row['maximum_untruncated_tokens']
                or row['padded_token_slots_after_model_collate'] != 64 * max_length
                or not _digest(row['ordered_active_token_ids_sha256'])):
            raise ValueError('invalid original source Cell tokenizer preflight counts')
        digests.append(row['ordered_active_token_ids_sha256'])
    return {'cell_stream_sha256': digests,
            'preflight_file_sha256': hashlib.sha256(raw).hexdigest(),
            'real_encoder_independently_verified': False,
            'production_admission': 'BLOCKED'}

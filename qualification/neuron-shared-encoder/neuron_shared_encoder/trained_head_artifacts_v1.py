"""Train -> immutable safetensors -> exact readback -> packed Head (research ONLY).

The provenance digests below are candidate self-consistency checks. A signer,
source authorizer, NDU evaluator and production final-use owner are ABSENT.
Never execute an externally supplied pickle or select a production Cell here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import torch
from torch import Tensor
from torch.nn import functional as F
from safetensors.torch import load as safe_load, save as safe_save

from .packed_cell_head_v1 import MAX_PACKED_WEIGHT_BYTES, PackedCellHeadBankV1
from .token_reader_v1 import CellHead, _audit, _hex_digest, snapshot_sha256

SCHEMA = 'hepta.neuron.trained-packed-head.shadow.v1'
KINDS = {'pooled_cached': 'pooled_feature_gate',
         'token_query_prepared': 'token_query_gate'}
STATE_KEYS = {'query', 'down.weight', 'up.weight', 'classifier.weight', 'classifier.bias'}
MAX_MANIFEST = 8192
MAX_WEIGHTS = 1024 * 1024
MAX_LOAD_CELLS = 4096


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: dict) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _validate_training(training: Any) -> None:
    if (not isinstance(training, dict)
            or set(training) != {'seed', 'steps', 'batch', 'sample_sha256',
                                 'learning_rate', 'optimizer', 'weight_decay', 'torch_version'}
            or any(type(training[key]) is not int or training[key] <= 0
                   for key in ('steps', 'batch'))
            or type(training['seed']) is not int or not 0 <= training['seed'] < 2**31
            or not _hex_digest(training['sample_sha256'])
            or type(training['learning_rate']) is not float
            or not 0 < training['learning_rate'] <= 0.1
            or training['optimizer'] != 'AdamW'
            or type(training['weight_decay']) is not float
            or training['weight_decay'] != 0.01
            or type(training['torch_version']) is not str
            or not 1 <= len(training['torch_version']) <= 64):
        raise ValueError('bounded exact optimizer provenance required')


def _head_geometry(head: CellHead) -> tuple[int, int, int]:
    if not isinstance(head, CellHead):
        raise ValueError('only versioned CellHead parameters supported')
    return (head.down.in_features, head.down.out_features, head.classifier.out_features)


def _head_tensors(head: CellHead) -> dict[str, Tensor]:
    state = head.state_dict()
    if set(state) != STATE_KEYS:
        raise ValueError('unexpected Head tensor keys')
    if any(t.device.type != 'cpu' or t.dtype != torch.float32 or
           not bool(torch.isfinite(t).all()) for t in state.values()):
        raise ValueError('nonfinite or non-CPU FP32 Head weights refused')
    return {key: value.detach().contiguous().clone() for key, value in state.items()}


def _regular_bytes(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular non-symlink artifact file required')
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise ValueError('artifact exceeds byte limit or empty')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) != size:
        raise ValueError('artifact changed during bounded read')
    return raw


def _write_once(path: Path, payload: bytes) -> None:
    # Create-only 0600; crash/incomplete writes poison the candidate directory.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_CLOEXEC', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class PinnedHeadArtifactV1:
    directory: Path
    manifest_sha256: str


def seal_head_v1(directory: Path, head: CellHead, *, kind: str,
                 scope: dict[str, str], pins: dict, training_snapshot_sha256: str,
                 training: dict[str, Any]) -> PinnedHeadArtifactV1:
    """Create-only, nonauthorizing checkpoint; Head is trained by a separate caller."""
    if kind not in KINDS or not _hex_digest(training_snapshot_sha256):
        raise ValueError('unknown Head type or unpinned frozen training source')
    fields = ('principal', 'purpose', 'organ_id', 'cell_id')
    if (not isinstance(scope, dict) or set(scope) != set(fields)
            or any(type(scope[key]) is not str or not 1 <= len(scope[key]) <= 128
                   for key in fields)):
        raise ValueError('complete bounded Cell scope required')
    digest_fields = ('encoder_sha256', 'tokenizer_sha256', 'preprocessor_sha256',
                     'normalizer_sha256', 'dataset_sha256')
    if (not isinstance(pins, dict) or set(pins) != set(digest_fields) | {'generation', 'authority_epoch'}
            or any(not _hex_digest(pins[key]) for key in digest_fields)
            or any(type(pins[key]) is not int or pins[key] <= 0
                   for key in ('generation', 'authority_epoch'))):
        raise ValueError('complete model/generation/epoch pins required')
    _validate_training(training)
    width, rank, classes = _head_geometry(head)
    if not (1 <= width <= 768 and 1 <= rank <= 32 and 2 <= classes <= 16):
        raise ValueError('invalid Head dimensions')
    tensors = _head_tensors(head)
    payload = safe_save(tensors)
    if not 0 < len(payload) <= MAX_WEIGHTS:
        raise ValueError('oversized serialized Head')
    record = {'schema': SCHEMA, 'scope': dict(scope), 'pins': dict(pins),
              'training_snapshot_sha256': training_snapshot_sha256,
              'training': dict(training), 'kind': kind,
              'dimensions': [width, rank, classes],
              'weights_file': 'head.safetensors',
              'weights_sha256': _sha(payload), 'weights_bytes': len(payload),
              'production_admission': 'BLOCKED',
              'selection_authorized': False, 'independent_signature_verified': False}
    manifest = _canonical(record)
    if len(manifest) > MAX_MANIFEST:
        raise ValueError('oversized checkpoint manifest')
    directory = Path(directory)
    if directory.is_symlink() or directory.exists():
        raise ValueError('checkpoint directory must not already exist')
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    _write_once(directory / 'head.safetensors', payload)
    _write_once(directory / 'manifest.json', manifest)
    return PinnedHeadArtifactV1(directory, _sha(manifest))


def train_and_seal_head_v1(directory: Path, tokens: Tensor, mask: Tensor, labels: Tensor,
                           rows: list[dict], pins: dict, expected_snapshot_sha256: str, *,
                           kind: str = 'token_query_prepared', rank: int = 8,
                           seed: int = 11, steps: int = 20, batch: int = 16,
                           lr: float = 1e-3) -> PinnedHeadArtifactV1:
    """Actually optimize one private Head on train-only rows; do not select it."""
    if (kind not in KINDS or not 1 <= rank <= 32 or not 1 <= steps <= 128
            or not 1 <= batch <= 64 or not 0 <= seed < 2**31
            or not 0 < lr <= 0.1 or not isinstance(lr, float)):
        raise ValueError('bounded training controls required')
    groups = _audit(tokens, mask, labels, rows, pins, expected_snapshot_sha256)
    train_ids = groups['train']
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        head = CellHead(tokens.shape[-1], rank, len(rows[0]['options']))
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, betas=(0.9, 0.999),
                                  eps=1e-8, weight_decay=0.01)
    generator = torch.Generator(device='cpu').manual_seed(seed + 9127)
    samples = [train_ids[torch.randint(len(train_ids), (min(batch, len(train_ids)),),
                                    generator=generator)] for _ in range(steps)]
    sample_sha = _sha(_canonical({'sample_ids': [v.tolist() for v in samples]}))
    head.train()
    for indices in samples:
        logits = head(tokens[indices], mask[indices], KINDS[kind])
        loss = F.cross_entropy(logits, labels[indices])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    head.eval()
    if snapshot_sha256(tokens, mask, rows, pins) != expected_snapshot_sha256:
        raise ValueError('training features changed during optimizer execution')
    scope = {key: rows[0][key] for key in ('principal', 'purpose', 'organ_id', 'cell_id')}
    return seal_head_v1(directory, head, kind=kind, scope=scope, pins=pins,
                        training_snapshot_sha256=expected_snapshot_sha256,
                        training={'seed': seed, 'steps': steps, 'batch': batch,
                                  'sample_sha256': sample_sha, 'learning_rate': lr,
                                  'optimizer': 'AdamW', 'weight_decay': 0.01,
                                  'torch_version': str(torch.__version__)})


class ReadbackPackedHeadV1:
    """Frozen shadow Head roster. No authorization or selected runtime authority."""

    def __init__(self, heads: list[tuple[str, CellHead]], *, kind: str,
                 manifests: tuple[str, ...], scope: dict, pins: dict):
        self._heads = heads
        self._kind = kind
        self._scope = dict(scope)
        self._pins = dict(pins)
        self._manifests = manifests
        self._bank = PackedCellHeadBankV1(heads)

    def verify_parity(self, tokens: Tensor, mask: Tensor, *, atol: float = 1e-5) -> dict:
        """All loaded trained Head outputs must match the packed FP32 execution."""
        if not 0 < atol <= 1e-4:
            raise ValueError('bounded numeric tolerance required')
        with torch.inference_mode():
            scalar = torch.cat([head(tokens.unsqueeze(0), mask.unsqueeze(0), KINDS[self._kind])
                                for _, head in self._heads], dim=0)
            packed = self._bank.execute(tokens, mask, kind=self._kind)
            difference = float((scalar - packed).abs().amax())
            if not torch.allclose(scalar, packed, rtol=0.0, atol=atol):
                raise ValueError('reloaded trained Head packed/scalar parity mismatch')
        return {'experiment': 'RELOADED_TRAINED_PACKED_HEAD_SHADOW_V1',
                'cell_count': len(self._heads), 'cell_ids': [name for name, _ in self._heads],
                'kind': self._kind, 'manifest_sha256s': list(self._manifests),
                'bank_sha256': self._bank.bank_sha256,
                'head_weight_bytes': self._bank.head_weight_bytes,
                'maximum_prediction_difference': difference, 'atol': atol,
                'safetensors_weight_readback_verified': True,
                'training_record_is_self_reported': True,
                'independent_training_verified': False,
                'actual_pretrained_encoder_executed_here': False,
                'independent_source_and_signature_verified': False,
                'native_q24_or_worker_verified': False,
                'independent_future_ndu_verified': False,
                'production_admission': 'BLOCKED', 'selection_authorized': False}


def load_pinned_trained_bank_v1(refs: list[PinnedHeadArtifactV1], *,
                                expected_principal: str, expected_purpose: str,
                                expected_organ: str, expected_pins: dict,
                                kind: str) -> ReadbackPackedHeadV1:
    """Read only EXACT caller-pinned artifact bytes. Pins are NOT trusted grants."""
    if kind not in KINDS or not isinstance(refs, list) or not 1 <= len(refs) <= MAX_LOAD_CELLS:
        raise ValueError('bounded same-kind model roster required')
    if any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in
           (expected_principal, expected_purpose, expected_organ)):
        raise ValueError('complete expected scope required')
    if not isinstance(expected_pins, dict):
        raise ValueError('complete expected model/generation tuple required')
    heads: list[tuple[str, CellHead]] = []
    witnesses: list[str] = []
    seen: set[str] = set()
    expected_shape: tuple[int, int, int] | None = None
    predicted_bank_bytes = 0
    for ref in refs:
        if not isinstance(ref, PinnedHeadArtifactV1) or not _hex_digest(ref.manifest_sha256):
            raise ValueError('exact externally pinned artifact required')
        path = Path(ref.directory)
        if path.is_symlink() or not path.is_dir():
            raise ValueError('regular checkpoint directory required')
        raw = _regular_bytes(path / 'manifest.json', MAX_MANIFEST)
        if _sha(raw) != ref.manifest_sha256:
            raise ValueError('pinned checkpoint manifest SHA256 mismatch')
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError('invalid bounded checkpoint manifest') from exc
        if not isinstance(record, dict) or raw != _canonical(record):
            raise ValueError('canonical checkpoint manifest required')
        if (set(record) != {'schema', 'scope', 'pins', 'training_snapshot_sha256',
                            'training', 'kind', 'dimensions', 'weights_file',
                            'weights_sha256', 'weights_bytes', 'production_admission',
                            'selection_authorized', 'independent_signature_verified'}
                or record['schema'] != SCHEMA or record['kind'] != kind
                or record['production_admission'] != 'BLOCKED'
                or record['selection_authorized'] is not False
                or record['independent_signature_verified'] is not False
                or record['pins'] != expected_pins):
            raise ValueError('selected artifact/model/generation conflict')
        if not _hex_digest(record['training_snapshot_sha256']):
            raise ValueError('missing or invalid optimizer/feature lineage')
        _validate_training(record['training'])
        scope = record['scope']
        if (not isinstance(scope, dict) or set(scope) != {'principal', 'purpose', 'organ_id', 'cell_id'}
                or scope['principal'] != expected_principal
                or scope['purpose'] != expected_purpose
                or scope['organ_id'] != expected_organ
                or not isinstance(scope['cell_id'], str) or not 1 <= len(scope['cell_id']) <= 128
                or scope['cell_id'] in seen):
            raise ValueError('cross-scope or duplicate Cell checkpoint')
        seen.add(scope['cell_id'])
        dims = record['dimensions']
        if (not isinstance(dims, list) or len(dims) != 3
                or any(type(v) is not int for v in dims)):
            raise ValueError('versioned Head dimensions required')
        width, rank, classes = dims
        if not 1 <= width <= 768 or not 1 <= rank <= 32 or not 2 <= classes <= 16:
            raise ValueError('bounded loaded Head dimensions required')
        if expected_shape is None:
            expected_shape = (width, rank, classes)
        elif expected_shape != (width, rank, classes):
            raise ValueError('incompatible packed Head geometry')
        predicted_bank_bytes += (width + 2 * width * rank + width * classes + classes) * 4
        if predicted_bank_bytes > MAX_PACKED_WEIGHT_BYTES:
            raise ValueError('aggregate loaded Head bank exceeds memory cap')
        if (record['weights_file'] != 'head.safetensors'
                or not _hex_digest(record['weights_sha256'])
                or type(record['weights_bytes']) is not int):
            raise ValueError('exact safe tensor artifact identity required')
        raw_tensor = _regular_bytes(path / 'head.safetensors', MAX_WEIGHTS)
        if _sha(raw_tensor) != record['weights_sha256'] or len(raw_tensor) != record['weights_bytes']:
            raise ValueError('pinned Head weights bytes conflict')
        try:
            values = safe_load(raw_tensor)
        except Exception as exc:
            raise ValueError('invalid safetensors checkpoint') from exc
        expected_shapes = {'query': (width,), 'down.weight': (rank, width),
                           'up.weight': (width, rank), 'classifier.weight': (classes, width),
                           'classifier.bias': (classes,)}
        if (set(values) != STATE_KEYS or any(tuple(values[key].shape) != expected_shapes[key]
                or values[key].dtype != torch.float32 or not bool(torch.isfinite(values[key]).all())
                for key in STATE_KEYS)):
            raise ValueError('incompatible numeric Head checkpoint')
        head = CellHead(width, rank, classes)
        head.load_state_dict(values, strict=True)
        head.eval()
        heads.append((scope['cell_id'], head))
        witnesses.append(ref.manifest_sha256)
    return ReadbackPackedHeadV1(heads, kind=kind, manifests=tuple(witnesses),
                                scope={'principal': expected_principal, 'purpose': expected_purpose,
                                       'organ_id': expected_organ}, pins=expected_pins)

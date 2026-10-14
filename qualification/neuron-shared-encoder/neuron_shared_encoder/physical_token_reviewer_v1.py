"""Independent, non-authorizing numerical review of a sealed physical token study.

Re-encodes exact publisher inputs in its own process, then evaluates frozen
safetensors using NumPy equations rather than the producer's Torch CellHead,
optimizer or PackedCellHeadBank. A hash is never a third-party signature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import torch
from safetensors.torch import load as safe_load

from .physical_pooled_replay_v1 import MODEL, _member, _parsed, read_public_physical_features
from .token_reader_offline import INPUT_ENCODING, NORMALIZATION, _joint_text, _tokenize_and_capture
from .token_reader_v1 import snapshot_sha256
from .trained_head_artifacts_v1 import _canonical

SCHEMA = 'hepta.neuron.token-pair-independent-numerical-review.v1'
SOURCE_SCHEMA = 'hepta.neuron.real-token-paired-retrospective.v1'
KINDS = ('pooled_cached', 'token_query_prepared')
SPLITS = ('calibration', 'holdout')
EXPECTED_KEYS = {'query', 'down.weight', 'up.weight', 'classifier.weight', 'classifier.bias'}
MAX_REPORT_BYTES = 128 * 1024
MAX_CHECKPOINT_BYTES = 128 * 1024


def _hash(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _fixed_read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError('bounded regular sealed artifact required')
    data = path.read_bytes()
    if len(data) != path.stat().st_size:
        raise ValueError('sealed artifact changed while reading')
    return data


def _json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate critical JSON key')
            result[k] = v
        return result
    try:
        obj = json.loads(raw, object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('invalid sealed JSON') from exc
    if not isinstance(obj, dict) or raw != _canonical(obj):
        raise ValueError('canonical sealed JSON required')
    return obj


def _normal(tokens: torch.Tensor, mask: torch.Tensor, records: list[dict]) -> np.ndarray:
    train = [i for i, row in enumerate(records) if row['split'] == 'train']
    if len(train) != 32:
        raise ValueError('incomplete original Cell train partition')
    seen = tokens[train][mask[train]]
    mean = seen.mean(0)
    sd = seen.std(0, unbiased=False).clamp_min(1e-4)
    result = ((tokens - mean) / sd).clamp(-8, 8).masked_fill(~mask.unsqueeze(-1), 0)
    return result.detach().cpu().numpy().astype(np.float64, copy=False)


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(value, -80, 80)))


def numpy_head_logits(data: np.ndarray, mask: np.ndarray, weights: dict, kind: str) -> np.ndarray:
    """Independent inference arithmetic; never calls the Torch Head implementation."""
    if kind not in KINDS or data.ndim != 3 or mask.shape != data.shape[:2]:
        raise ValueError('invalid independent Head input')
    if set(weights) != EXPECTED_KEYS:
        raise ValueError('not a complete safe checkpoint')
    q = weights['query']
    width = data.shape[-1]
    rank = weights['down.weight'].shape[0]
    classes = weights['classifier.weight'].shape[0]
    shapes = {'query': (width,), 'down.weight': (rank, width),
              'up.weight': (width, rank), 'classifier.weight': (classes, width),
              'classifier.bias': (classes,)}
    if any(weights[key].shape != shape or not np.isfinite(weights[key]).all()
           for key, shape in shapes.items()):
        raise ValueError('invalid immutable checkpoint dimensions/numerics')
    if not np.all(mask.any(axis=1)):
        raise ValueError('empty independent attention mask')
    if kind == 'pooled_cached':
        pooled = (data * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
        selected = pooled * (2 * _sigmoid(q))
    else:
        scores = data @ q / math.sqrt(width)
        scores = np.where(mask, scores, -np.inf)
        scores = np.exp(scores - np.max(scores, axis=1, keepdims=True))
        attention = scores / scores.sum(axis=1, keepdims=True)
        selected = (attention[..., None] * data).sum(axis=1)
    down = selected @ weights['down.weight'].T
    silu = down * _sigmoid(down)
    gate = 2 * _sigmoid(silu @ weights['up.weight'].T)
    logits = (selected * gate) @ weights['classifier.weight'].T + weights['classifier.bias']
    if not np.isfinite(logits).all():
        raise ValueError('nonfinite independent Head output')
    return logits


def _measure(logits: np.ndarray, labels: list[int]) -> dict[str, float]:
    targets = np.asarray(labels, dtype=np.int64)
    if len(targets) != len(logits) or len(set(targets)) > 4:
        raise ValueError('misaligned independent evaluation labels')
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    probs = np.exp(shifted)
    probs /= probs.sum(axis=-1, keepdims=True)
    truth = np.eye(logits.shape[-1])[targets]
    return {'accuracy': float(np.mean(logits.argmax(-1) == targets)),
            'brier': float(np.mean(np.sum((probs - truth) ** 2, axis=-1))),
            'nll': float(np.mean(-np.log(np.maximum(probs[np.arange(len(targets)), targets], 1e-300))))}


def _recreate_cell_rows(source: list[dict]) -> dict[int, list[dict]]:
    """Strict original source validation, without importing producer training."""
    if len(source) != 128:
        raise ValueError('original public roster must have 128 cases')
    seen_case, seen_group = set(), set()
    cells = {0: [], 1: []}
    for row in source:
        if (not isinstance(row, dict) or set(row) != {
                'case_id', 'cell', 'group', 'label', 'observed_at', 'scope', 'split', 'text'}
                or type(row['cell']) is not int or row['cell'] not in cells
                or row['split'] not in ('train', 'calibration', 'holdout')
                or row['observed_at'] is not None or row['scope'] != 'public-ag-news-research'
                or type(row['label']) is not int or not 0 <= row['label'] < 4
                or type(row['text']) is not str or not 1 <= len(row['text']) <= 8192
                or row['case_id'] in seen_case or row['group'] in seen_group):
            raise ValueError('unqualified, duplicate or fake-time source row')
        seen_case.add(row['case_id'])
        seen_group.add(row['group'])
        assembled = {**row, 'question': 'Which AG News category best describes this article?',
                     'options': ['World', 'Sports', 'Business', 'Science and Technology'],
                     'state': row['text']}
        assembled['joint_text'], assembled['input_sha256'] = _joint_text(assembled)
        cells[row['cell']].append(assembled)
    for cell in (0, 1):
        records = cells[cell]
        if ({s: sum(row['split'] == s for row in records)
             for s in ('train', 'calibration', 'holdout')} !=
            {'train': 32, 'calibration': 16, 'holdout': 16}):
            raise ValueError('missing complete original Cell partition')
    return cells


def audit_sealed_token_pair(*, results_dir: Path, source: list[dict],
                            features: dict[int, tuple[torch.Tensor, torch.Tensor]],
                            pins: dict, source_zip_sha256: str,
                            model_id: str, model_revision: str,
                            actual_reencoding: bool = False) -> dict:
    """Compare all frozen Head outputs to wholly separate NumPy calculations."""
    by_cell = _recreate_cell_rows(source)
    root = Path(results_dir)
    report_raw = _fixed_read(root/'report.json', MAX_REPORT_BYTES)
    original = _json(report_raw)
    if (original.get('schema') != SOURCE_SCHEMA
            or original.get('production_admission') != 'BLOCKED'
            or original.get('selection_authorized') is not False
            or original.get('source_zip_sha256') != source_zip_sha256
            or original.get('model_id') != model_id
            or original.get('model_revision') != model_revision
            or original.get('distinct_holdout_cases') != 32
            or original.get('real_model_encoder_forward_observed') is not actual_reencoding
            or original.get('real_deployed_no_change_baseline_verified') is not False
            or original.get('no_independent_future_or_ood_window_verified') is not True
            or original.get('negative_transfer_and_NDU_verified') is not False
            or not isinstance(original.get('runs'), list)
            or not 1 <= len(original['runs']) <= 3):
        raise ValueError('wrong or self-promoting source report')
    if set(features) != {0, 1}:
        raise ValueError('complete two-Cell features required for independent review')
    prepared = {}
    for cell in (0, 1):
        tokens, mask = features[cell]
        if (tokens.dtype != torch.float32 or tokens.ndim != 3 or tokens.device.type != 'cpu'
                or not tokens.is_contiguous() or tokens.shape[0] != 64
                or tokens.shape[-1] not in (24, 768)
                or not 1 <= tokens.shape[1] <= 256
                or tokens.numel() > 8_388_608
                or not torch.isfinite(tokens).all()
                or mask.dtype != torch.bool or mask.shape != tokens.shape[:2]
                or not mask.is_contiguous() or not mask.any(1).all()):
            raise ValueError('actual bounded token observation required')
        metadata = [dict(case_id=r['case_id'], group=r['group'], scope=r['scope'],
                         cell=r['cell'], split=r['split'], input_sha256=r['input_sha256'])
                    for r in by_cell[cell]]
        feature_digest = snapshot_sha256(tokens, mask, metadata, pins)
        prepared[cell] = (_normal(tokens, mask, by_cell[cell]), mask.cpu().numpy(), feature_digest)
    measured = []
    seen_seeds = set()
    for run in original['runs']:
        seed = run.get('seed')
        if (type(seed) is not int or not 0 <= seed < 2**31 or seed in seen_seeds
                or run.get('all_32_holdout_rows_for_both_arms_verified') is not True
                or not isinstance(run.get('candidate_heads'), list) or len(run['candidate_heads']) != 4
                or not isinstance(run.get('observations'), list) or len(run['observations']) != 4):
            raise ValueError('invalid/incomplete sealed seed roster')
        seen_seeds.add(seed)
        indexed = {}
        for candidate in run['candidate_heads']:
            key = (candidate.get('cell'), candidate.get('kind'))
            if (key in indexed or key[0] not in (0, 1) or key[1] not in KINDS):
                raise ValueError('duplicate or cross-Cell Head candidate')
            indexed[key] = candidate
        if set(indexed) != {(cell, kind) for cell in (0,1) for kind in KINDS}:
            raise ValueError('incomplete Head candidates')
        observed = {}
        for item in run['observations']:
            key = (item.get('cell'), item.get('split'))
            if key in observed or key[0] not in (0,1) or key[1] not in SPLITS:
                raise ValueError('duplicate or cross-split metric observation')
            observed[key] = item
        if set(observed) != {(cell, split) for cell in (0,1) for split in SPLITS}:
            raise ValueError('incomplete heldout/calibration metric comparison')
        independent_logits = {}
        for cell in (0,1):
            rec = by_cell[cell]
            features_np, mask_np, feature_digest = prepared[cell]
            train_labels = [r['label'] for r in rec if r['split'] == 'train']
            train_labels_sha = _hash(_canonical(train_labels))
            for kind in KINDS:
                candidate = indexed[(cell, kind)]
                root_name = f'seed-{seed}-cell-{cell}-{kind}'
                ckpt_dir = root/root_name
                manifest_raw = _fixed_read(ckpt_dir/'manifest.json', 8192)
                manifest = _json(manifest_raw)
                if (_hash(manifest_raw) != candidate.get('head_manifest_sha256')
                        or manifest.get('schema') != 'hepta.neuron.trained-packed-head.shadow.v1'
                        or manifest.get('production_admission') != 'BLOCKED'
                        or manifest.get('selection_authorized') is not False
                        or manifest.get('independent_signature_verified') is not False
                        or manifest.get('pins') != pins
                        or manifest.get('kind') != kind
                        or manifest.get('scope') != {'principal':'public-ag-news-research',
                            'purpose':'ag-news-retrospective-token-pair',
                            'organ_id':'ag-news','cell_id':f'cell-{cell}'}
                        or manifest.get('dimensions') != [features_np.shape[-1],8,4]
                        or candidate.get('parameter_count') !=
                           features_np.shape[-1] + 2*features_np.shape[-1]*8 + 4*features_np.shape[-1] + 4
                        or manifest.get('weights_file') != 'head.safetensors'):
                    raise ValueError('wrong signed-status/geometry/source Head manifest')
                training = manifest.get('training', {})
                sample_digest = candidate.get('training_sample_sha256')
                if (training.get('steps') != original.get('head_train_steps_per_candidate')
                        or training.get('batch') != 16
                        or training.get('sample_sha256') != sample_digest
                        or sample_digest != indexed[(cell,KINDS[0])].get('training_sample_sha256')
                        or candidate.get('train_label_sha256') != train_labels_sha):
                    raise ValueError('incompatible training schedule or label lineage')
                train_witness = _hash(_canonical([feature_digest,train_labels_sha,sample_digest]))
                if manifest.get('training_snapshot_sha256') != train_witness:
                    raise ValueError('source/checkpoint optimizer witness mismatch')
                tensor_raw = _fixed_read(ckpt_dir/'head.safetensors', MAX_CHECKPOINT_BYTES)
                if (manifest.get('weights_sha256') != _hash(tensor_raw)
                        or manifest.get('weights_bytes') != len(tensor_raw)):
                    raise ValueError('physical safe Head artifact digest mismatch')
                tensors = safe_load(tensor_raw)
                if set(tensors) != EXPECTED_KEYS:
                    raise ValueError('unexpected checkpoint tensors')
                weights = {k:tensors[k].cpu().numpy().astype(np.float64, copy=False)
                           for k in EXPECTED_KEYS}
                for split in SPLITS:
                    indices = [i for i,r in enumerate(rec) if r['split'] == split]
                    logits = numpy_head_logits(features_np[indices],mask_np[indices],weights,kind)
                    reference = observed[(cell, split)].get(kind)
                    numeric = _measure(logits,[rec[i]['label'] for i in indices])
                    if (not isinstance(reference,dict)
                            or reference.get('head_manifest_sha256') != _hash(manifest_raw)
                            or any(type(reference.get(k)) not in (float,int)
                                   or not math.isfinite(reference[k])
                                   or abs(reference[k] - numeric[k]) > 8e-5
                                   for k in ('accuracy','brier','nll'))):
                        raise ValueError('independent NumPy Head metrics mismatch')
                    independent_logits[(cell,split,kind)] = logits
        for cell in (0,1):
            rec = by_cell[cell]
            for split in SPLITS:
                ids=[i for i,r in enumerate(rec) if r['split'] == split]
                gold=np.asarray([rec[i]['label'] for i in ids], dtype=int)
                left=independent_logits[(cell,split,KINDS[0])].argmax(axis=-1)
                right=independent_logits[(cell,split,KINDS[1])].argmax(axis=-1)
                claimed=observed[(cell,split)][KINDS[1]]
                if (claimed.get('newly_correct_v_pooled') != int(((left!=gold)&(right==gold)).sum())
                        or claimed.get('newly_incorrect_v_pooled') != int(((left==gold)&(right!=gold)).sum())):
                    raise ValueError('changed-case independent comparison mismatch')
                measured.append({'seed':seed,'cell':cell,'split':split,
                    'token_minus_pooled_accuracy':float(np.mean(right==gold)-np.mean(left==gold)),
                    'independent_head_results_replayed':True})
    return {'schema':SCHEMA,'research_producer_report_sha256':_hash(report_raw),
            'source_zip_sha256':source_zip_sha256,'model_id':model_id,
            'model_revision':model_revision,'training_seeds':sorted(seen_seeds),
            'checked_head_checkpoints':4*len(seen_seeds),
            'checked_holdout_cases_per_seed':32,
            'independent_numeric_replay_all_metrics_passed':True,
            'real_pretrained_encoder_forward_reobserved':actual_reencoding,
            'original_observer_independently_signed':False,
            'verified_prospective_future_NDU':False,
            'deployed_no_change_compared':False,
            'production_admission':'BLOCKED','selection_authorized':False,
            'descriptive_seed_repeated_deltas':measured}


def review_pinned_real_token_pair(*, archive_path: Path, archive_sha256: str,
                                  checkpoint_dir: Path, bundle_sha256: str,
                                  results_dir: Path, output: Path,
                                  max_length: int = 128, batch: int = 8) -> dict:
    """Real run: fresh model forward in reviewer process and safe checkpoint replay."""
    from .bundle import verify_checkpoint_bundle
    from .contracts import sha256_file
    from .models import OfflineEncoder
    _, source, source_info = read_public_physical_features(archive_path, archive_sha256,arm='modernbert')
    if not source_info['physical_source_verified_locally']:
        raise ValueError('cannot review synthetic or unknown source')
    with ZipFile(archive_path) as archive:
        manifest = _parsed(_member(archive,'hepta-modernbert-pair/manifest.json',65536))
    model = manifest['model']
    if (model['model_id'] != MODEL['modernbert'][1]
            or model['revision'] != MODEL['modernbert'][2]
            or model['conversion'] is not None):
        raise ValueError('pinned original ModernBERT revision mismatch')
    for name, sha in model['files'].items():
        if (not (Path(checkpoint_dir)/name).is_file()
                or (Path(checkpoint_dir)/name).is_symlink()
                or sha256_file(Path(checkpoint_dir)/name) != sha):
            raise ValueError('publisher model file differs')
    verify_checkpoint_bundle(checkpoint_dir,'modernbert-joint',bundle_sha256)
    model_backend = OfflineEncoder('modernbert-joint',str(checkpoint_dir),
                                  model['files']['model.safetensors'],
                                  device='cpu',max_length=max_length,
                                  expected_bundle_sha256=bundle_sha256)
    cells = _recreate_cell_rows(source)
    features={}
    for cell in (0,1):
        texts=[r['joint_text'] for r in cells[cell]]
        tokens,mask,observation = _tokenize_and_capture(model_backend,texts,
                                                       max_length=max_length,batch=batch)
        if observation['model_forward_observation']['module_forward_completions'] <= 0:
            raise ValueError('independent physical Encoder did not run')
        features[cell]=(tokens,mask)
    model_backend._check_bundle_unchanged()
    pins={'encoder_sha256':bundle_sha256,
          'tokenizer_sha256':model['files']['tokenizer.json'],
          'preprocessor_sha256':_hash(INPUT_ENCODING),
          'normalizer_sha256':_hash(NORMALIZATION),
          'dataset_sha256':source_info['dataset_sha256'],
          'generation':1,'authority_epoch':1}
    result=audit_sealed_token_pair(results_dir=results_dir,source=source,
          features=features,pins=pins,source_zip_sha256=archive_sha256,
          model_id=MODEL['modernbert'][1],model_revision=MODEL['modernbert'][2],
          actual_reencoding=True)
    target=Path(output)
    if target.exists() or target.is_symlink():
        raise ValueError('independent result must use new path')
    payload=_canonical(result)
    fd=os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(payload);f.flush();os.fsync(f.fileno())
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-zip', type=Path, required=True)
    ap.add_argument('--source-sha256',required=True)
    ap.add_argument('--checkpoint-dir',type=Path,required=True)
    ap.add_argument('--bundle-sha256',required=True)
    ap.add_argument('--producer',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--max-length',type=int,default=128)
    ap.add_argument('--batch',type=int,default=8)
    args=ap.parse_args()
    review_pinned_real_token_pair(archive_path=args.source_zip,
           archive_sha256=args.source_sha256,checkpoint_dir=args.checkpoint_dir,
           bundle_sha256=args.bundle_sha256,results_dir=args.producer,
           output=args.output,max_length=args.max_length,batch=args.batch)


if __name__ == '__main__':
    main()

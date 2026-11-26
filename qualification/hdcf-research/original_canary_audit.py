"""Read-only, exact-archive verifier for real pretrained ModernBERT CellBank.

The fixed historical artifact includes original physical learned Head tensors
and predictions, but NOT publisher-owned test labels or original cached features.
Never upgrade historic summary accuracy into independently rescored accuracy.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import struct
import zipfile

EXPECTED_ZIP_SHA256 = 'fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a'
EXPECTED_SOURCE_REVISION = '57ec275d8078af65b7731c2a98be812d844a6d6b'
EXPECTED_MODEL_REVISION = '8949b909ec900327062f0ebf497f51aef5e6f0c8'
EXPECTED_MODEL_SNAPSHOT = '43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d'
ROOT = 'public-cell-learning/'
ARMS = ('dense16', 'sparse16_top2')
NAMES = frozenset((
    'public-cell-learning.log',
    *[ROOT + x for x in ('pre-execution-plan.json', 'selection.json', 'scores.json',
                        'data/SOURCE.json', 'data/MATERIAL.json', 'data/LICENSE',
                        'trial/COMMITTED.json', 'trial/plan.json', 'trial/shared-encoder.json')],
    *[ROOT + f'trial/{arm}/{item}' for arm in ARMS for item in
      ('COMMITTED.json', 'bank.safetensors', 'execution.json', 'predictions.json')]
))
MAX_ARCHIVE_BYTES = 15_000_000
MAX_MEMBER_BYTES = 2_500_000


class Denied(ValueError):
    pass


def _pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise Denied('duplicate JSON key')
        out[k] = v
    return out


def _nonfinite(value):
    raise Denied('nonfinite JSON constant')


def _json(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (ValueError, UnicodeError) as exc:
        raise Denied('invalid JSON') from exc


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, allow_nan=False).encode())


def _require(cond, reason):
    if not cond:
        raise Denied(reason)


def _safetensors_recount(raw):
    """Hash genuine serialized tensor bytes, not a self-reported weight digest."""
    _require(len(raw) >= 16, 'truncated safetensors')
    nheader = struct.unpack_from('<Q', raw)[0]
    _require(2 <= nheader < 200_000 and 8+nheader <= len(raw), 'bad tensor header')
    tensors = _json(raw[8:8+nheader]); _require(type(tensors) is dict, 'tensor header object')
    payload = raw[8+nheader:]
    last = 0; scalars = 0
    rows = []
    for name, spec in tensors.items():
        if name == '__metadata__':
            _require(spec == {} or type(spec) is dict, 'invalid metadata')
            continue
        _require(type(name) is str and len(name) <= 256 and type(spec) is dict and
                 set(spec) == {'dtype', 'shape', 'data_offsets'}, 'tensor inventory error')
        _require(spec['dtype'] == 'F32', 'unexpected weight dtype')
        shape = spec['shape']; span = spec['data_offsets']
        _require(type(shape) is list and 1 <= len(shape) <= 3 and
                 all(type(s) is int and 1 <= s <= 8192 for s in shape), 'bad tensor shape')
        _require(type(span) is list and len(span) == 2 and
                 all(type(i) is int for i in span), 'bad tensor offsets')
        count = math.prod(shape)
        lo, hi = span
        _require(0 <= lo <= hi <= len(payload) and hi-lo == count*4, 'invalid tensor byte count')
        scalars += count
        rows.append((lo, hi, name, tuple(shape)))
    _require(0 < len(rows) <= 256, 'tensor count limit')
    for lo, hi, _, _ in sorted(rows):
        _require(lo == last, 'tensor overlap or gap')
        last = hi
    _require(last == len(payload), 'unaccounted trailing tensor bytes')
    h = hashlib.sha256(b'hepta.cell-bank.actual-state.v1\0')
    for lo, hi, name, shape in sorted(rows, key=lambda r: r[2]):
        desc = f'{name}:torch.float32:{shape}'.encode()
        for part in (desc, payload[lo:hi]):
            h.update(len(part).to_bytes(8, 'big')); h.update(part)
    return {'parameter_count': scalars, 'tensor_count': len(rows),
            'tensor_payload_bytes': scalars * 4, 'actual_trained_state_sha256': h.hexdigest()}


def audit_bytes(archive: bytes, *, expected_sha256: str = EXPECTED_ZIP_SHA256):
    """Verify exact original archive bytes and all internal source/weight seals.

    expected_sha256 is an external trusted input; testing a different hash only
    proves that artifact's self-consistency, not independent publisher approval.
    """
    _require(type(archive) is bytes and 0 < len(archive) <= MAX_ARCHIVE_BYTES, 'bounded archive bytes required')
    _require(type(expected_sha256) is str and _sha(archive) == expected_sha256, 'original ZIP SHA mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            infos = z.infolist()
            _require(len(infos) == len(NAMES) and set(t.filename for t in infos) == NAMES,
                     'incomplete, duplicate or unknown ZIP members')
            _require(all(i.file_size <= MAX_MEMBER_BYTES and i.compress_size <= MAX_ARCHIVE_BYTES
                         and i.flag_bits & 1 == 0 and i.filename[-1] != '/'
                         and (i.external_attr >> 16) & 0o170000 not in (0o120000, 0o060000)
                         for i in infos), 'oversized or unsafe ZIP member')
            _require(sum(i.file_size for i in infos) <= 5_000_000, 'ZIP total size exceeded')
            raw = {i.filename: z.read(i) for i in infos}
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise Denied('unreadable ZIP') from exc
    def get(name):
        return _json(raw[ROOT + name])

    scores, selection, manifest = get('scores.json'), get('selection.json'), get('trial/COMMITTED.json')
    plan, shared = get('trial/plan.json'), get('trial/shared-encoder.json')
    source, material = get('data/SOURCE.json'), get('data/MATERIAL.json')
    _require(source['revision'] == EXPECTED_SOURCE_REVISION and source == material['source'] and
             selection['raw_sha256'] == {'train': material['sha256']['banking_data/train.csv'],
                                           'test': material['sha256']['banking_data/test.csv']} and
             material['sha256']['LICENSE'] == _sha(raw[ROOT+'data/LICENSE']), 'original data lineage mismatch')
    _require(scores['schema'] == 'hepta.public-cell-learning-scores.v1' and
             scores['dataset_revision'] == source['revision'] and
             scores['dataset_files_sha256'] == selection['raw_sha256'], 'invalid public score lineage')
    for flag in ('efficacy_established', 'production_authorized', 'observer_independence_established',
                 'source_group_independence_verified', 'full_system_cost_measured', 'pretraining_contamination_checked'):
        _require(scores[flag] is False, 'incorrect positive capability claim')
    _require(scores['task_subset_not_full_benchmark'] is True and
             scores['fitting_examples'] == 64 and scores['heldout_examples'] == 32 and
             selection['input_id'] == plan['input_id'] and
             len(selection['selected_ids']['fit']) == 64 and
             len(selection['selected_ids']['heldout']) == 32 and
             set(selection['selected_ids']['fit']).isdisjoint(selection['selected_ids']['heldout']), 'case census mismatch')
    _require(plan['schema'] == 'hepta.public-cell-learning-plan.v1' and
             plan['plan_id'] == _digest({k:v for k,v in plan.items() if k!='plan_id'}) and
             plan['arms'] == {'dense16': 16, 'sparse16_top2': 2} and plan['train_steps'] == 64 and
             plan['snapshot_sha256'] == EXPECTED_MODEL_SNAPSHOT and
             plan == get('pre-execution-plan.json'), 'original plan drift')
    _require(_sha(raw[ROOT+'trial/plan.json']) == manifest['plan_sha256'] and
             _sha(raw[ROOT+'trial/shared-encoder.json']) == manifest['shared_encoder_sha256'] and
             manifest['schema'] == 'hepta.public-cell-learning-terminals.v1' and
             manifest['run_id'] == _digest({k:v for k,v in manifest.items() if k!='run_id'}) and
             scores['run_id'] == manifest['run_id'] == _digest({k:v for k,v in manifest.items() if k!='run_id'}),
             'original run terminal drift')
    receipt = shared['encoder_receipt']
    _require(receipt['snapshot_sha256'] == EXPECTED_MODEL_SNAPSHOT and
             receipt['upstream_revision'] == EXPECTED_MODEL_REVISION and
             receipt['frozen_encoder_params'] == 149655232 and
             receipt['pretrained_provenance_independently_verified'] is False and
             shared['counted_once_for_both_arms'] is True and
             shared['feature_payload_bytes'] == 96*768*4 and
             len(shared['token_counts']['fit']) == 64 and
             len(shared['token_counts']['heldout']) == 32 and
             scores['shared_encoder'] == shared, 'unsupported or drifted real Encoder receipt')
    _require(set(scores['scores']) == set(ARMS) and set(manifest['terminals']) == set(ARMS),
             'incomplete arms')
    per_arm = {}
    first_init = None
    for arm in ARMS:
        prefix = 'trial/'+arm+'/'
        seal, ex, predictions = get(prefix+'COMMITTED.json'), get(prefix+'execution.json'), get(prefix+'predictions.json')
        _require(seal['schema'] == 'hepta.stem.prediction-seal.v1' and
                 seal['seal_id'] == _digest({k:v for k,v in seal.items() if k!='seal_id'}) and
                 manifest['terminals'][arm] == {'id': seal['seal_id'], 'kind': 'completed'} and
                 set(seal['files']) == {'execution.json', 'predictions.json', 'bank.safetensors'} and
                 all(_sha(raw[ROOT+prefix+name]) == expected for name,expected in seal['files'].items()),
                 'invalid per-arm artifact seal')
        _require(ex['schema'] == 'hepta.public-cell-learning-arm.v1' and ex['arm'] == arm and
                 ex['input_id'] == plan['input_id'] and ex['plan_id'] == plan['plan_id'] and
                 ex['shared_encoder_sha256'] == manifest['shared_encoder_sha256'] and
                 ex['heldout_labels_loaded'] is False and ex['production_authorized'] is False,
                 'wrong per-arm source or authority')
        wt = _safetensors_recount(raw[ROOT+prefix+'bank.safetensors'])
        inv = ex['inventory']
        _require(wt['parameter_count'] == inv['parameters'] == inv['trainable_parameters'] == 395776 and
                 wt['tensor_payload_bytes'] == inv['unique_weight_bytes'] and
                 wt['actual_trained_state_sha256'] == ex['trained_sha256'] and
                 ex['trained_sha256'] != ex['initial_sha256'] and
                 inv['cells'] == 16 and inv['active_cells_cap'] == plan['arms'][arm] and
                 ex['training']['steps'] == 64, 'physically learned weights not matched')
        if first_init is None:
            first_init = ex['initial_sha256']
        _require(ex['initial_sha256'] == first_init and scores['scores'][arm]['execution'] == ex,
                 'unmatched initialization or reviewed execution')
        _require(type(predictions) is list and len(predictions) == 32 and
                 [r['id'] for r in predictions] == selection['selected_ids']['heldout'],
                 'mismatched heldout prediction identities')
        for row in predictions:
            _require(set(row) == {'id', 'before_logits', 'after_logits'} and
                     all(type(v) is list and len(v) == 4 and
                         all(type(x) in (int,float) and math.isfinite(x) for x in v)
                         for v in (row['before_logits'],row['after_logits'])),
                     'invalid actual model prediction')
        observed = scores['scores'][arm]
        _require(observed['status']=='completed' and
                 observed['before']['count']==32 and observed['after']['count']==32 and
                 type(observed['after']['accuracy']) in (int,float) and
                 observed['after']['accuracy']*32 in range(33), 'bad original reported accuracy')
        per_arm[arm] = {'physical_model_parameters':wt['parameter_count'],
                        'physical_model_tensor_count':wt['tensor_count'],
                        'trained_state_sha256_recomputed':wt['actual_trained_state_sha256'],
                        'observed_train_cpu_ns':ex['work_observation']['cpu_ns'],
                        'original_reported_held_accuracy':observed['after']['accuracy'],
                        'reported_accuracy_independently_recomputed':False}
    return {'schema':'hepta.hdcf.original-modernbert-archive-audit.v1',
            'archive_sha256':_sha(archive),'archive_id':11877613315,
            'model_snapshot_sha256':EXPECTED_MODEL_SNAPSHOT,
            'publisher_model_signature_verified':False,
            'original_experiment_physical_tensors_reverified':True,
            'source_label_bytes_present_in_archive':False,
            'independent_task_score_verified':False,
            'future_source_independence_verified':False,
            'encoder_outputs_exported_for_hdcf':False,
            'model_promotion_authorized':False,'native_effect_authorized':False,
            'arms':per_arm}


def audit_file(path: str):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise Denied('untrusted archive source')
    return audit_bytes(path.read_bytes())


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    a = ap.parse_args()
    print(json.dumps(audit_file(a.zip),sort_keys=True,separators=(',',':')))

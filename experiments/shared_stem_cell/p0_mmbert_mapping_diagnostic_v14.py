#!/usr/bin/env python3
"""Read-only identity diagnostic for the exact original mmBERT-small MLM snapshot.

Never emits model tensors, tokens, labels or a model-acceptance claim. It does not
change or retry original four-model research decisions. A successful diagnostic
only identifies why the strict original checkpoint loader refused the source.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

SCHEMA = 'hepta.p0.mmbert-serialized-key-mapping-observation.v14'
REPO = 'jhu-clsp/mmBERT-small'
REVISION = '0eb3d056ec1d6333cf4e19b0966dfde342a41a3a'
ALIAS = frozenset(('decoder.weight', 'model.embeddings.tok_embeddings.weight'))
SAFE_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.]*\Z')


class Invalid(ValueError):
    pass


def names(value):
    """Bounded tensor *names* only, never tensor values or source paths."""
    if type(value) not in (tuple, list, set, frozenset) or len(value) > 8192:
        raise Invalid('unbounded or invalid model tensor-name inventory')
    result = set()
    for item in value:
        if type(item) is not str or len(item) > 160 or SAFE_NAME.fullmatch(item) is None:
            raise Invalid('unsafe tensor-name inventory')
        if item in result:
            raise Invalid('duplicate tensor name')
        result.add(item)
    return result


def inspect_key_mapping(info, runtime_names, checkpoint_names, *, revision=REVISION):
    """Bounded names-only observation; never a source or model qualification."""
    if revision != REVISION or type(info) is not dict:
        raise Invalid('changed original revision or loading report')
    state = names(runtime_names)
    source = names(checkpoint_names)
    if not state or not source:
        raise Invalid('empty real model/source tensor inventory')
    result = {}
    for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys'):
        original = info.get(k, ())
        if k == 'mismatched_keys' and type(original) in (list, tuple):
            # HF may publish (name, actual_shape, expected_shape) tuples.
            original = [entry[0] if type(entry) in (tuple, list) and len(entry)==3
                        else entry for entry in original]
        result[k] = names(original)
    if result['missing_keys'] & result['unexpected_keys']:
        raise Invalid('contradictory model loading inventory')
    missing_nontied = result['missing_keys'] - ALIAS
    unmapped_state = state - source
    unmapped_source = source - state
    return {
        'schema': SCHEMA, 'original_model_repository': REPO,
        'original_full_revision': REVISION,
        'missing_loader_keys': sorted(result['missing_keys']),
        'non_tied_missing_loader_keys': sorted(missing_nontied),
        'unexpected_loader_keys': sorted(result['unexpected_keys']),
        'mismatched_loader_keys': sorted(result['mismatched_keys']),
        'runtime_only_state_keys': sorted(unmapped_state),
        'source_only_saved_keys': sorted(unmapped_source),
        'runtime_tensor_name_count': len(state),
        'source_tensor_name_count': len(source),
        'non_tied_missing_count': len(missing_nontied),
        'strict_loader_would_refuse_non_tied_missing': bool(missing_nontied),
        'diagnostic_only': True,
        'actual_original_weights_compared_by_this_diagnostic': False,
        'independent_publisher_or_hardware_attestation': False,
        'real_source_task_efficacy_proved': False,
        'production_accepted': False,
        'authority': 'DENY_ALL',
    }


def write_create_only(path, value):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError('refuse overwrite of source diagnosis')
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > 1_000_000:
        raise Invalid('unsafe diagnostics size')
    with path.open('xb') as fd:
        fd.write(raw)
        fd.flush()
        os.fsync(fd.fileno())


def observe_exact_original_snapshot(output):
    """Hosted opt-in; checkpoint acquisition is already a separate pinned gate."""
    from huggingface_hub import hf_hub_download
    from safetensors import safe_open
    from transformers import AutoModelForMaskedLM
    opts = {'revision': REVISION, 'local_files_only': True,
            'trust_remote_code': False, 'use_safetensors': True,
            'output_loading_info': True}
    loaded = AutoModelForMaskedLM.from_pretrained(REPO, **opts)
    if type(loaded) is not tuple or len(loaded) != 2:
        raise Invalid('original loading-info contract unavailable')
    model, info = loaded
    original = hf_hub_download(repo_id=REPO, filename='model.safetensors',
                               revision=REVISION, local_files_only=True)
    with safe_open(original, framework='pt', device='cpu') as f:
        source_names = list(f.keys())
    report = inspect_key_mapping(info, list(model.state_dict().keys()), source_names)
    write_create_only(output, report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    # The diagnostic failure is recorded separately; original admission still
    # must pass all untouched physical loader/model/label gates.
    try:
        result = observe_exact_original_snapshot(args.output)
    except Exception as e:
        result = {'schema': SCHEMA, 'original_full_revision': REVISION,
                  'diagnostic_status': 'unavailable', 'exception_class': type(e).__name__,
                  'diagnostic_only': True, 'production_accepted': False,
                  'authority': 'DENY_ALL'}
        write_create_only(args.output, result)
    print(json.dumps({'schema': SCHEMA, 'status': result.get('diagnostic_status','observed'),
                      'non_tied_missing_count': result.get('non_tied_missing_count'),
                      'production_accepted': False}, sort_keys=True))


if __name__ == '__main__':
    main()

"""Fail-closed checkpoint-load report for original pinned mmBERT MLM.

Loading metadata does not establish pretrained identity. Every permitted tied
alias MUST subsequently pass the existing full physical tensor comparison.
Research-only; no model-selection or FinalUse authority.
"""
from __future__ import annotations

import re

TIED_ALIASES = frozenset({
    'decoder.weight',
    'model.embeddings.tok_embeddings.weight',
})
SAFE_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.]*\Z')
# Transformers loading metadata can expose ordinary sequences or native set
# collections. These four exact built-ins are finite, bounded, and iterable;
# accepting one as an input is NOT evidence that a pretrained weight loaded.
NAME_COLLECTIONS = (list, tuple, set, frozenset)

class Invalid(ValueError):
    pass


def _names(value, label):
    if type(value) not in NAME_COLLECTIONS or len(value) > 8192:
        raise Invalid(f'invalid {label} collection')
    names = []
    for item in value:
        if type(item) is not str or len(item) > 160 or not SAFE_NAME.fullmatch(item):
            raise Invalid(f'invalid {label} tensor name')
        names.append(item)
    if len(set(names)) != len(names):
        raise Invalid(f'duplicate {label} tensor name')
    return frozenset(names)


def require_alias_only_loading_report(info):
    """Accept absent/one/both tied aliases; never a non-tied missing tensor.

    This does NOT admit pretrained weights. The caller must independently:
     - enforce exact original revision and safetensors-only material;
     - prove the decoder and token embedding physically share storage;
     - compare every serialized tensor against the pinned source bytes.
    """
    if type(info) is not dict:
        raise Invalid('missing original model loading-info object')
    if set(info) - {'missing_keys', 'unexpected_keys', 'mismatched_keys',
                    'error_msgs'}:
        # Other upstream versions may add fields; fail closed rather than ignore
        # a potentially meaningful new loading-status field.
        raise Invalid('unknown pretrained model loading-report fields')
    unexpected = _names(info.get('unexpected_keys', []), 'unexpected')
    missing = _names(info.get('missing_keys', []), 'missing')
    mismatched = info.get('mismatched_keys', [])
    errors = info.get('error_msgs', [])
    # Unexpected/mismatched/error entries are ALWAYS DENIED regardless of
    # which supported collection holds them. Do not silently coerce None,
    # strings or dictionaries into an empty successful report.
    if (type(mismatched) not in NAME_COLLECTIONS or len(mismatched) > 8192 or
        type(errors) not in NAME_COLLECTIONS or len(errors) > 8192 or
        mismatched or errors or unexpected):
        raise Invalid('unverified or mismatched pretrained parameter')
    if not missing.issubset(TIED_ALIASES):
        raise Invalid('non-tied pretrained MLM parameter initialized randomly')
    return {
        'schema': 'hepta.p0.mmbert-alias-only-loading-contract.v15',
        'missing_tied_aliases': sorted(missing),
        'needs_full_tensor_comparison': True,
        'actual_pretrained_tensor_bytes_verified': False,
        'model_selected': False,
        'production_accepted': False,
        'authority': 'DENY_ALL',
    }

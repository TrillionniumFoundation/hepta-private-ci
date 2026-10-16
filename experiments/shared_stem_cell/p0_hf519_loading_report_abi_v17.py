#!/usr/bin/env python3
"""Exact pinned HF 5.19 loading-report ABI probe. NO pretrained model or task.

The real 5.19 LoadStateDictInfo.to_dict() yields three *set* fields and one
*list* field. Report metadata is NEVER a substitute for same-storage tied
embedding and complete original safetensors tensor-by-tensor byte proof.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

SCHEMA = 'hepta.p0.hf519-original-load-report-abi.v17'
PINNED_VERSION = '5.19.0'
UPSTREAM_SOURCE_BLOB = '8d7e71944fa9edc98d94a0601783b3390cd39cde'
REPORT_TYPES = {'missing_keys': set, 'unexpected_keys': set,
                'mismatched_keys': set, 'error_msgs': list}
TIED_ALIASES = ('decoder.weight', 'model.embeddings.tok_embeddings.weight')


class Invalid(ValueError):
    pass


def verify_report_abi(make_info, strict_validator, strict_error):
    """Adversarial ABI check with an injected report constructor.

    Offline tests use a source-shaped STDLIB fixture. Hosted opt-in calls this
    with the ACTUAL pinned transformers.utils.loading_report.LoadStateDictInfo.
    It never calls a model or modifies/loads model weights.
    """
    clean = make_info()
    if type(clean) is not dict or set(clean) != set(REPORT_TYPES):
        raise Invalid('unsupported pinned loading-info report fields')
    for key, typ in REPORT_TYPES.items():
        if type(clean[key]) is not typ or clean[key]:
            raise Invalid('unexpected upstream loading-info collection shape')
    safe = strict_validator(clean)
    if (type(safe) is not dict or safe.get('needs_full_tensor_comparison') is not True or
            safe.get('actual_pretrained_tensor_bytes_verified') is not False or
            safe.get('production_accepted') is not False or safe.get('authority') != 'DENY_ALL' or
            safe.get('missing_tied_aliases') != []):
        raise Invalid('metadata gate falsely claimed weight verification')

    for name in TIED_ALIASES:
        record = strict_validator(make_info(missing_keys={name}))
        if (record.get('missing_tied_aliases') != [name] or
                record.get('needs_full_tensor_comparison') is not True or
                record.get('actual_pretrained_tensor_bytes_verified') is not False or
                record.get('production_accepted') is not False or record.get('authority') != 'DENY_ALL'):
            raise Invalid('tied alias metadata is not provisional')
    both = strict_validator(make_info(missing_keys=set(TIED_ALIASES)))
    if (both.get('missing_tied_aliases') != sorted(TIED_ALIASES) or
            both.get('actual_pretrained_tensor_bytes_verified') is not False or
            both.get('production_accepted') is not False):
        raise Invalid('multiple tied aliases falsely qualified')

    # Every unexpected source tensor, shape mismatch, non-tied missing tensor
    # or loader error must remain a hard exception, including native sets.
    attempted = 0
    for mutation in (
        {'missing_keys': {'random.non_tied.weight'}},
        {'missing_keys': {'decoder.weight', 'random.non_tied.weight'}},
        {'unexpected_keys': {'unexpected.saved.weight'}},
        {'mismatched_keys': {('bad.weight', (2,), (3,))}},
        {'error_msgs': ['failed-original-source-tensor-conversion']},
    ):
        attempted += 1
        try:
            strict_validator(make_info(**mutation))
        except strict_error:
            pass
        else:
            raise Invalid('strict original loader permitted an unsafe tensor state')

    # Upstream's .to_dict() intentionally hides conversion_errors and skipped
    # pipeline keys; this probe does NOT infer they are empty during a load.
    # Only the downstream full-model byte verifier can qualify the weights.
    with_hidden_conversion = make_info(conversion_errors={'private.name': 'not exported'})
    if with_hidden_conversion != clean:
        raise Invalid('upstream loading-info dictionary contract changed')
    return {
        'schema': SCHEMA, 'installed_transformers_required_version': PINNED_VERSION,
        'upstream_source_git_blob_reference': UPSTREAM_SOURCE_BLOB,
        'observed_report_collection_kinds': {k: typ.__name__ for k, typ in REPORT_TYPES.items()},
        'strict_denial_cases_tested': attempted,
        'conversion_error_field_exported_by_loading_dict': False,
        'source_report_abi_qualified_only': True,
        'actual_model_weights_loaded_by_this_probe': False,
        'complete_original_tensor_byte_comparison_by_this_probe': False,
        'original_human_label_accessed': False,
        'independent_publisher_signature_verified': False,
        'runtime_package_wheel_independently_authenticated': False,
        'full_four_stem_efficacy_proven': False,
        'model_selected': False,
        'production_accepted': False,
        'authority': 'DENY_ALL',
    }


def write_new(path, payload):
    target = Path(path)
    if target.is_symlink() or target.exists():
        raise FileExistsError('original ABI source evidence must be create-only')
    raw = (json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(raw) > 4096:
        raise Invalid('unexpectedly large public loading ABI evidence')
    with target.open('xb') as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    try:
        import transformers
        if transformers.__version__ != PINNED_VERSION:
            raise Invalid('different upstream loading ABI version')
        from transformers.utils.loading_report import LoadStateDictInfo
        from p0_mmbert_tied_load_contract_v15 import (
            Invalid as ContractInvalid, require_alias_only_loading_report)

        def make_info(*, missing_keys=(), unexpected_keys=(), mismatched_keys=(),
                      error_msgs=(), conversion_errors=None):
            # REAL installed upstream class, not a local imitation. No model or
            # private artifact is materialized by this constructor.
            report = LoadStateDictInfo(
                missing_keys=set(missing_keys), unexpected_keys=set(unexpected_keys),
                mismatched_keys=set(mismatched_keys), error_msgs=list(error_msgs),
                conversion_errors={} if conversion_errors is None else dict(conversion_errors),
                skipped_pp_keys=set(),
            )
            return report.to_dict()

        receipt = verify_report_abi(make_info, require_alias_only_loading_report,
                                    ContractInvalid)
        write_new(args.output, receipt)
        print(json.dumps({'schema':SCHEMA, 'status':'abi-observed-not-model-qualified',
                          'authority':'DENY_ALL'}, sort_keys=True))
    except Exception as exc:
        # Never expose original model paths, tensor names, exception messages,
        # human labels or network IDs. A failure always terminates this job.
        if not args.output.exists() and not args.output.is_symlink():
            write_new(args.output, {'schema':SCHEMA, 'status':'abi-unqualified',
                                   'failure_class_only':type(exc).__name__,
                                   'production_accepted':False, 'authority':'DENY_ALL'})
        print(json.dumps({'schema':SCHEMA, 'status':'abi-unqualified',
                          'failure_class_only':type(exc).__name__,
                          'authority':'DENY_ALL'}, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()

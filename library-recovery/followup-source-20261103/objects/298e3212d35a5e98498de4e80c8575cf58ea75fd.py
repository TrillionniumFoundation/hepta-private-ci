#!/usr/bin/env python3
"""Read-only STAGE census for strict original mmBERT CPU loading failures.

Source/revision/weight verification is *never* bypassed. No original task
labels, checkpoint tensors, model prediction values or private stack traces
are included in the finite output. Every failure is nonzero / DENY_ALL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = 'hepta.p0.mmbert-original-stage-census.v16'
REPO = 'jhu-clsp/mmBERT-small'
REVISION = '0eb3d056ec1d6333cf4e19b0966dfde342a41a3a'
STAGES = ('pinned_source_preflight', 'runtime_checkout_and_imports',
          'original_mlm_load',
          'strict_alias_loading_report', 'stock_architecture',
          'physical_tied_storage', 'original_tied_table_bytes',
          'all_serialized_tensor_bytes', 'original_frozen_cpu_forward')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')


class Invalid(ValueError):
    pass


def strict_pairs(pairs):
    out = {}
    for name, value in pairs:
        if name in out:
            raise Invalid('duplicate source or receipt JSON key')
        out[name] = value
    return out


def read_preflight(path: Path) -> tuple[dict, str]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise Invalid('missing or symlinked pinned source preflight')
    meta = path.stat()
    if not stat.S_ISREG(meta.st_mode) or not 10 < meta.st_size < 65536:
        raise Invalid('unsafe original source preflight byte size')
    raw = path.read_bytes()
    result = json.loads(raw, object_pairs_hook=strict_pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(Invalid('invalid preflight number')))
    mm = result.get('models', {}).get('mmbert_small') if type(result) is dict else None
    if (type(mm) is not dict or
            result.get('schema') != 'hepta.p0.independent-model-preflight-observations.v9' or
            result.get('requested_models') != ['mmbert_small'] or
            result.get('scoped_single_candidate') is not True or
            result.get('whole_four_model_success') is not False or
            result.get('human_labels_accessed') is not False or
            result.get('production_promotion_permitted') is not False or
            result.get('authority') != 'DENY_ALL' or
            mm.get('status') != 'source_materialized_not_model_qualified' or
            mm.get('snapshot_source') != 'original_hub_revision' or
            mm.get('source_revision') != REVISION or
            type(mm.get('publisher_lfs_files_checked')) is not int or
            mm['publisher_lfs_files_checked'] < 2 or
            mm.get('complete_model_parameter_loading_verified_by_this_preflight') is not False):
        raise Invalid('the original strict source SHA/LFS check did not qualify')
    return result, hashlib.sha256(raw).hexdigest()


class StageLedger:
    """Fixed progression with explicit, non-authorizing failure stages."""

    def __init__(self, source_head: str, run_id: int, arm: str):
        if (type(source_head) is not str or HEX40.fullmatch(source_head) is None or
                type(run_id) is not int or run_id <= 0 or
                arm not in ('source', 'merge')):
            raise Invalid('unregistered source HEAD/run/candidate')
        self.source_head = source_head
        self.run_id = run_id
        self.arm = arm
        self.completed: list[str] = []
        self.failed: str | None = None
        self.error_class: str | None = None
        self.preflight_sha: str | None = None

    def perform(self, stage: str, callable_fn):
        if (self.failed is not None or len(self.completed) >= len(STAGES) or
                stage != STAGES[len(self.completed)]):
            raise Invalid('out-of-order or resumed stage execution')
        try:
            result = callable_fn()
        except Exception as exc:
            self.failed = stage
            cls = type(exc).__name__
            self.error_class = cls if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', cls) else 'Exception'
            raise
        self.completed.append(stage)
        return result

    def receipt(self) -> dict:
        outcome = ('all_stages_passed' if self.failed is None and
                   self.completed == list(STAGES) else
                   'stage_failed' if self.failed is not None else 'incomplete')
        return {'schema': SCHEMA, 'model': 'mmbert_small',
                'model_repository': REPO, 'original_immutable_revision': REVISION,
                'exact_source_head': self.source_head, 'github_run_id': self.run_id,
                'candidate': self.arm, 'preflight_bytes_sha256': self.preflight_sha,
                'ordered_completed_stages': list(self.completed),
                'first_failed_stage': self.failed, 'exception_class_only': self.error_class,
                'outcome': outcome, 'source_stage_census_only': True,
                'original_human_labels_read': False, 'model_weights_exported': False,
                'physical_source_signer_independently_verified': False,
                'full_four_stem_original_human_efficacy_verified': False,
                'production_promotion_permitted': False, 'authority': 'DENY_ALL'}


def write_create_only(path: Path, value: dict) -> None:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError('strict diagnostic receipt is create-only')
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > 16 * 1024:
        raise Invalid('unbounded public stage receipt')
    with path.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


def execute_real(ledger: StageLedger, preflight: Path, compact_checkout: Path) -> dict:
    # Verify original SHA/LFS source BEFORE costly native model imports.
    _, proof_digest = ledger.perform('pinned_source_preflight', lambda: read_preflight(preflight))
    ledger.preflight_sha = proof_digest
    # Stage external/native checkout and runtime imports explicitly.  The
    # original code imported these BETWEEN ledger.perform calls, so missing
    # packages/source appeared as an original_mlm_load failure even though
    # from_pretrained had never been attempted.
    def load_runtime():
        import sys
        checkout = Path(compact_checkout)
        root = checkout / 'qualification/neuron-stem'
        if checkout.is_symlink() or root.is_symlink() or not root.is_dir():
            raise Invalid('original pinned compact source checkout absent')
        sys.path.insert(0, str(root))
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import AutoModelForMaskedLM, AutoTokenizer
        from e1_mmbert_tied_loader import (FrozenMMBert, verify_tied_pretrained_table,
                                          verify_complete_pretrained_state)
        from multimodal_exact_tied_alias_v11 import same_physical_view
        from p0_mmbert_tied_load_contract_v15 import require_alias_only_loading_report
        return (torch, hf_hub_download, AutoModelForMaskedLM, AutoTokenizer,
                FrozenMMBert, verify_tied_pretrained_table,
                verify_complete_pretrained_state, same_physical_view,
                require_alias_only_loading_report)

    (torch, hf_hub_download, AutoModelForMaskedLM, AutoTokenizer,
     FrozenMMBert, verify_tied_pretrained_table, verify_complete_pretrained_state,
     same_physical_view, require_alias_only_loading_report) = ledger.perform(
        'runtime_checkout_and_imports', load_runtime)

    def load_original():
        opts = dict(revision=REVISION, local_files_only=True, trust_remote_code=False)
        tokenizer = AutoTokenizer.from_pretrained(REPO, **opts)
        loaded = AutoModelForMaskedLM.from_pretrained(
            REPO, use_safetensors=True, output_loading_info=True, **opts)
        if (type(loaded) is not tuple or len(loaded) != 2 or
                type(loaded[1]) is not dict):
            raise Invalid('full original MLM loading-info report unavailable')
        return tokenizer, loaded[0], loaded[1]

    _, mlm, info = ledger.perform('original_mlm_load', load_original)
    ledger.perform('strict_alias_loading_report', lambda: require_alias_only_loading_report(info))

    def architecture():
        if (type(mlm).__name__ != 'ModernBertForMaskedLM' or
                getattr(mlm.config, 'hidden_size', None) != 384 or
                getattr(mlm.config, 'tie_word_embeddings', None) is not True):
            raise Invalid('wrong original physical stock model architecture')
        return True

    ledger.perform('stock_architecture', architecture)

    def check_physical_alias():
        mlm.to('cpu').eval()
        body = getattr(mlm, 'model', None)
        embedding = getattr(getattr(body, 'embeddings', None), 'tok_embeddings', None)
        decoder = getattr(mlm, 'decoder', None)
        if (embedding is None or decoder is None or
                not same_physical_view(embedding.weight, decoder.weight) or
                len(embedding.weight.shape) != 2 or embedding.weight.shape[1] != 384):
            raise Invalid('original embedding/decoder are not physically tied')
        return True

    ledger.perform('physical_tied_storage', check_physical_alias)
    # A missing pinned safetensors file belongs to the original tied-table
    # stage, NOT the following all-serialized tensor-verification stage.
    def original_tied_table():
        weights = hf_hub_download(repo_id=REPO, filename='model.safetensors',
                                  revision=REVISION, local_files_only=True)
        verify_tied_pretrained_table(torch, mlm, weights)
        return weights

    weights = ledger.perform('original_tied_table_bytes', original_tied_table)
    ledger.perform('all_serialized_tensor_bytes', lambda: verify_complete_pretrained_state(torch, mlm, weights))
    # Re-enter the EXACT original research loader. Any cleanup/import problem
    # is part of the cold re-entry/forward stage, never an untracked gap.
    def original_forward():
        # Release the first fully-verified original MLM before the second
        # cold loader call: stage attribution must NOT duplicate resident
        # foundation model weights or change the original peak-RSS behavior.
        nonlocal mlm
        mlm = None
        import gc
        gc.collect()
        f = FrozenMMBert(REVISION, device='cpu', max_tokens=512)
        row = {'state':'Fixed public pretrained-source probe, no task label.',
               'question':'Does the strict frozen Encoder execute one physical CPU forward?',
               'options':['probe_only', 'no_effects']}
        feature, digest, metadata = f.encode(row, allow_truncation=False)
        vec = feature.detach().cpu().reshape(-1)
        if (tuple(vec.shape) != (384,) or not bool(torch.isfinite(vec).all()) or
                type(metadata.get('original_tokens')) is not int or
                not 1 <= metadata['original_tokens'] <= 512 or
                not isinstance(digest, (dict, str))):
            raise Invalid('actual original frozen CPU forward not verified')
        return True

    ledger.perform('original_frozen_cpu_forward', original_forward)
    return ledger.receipt()


def mark_external_failure(ledger: StageLedger, error: Exception) -> None:
    """Preserve untracked failure without falsely blaming a model verifier."""
    if ledger.failed is not None:
        raise Invalid('cannot overwrite a stage failure')
    ledger.failed = 'external_setup'
    cls = type(error).__name__
    ledger.error_class = cls if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', cls) else 'Exception'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preflight', type=Path, required=True)
    p.add_argument('--compact-checkout', type=Path, required=True)
    p.add_argument('--source-head', required=True)
    p.add_argument('--run-id', required=True, type=int)
    p.add_argument('--candidate', required=True, choices=('source','merge'))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    ledger = StageLedger(a.source_head, a.run_id, a.candidate)
    failed = False
    try:
        execute_real(ledger, a.preflight, a.compact_checkout)
    except Exception as err:
        # A failure OUTSIDE a tracked perform call must not be fabricated
        # as failure of the next model gate. Record a separate non-authorizing
        # external_setup stage and bounded exception *class* only.
        failed = True
        if ledger.failed is None:
            mark_external_failure(ledger, err)
    write_create_only(a.output, ledger.receipt())
    print(json.dumps({'schema': SCHEMA, 'outcome': ledger.receipt()['outcome'],
                      'last_completed_stage': ledger.completed[-1] if ledger.completed else None,
                      'first_failed_stage': ledger.failed,
                      'error_class_only': ledger.error_class,
                      'production_promotion_permitted': False, 'authority': 'DENY_ALL'}, sort_keys=True))
    if failed or ledger.receipt()['outcome'] != 'all_stages_passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

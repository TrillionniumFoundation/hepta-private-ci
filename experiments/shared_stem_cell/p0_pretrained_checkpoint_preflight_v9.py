#!/usr/bin/env python3
"""Isolation of REAL pretrained compact-checkpoint acquisition (P0 research).

Do not let one pinned model's download/source-integrity failure suppress a
separate model's otherwise valid physical run. A failed arm writes a durable,
explicit .failed.txt slot. The original four-model job MUST still fail overall;
partial success is advisory only and never grants selection or FinalUse.

This program has no synthetic-weight fallback, no target labels or side-effect
rights. Verification here is local source-byte consistency, not independent
publisher signing. The native model loader remains separately responsible for
its own complete pretrained tensor checks (especially mmBERT tied MLM).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CANDIDATES = {
    'granite_97m_r2': (
        'ibm-granite/granite-embedding-97m-multilingual-r2',
        '835ad14087e140460703cf0fae09f97d469d65c2'),
    'mmbert_small': (
        'jhu-clsp/mmBERT-small',
        '0eb3d056ec1d6333cf4e19b0966dfde342a41a3a'),
}
SCHEMA = 'hepta.p0.independent-model-preflight-observations.v9'
ALLOW = ('*.json', '*.safetensors', '*.txt', '*.model')
REQUIRED = {'model.safetensors', 'tokenizer.json', 'config.json'}
DENIED_SUFFIXES = ('.bin', '.pkl', '.pickle', '.pt', '.py', '.so')


class Invalid(ValueError):
    pass


def verify_snapshot(repo, revision, *, model_info, download):
    """Check actual immutable remote revision, native files, and LFS bytes."""
    info = model_info(repo_id=repo, revision=revision, files_metadata=True)
    if getattr(info, 'sha', None) != revision:
        raise Invalid('immutable upstream model revision differs from registered SHA')
    source = Path(download(repo_id=repo, revision=revision, allow_patterns=list(ALLOW)))
    if not source.is_dir():
        raise Invalid('no materialized snapshot')
    found = {p.relative_to(source).as_posix(): p for p in source.rglob('*') if p.is_file()}
    if not REQUIRED.issubset(found) or any(k.endswith(DENIED_SUFFIXES) for k in found):
        raise Invalid('incomplete native safe model files or unsafe serialized fallback')
    siblings = getattr(info, 'siblings', None)
    if not isinstance(siblings, (tuple, list)) or not siblings:
        raise Invalid('missing publisher file inventory')
    checked = 0
    for item in siblings:
        name = getattr(item, 'rfilename', None)
        if type(name) is not str:
            raise Invalid('malformed source inventory')
        if name not in found:
            continue
        lfs = getattr(item, 'lfs', None)
        expected = lfs.get('sha256') if isinstance(lfs, dict) else getattr(lfs, 'sha256', None)
        if expected is None:
            continue
        if (type(expected) is not str or len(expected) != 64
                or any(c not in '0123456789abcdef' for c in expected)):
            raise Invalid('invalid model source LFS checksum')
        actual = hashlib.sha256(found[name].read_bytes()).hexdigest()
        if actual != expected:
            raise Invalid('local native file differs from publisher LFS checksum')
        checked += 1
    return {'snapshot_source':'original_hub_revision', 'source_revision':revision,
            'materialized_safe_files':len(found),'publisher_lfs_files_checked':checked,
            'complete_model_parameter_loading_verified_by_this_preflight':False}


def preflight(root, *, model_info, download):
    """Try BOTH registered models even when one fails; never report acceptance."""
    root = Path(root)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise Invalid('untrusted artifact output directory')
    root.mkdir(parents=True, exist_ok=True)
    observations = {}
    for model,(repo,revision) in CANDIDATES.items():
        failure = root / (model + '.failed.txt')
        existing_success = root / (model + '.json')
        if failure.exists() or failure.is_symlink() or existing_success.exists():
            raise Invalid('refuse a preexisting model result or failure slot')
        try:
            receipt = verify_snapshot(repo, revision, model_info=model_info, download=download)
        except Exception as err:
            # Only a sanitized failure CLASS is published; upstream exceptions
            # can contain URLs or sensitive token/host diagnostics.
            with failure.open('x', encoding='utf-8') as stream:
                stream.write(f'{model} pinned native checkpoint preflight FAILED: {type(err).__name__}\n')
            observations[model] = {'status':'unavailable','preflight_failure_class':type(err).__name__,
                                   'source_revision':revision}
        else:
            observations[model] = {'status':'source_materialized_not_model_qualified', **receipt}
    result = {'schema':SCHEMA,'models':observations,
              'all_compact_source_preflight_completed':all(
                  x['status']=='source_materialized_not_model_qualified' for x in observations.values()),
              'whole_four_model_success':False,'human_labels_accessed':False,
              'original_checkpoint_publisher_independently_authenticated':False,
              'model_selected':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}
    receipt_path = root / 'compact-preflight-v9.json'
    with receipt_path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')
    # Overall CI completeness is deliberately adjudicated by the original
    # all-four-model step, not this observational acquisition boundary.
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True, type=Path)
    args=parser.parse_args()
    from huggingface_hub import HfApi, snapshot_download
    result=preflight(args.output_root, model_info=HfApi().model_info, download=snapshot_download)
    print(json.dumps({'schema':SCHEMA,'model_statuses':{
        k:v['status'] for k,v in result['models'].items()},
        'production_promotion_permitted':False,'authority':'DENY_ALL'}, sort_keys=True))


if __name__ == '__main__':
    main()

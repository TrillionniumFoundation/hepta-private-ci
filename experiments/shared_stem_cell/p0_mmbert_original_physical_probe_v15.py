"""Original SHA-pinned mmBERT physical CPU proof; no task scoring or FinalUse.

Requires the same existing strict mmBERT loader used in P0, a complete
serialized-tensor byte comparison, physically tied table and one actual CPU
feature forward. All input text is a fixed public non-task probe. This does
not establish any future-source or pretrained Reader task quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

REVISION = '0eb3d056ec1d6333cf4e19b0966dfde342a41a3a'
SCHEMA = 'hepta.p0.mmbert-strict-physical-forward.v15'
HEX = re.compile(r'[0-9a-f]{64}\Z')

class Invalid(ValueError):
    pass


def checked_observation(backend, *, original_preflight=True):
    """Shape/lineage checks on proof, not a substitute for the actual loader."""
    if original_preflight is not True:
        raise Invalid('original SHA-pinned LFS preflight not established')
    table = getattr(backend, 'pretrained_weight_receipt', None)
    complete = getattr(backend, 'complete_weight_receipt', None)
    if type(table) is not dict or type(complete) is not dict:
        raise Invalid('missing independently byte-matched pretrained receipts')
    if (table.get('actual_local_full_tied_embedding_checkpoint_verified') is not True or
        complete.get('all_serialized_pretrained_tensor_bytes_verified') is not True or
        complete.get('source_tensor_count') != 137):
        raise Invalid('non-complete original pretrained tensor proof')
    t=table.get('complete_table_sha256')
    c=complete.get('whole_pretrained_state_sha256')
    if type(t) is not str or not HEX.fullmatch(t) or type(c) is not str or not HEX.fullmatch(c):
        raise Invalid('unverifiable original pretrained digest')
    if table.get('authority')!='DENY_ALL' or complete.get('authority')!='DENY_ALL':
        raise Invalid('unauthorized pretrained loader report')
    return {'source_tensor_count':137,'tied_token_table_sha256':t,
            'whole_original_serialized_pretrained_sha256':c}


def run_original(*, compact_dir, output):
    import sys
    import torch
    root = Path(compact_dir)
    if root.is_symlink() or not root.is_dir():
        raise Invalid('missing strict pinned compact source checkout')
    q = root/'qualification/neuron-stem'
    if q.is_symlink() or not q.is_dir():
        raise Invalid('missing reviewed original source functions')
    sys.path.insert(0,str(q))
    from e1_mmbert_tied_loader import FrozenMMBert
    frozen = FrozenMMBert(REVISION, device='cpu', max_tokens=512)
    proof=checked_observation(frozen)
    row={
       'state':'Original fixed pretrained mmBERT parameter-integrity probe. No evaluation label.',
       'question':'Can the exact checkpoint execute a frozen CPU encoder forward?',
       'options':['probe only','no user task'],
    }
    feature, digest, metadata = frozen.encode(row, allow_truncation=False)
    values=feature.detach().cpu().reshape(-1)
    if values.shape != (384,) or not bool(torch.isfinite(values).all()):
        raise Invalid('actual CPU Encoder did not return a finite 384D feature')
    if type(metadata.get('original_tokens')) is not int or not 1<=metadata['original_tokens']<=512:
        raise Invalid('unverified original tokenizer or truncated probe')
    feature_digest=hashlib.sha256(values.contiguous().numpy().tobytes()).hexdigest()
    result={
        'schema':SCHEMA, 'model_repository':'jhu-clsp/mmBERT-small',
        'original_immutable_revision':REVISION,
        **proof,
        'strict_frozen_cpu_encoder_forward_executed':True,
        'original_encoder_output_feature_width':384,
        'original_input_token_count':metadata['original_tokens'],
        'original_frozen_feature_q24_sha256':feature_digest,
        'task_outcome_verified':False,
        'future_source_benefit_verified':False,
        'original_model_publisher_independently_authenticated':False,
        'model_selected':False,'production_accepted':False,'authority':'DENY_ALL',
    }
    target=Path(output)
    if target.exists() or target.is_symlink():
        raise FileExistsError('strict proof create-only')
    with target.open('x', encoding='utf-8') as f:
        f.write(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
        f.flush()
        os.fsync(f.fileno())
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compact-checkout', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args=ap.parse_args()
    try:
        r=run_original(compact_dir=args.compact_checkout,output=args.output)
    except Exception as exc:
        # No source paths, failed checks, model or token values in public logs.
        print(json.dumps({'schema':SCHEMA,'original_checkpoint_qualified':False,
                          'exception_class':type(exc).__name__,
                          'production_accepted':False,'authority':'DENY_ALL'},sort_keys=True))
        raise SystemExit(1) from None
    print(json.dumps({'schema':SCHEMA,'original_checkpoint_qualified':True,
                      'source_tensor_count':r['source_tensor_count'],
                      'task_outcome_verified':False,'production_accepted':False,
                      'authority':'DENY_ALL'},sort_keys=True))


if __name__=='__main__':main()

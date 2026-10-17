"""Read-only source-value census for an already pinned safetensors model.

Every unique loaded *parameter* must be recoverable from the original, immutable
checkpoint by exact FP32 values and shape.  This guards against e.g. HF
`from_pretrained` silently creating an uninitialized embedding.  It does not
assert logical tensor-key identity or issuer authentication, and deliberately
fails closed on architecture transforms that need a separately reviewed mapping.

No labels, network, optimizer, mutation, or effect authority are used.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import time

PROFILE = 'hepta.stem.source-value-coverage-fp32.v5'
MAX_SOURCE_TENSORS = 5000
MAX_RUNTIME_TENSORS = 2500
MAX_SOURCE_ELEMENTS = 1_000_000_000


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def _fingerprint(t):
    """Bind shape and bit-exact FP32 values, not a self-reported name or count."""
    import torch
    need(isinstance(t, torch.Tensor) and t.ndim >= 1 and t.numel() > 0,
         'not a parameter-shaped tensor')
    need(t.dtype in (torch.float16, torch.bfloat16, torch.float32),
         'checkpoint/runtime tensor has unsupported dtype')
    y = t.detach().to(device='cpu', dtype=torch.float32).contiguous()
    need(bool(torch.isfinite(y).all().item()), 'nonfinite original tensor values')
    h = hashlib.sha256()
    h.update(b'hepta.source-fp32-shape-v1\0')
    h.update(struct.pack('<I', y.ndim))
    for dim in y.shape:
        h.update(struct.pack('<Q', dim))
    # Hash via a buffer view rather than converting large tensors to Python lists.
    h.update(memoryview(y.numpy()))
    return (tuple(y.shape), h.hexdigest())


def verify_source_value_coverage(model, source_safetensors: Path, *, expected_sha: str):
    """Fail before inference if a live parameter is absent in the source file.

    Matching source tensor *contents* is stronger than trusting HF's warnings or
    counting loaded parameters; it remains weaker than explicit per-key name
    mapping/issuer signature, which must be separately qualified.
    """
    from safetensors import safe_open
    import torch
    need(type(expected_sha) is str and len(expected_sha) == 64 and
         all(ch in '0123456789abcdef' for ch in expected_sha),
         'unregistered expected material digest')
    path = Path(source_safetensors)
    need(path.is_file() and not path.is_symlink(), 'unsafe original tensor material')
    start = time.perf_counter()
    observed_hash = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            observed_hash.update(chunk)
    need(observed_hash.hexdigest() == expected_sha, 'model material not original SHA')

    # Load source one tensor at a time and store only small shape+digest records;
    # avoid retaining all 740M source parameters in RAM.
    available = Counter()
    source_elements = 0
    source_names = []
    with safe_open(str(path), framework='pt', device='cpu') as archive:
        names = archive.keys()
        need(1 <= len(names) <= MAX_SOURCE_TENSORS, 'unbounded source tensor inventory')
        for name in names:
            need(isinstance(name, str) and name and len(name) <= 512,
                 'invalid source key name')
            t = archive.get_tensor(name)
            source_elements += t.numel()
            need(source_elements <= MAX_SOURCE_ELEMENTS, 'oversized original tensor census')
            # A checkpoint may carry non-trainable integer buffers.  Every
            # loaded trainable parameter, however, must match a floating tensor.
            if t.dtype in (torch.float16, torch.bfloat16, torch.float32):
                available[_fingerprint(t)] += 1
            source_names.append(name)
            del t

    # Named parameters deduplicate physical ties by default.  Reject separate
    # identical initialized parameters unless the original checkpoint contains
    # the corresponding number of values; no fabricated tie waivers.
    live = list(model.named_parameters(remove_duplicate=True))
    need(1 <= len(live) <= MAX_RUNTIME_TENSORS and
         len(set(name for name, _ in live)) == len(live),
         'ambiguous model parameters')
    count = 0
    proof = hashlib.sha256()
    proof.update(b'hepta.stem.model-parameter-census-v5\0')
    proof.update(expected_sha.encode('ascii'))
    for name, param in live:
        need(type(name) is str and 0 < len(name) <= 512 and
             isinstance(param, torch.nn.Parameter) and
             param.dtype is torch.float32,
             'not an FP32 source-backed runtime parameter')
        fp = _fingerprint(param)
        count += param.numel()
        need(available[fp] >= 1,
             'loaded parameter lacks original source tensor values')
        available[fp] -= 1
        # A digest commits to keys + original contents without embedding any
        # actual tensor values in the publicly uploaded signed-no-authority receipt.
        proof.update(name.encode('utf-8') + b'\0')
        proof.update(fp[1].encode('ascii'))
    need(count > 0, 'no original text-model parameters')
    return {
        'profile': PROFILE,
        'original_weight_sha256': expected_sha,
        'runtime_parameter_elements': count,
        'runtime_unique_parameter_tensors': len(live),
        'original_archive_tensor_count': len(source_names),
        'source_tensor_elements_including_unused_modalities': source_elements,
        'source_value_coverage_verified': True,
        'strict_logical_name_mapping_verified': False,
        'model_issuer_signature_verified': False,
        'proof_digest': proof.hexdigest(),
        'audit_wall_seconds_unattested': time.perf_counter() - start,
    }

"""Explicit source boundary and semantic hashes for the FV continuation candidate."""

import hashlib
import json
from pathlib import Path

import torch


SOURCE_FILES = (
    "qualification/hcsn/__init__.py", "qualification/hcsn/reference.py", "qualification/hcsn/population.py",
    "qualification/hcsn_regenerative/__init__.py", "qualification/hcsn_regenerative/process.py",
    "qualification/hcsn_regenerative/tensor.py", "qualification/hcsn_regenerative/tensor_short.py",
    "qualification/hcsn_regenerative/tensor_normal.py", "qualification/hcsn_regenerative/tensor_state.py",
    "qualification/hcsn_regenerative/distribution.py", "qualification/hcsn_regenerative/distribution_kernel.py",
    "qualification/hcsn_regenerative/distribution_operator.py", "qualification/hcsn_regenerative/distribution_manifest.py",
    "qualification/hcsn_regenerative/run_distribution_audit.py",
    "qualification/hcsn_regenerative/run_distribution_recovery.py",
    "qualification/hcsn_regenerative/tests/__init__.py",
    "qualification/hcsn_regenerative/tests/test_distribution.py",
    "qualification/hcsn_regenerative/DISTRIBUTION_PROTOCOL.md",
)


def source_map():
    root = Path(__file__).resolve().parents[2]
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def serial(value):
    """Hash semantic tensor bytes rather than nondeterministic torch ZIP metadata."""
    if isinstance(value, torch.Tensor):
        tensor = value.detach().cpu().contiguous()
        return dict(dtype=str(tensor.dtype), shape=list(tensor.shape),
                    sha256=hashlib.sha256(tensor.numpy().tobytes()).hexdigest())
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(serial(value), sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()

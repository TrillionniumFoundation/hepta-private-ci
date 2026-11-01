"""First-order CPU PyTorch bridge to the immutable R16 H-X FP64 kernel.

Inputs are packed [..., 10] CPU float32 tensors. Internal financial arithmetic
and five outputs are float64. Backward applies the continuous-model Jacobian
at the represented inputs and returns float32; it does not differentiate the
rounding map. Higher derivatives and compiler/accelerator integration are not
supported by this eager NumPy/ctypes bridge.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import torch

FROZEN_PROTOCOL_SHA256 = '76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0'
INPUT_ORDER = ('r', 'delta', 'sigma', 'alpha', 'tax', 'liquidity', 'maturity', 'coupon', 'principal', 'state')
OUTPUT_ORDER = ('boundary', 'equity', 'F', 'G', 'debt')
FEATURE_ORDER = OUTPUT_ORDER+('R', 'x')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FrozenBackend:
    """Hash-bound read-only transport; no source generation or recompilation."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        protocol_path = self.root/'RECOVERY_PROTOCOL_V1.json'
        if digest(protocol_path) != FROZEN_PROTOCOL_SHA256:
            raise ValueError('Wrong frozen financial protocol')
        self.protocol = json.loads(protocol_path.read_text())
        self.files = dict(self.protocol['source_sha256'])
        self.files.update({'RECOVERY_PROTOCOL_V1.json': FROZEN_PROTOCOL_SHA256,
                           'RECOVERED_BUILD.json': self.protocol['build_receipt_sha256'],
                           'RECOVERY_CASES_V1.json': self.protocol['manifest_sha256'],
                           'recovered.so': self.protocol['binary_sha256']})
        self.verify()
        spec = importlib.util.spec_from_file_location('_verified_hx_compiled_transport', self.root/'compiled.py')
        if spec is None or spec.loader is None:
            raise ImportError('Cannot load frozen C API transport')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.kernel = module.Kernel(self.root/'recovered.so')
        self.calls = 0
        self.states = 0
        self.verify()

    def verify(self):
        for name, expected in self.files.items():
            if digest(self.root/name) != expected:
                raise ValueError('Frozen financial dependency changed: '+name)

    def evaluate_numpy(self, packed, coordinate):
        if coordinate not in ('asset', 'log_distance'):
            raise ValueError('coordinate must be asset or log_distance')
        if not isinstance(packed, np.ndarray) or packed.dtype != np.float32:
            raise TypeError('Financial inputs must be represented float32 words')
        if packed.ndim != 2 or packed.shape[1] != 10 or packed.shape[0] == 0:
            raise ValueError('Expected a nonempty N by 10 packed array')
        if not np.all(np.isfinite(packed)):
            raise ValueError('Inputs must be finite')
        state = packed[:, 9]
        if coordinate == 'asset' and np.any(state <= 0):
            raise ValueError('asset requires V > 0, including default states')
        if coordinate == 'log_distance' and np.any(state < 0):
            raise ValueError('log_distance supports x >= 0; x=0 uses continuation-side right derivatives')
        self.calls += 1
        self.states += len(packed)
        values, jacobian, status = self.kernel.batch(packed[:, :9], state, [coordinate]*len(packed), 'float64')
        valid = (status == 0) & np.all(np.isfinite(values), axis=1) & np.all(np.isfinite(jacobian), axis=(1, 2))
        if not np.all(valid):
            raise ArithmeticError('Financial kernel rejected rows '+str(np.flatnonzero(~valid).tolist()))
        return values, jacobian


class _FinancialFunction(torch.autograd.Function):
    @staticmethod
    def forward(ctx, packed, coordinate, backend):
        if packed.device.type != 'cpu' or packed.dtype != torch.float32:
            raise TypeError('HXOperator accepts CPU torch.float32 only; no silent input downcast')
        if packed.ndim < 1 or packed.shape[-1] != 10 or packed.numel() == 0:
            raise ValueError('Expected nonempty packed input [...,10]')
        shape = packed.shape[:-1]
        array = packed.detach().contiguous().reshape(-1, 10).numpy()
        values, jacobian = backend.evaluate_numpy(array, coordinate)
        saved = torch.from_numpy(np.array(jacobian, dtype=np.float64, copy=True)).reshape((*shape, 5, 10))
        ctx.save_for_backward(saved)
        return torch.from_numpy(np.array(values, dtype=np.float64, copy=True)).reshape((*shape, 5))

    @staticmethod
    def backward(ctx, grad_output):
        # Check BEFORE any no_grad wrapper can hide a create_graph request.
        # This also prevents silently incomplete Hessians through readout paths.
        if torch.is_grad_enabled():
            raise RuntimeError('HXOperator supports first-order reverse AD only; create_graph=True is unsupported')
        (jacobian,) = ctx.saved_tensors
        if not bool(torch.isfinite(grad_output).all()):
            raise ArithmeticError('Nonfinite upstream gradient')
        grad_input = torch.einsum('...o,...oi->...i', grad_output.to(torch.float64), jacobian)
        if not bool(torch.isfinite(grad_input).all()):
            raise ArithmeticError('Nonfinite financial VJP')
        represented_gradient = grad_input.to(torch.float32)
        if not bool(torch.isfinite(represented_gradient).all()):
            raise ArithmeticError('Financial VJP exceeds the float32 gradient range')
        return represented_gradient, None, None


class HXOperator(torch.nn.Module):
    """Original five fields, with an optional seven-field observable readout.

    asset: state is positive V. V <= b uses the kernel's default branch:
    E=0, F=G=1 and debt=alpha*b/m, with that branch's parameter derivatives.
    log_distance: state is independent x >= 0. At x=0 the kernel supplies
    the continuation-side right derivative, not a two-sided extension.

    `features` appends R=1-(1-F)^2 and x. R is a new C1 observable under the
    regularity assumptions of the finite-time model; it does not rename F/G
    or make them globally C1. No second-order force/Hessian is supplied.
    """

    def __init__(self, frozen_root, coordinate='asset', backend=None):
        super().__init__()
        if coordinate not in ('asset', 'log_distance'):
            raise ValueError('Unknown state coordinate')
        self.coordinate = coordinate
        if backend is not None and not isinstance(backend, FrozenBackend):
            raise TypeError('Shared backend must be a verified FrozenBackend')
        self.backend = backend if backend is not None else FrozenBackend(frozen_root)
        if self.backend.root != Path(frozen_root).resolve():
            raise ValueError('Backend root mismatch')

    def forward(self, packed):
        return _FinancialFunction.apply(packed, self.coordinate, self.backend)

    def features(self, packed):
        """Seven diagnostic fields; the full vector is NOT globally C1."""
        raw = self(packed)
        risk = 1.-(1.-raw[..., 2]).square()
        margin = torch.log(packed[..., 9].to(torch.float64)/raw[..., 0]) if self.coordinate == 'asset' else packed[..., 9].to(torch.float64)
        return torch.cat((raw, risk.unsqueeze(-1), margin.unsqueeze(-1)), dim=-1)

    def readout(self, packed):
        """Only E/b, R, x: conditional joint-C1 model-observable candidates.

        This does not assert differentiability of floating-point rounding or
        supply a C2 force. The original F/G/debt are not output channels here.
        """
        fields = self.features(packed)
        return torch.stack((fields[..., 1]/fields[..., 0], fields[..., 5], fields[..., 6]), dim=-1)

"""Two-layer continuous-margin cell: time-varying static H-X features.

No time-dependent financial PDE or analytic recurrent flow is claimed. All
financial evaluations reuse immutable V3 and the frozen FP64 C++ kernel.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import torch

ADAPTER_PROTOCOL_SHA256 = '9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72'
ADAPTER_SHA256 = '8117df2cae6b17612d7537b96d72ca74a340bb5356e61bbc3f73b9fe478aa870'
GRADIENT_MODES = ('full', 'drive_only', 'conditioning_only', 'both_detached')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_adapter(root):
    root = Path(root).resolve()
    if sha(root/'ADAPTER_PROTOCOL.json') != ADAPTER_PROTOCOL_SHA256 or sha(root/'hx_autograd.py') != ADAPTER_SHA256:
        raise ValueError('Wrong immutable V3 adapter')
    for name, expected in json.loads((root/'ADAPTER_PROTOCOL.json').read_text())['source_sha256'].items():
        if sha(root/name) != expected:
            raise ValueError('Adapter dependency changed '+name)
    spec = importlib.util.spec_from_file_location('_two_layer_verified_hx_v3', root/'hx_autograd.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def require_word_tensor(value, name):
    if not isinstance(value, torch.Tensor) or value.device.type != 'cpu' or value.dtype != torch.float32:
        raise TypeError(name+' requires CPU FP32; no implicit downcast')
    if value.numel() == 0 or not bool(torch.isfinite(value).all()):
        raise ValueError(name+' must be finite and nonempty')


class BatchedAssetReadout(torch.nn.Module):
    """The V3 Q/R/x readout plus diagnostic raw b, for shared or batched theta.

    Uses V3.features once and selects exactly the same three neural fields as
    V3.readout. F/G/debt remain unused diagnostic internals, not C1 channels.
    """

    def __init__(self, operator):
        super().__init__()
        if operator.coordinate != 'asset':
            raise ValueError('Expected original asset coordinate')
        self.operator = operator

    def forward(self, theta, z):
        require_word_tensor(theta, 'theta'); require_word_tensor(z, 'z')
        if theta.shape == (9,):
            rows = theta.expand((*z.shape, 9))
        elif theta.shape == (*z.shape, 9):
            rows = theta
        else:
            raise ValueError('theta must be [9] or z.shape+[9]')
        asset = torch.exp(z)
        if not bool(torch.isfinite(asset).all() and (asset > 0.).all()):
            raise ValueError('Represented exp(z) must be finite and positive')
        packed = torch.cat((rows, asset.unsqueeze(-1)), dim=-1)
        fields = self.operator.features(packed)
        readout = torch.stack((fields[..., 1]/fields[..., 0], fields[..., 5], fields[..., 6]), dim=-1)
        if not bool(torch.isfinite(readout).all() and torch.isfinite(fields[..., 0]).all()):
            raise ArithmeticError('Nonfinite H-X readout/boundary')
        return {'readout': readout, 'boundary': fields[..., 0], 'represented_asset': asset, 'effective_theta': rows}


class TwoLayerBoundaryCell(torch.nn.Module):
    """Two one-way-coupled (z,a) states and exactly eighteen raw parameters.

    One old-state layer-1 margin drives TWO differentiable links to layer 2:
       u2 = external_u2 + coupling_gain * link
       theta2 = base2*(1+fraction*tanh(raw2+conditioning_gain*link))
    Both links keep their forward values in every diagnostic gradient mode.
    Only edges are detached. There is no feedback from layer 2 to layer 1.
    """

    def __init__(self, readout, base1, base2, config):
        super().__init__()
        for value, name in ((base1, 'base1'), (base2, 'base2')):
            require_word_tensor(value, name)
            if value.shape != (9,):
                raise ValueError('Each base requires nine financial parameters')
        self.readout = readout
        self.register_buffer('base1', base1.clone()); self.register_buffer('base2', base2.clone())
        self.raw_theta1 = torch.nn.Parameter(torch.zeros(9, dtype=torch.float32))
        self.raw_theta2 = torch.nn.Parameter(torch.zeros(9, dtype=torch.float32))
        self.config = dict(config)
        self.register_buffer('z_rest1', torch.tensor(config['z_rest1'], dtype=torch.float32))
        self.register_buffer('z_rest2', torch.tensor(config['z_rest2'], dtype=torch.float32))
        require_word_tensor(self.z_rest1, 'z_rest1'); require_word_tensor(self.z_rest2, 'z_rest2')
        for name in ('dt', 'leak', 'k_equity', 'k_risk', 'tau', 'fraction', 'coupling_gain', 'conditioning_gain'):
            if not 0. < float(config[name]) < float('inf'):
                raise ValueError('Expected positive finite '+name)

    def theta1(self):
        return self.base1*(1.+self.config['fraction']*torch.tanh(self.raw_theta1))

    def layer2_parameters(self, margin_signal):
        preactivation = self.raw_theta2+self.config['conditioning_gain']*margin_signal.unsqueeze(-1)
        tanh_value = torch.tanh(preactivation)
        return self.base2*(1.+self.config['fraction']*tanh_value), preactivation, tanh_value

    def _drift(self, z, a, readout, drive, z_rest):
        q, risk = readout[..., 0].to(torch.float32), readout[..., 1].to(torch.float32)
        return torch.stack((drive-self.config['leak']*(z-z_rest)-self.config['k_equity']*q-self.config['k_risk']*risk+a,
                            (self.config['k_risk']*risk-a)/self.config['tau']), dim=-1)

    def rollout(self, z10, a10, z20, a20, external_u1, external_u2, gradient_mode='full'):
        if gradient_mode not in GRADIENT_MODES:
            raise ValueError('Unknown gradient mode')
        require_word_tensor(self.raw_theta1, 'raw_theta1'); require_word_tensor(self.raw_theta2, 'raw_theta2')
        for value, name in ((z10, 'z10'), (a10, 'a10'), (z20, 'z20'), (a20, 'a20'), (external_u1, 'u1'), (external_u2, 'u2')):
            require_word_tensor(value, name)
        if z10.ndim != 1 or not all(v.shape == z10.shape for v in (a10, z20, a20)):
            raise ValueError('Initial states must share [batch] shape')
        expected_drive_shape = (self.config['steps'], len(z10))
        if external_u1.shape != expected_drive_shape or external_u2.shape != expected_drive_shape:
            raise ValueError('Wrong frozen drive shape')
        tanh1 = torch.tanh(self.raw_theta1)
        theta1 = self.base1*(1.+self.config['fraction']*tanh1)
        z1, a1, z2, a2 = z10, a10, z20, a20
        states = [torch.stack((z1, a1, z2, a2), dim=-1)]
        state_nodes = [(z1, a1, z2, a2)]
        rows1, rows2, links, conditioned_preactivations, conditioned_tanh = [], [], [], [], []
        used_drive2, drifts, theta1_nodes, theta2_nodes = [], [], [], []
        for u1, u2 in zip(external_u1.unbind(0), external_u2.unbind(0)):
            theta1_t = theta1.clone()
            layer1 = self.readout(theta1_t, z1)
            link = layer1['readout'][..., 2].to(torch.float32)
            drive_link = link if gradient_mode in ('full', 'drive_only') else link.detach()
            condition_link = link if gradient_mode in ('full', 'conditioning_only') else link.detach()
            theta2_t, preactivation, tanh_value = self.layer2_parameters(condition_link)
            layer2 = self.readout(theta2_t, z2)
            drive2 = u2+self.config['coupling_gain']*drive_link
            d1 = self._drift(z1, a1, layer1['readout'], u1, self.z_rest1)
            d2 = self._drift(z2, a2, layer2['readout'], drive2, self.z_rest2)
            dt = self.config['dt']
            z1, a1, z2, a2 = z1+dt*d1[..., 0], a1+dt*d1[..., 1], z2+dt*d2[..., 0], a2+dt*d2[..., 1]
            if not all(bool(torch.isfinite(v).all()) for v in (z1, a1, z2, a2)):
                raise ArithmeticError('Nonfinite two-layer Euler state')
            states.append(torch.stack((z1, a1, z2, a2), dim=-1)); state_nodes.append((z1, a1, z2, a2))
            rows1.append(layer1); rows2.append(layer2); links.append(link)
            conditioned_preactivations.append(preactivation); conditioned_tanh.append(tanh_value)
            used_drive2.append(drive2); drifts.append(torch.cat((d1, d2), dim=-1))
            theta1_nodes.append(theta1_t); theta2_nodes.append(theta2_t)
        # Final diagnostic features use no-grad and cannot enter the z2/a2 loss.
        with torch.no_grad():
            last1 = self.readout(theta1.detach(), z1.detach())
            last_link = last1['readout'][..., 2].to(torch.float32)
            last_theta2, _, _ = self.layer2_parameters(last_link)
            last2 = self.readout(last_theta2, z2.detach())
        return {'state': states, 'state_nodes': state_nodes, 'layer1': rows1, 'layer2': rows2,
                'final_layer1': last1, 'final_layer2': last2, 'links': links,
                'theta2_preactivation': conditioned_preactivations, 'theta2_tanh': conditioned_tanh,
                'used_drive2': used_drive2, 'drifts': drifts, 'theta1': theta1,
                'theta1_tanh': tanh1,
                'theta1_nodes': theta1_nodes, 'theta2_nodes': theta2_nodes,
                'gradient_mode': gradient_mode, 'raw_theta1': self.raw_theta1, 'raw_theta2': self.raw_theta2}


def terminal_loss(trace, target_z2, target_a2, adaptation_weight):
    z2, a2 = trace['state_nodes'][-1][2:]
    return (z2-target_z2).square().mean()+adaptation_weight*(a2-target_a2).square().mean()

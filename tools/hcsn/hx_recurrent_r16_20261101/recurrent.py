"""A signed C1 value readout and explicit Euler H-X recurrent prototype.

The frozen financial operator retains its x>=0 domain and original raw fields.
Only the new neural readout is extended to signed x. Temporal integration is
ordinary FP32 Euler, not an analytic flow or derivative of rounding.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import torch

ADAPTER_SHA256 = '8117df2cae6b17612d7537b96d72ca74a340bb5356e61bbc3f73b9fe478aa870'
ADAPTER_PROTOCOL_SHA256 = '9343b6c6727995809a4ec19b4059e3e0806dca5a822807aff55db26b667abf72'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_adapter(root):
    root = Path(root).resolve()
    if sha(root/'hx_autograd.py') != ADAPTER_SHA256 or sha(root/'ADAPTER_PROTOCOL.json') != ADAPTER_PROTOCOL_SHA256:
        raise ValueError('Wrong immutable V3 adapter')
    protocol = json.loads((root/'ADAPTER_PROTOCOL.json').read_text())
    for name, expected in protocol['source_sha256'].items():
        if sha(root/name) != expected:
            raise ValueError('Adapter source changed: '+name)
    spec = importlib.util.spec_from_file_location('_hx_recurrent_verified_v3', root/'hx_autograd.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_cpu_float32(value, name):
    if not isinstance(value, torch.Tensor) or value.device.type != 'cpu' or value.dtype != torch.float32:
        raise TypeError(name+' must be a CPU torch.float32 tensor')
    if value.numel() == 0 or not bool(torch.isfinite(value).all()):
        raise ValueError(name+' must be nonempty and finite before any clamping')


class SignedC1Readout(torch.nn.Module):
    """Return [Q=E/b, R=1-(1-F)^2, x], allowing finite signed neural x.

    x<=0: Q=0 and R=1 exactly; their local theta/state derivatives are zero.
    x>0: the original continuation formulas and full boundary chain apply.
    x always passes unchanged, including its identity state derivative.
    C1 refers to the underlying continuous formulas under the financial
    regularity assumptions. No higher derivatives or raw default fields are
    inferred from the clamped financial call.
    """

    def __init__(self, operator):
        super().__init__()
        if operator.coordinate != 'log_distance':
            raise ValueError('Signed extension requires the unchanged log_distance interface')
        self.operator = operator

    def forward(self, theta, x):
        require_cpu_float32(theta, 'theta')
        require_cpu_float32(x, 'signed x')
        if theta.shape != (9,):
            raise ValueError('This prototype uses one shared theta with shape [9]')
        xp = x.clamp_min(0.)
        packed = torch.cat((theta.expand((*x.shape, 9)), xp.unsqueeze(-1)), dim=-1)
        continued = self.operator.readout(packed)
        q = torch.where(x > 0., continued[..., 0], torch.zeros_like(continued[..., 0]))
        risk = torch.where(x > 0., continued[..., 1], torch.ones_like(continued[..., 1]))
        result = torch.stack((q, risk, x.to(torch.float64)), dim=-1)
        if not bool(torch.isfinite(result).all()):
            raise ArithmeticError('Nonfinite signed readout')
        return result


class HXRecurrentCell(torch.nn.Module):
    """Nine bounded financial parameters; fixed gains and explicit Euler.

    dx/dt = drive - leak*x - k_equity*Q - k_risk*R + adaptation
    da/dt = (k_risk*R - adaptation)/tau

    Both updates use the old states. There are no resets, clipped states,
    binary event outputs, detach calls or learned output heads in the normal
    trajectory. detach_state is an explicit diagnostic negative control.
    """

    def __init__(self, readout, base_theta, config):
        super().__init__()
        require_cpu_float32(base_theta, 'base theta')
        if base_theta.shape != (9,):
            raise ValueError('Expected nine base financial parameters')
        self.readout = readout
        self.register_buffer('base_theta', base_theta.clone())
        self.raw_theta = torch.nn.Parameter(torch.zeros(9, dtype=torch.float32))
        self.config = dict(config)
        for name in ('dt', 'leak', 'k_equity', 'k_risk', 'tau', 'theta_fraction'):
            value = float(config[name])
            if not 0. < value < float('inf'):
                raise ValueError('Expected positive finite '+name)

    def theta(self):
        return self.base_theta*(1.+self.config['theta_fraction']*torch.tanh(self.raw_theta))

    def rollout(self, initial_x, initial_adaptation, drive, detach_state=False):
        for value, name in ((initial_x, 'initial x'), (initial_adaptation, 'initial adaptation'), (drive, 'drive')):
            require_cpu_float32(value, name)
        if initial_x.ndim != 1 or initial_adaptation.shape != initial_x.shape or drive.ndim != 2 or drive.shape[1:] != initial_x.shape:
            raise ValueError('Expected state [batch] and drive [steps,batch]')
        if len(drive) != self.config['steps']:
            raise ValueError('Unexpected temporal length')
        theta = self.theta()
        x, adaptation = initial_x, initial_adaptation
        xs, adaptations = [x], [adaptation]
        readouts, drifts, theta_nodes = [], [], []
        dt = self.config['dt']
        for u in drive.unbind(0):
            if detach_state:
                x, adaptation = x.detach(), adaptation.detach()
            theta_t = theta.clone()
            observable = self.readout(theta_t, x)
            q, risk = observable[..., 0].to(torch.float32), observable[..., 1].to(torch.float32)
            dx = u-self.config['leak']*x-self.config['k_equity']*q-self.config['k_risk']*risk+adaptation
            da = (self.config['k_risk']*risk-adaptation)/self.config['tau']
            x, adaptation = x+dt*dx, adaptation+dt*da
            if not bool(torch.isfinite(x).all() and torch.isfinite(adaptation).all()):
                raise ArithmeticError('Nonfinite Euler state')
            xs.append(x); adaptations.append(adaptation)
            readouts.append(observable); drifts.append(torch.stack((dx, da), dim=-1)); theta_nodes.append(theta_t)
        return {'x': xs, 'adaptation': adaptations, 'readouts': readouts, 'drifts': drifts,
                'theta_nodes': theta_nodes, 'theta': theta, 'drive': drive,
                'detach_state_negative_control': bool(detach_state)}


def terminal_loss(trace, target_x, target_adaptation, weight):
    return (trace['x'][-1]-target_x).square().mean()+weight*(trace['adaptation'][-1]-target_adaptation).square().mean()

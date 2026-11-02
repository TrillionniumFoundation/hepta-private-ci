"""Fixed physical log-potential H-X recurrence, separate from fixed margin V1."""
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
    spec = importlib.util.spec_from_file_location('_hx_asset_recurrent_verified_v3', root/'hx_autograd.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_cpu_float32(value, name):
    if not isinstance(value, torch.Tensor) or value.device.type != 'cpu' or value.dtype != torch.float32:
        raise TypeError(name+' must be a CPU torch.float32 tensor')
    if value.numel() == 0 or not bool(torch.isfinite(value).all()):
        raise ValueError(name+' must be nonempty and finite')


class FixedPotentialReadout(torch.nn.Module):
    """Original V3 asset.readout at represented V=exp(z), without recentering.

    Returns Q=E/b, R=1-(1-F)^2 and x=log(V_repr/b). Original financial asset
    default semantics apply. z and V are independent of theta at fixed state.
    x is a diagnostic output; the temporal loss uses z/adaptation only.
    """

    def __init__(self, operator):
        super().__init__()
        if operator.coordinate != 'asset':
            raise ValueError('Fixed physical potential requires the original asset interface')
        self.operator = operator

    def evaluate(self, theta, z):
        require_cpu_float32(theta, 'theta'); require_cpu_float32(z, 'log potential z')
        if theta.shape != (9,):
            raise ValueError('Expected one shared financial theta with shape [9]')
        asset = torch.exp(z)
        if not bool(torch.isfinite(asset).all() and (asset > 0.).all()):
            raise ValueError('Represented FP32 exp(z) must be finite and strictly positive')
        packed = torch.cat((theta.expand((*z.shape, 9)), asset.unsqueeze(-1)), dim=-1)
        observable = self.operator.readout(packed)
        if not bool(torch.isfinite(observable).all()):
            raise ArithmeticError('Nonfinite fixed-potential readout')
        return observable, asset

    def forward(self, theta, z):
        return self.evaluate(theta, z)[0]


class FixedPotentialCell(torch.nn.Module):
    """Fixed z_rest and z0, nine trainable theta, 16 simultaneous Euler steps.

    dz/dt = drive - leak*(z-z_rest) - k_equity*Q - k_risk*R + adaptation
    da/dt = (k_risk*R-adaptation)/tau

    This changes the vector field and initial-state family from independent x
    V1. It is not presented as an equivalent coordinate transformation.
    """

    def __init__(self, readout, base_theta, config):
        super().__init__()
        require_cpu_float32(base_theta, 'base theta')
        if base_theta.shape != (9,):
            raise ValueError('Expected nine base financial parameters')
        self.readout = readout
        self.register_buffer('base_theta', base_theta.clone())
        self.register_buffer('rest_log_potential', torch.tensor(config['z_rest'], dtype=torch.float32))
        self.raw_theta = torch.nn.Parameter(torch.zeros(9, dtype=torch.float32))
        self.config = dict(config)
        require_cpu_float32(self.rest_log_potential, 'fixed rest log potential')
        for name in ('dt', 'leak', 'k_equity', 'k_risk', 'tau', 'theta_fraction'):
            if not 0. < float(config[name]) < float('inf'):
                raise ValueError('Expected positive finite '+name)

    def theta(self):
        return self.base_theta*(1.+self.config['theta_fraction']*torch.tanh(self.raw_theta))

    def rollout(self, initial_z, initial_adaptation, drive, detach_state=False):
        for value, name in ((initial_z, 'initial z'), (initial_adaptation, 'initial adaptation'), (drive, 'drive')):
            require_cpu_float32(value, name)
        if initial_z.ndim != 1 or initial_adaptation.shape != initial_z.shape or drive.ndim != 2 or drive.shape[1:] != initial_z.shape:
            raise ValueError('Expected state [batch] and drive [steps,batch]')
        if len(drive) != self.config['steps']:
            raise ValueError('Unexpected temporal length')
        theta = self.theta()
        z, adaptation = initial_z, initial_adaptation
        zs, adaptations = [z], [adaptation]
        readouts, assets, drifts, theta_nodes = [], [], [], []
        dt = self.config['dt']
        for u in drive.unbind(0):
            if detach_state:
                z, adaptation = z.detach(), adaptation.detach()
            theta_t = theta.clone()
            observable, asset = self.readout.evaluate(theta_t, z)
            q, risk = observable[..., 0].to(torch.float32), observable[..., 1].to(torch.float32)
            dz = u-self.config['leak']*(z-self.rest_log_potential)-self.config['k_equity']*q-self.config['k_risk']*risk+adaptation
            da = (self.config['k_risk']*risk-adaptation)/self.config['tau']
            z, adaptation = z+dt*dz, adaptation+dt*da
            if not bool(torch.isfinite(z).all() and torch.isfinite(adaptation).all()):
                raise ArithmeticError('Nonfinite Euler state')
            zs.append(z); adaptations.append(adaptation)
            readouts.append(observable); assets.append(asset)
            drifts.append(torch.stack((dz, da), dim=-1)); theta_nodes.append(theta_t)
        # One final readout is explicitly logging-only. Neither final Q/R/x nor
        # this detached diagnostic can enter the terminal z/a training loss.
        with torch.no_grad():
            final_readout, final_asset = self.readout.evaluate(theta.detach(), z.detach())
        return {'z': zs, 'adaptation': adaptations, 'readouts': readouts, 'assets': assets,
                'final_readout': final_readout, 'final_asset': final_asset,
                'drifts': drifts, 'theta_nodes': theta_nodes, 'theta': theta, 'drive': drive,
                'detach_state_negative_control': bool(detach_state), 'fixed_z_rest': self.rest_log_potential}


def terminal_loss(trace, target_z, target_adaptation, weight):
    return (trace['z'][-1]-target_z).square().mean()+weight*(trace['adaptation'][-1]-target_adaptation).square().mean()

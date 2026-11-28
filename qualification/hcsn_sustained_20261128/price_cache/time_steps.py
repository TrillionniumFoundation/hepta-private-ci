"""Interleaved whole-network timings and explicit first derivatives of both price surfaces."""
import argparse
import json
from pathlib import Path
import statistics
import time

import torch
from population import BoundaryPopulation, ContinuousSpikingNetwork


def check_price_derivatives(atoms):
    layer = BoundaryPopulation(3, 2, atoms)
    layer.grid.requires_grad_()
    layer.prices.basis_y.requires_grad_()
    p = torch.tensor([[48.1, 66.7], [59.1, 76.2]], dtype=torch.float64, requires_grad=True)
    weights = torch.linspace(-.7, 1., atoms, dtype=p.dtype)
    def values(cached):
        if cached:
            lo_hi, equity, loss = layer._price_basis()
            fraction = (p[..., None] - lo_hi[0]) / (lo_hi[1] - lo_hi[0])
            return (torch.lerp(equity[0], equity[1], fraction),
                    torch.lerp(loss[0], loss[1], fraction))
        return layer.priced_channels(p)
    u, v = values(False), values(True)
    report = {'atoms': atoms, 'prices': []}
    for label, orig, cache in zip(('equity','monetary loss'), u, v):
        args = (p, layer.grid, layer.prices.basis_y)
        a = torch.autograd.grad((orig * weights).sum(), args, retain_graph=True, allow_unused=True)
        b = torch.autograd.grad((cache * weights).sum(), args, retain_graph=True, allow_unused=True)
        grads = {}
        for var, x, y in zip(('principal','grid','registered_spectral_buffer'), a, b):
            assert (x is None) == (y is None)
            if x is not None:
                grads[var] = (x-y).abs().max().item()
                assert grads[var] < 5e-11
        err = (orig-cache).abs().max().item()
        assert err < 4e-13
        report['prices'].append({'name': label, 'max_value_error': err, 'max_gradient_errors': grads})
    return report


def time_network(atoms):
    torch.manual_seed(439)
    uncached = ContinuousSpikingNetwork(8, 3, 2, atoms, port='priced')
    cached = ContinuousSpikingNetwork(8, 3, 2, atoms, port='priced', cache_prices=True)
    cached.load_state_dict(uncached.state_dict())
    models = {'direct':uncached, 'cached':cached}
    x = torch.randn(8, 8, 8, dtype=torch.float64)
    y = torch.arange(8) % 2
    def step(model):
        model.zero_grad(set_to_none=True)
        outputs = model(x)[0]
        torch.nn.functional.cross_entropy(outputs[-1], y).backward()
    for model in models.values():
        for _ in range(3):
            step(model)
    seconds = {key: [] for key in models}
    for repeat in range(11):
        order = ('cached','direct') if repeat % 2 == 0 else ('direct','cached')
        for name in order:
            start = time.perf_counter()
            step(models[name])
            seconds[name].append(time.perf_counter()-start)
    medians = {name: statistics.median(vals) for name, vals in seconds.items()}
    return {'atoms': atoms, 'frames': 8, 'batch': 8, 'width': 3, 'layers': 2,
            'median_forward_and_backward_s': medians, 'seconds': seconds,
            'median_ratio': medians['direct']/medians['cached']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    obj = {'torch': str(torch.__version__), 'device':'cpu', 'threads':torch.get_num_threads(),
           'derivatives':[check_price_derivatives(k) for k in (12,64)],
           'timing':[time_network(k) for k in (12,64)]}
    args.output.write_text(json.dumps(obj,indent=2)+'\n')

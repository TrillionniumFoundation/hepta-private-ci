"""Finite-horizon fixed-physics content transport; never an adaptive-rate kernel.

Only zero initial signed contents, the source FlowNetwork write order, and a
frozen rational interval are admitted. The probability law is input-independent.
An impulse at each write time gives a time-varying triangular transport matrix.
Nonlinear writers remain exact network operations; full pending states can be
reconstructed from the same basis. Floating reduction order is changed, so the
implementation does not claim bitwise identity or arbitrary-history fixed memory.
"""
from dataclasses import dataclass, replace
import hashlib
import json

import torch

from qualification.hcsn_currentstate.differentiable import (
    Atom, Flux, Work, advance, initial,
)
from qualification.hcsn_network.network import NetworkState


def physics_digest(physics):
    digest = hashlib.sha256()
    for p in physics:
        digest.update(str(p.delay).encode())
        for name in ('generator', 'lower', 'upper', 'reset', 'reward',
                     'escape_reward', 'spike_reward', 'discount'):
            value = getattr(p, name)
            if value.device.type != 'cpu' or value.dtype != torch.float64:
                raise ValueError('only CPU FP64 physics is admitted')
            if value.requires_grad:
                raise ValueError('physics gradients invalidate this frozen cache')
            digest.update(name.encode())
            digest.update(str(tuple(value.shape)).encode())
            digest.update(value.detach().contiguous().numpy().tobytes())
    return digest.hexdigest()


def graph_descriptor(flow, steps):
    if flow.rate_drive or flow.drives is not None:
        raise ValueError('input-driven physics cannot use fixed-law specialization')
    if flow.activation not in ('linear', 'tanh') or flow.message_mode not in ('full', 'mass'):
        raise ValueError('unsupported graph semantics')
    if not 1 <= steps <= 32:
        raise ValueError('finite horizon must be in 1..32')
    if len(flow.writers) != flow.layers:
        raise ValueError('writer count does not match declared layers')
    for index, writer in enumerate(flow.writers):
        incoming = flow.input_size if index == 0 else flow.content_size+1
        if (type(writer) is not torch.nn.Linear or writer.in_features != incoming
                or writer.out_features != flow.content_size):
            raise ValueError('only the declared pointwise linear writers are admitted')
        for param in writer.parameters():
            if param.dtype != torch.float64 or param.device.type != 'cpu' or not bool(torch.isfinite(param).all()):
                raise ValueError('writer parameters must be finite CPU FP64')
    return dict(input_size=flow.input_size, content_size=flow.content_size,
                layers=flow.layers, dt=str(flow.dt), activation=flow.activation,
                message_mode=flow.message_mode, steps=steps, rate_drive=False,
                initial_state='reset_probability_zero_signed_content')


@dataclass(frozen=True)
class LayerKernel:
    final_basis: object
    hit_kernel: torch.Tensor
    hit_probability: torch.Tensor
    active_write_mass: torch.Tensor


def kernel_digest(kernels):
    digest = hashlib.sha256()
    for kernel in kernels:
        digest.update(str(kernel.final_basis.time).encode())
        for packet in kernel.final_basis.pending:
            if isinstance(packet, Flux):
                digest.update(str((packet.start, packet.end)).encode())
            else:
                digest.update(str(packet.time).encode())
        for tensor in (*kernel.final_basis.tensors(), kernel.hit_kernel,
                       kernel.hit_probability, kernel.active_write_mass):
            digest.update(str(tuple(tensor.shape)).encode())
            digest.update(tensor.detach().contiguous().numpy().tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class CompiledFlow:
    graph: dict
    physics_sha256: str
    kernels: tuple
    kernel_sha256: str
    exponentials: int
    largest_dimension: int

    def tensor_bytes(self):
        return sum(sum(t.numel()*t.element_size() for t in
                       (*k.final_basis.tensors(), k.hit_kernel,
                        k.hit_probability, k.active_write_mass)) for k in self.kernels)


def compile_flow(flow, physics, steps):
    graph = graph_descriptor(flow, steps)
    identity = physics_digest(physics)
    if len(physics) != flow.layers:
        raise ValueError('one law per layer required')
    work = Work(max_exponentials=4096)
    kernels = []
    with torch.no_grad():
        for p in physics:
            cell = initial(torch.cat((p.reset[None], p.reset.new_zeros(steps, p.reset.numel()))))
            hits, probabilities, active_mass = [], [], []
            for index in range(steps):
                cell = advance(cell, p, cell.time, work)
                active_mass.append(cell.active[0].sum())
                active = cell.active.clone()
                active[index+1] = active[index+1] + active[0]
                updated = advance(replace(cell, active=active), p, cell.time+flow.dt, work)
                increment = updated.hits-cell.hits
                hits.append(increment[1:])
                probabilities.append(increment[0])
                cell = updated
            kernels.append(LayerKernel(cell, torch.stack(hits),
                                       torch.stack(probabilities), torch.stack(active_mass)))
    kernels = tuple(kernels)
    return CompiledFlow(graph, identity, kernels, kernel_digest(kernels),
                        work.exponentials, work.largest_dimension)


def _contract(values, marks):
    """Preserve probability row and reconstruct flattened [batch,content] rows."""
    flattened = marks.flatten(1, 2)
    signed = torch.einsum('td,t...->d...', flattened, values[1:])
    return torch.cat((values[:1], signed), dim=0)


def _reconstruct(kernel, marks):
    basis = kernel.final_basis
    fields = {name:_contract(getattr(basis, name), marks) for name in
              ('active', 'upper', 'hits', 'discounted_hits', 'occupation', 'value')}
    pending = []
    for packet in basis.pending:
        if isinstance(packet, Flux):
            pending.append(replace(packet, alpha=_contract(packet.alpha, marks)))
        elif isinstance(packet, Atom):
            pending.append(replace(packet, mass=_contract(packet.mass, marks)))
        else:
            raise ValueError('unknown pending state representation')
    return replace(basis, **fields, pending=tuple(pending))


def apply_flow(compiled, flow, sequence, physics):
    """Return the same observable interface, with a fully reconstructed final state."""
    if sequence.ndim != 3 or sequence.dtype != torch.float64 or sequence.device.type != 'cpu':
        raise ValueError('expected [time,batch,input] CPU FP64 input')
    steps, batch, input_size = sequence.shape
    if not 1 <= batch <= 256 or input_size != flow.input_size or not bool(torch.isfinite(sequence).all()):
        raise ValueError('invalid input contract')
    if graph_descriptor(flow, steps) != compiled.graph:
        raise ValueError('graph, logical interval or horizon changed')
    if len(compiled.kernels) != flow.layers or len(physics) != flow.layers:
        raise ValueError('kernel or physics layer count mismatch')
    if physics_digest(physics) != compiled.physics_sha256:
        raise ValueError('physics changed; rebuild is required')
    if kernel_digest(compiled.kernels) != compiled.kernel_sha256:
        raise ValueError('compiled constants changed')
    cells, messages, written, totals = [], [], [], []
    source = sequence
    emissions = None
    for index, (writer, kernel) in enumerate(zip(flow.writers, compiled.kernels)):
        if index and flow.message_mode == 'mass':
            source = torch.cat((source[:, :, :1], torch.zeros_like(source[:, :, 1:])), dim=2)
        mark = writer(source)
        if flow.activation == 'tanh':
            mark = mark.tanh()
        content = torch.einsum('ts,sbc->tbc', kernel.hit_kernel, mark)
        probability = kernel.hit_probability[:, None, None].expand(-1, batch, 1)
        emissions = torch.cat((probability, content), dim=2)
        cells.append(_reconstruct(kernel, mark))
        messages.append(emissions[-1])
        written.append(torch.einsum('t,tbc->bc', kernel.active_write_mass, mark))
        totals.append(torch.cat((physics[index].reset.sum().reshape(1),
                                 mark.new_zeros(batch*flow.content_size))))
        source = torch.cat((torch.zeros_like(emissions[:1]), emissions[:-1]), dim=0)
    state = NetworkState(tuple(cells), tuple(messages), tuple(written), tuple(totals), batch)
    if any(not bool(torch.isfinite(t).all()) for t in state.tensors()):
        raise FloatingPointError('nonfinite specialized state')
    return emissions, state


def readout_features(state, batch, content):
    cell = state.cells[-1]
    return torch.cat((cell.hits[1:].reshape(batch, content),
                      cell.active[1:].sum(1).reshape(batch, content)), dim=1)

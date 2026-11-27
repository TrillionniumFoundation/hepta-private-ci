"""Synchronous, causal population-flow network with explicit interlayer messages.

Each population conserves its own probability. A spike message is the interval's
integrated hit probability and signed content mass, not transferred probability.
The next layer receives that message at the following interval's start. Content
writes add a mark to the active population only; refractory/escaped content is
unchanged. This is a discrete coupling contract with one interval of synaptic
latency, over exact frozen-segment finite CTMC/deterministic-delay dynamics.
"""

from dataclasses import dataclass, replace
from fractions import Fraction

import torch

from qualification.hcsn_currentstate.differentiable import (
    Physics, State, Work, advance, initial, refractory,
)


@dataclass(frozen=True)
class NetworkState:
    cells: tuple
    messages: tuple
    written: tuple
    initial_totals: tuple
    batch_size: int = 1

    @property
    def time(self):
        return self.cells[0].time

    def tensors(self):
        for cell in self.cells:
            yield from cell.tensors()
        yield from (*self.messages, *self.written, *self.initial_totals)

    def tensor_bytes(self):
        """Logical payload with repeated tensors counted; not allocator or AD memory."""
        return sum(t.numel() * t.element_size() for t in self.tensors())

    def balances(self, work=None):
        """Actual total minus initial total and all subsequently written content."""
        work = Work() if work is None else work
        return tuple(cell.active.sum(1) + cell.upper + refractory(cell, work)
                     - start - torch.cat((write.new_zeros(1), write.flatten()))
                     for cell, write, start in zip(self.cells, self.written, self.initial_totals))


class FlowNetwork(torch.nn.Module):
    """A stack of finite populations sharing a spatial law across the batch.

`rate_drive=True` adds a bounded learned time change exp(tanh(drive)) to each
population's active generator. It does not retain a separately derived policy's
task-optimality. With the default False, supplied Physics stays unchanged.
"""

    def __init__(self, input_size, content_size, layers=2, dt=Fraction(1, 10),
                 *, message_mode="full", rate_drive=False, bias=False, activation="tanh"):
        super().__init__()
        if any(type(n) is not int or not 1 <= n <= 64 for n in
               (input_size, content_size, layers)) or layers > 8:
            raise ValueError("input/content 1..64 and layers 1..8 required")
        if not isinstance(dt, Fraction) or dt <= 0 or message_mode not in ("full", "mass"):
            raise ValueError("positive rational dt and full/mass message mode required")
        if type(rate_drive) is not bool or type(bias) is not bool:
            raise ValueError("rate_drive and bias must be booleans")
        if activation not in ("linear", "tanh"):
            raise ValueError("activation must be linear or tanh")
        self.input_size, self.content_size, self.layers = input_size, content_size, layers
        self.dt, self.message_mode, self.rate_drive = dt, message_mode, rate_drive
        self.activation = activation
        sizes = [input_size] + [content_size + 1] * (layers - 1)
        self.writers = torch.nn.ModuleList(torch.nn.Linear(n, content_size, bias=bias) for n in sizes)
        self.drives = torch.nn.ModuleList(torch.nn.Linear(n, 1) for n in sizes) if rate_drive else None

    def initial_state(self, physics, probabilities=None, contents=None, *, batch_size=1):
        """Signed masses have shape [batch,content,space], or [content,space] for B=1.

The identical probability trajectory is represented once. The batch's signed
content channels are flattened; matrix actions never mix those channels.
        """
        if type(batch_size) is not int or not 1 <= batch_size <= 256:
            raise ValueError("batch_size must be an integer in 1..256")
        if self.rate_drive and batch_size != 1:
            raise ValueError("input-dependent rate drive requires batch_size=1")
        if len(physics) != self.layers or any(not isinstance(p, Physics) for p in physics):
            raise ValueError("one Physics per population required")
        probabilities = tuple(p.reset for p in physics) if probabilities is None else probabilities
        contents = tuple(p.lower.new_zeros(batch_size, self.content_size, p.lower.numel()) for p in physics) \
            if contents is None else contents
        if len(probabilities) != self.layers or len(contents) != self.layers:
            raise ValueError("one probability/content block per population required")
        cells = []
        for p, probability, content in zip(physics, probabilities, contents):
            if batch_size == 1 and content.ndim == 2:
                content = content[None]
            if probability.shape != p.lower.shape or content.shape != (batch_size, self.content_size, p.lower.numel()):
                raise ValueError("probability/content shape mismatch")
            cells.append(initial(torch.cat((probability[None], content.flatten(0, 1)), 0)))
        cells = tuple(cells)
        return NetworkState(cells, tuple(c.hits.new_zeros(batch_size, self.content_size + 1) for c in cells),
                            tuple(c.hits.new_zeros(batch_size, self.content_size) for c in cells),
                            tuple(c.active.sum(1) for c in cells), batch_size)

    def step(self, vector, state, physics, work=None):
        """One common-clock interval; every layer reads the old message buffer."""
        unbatched = vector.ndim == 1
        vector = vector[None] if unbatched else vector
        if vector.shape != (state.batch_size, self.input_size) or not bool(torch.isfinite(vector).all()):
            raise ValueError("finite input with matching [batch,input_size] required")
        if self.rate_drive and state.batch_size != 1:
            raise ValueError("input-dependent rate drive requires batch_size=1")
        if any(len(x) != self.layers for x in
               (physics, state.cells, state.messages, state.written, state.initial_totals)):
            raise ValueError("population count mismatch")
        if any(c.time != state.time for c in state.cells):
            raise ValueError("population clocks disagree")
        work = Work() if work is None else work
        cells, messages, written = [], [], []
        target = state.time + self.dt
        for i, (cell, p) in enumerate(zip(state.cells, physics)):
            # Scheduled returns at this clock edge join active mass before writing.
            cell = advance(cell, p, cell.time, work)
            source = vector if i == 0 else state.messages[i - 1]
            if i and self.message_mode == "mass":
                source = torch.cat((source[:, :1], torch.zeros_like(source[:, 1:])), 1)
            mark = self.writers[i](source)
            if self.activation == "tanh":
                mark = mark.tanh()
            if self.rate_drive:
                scale = self.drives[i](source).squeeze().tanh().exp()
                p = replace(p, generator=p.generator * scale, lower=p.lower * scale, upper=p.upper * scale)
            active = torch.cat((cell.active[:1], cell.active[1:] + mark.flatten()[:, None] * cell.active[:1]), 0)
            updated = advance(replace(cell, active=active), p, target, work)
            cells.append(updated)
            increment = updated.hits - cell.hits
            messages.append(torch.cat((increment[:1].expand(state.batch_size, 1),
                                        increment[1:].reshape(state.batch_size, self.content_size)), 1))
            written.append(state.written[i] + mark * cell.active[0].sum())
        updated = NetworkState(tuple(cells), tuple(messages), tuple(written), state.initial_totals, state.batch_size)
        if any(not bool(torch.isfinite(t).all()) for t in updated.tensors()):
            raise FloatingPointError("nonfinite network state")
        return updated.messages[-1][0] if unbatched else updated.messages[-1], updated

    def forward(self, sequence, physics, state=None, work=None):
        """Return emissions [time,batch,1+content] and complete state.

The loss is applied to this deterministic population-flow network. It is not
claimed equal to the expected nonlinear loss of a sampled discrete SNN.
        """
        unbatched = sequence.ndim == 2
        sequence = sequence[:, None] if unbatched else sequence
        if sequence.ndim != 3 or sequence.shape[2] != self.input_size or not len(sequence):
            raise ValueError("nonempty [time,batch,input_size] or [time,input_size] sequence required")
        state = self.initial_state(physics, batch_size=sequence.shape[1]) if state is None else state
        work = Work() if work is None else work
        emissions = []
        for vector in sequence:
            emitted, state = self.step(vector, state, physics, work)
            emissions.append(emitted)
        output = torch.stack(emissions)
        return output[:, 0] if unbatched else output, state

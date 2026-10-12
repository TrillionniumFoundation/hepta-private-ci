"""Research tensor composition for existing Cell/Organ and modality owners.

No tower, generator, persistent state, backend scheduler or NDU subject is
created. Frozen tower outputs enter explicitly; recurrent state leaves explicitly.
"""

import math

import torch
from torch import nn

from development_tensors import checked_tensor


class SharedCellRecurrence(nn.Module):
    """One reusable GRU cell; requested depth never duplicates its parameters."""

    def __init__(self, width, *, maximum_depth=32):
        super().__init__()
        if (type(width) is not int or not 1 <= width <= 512
                or type(maximum_depth) is not int or not 1 <= maximum_depth <= 32):
            raise ValueError("invalid recurrent bounds")
        self.width, self.maximum_depth = width, maximum_depth
        self.cell = nn.GRUCell(width, width)

    def forward(self, tokens, valid, initial, *, depth):
        checked_tensor(tokens, 3, "causal workspace tokens")
        checked_tensor(initial, 2, "caller-owned state")
        if (type(depth) is not int or not 1 <= depth <= self.maximum_depth
                or tokens.shape[0] != len(initial) or not 1 <= len(initial) <= 32
                or tokens.shape[2] != self.width or initial.shape[1] != self.width
                or tokens.dtype != initial.dtype or tokens.dtype != self.cell.weight_ih.dtype
                or not isinstance(valid, torch.Tensor) or valid.dtype != torch.bool
                or valid.device.type != "cpu" or valid.shape != tokens.shape[:2]
                or not valid.any(dim=1).all() or tokens.shape[1] > 1024):
            raise ValueError("invalid bounded recurrent workspace")
        # Padded values do not participate in attention or receive gradients.
        state = initial.clone()
        trace = []
        for _ in range(depth):
            scores = (tokens * state[:, None, :]).sum(-1) / math.sqrt(self.width)
            weights = torch.softmax(scores.masked_fill(~valid, -torch.inf), dim=-1)
            message = (tokens * weights[:, :, None]).sum(1)
            state = self.cell(message, state)
            trace.append(state)
        return state, tuple(trace)


class TemporalModalBridge(nn.Module):
    """Train only connectors, preserving each object's token and timestamp.

    Text can be an exact identity connection. Image/video/audio towers are
    supplied by inference.control, not downloaded or claimed present here.
    Returned timestamps use caller-declared common units, without renormalizing
    them from future observations. This method requires already-observed tokens.
    """

    MODALITIES = ("text", "image", "video", "audio")

    def __init__(self, input_widths, shared_width):
        super().__init__()
        if (not isinstance(input_widths, dict) or not input_widths
                or not set(input_widths) <= set(self.MODALITIES)
                or type(shared_width) is not int or not 1 <= shared_width <= 512
                or any(type(w) is not int or not 1 <= w <= 8192 for w in input_widths.values())
                or sum(input_widths.values()) * shared_width > 4_194_304):
            raise ValueError("invalid connector dimensions")
        self.widths = dict(input_widths)
        self.shared_width = shared_width
        if "text" in input_widths and input_widths["text"] != shared_width:
            raise ValueError("identity text bridge requires equal width")
        self.projectors = nn.ModuleDict({
            name: nn.Identity() if name == "text" else nn.Linear(width, shared_width)
            for name, width in input_widths.items()
        })
        self.time_projection = nn.Linear(2, shared_width, bias=False)
        self.modality = nn.Embedding(len(self.MODALITIES), shared_width)

    def forward(self, streams, *, observed_until):
        if (not isinstance(streams, dict) or not streams or not set(streams) <= set(self.widths)
                or type(observed_until) not in (int, float) or not math.isfinite(observed_until)):
            raise ValueError("invalid observed modality set")
        packed, times, masks = [], [], []
        batch = None
        dtype = self.time_projection.weight.dtype
        for name in self.MODALITIES:
            if name not in streams:
                continue
            stream = streams[name]
            if not isinstance(stream, tuple) or len(stream) != 3:
                raise ValueError("tokens/times/mask tuple required")
            values, timestamps, valid = stream
            checked_tensor(values, 3, name)
            checked_tensor(timestamps, 2, "timestamps")
            if (values.shape[2] != self.widths[name] or values.dtype != dtype
                    or timestamps.dtype != dtype or timestamps.shape != values.shape[:2]
                    or not isinstance(valid, torch.Tensor) or valid.dtype != torch.bool
                    or valid.device.type != "cpu" or valid.shape != timestamps.shape
                    or not valid.any(dim=1).all() or values.shape[1] > 1024
                    or not 1 <= values.shape[0] <= 32):
                raise ValueError("invalid modal stream shape")
            if batch is None:
                batch = len(values)
            if batch != len(values):
                raise ValueError("unpaired modal batches")
            for t, mask in zip(timestamps, valid):
                selected = t[mask]
                if (bool((selected > observed_until).any())
                        or bool((selected[1:] < selected[:-1]).any())):
                    raise ValueError("future or reversed modality timestamps")
            # Frozen inputs are detached, but connector gradients remain active.
            projected = self.projectors[name](values.detach().clone())
            if name != "text":
                phase = torch.stack((timestamps.sin(), timestamps.cos()), dim=-1).detach()
                index = self.MODALITIES.index(name)
                projected = projected + self.time_projection(phase) + self.modality.weight[index]
            packed.append(projected.masked_fill(~valid[:, :, None], 0))
            times.append(timestamps.detach().clone())
            masks.append(valid.clone())
        values, timestamps, valid = torch.cat(packed, 1), torch.cat(times, 1), torch.cat(masks, 1)
        if values.shape[1] > 1024:
            raise ValueError("combined modal token budget exceeded")
        # Stable ordering preserves within-frame object order on equal times.
        order = timestamps.masked_fill(~valid, torch.inf).argsort(dim=1, stable=True)
        values = values.gather(1, order[:, :, None].expand(-1, -1, self.shared_width))
        return values, timestamps.gather(1, order), valid.gather(1, order)

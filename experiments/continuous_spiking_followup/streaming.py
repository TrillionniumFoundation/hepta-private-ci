"""Frozen-model incremental inference with bounded recurrent state or KV cache.

Inputs are consumed exactly once. No prefix tensors are retained. This adapter
is inference-only and does not modify the sealed study001 model or equations.
"""

import copy
import hashlib
import json

import torch

from .stream_layers import advance_backbone, initial_layers


FORMAT = "hcsn-incremental-state-v2"


def model_digest(model):
    """Bind architecture/configuration and every model state tensor, not a label."""
    digest = hashlib.sha256(json.dumps(model.config, sort_keys=True).encode())
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        metadata = [name, str(tensor.dtype), list(tensor.shape)]
        digest.update(json.dumps(metadata, separators=(",", ":")).encode())
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


class StreamingClassifier:
    """Incrementally evaluate a frozen ``SequenceClassifier`` in evaluation mode.

    ``steps`` counts time-step calls; ``processed_rows`` counts actual row steps,
    including rows later removed by ``select_batch``. ``state_bytes`` counts
    persistent state tensor payloads, excluding model weights and transient work.
    Model parameters must remain immutable for the lifetime of this adapter.
    """

    def __init__(self, model):
        if model.training:
            raise ValueError("streaming requires model.eval()")
        self.model = model
        self.model_sha256 = model_digest(model)
        self.batch_size = None
        self.steps = 0
        self.processed_rows = 0
        self.elapsed = None
        self.layers = []

    @property
    def state_bytes(self):
        values = ([] if self.elapsed is None else [self.elapsed]) + [
            value for layer in self.layers for value in layer.values()
        ]
        return sum(value.numel() * value.element_size() for value in values)

    @torch.inference_mode()
    def reset(self, batch_size=1):
        if type(batch_size) is not int or batch_size < 0:
            raise ValueError("batch_size must be a nonnegative integer")
        if model_digest(self.model) != self.model_sha256:
            raise ValueError("model weights changed; construct a new adapter")
        self.batch_size, self.steps, self.processed_rows = batch_size, 0, 0
        self.elapsed = torch.zeros(
            batch_size, device=next(self.model.parameters()).device, dtype=torch.float64
        )
        self.layers = initial_layers(self.model, batch_size)
        return self

    @torch.inference_mode()
    def step(self, x, dt):
        if self.model.training:
            raise ValueError("model changed to training mode")
        anchor = next(self.model.parameters())
        if x.ndim != 2 or x.shape[1] != self.model.config["input_dim"]:
            raise ValueError("x must have shape [active_batch,input_dim]")
        if x.device != anchor.device or x.dtype != anchor.dtype:
            raise ValueError("input dtype/device must match the model")
        if dt.ndim == 2 and dt.shape[1] == 1:
            dt = dt[:, 0]
        if dt.shape != x.shape[:1] or dt.device != x.device or dt.dtype != x.dtype:
            raise ValueError("dt must match input batch, dtype and device")
        if not bool(torch.isfinite(x).all() and torch.isfinite(dt).all()) or bool(
            (dt < 0).any()
        ):
            raise ValueError("inputs must be finite and dt nonnegative")
        if self.batch_size is None:
            self.reset(x.shape[0])
        if x.shape[0] != self.batch_size or self.batch_size == 0:
            raise ValueError(
                "batch size changed without select_batch/reset, or is empty"
            )
        # Float64 accumulation followed by one rounding matches the frozen CPU
        # float32 cumsum on the verified histories. Repeated float32 addition can
        # drift enough to change Transformer time encodings at T128.
        elapsed = self.elapsed + dt.double()
        model_elapsed = elapsed.to(x.dtype)
        common = torch.cat((x, dt[:, None] / 32, model_elapsed[:, None] / 32), dim=-1)
        output, layers, aux = advance_backbone(
            self.model, self.model.frontend(common), dt, model_elapsed, self.layers
        )
        logits = self.model.readout(output)
        self.elapsed, self.layers = elapsed, layers
        self.steps += 1
        self.processed_rows += self.batch_size
        return logits, aux

    @torch.inference_mode()
    def select_batch(self, indices):
        """Retain/reorder unique active rows without advancing any model state."""
        if self.batch_size is None:
            raise ValueError("reset or step before selecting active rows")
        indices = torch.as_tensor(indices, device=self.elapsed.device)
        if indices.ndim != 1 or (
            indices.numel() and indices.dtype not in (torch.int32, torch.int64)
        ):
            raise ValueError("indices must be a one-dimensional integer selection")
        indices = indices.long()
        if indices.numel() and (
            int(indices.min()) < 0
            or int(indices.max()) >= self.batch_size
            or indices.unique().numel() != indices.numel()
        ):
            raise ValueError("indices must be unique existing row indices")
        self.elapsed = self.elapsed.index_select(0, indices)
        self.layers = [
            {name: value.index_select(0, indices) for name, value in layer.items()}
            for layer in self.layers
        ]
        self.batch_size = indices.numel()
        return self

    @torch.inference_mode()
    def snapshot(self):
        if self.batch_size is None:
            raise ValueError("no initialized state")
        if model_digest(self.model) != self.model_sha256:
            raise ValueError("model weights changed while the stream was active")
        return {
            "format": FORMAT,
            "model_sha256": self.model_sha256,
            "config": copy.deepcopy(self.model.config),
            "steps": self.steps,
            "processed_rows": self.processed_rows,
            "batch_size": self.batch_size,
            "elapsed": self.elapsed.cpu().clone(),
            "layers": [
                {name: value.cpu().clone() for name, value in layer.items()}
                for layer in self.layers
            ],
        }

    @torch.inference_mode()
    def restore(self, snapshot):
        from .stream_state import validate_snapshot

        elapsed, layers = validate_snapshot(self.model, self.model_sha256, snapshot)
        # Assign only after all fields and tensors have passed validation.
        self.batch_size, self.steps = snapshot["batch_size"], snapshot["steps"]
        self.processed_rows = snapshot["processed_rows"]
        self.elapsed, self.layers = elapsed, layers
        return self

    def save_state(self, directory):
        from .stream_state import save_snapshot

        return save_snapshot(self.snapshot(), directory)

    def load_state(self, directory):
        from .stream_state import load_snapshot

        return self.restore(load_snapshot(directory))

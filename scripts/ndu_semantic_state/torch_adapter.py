"""Optional autograd-preserving construction of the common semantic features.

Importing this module does not require Torch. Validation snapshots detach only
for checks; the returned features concatenate the original graph tensors.
Discrete sampling/UTF-8 codecs are not differentiable. Text encoders used here
must consume a differentiable public output representation, or callers must use
the existing likelihood-score estimator for discrete emissions.
"""

from .state import MODALITIES, check_actor_binding, exact_fields, from_public_encodings


def features_torch(shared, encodings, state, binding):
    import numpy as np
    import torch

    exact_fields(encodings, MODALITIES, "output encodings")
    check_actor_binding(binding, state)
    tensors = [shared] + [encodings[name] for name in MODALITIES]
    snapshots = [state.shared] + [slot.encoding for slot in state.slots]
    for tensor, snapshot in zip(tensors, snapshots, strict=True):
        if (not isinstance(tensor, torch.Tensor) or tuple(tensor.shape) != state.shared.shape
                or tensor.dtype not in (torch.float32, torch.float64)
                or tensor.device != shared.device or tensor.dtype != shared.dtype
                or not torch.isfinite(tensor).all().item()):
            raise ValueError("Content tensors must share the validated shape, dtype and device")
        if not np.array_equal(tensor.detach().cpu().numpy(), snapshot):
            raise ValueError("Validated content snapshot differs from graph tensors")
    columns = [shared]
    for name, slot in zip(MODALITIES, state.slots, strict=True):
        columns.extend((encodings[name], torch.as_tensor(slot.metadata(), dtype=shared.dtype, device=shared.device)))
    clock = np.stack((np.log1p(state.remaining_budget), np.log1p(state.elapsed_seconds)), axis=-1)
    columns.append(torch.as_tensor(clock, dtype=shared.dtype, device=shared.device))
    return torch.cat(columns, dim=-1)


def encode_public_outputs_torch(shared, outputs, encoders, metadata):
    """Pass only the two current output tensors to registered output encoders.

    Returns (features, validated_snapshot, binding). This performs no model
    selection or gradient step and does not authenticate an encoder's behavior;
    executable/weight identities belong in the run's material manifest.
    """
    import torch
    from .state import actor_binding

    exact_fields(outputs, MODALITIES, "public outputs")
    exact_fields(encoders, MODALITIES, "public output encoders")
    if not isinstance(shared, torch.Tensor) or shared.dtype not in (torch.float32, torch.float64):
        raise ValueError("Shared content must be a floating Torch tensor")
    encodings = {}
    for name in MODALITIES:
        if not isinstance(outputs[name], torch.Tensor) or not callable(encoders[name]):
            raise ValueError("Public output tensors and callable encoders are required")
        encodings[name] = encoders[name](outputs[name])
        if not isinstance(encodings[name], torch.Tensor):
            raise ValueError("Encoder did not return a Torch tensor")
    snapshot = from_public_encodings(shared.detach().cpu().numpy(),
        {name: encodings[name].detach().cpu().numpy() for name in MODALITIES}, metadata)
    binding = actor_binding(snapshot)
    return features_torch(shared, encodings, snapshot, binding), snapshot, binding

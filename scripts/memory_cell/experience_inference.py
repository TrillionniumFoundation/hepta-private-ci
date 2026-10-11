"""Frozen experimental adapter switching with no hidden training-state changes.

PEFT 0.17.1 re-enables active adapters' requires_grad flags when leaving its
base-only context. Preserve the caller's frozen state without suppressing actual
parameter mutation: versions/identities and exact adapter values are checked.
The existing final full-base digest verification remains required.
"""

from contextlib import contextmanager, nullcontext


@contextmanager
def frozen_adapter_mode(model, *, enabled):
    import torch
    from peft import get_peft_model_state_dict

    parameters = dict(model.named_parameters())
    if (
        type(enabled) is not bool
        or model.training
        or any(p.requires_grad or p.grad is not None for p in parameters.values())
    ):
        raise ValueError("adapter inference requires an already frozen clean model")
    versions = {k: p._version for k, p in parameters.items()}
    before = {
        k: v.detach().clone() for k, v in get_peft_model_state_dict(model).items()
    }
    try:
        with torch.inference_mode():
            with nullcontext() if enabled else model.disable_adapter():
                yield
    finally:
        # Only restore the known library flag side effect; never restore weights
        # to hide an actual mutation or clear unexpectedly produced gradients.
        for parameter in parameters.values():
            parameter.requires_grad_(False)
        after_parameters = dict(model.named_parameters())
        if (
            model.training
            or parameters.keys() != after_parameters.keys()
            or any(
                after_parameters[k] is not p
                or p._version != versions[k]
                or p.grad is not None
                for k, p in parameters.items()
            )
        ):
            raise ValueError("inference changed parameters, gradients or model mode")
        after = get_peft_model_state_dict(model)
        if before.keys() != after.keys() or any(
            not torch.equal(v, before[k]) for k, v in after.items()
        ):
            raise ValueError("inference changed adapter tensor values")

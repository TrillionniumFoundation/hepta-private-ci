"""Read actual backward gradients before clipping or optimizer weight decay."""

import torch


def gradient_activity(model):
    """Partition trainable real scalars without changing gradients or state.

    Missing gradients differ from connected numerical zeros. Complex real and
    imaginary components count separately. This reports the current backward,
    not identifiability, accumulated coverage or causes of parameter movement.
    """
    records, frozen = [], 0
    for name, parameter in model.named_parameters():
        count = parameter.numel() * (2 if parameter.is_complex() else 1)
        if not parameter.requires_grad:
            frozen += count
            continue
        row = {
            "name": name,
            "shape": list(parameter.shape),
            "real_scalars": count,
            "missing": count,
            "zero": 0,
            "active": 0,
            "nonfinite": 0,
        }
        if parameter.grad is not None:
            values = parameter.grad.detach()
            if values.is_complex():
                values = torch.view_as_real(values.resolve_conj())
            finite = torch.isfinite(values)
            row.update(
                missing=0,
                zero=int((finite & (values == 0)).sum()),
                active=int((finite & (values != 0)).sum()),
                nonfinite=int((~finite).sum()),
            )
        records.append(row)
    return {
        "schema": "hcsn-gradient-activity-v1",
        "stage": "post_backward_pre_clip_pre_optimizer",
        "parameters": records,
        **{
            name: sum(row[name] for row in records)
            for name in ("real_scalars", "missing", "zero", "active", "nonfinite")
        },
        "frozen_real_scalars": frozen,
        "weight_decay_counted_as_gradient": False,
    }

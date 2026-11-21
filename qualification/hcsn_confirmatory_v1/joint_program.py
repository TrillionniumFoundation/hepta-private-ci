"""One-shot assistant program for an explicit outer dynamics/communication mask.

Inputs: public task specification, source semantics, incumbent weights. No labels,
loss feedback, search loop or optimizer. Heuristics are intentionally falsifiable;
dev may retain the incumbent. Preserve this source as the program artifact.
"""
import math


def apply_program(model, task):
    import torch
    flow = model.flow
    with torch.no_grad():
        if task == "first_passage":
            # Match the local drift's zero/linear term to observed physical drift.
            c = flow.encoder.config
            center = -c.base_drift / c.drift_scale
            flow.encoder.drive.weight.zero_()
            flow.encoder.drive.bias.fill_(math.atanh(center))
            flow.encoder.drive.weight[0, 1] = 1 / (c.drift_scale * (1 - center**2))
            # Compress large observed margins before bounded mark writing.
            flow.encoder.writer.weight[0].zero_()
            flow.encoder.writer.weight[0, 0] = .5
        elif task == "burst":
            # Raise event sensitivity to observed count while preserving bounds.
            flow.encoder.drive.weight[0, 0] = -2
            flow.boundary.weight[0, 0] = 2
            flow.encoder.writer.weight[0, 0] = 2
        elif task == "asynchronous":
            # Fuse two calibrated sensors using their known noise variances.
            reliability = .7**2
            flow.encoder.writer.weight[0].zero_()
            flow.encoder.writer.weight[0, 0] = 1 / (1 + reliability)
            flow.encoder.writer.weight[0, 1] = reliability / (.7 * (1 + reliability))
            flow.encoder.writer.weight[0, 3] = -.2 * reliability / (.7 * (1 + reliability))
            flow.encoder.drive.bias.fill_(.5)
        elif task == "association":
            # Suppress distractor-mark channels; reduce draining of stored marks.
            flow.encoder.writer.weight.zero_()
            flow.encoder.writer.bias.zero_()
            flow.encoder.writer.weight[0, 0] = 1
            flow.encoder.writer.weight[1, 1] = 1
            flow.encoder.drive.bias.fill_(.8)
        else:
            raise ValueError("unsupported public task")


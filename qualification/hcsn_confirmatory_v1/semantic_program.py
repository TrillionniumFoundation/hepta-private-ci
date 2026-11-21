"""Assistant-authored semantic program, frozen before observing task outcomes.

These are one-shot hypotheses, not loss-driven coordinate search or a claim of
MIT replication. No labels, residuals, optimizer, or evaluation callback enter.
All arms share the same explicit encoder prior; only the readout edit differs.
Discovery tokens, API cost and design time are UNKNOWN, not zero.
"""


def shared_encoder_prior(model, task):
    import torch
    with torch.no_grad():
        for p in model.parameters():
            p.zero_()
        model.encoder.writer.weight.copy_(torch.eye(4, dtype=torch.float64))
        if task == "first_passage":
            model.encoder.drive.weight[0, 1] = 1
            model.boundary.weight[0, 0] = -1
        elif task == "burst":
            model.encoder.drive.weight[0, 0] = -1
            model.boundary.weight[0, 0] = 1
        elif task == "asynchronous":
            model.encoder.writer.weight[1, 1] = 1 / .7
            model.encoder.writer.weight[1, 3] = -.2 / .7


def write_readout(task, names):
    # Event/risk evidence increases risk/count; signed marks carry sensor/value.
    rules = {
        "first_passage": {"last.risk": 1., "mean.risk": 1.},
        "burst": {"mean.event_rate": .25},
        "asynchronous": {"last.content_0": 2., "last.content_1": 2.,
                         "mean.content_0": 1., "mean.content_1": 1.},
        "association": {"mean.content_0": 2., "query.mean.content_1": 2.},
    }
    weights = [0.] * len(names)
    for name, value in rules[task].items():
        weights[names.index(name)] = value
    return weights, 0.


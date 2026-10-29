"""Full-parameter warm-up and literal reconstruction of its carried SGD state."""

import random

import numpy as np
import torch

from experiments.multimodal_output_portfolio.v6.neural import ACTIONS, parameter_hash
from .architecture import TrainablePortfolio
from .architecture_kernel import batch_digest, tape_seed, training_batches, update
from .architecture_state import capture, digest, read_checkpoint, restore


def optimizer_for(model, plan):
    return torch.optim.SGD(model.parameters(), lr=plan.learning_rate, momentum=plan.momentum,
                           dampening=0., weight_decay=0., nesterov=False, foreach=False, fused=False)


def load_generator_checkpoint(path, reference_root, plan):
    record = read_checkpoint(path)
    config = record["state"]["model_config"]
    if (config["hidden"] != plan.hidden or config["noise_scale"] != plan.noise_scale
            or record["metadata"]["plan_sha256"] != digest(plan.to_dict())):
        raise ValueError("Checkpoint differs from the frozen C execution plan")
    model = TrainablePortfolio(reference_root=reference_root, mode=config["mode"], seed=config["seed"],
                                hidden=config["hidden"], noise_scale=config["noise_scale"])
    optimizer = optimizer_for(model, plan)
    restore(model, optimizer, record["state"])
    return model, optimizer, record


def warmup(model, corpus, plan, seed, store, binding, role):
    store.work.phase = "warmup"
    store.check()
    common_rng = tape_seed(seed, "warmup-global", 0, 0, "rng")
    random.seed(common_rng)
    np.random.seed(common_rng % 2 ** 32)
    torch.manual_seed(common_rng)
    model.train()
    optimizer = optimizer_for(model, plan)
    initial = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    initial_sha = parameter_hash(model)
    gradient_seen, trace = set(), []
    work_before = store.work.snapshot()
    name = f"warmstarts/{model.config['mode']}-seed-{seed}"
    try:
        for step in range(plan.warmup_steps):
            store.check()
            batches = training_batches(corpus, plan, seed, 0, step, phase="warmup")
            noise = tape_seed(seed, "warmup", 0, step, "noise")
            actions = tuple(ACTIONS[(step + index) % 4] for index in range(step % 5))
            info = update(model, optimizer, None, batches, noise, actions, 1., plan,
                          store.work, gradient_seen=gradient_seen)
            trace.append({"step": step, "actions": list(actions), "noise_seed": noise,
                          "tape_identity": batch_digest(batches), **info})
        expected = {name for name, _ in model.named_parameters()}
        changed = {name for name, parameter in model.named_parameters()
                   if not torch.equal(parameter.detach(), initial[name])}
        if gradient_seen != expected or changed != expected:
            raise AssertionError("Every generator parameter must receive a nonzero gradient and change during warm-up")
        if any(parameter.grad is not None for parameter in model.parameters()):
            raise AssertionError("Declared microstep boundary did not clear gradients")
        state = capture(model, optimizer)
        metadata = {
            "schema": "hepta.fullstudy.C.warmstart.1", "seed": seed,
            "mode": model.config["mode"], "role": role, "config": model.config,
            "plan_sha256": digest(plan.to_dict()), "binding": binding,
            "initial_parameter_sha256": initial_sha, "parameter_sha256": parameter_hash(model),
            "warmup_steps": plan.warmup_steps, "optimizer_state_carried": True,
            "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
            "temporal_parameter_count": sum(parameter.numel() for name, parameter in model.named_parameters()
                                            if name.startswith(("text_encoder.", "text_decoder."))),
            "gradient_seen": sorted(gradient_seen), "changed_parameters": sorted(changed),
            "paired_tape_sha256": digest([{key: item[key] for key in ("step", "actions", "noise_seed", "tape_identity")}
                                           for item in trace]),
            "work_before": work_before, "work_after": store.work.snapshot(),
        }
        checkpoint = store.checkpoint(name + ".pt.gz", state, metadata)
        trace_artifact = store.json_gzip(name + ".trace.json.gz", {"metadata": metadata, "trace": trace})
        return {"seed": seed, "mode": model.config["mode"], "role": role,
                "checkpoint": checkpoint, "state_sha256": digest(state),
                "initial_parameter_sha256": initial_sha, "parameter_sha256": metadata["parameter_sha256"],
                "trace": trace_artifact, "metadata": metadata}
    except BaseException as error:
        failure = {"seed": seed, "mode": model.config["mode"], "role": role,
                   "error_type": type(error).__name__, "message": str(error),
                   "trace": trace, "work": store.work.snapshot()}
        try:
            store.checkpoint(name + ".failed-state.pt.gz", capture(model, optimizer), failure, failure_record=True)
            store.json_gzip(name + ".FAILED.json.gz", failure, failure_record=True)
        except BaseException as preservation_error:
            error.add_note("Warm-up failure preservation blocked: " + str(preservation_error))
        raise

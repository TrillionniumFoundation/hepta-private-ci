"""Current-state optimizer direction probes for a separately frozen H12 study.

No future parameter update or held-out outcome is evaluated. Incoming parameter
gradients, carried optimizer state, and global CPU Torch RNG are preserved.
"""

import hashlib
import json
import time

import numpy as np
import torch

from ..field_bridge_20261027.adapters import local_hash, local_parameters
from ..field_bridge_20261027.adaptation import fixed_output
from ..v6.data import make_batch
from .learning import P, optimizer_hash, update

DIRECTIONAL_NAMES = ("next_clipped_gradient_rms", "gradient_momentum_cosine",
                     "response_image_bce_derivative_along_v", "response_text_ce_derivative_along_v",
                     "clean_joint_loss_derivative_along_v")


def _tensor_hash(tensors):
    digest = hashlib.sha256()
    for tensor in tensors:
        if tensor is None:
            digest.update(b"none\0")
        else:
            digest.update(str((tuple(tensor.shape), str(tensor.dtype))).encode()+b"\0")
            digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def probe_losses(model, response, clean, fixed_action):
    """Exact three teacher-forced probe means used by the registered H7 map.

    Response image/text components share the same forward graphs. The caller
    retaining these graphs for two reverse passes must detach its direction.
    """
    if not response or not clean:
        raise ValueError("Training response and clean probe panels are required")
    losses = []
    for index, (_, batch) in enumerate(response):
        output = fixed_output(model, batch, fixed_action, 71027+index, teacher=True)
        losses.append(model.loss(output, batch.target))
    image = torch.stack([row["image_bce"].mean() for row in losses]).mean()
    text = torch.stack([row["text_ce"].mean() for row in losses]).mean()
    clean_output = fixed_output(model, clean[0][1], fixed_action, 81027, teacher=True)
    clean_joint = model.loss(clean_output, clean[0][1].target)["joint"].mean()
    return image, text, clean_joint


def measure_directional(model, original, optimizer, data, recipe, seed, schedule_id,
                        step, response, clean, fixed_action):
    """Measure five appended features before the common first future minibatch.

    v is the detached positive SGD buffer proposal beta*m+g, not the signed
    parameter step. Actual learning moves by -learning_rate*multiplier*v.
    If a parameter has no current gradient, SGD skips it and v is zero there.
    A missing initial momentum buffer is zero; zero-norm cosine is defined as 0.
    """
    if torch.is_inference_mode_enabled():
        raise ValueError("Directional probes require autograd, not inference_mode")
    if not isinstance(optimizer, torch.optim.SGD):
        raise TypeError("The directional contract supports the registered SGD only")
    parameters = local_parameters(model)
    groups = {}
    for group in optimizer.param_groups:
        if (group.get("weight_decay", 0) != 0 or group.get("dampening", 0) != 0
                or group.get("nesterov", False) or group.get("maximize", False)
                or group["momentum"] != P["momentum"]):
            raise ValueError("SGD semantics differ from the declared beta*m+g direction")
        for parameter in group["params"]:
            if id(parameter) in groups:
                raise ValueError("Duplicate optimizer parameter")
            groups[id(parameter)] = group
    if not parameters or set(groups) != {id(p) for p in parameters}:
        raise ValueError("Optimizer/local parameter inventory mismatch")
    before = dict(parameters=local_hash(model), optimizer=optimizer_hash(optimizer))
    incoming = [p.grad for p in parameters]
    incoming_hash = _tensor_hash(incoming)
    rng_before = torch.get_rng_state().clone()
    started = time.perf_counter_ns()
    batch_seed = seed*100003 + 600000 + schedule_id*1009 + step
    batch = make_batch(data, "train", P["batch_size"], batch_seed,
                       corruption=P["conditions"][step % 4])
    try:
        with torch.enable_grad():
            current_gradient = update(model, original, optimizer, batch, fixed_action,
                                      0., 107+step, recipe)
            gradients, momenta, directions = [], [], []
            active_gradient_parameters = 0
            for parameter in parameters:
                gradient = parameter.grad.detach().clone() if parameter.grad is not None else torch.zeros_like(parameter)
                buffer = optimizer.state.get(parameter, {}).get("momentum_buffer")
                momentum = buffer.detach().clone() if buffer is not None else torch.zeros_like(parameter)
                if parameter.grad is None:
                    direction = torch.zeros_like(parameter)
                elif buffer is None:
                    direction = gradient.clone()
                    active_gradient_parameters += 1
                else:
                    direction = momentum.clone().mul_(groups[id(parameter)]["momentum"]).add_(gradient)
                    active_gradient_parameters += 1
                gradients.append(gradient)
                momenta.append(momentum)
                directions.append(direction.detach())
            gradient_square = sum(float(g.double().square().sum()) for g in gradients)
            momentum_square = sum(float(m.double().square().sum()) for m in momenta)
            direction_square = sum(float(v.double().square().sum()) for v in directions)
            inner = sum(float((g.double()*m.double()).sum()) for g,m in zip(gradients,momenta,strict=True))
            cosine = inner/(gradient_square*momentum_square)**.5 if gradient_square*momentum_square > 0 else 0.
            # Roundoff can put a cosine an ulp outside its mathematical range.
            cosine = min(1., max(-1., cosine))
            values = list(probe_losses(model, response, clean, fixed_action))
            derivatives = []
            for index, loss in enumerate(values):
                probe = torch.autograd.grad(loss, parameters, retain_graph=index==0, allow_unused=True)
                derivatives.append(sum(float((g.detach().double()*v.double()).sum())
                    for g,v in zip(probe,directions,strict=True) if g is not None))
            features = [(gradient_square/sum(p.numel() for p in parameters))**.5, cosine, *derivatives]
            if not np.isfinite(features).all():
                raise FloatingPointError("Nonfinite directional feature")
            measured = dict(gradient_sha256=_tensor_hash(gradients),momentum_sha256=_tensor_hash(momenta),
                            direction_sha256=_tensor_hash(directions), gradient_l2=gradient_square**.5,
                            momentum_l2=momentum_square**.5,direction_l2=direction_square**.5,
                            gradient_momentum_dot=inner,proxy_loss_before_update=current_gradient["loss"],
                            unclipped_gradient_l2=current_gradient["gradient_norm"],
                            probe_values=[float(value.detach()) for value in values],
                            active_gradient_parameter_tensors=active_gradient_parameters)
    finally:
        for parameter, grad in zip(parameters,incoming,strict=True):
            parameter.grad = grad
    after = dict(parameters=local_hash(model), optimizer=optimizer_hash(optimizer))
    if (after != before or _tensor_hash([p.grad for p in parameters]) != incoming_hash
            or not torch.equal(rng_before,torch.get_rng_state())):
        raise RuntimeError("Directional measurement changed parameters, optimizer, incoming gradients, or global RNG")
    response_examples=sum(len(batch.source_ids) for _,batch in response)
    clean_examples=len(clean[0][1].source_ids)
    receipt = dict(schema="hepta.field-bridge-v2.directional-feature.v1", names=list(DIRECTIONAL_NAMES),
        features=features,seed=seed,schedule_id=schedule_id,step=step,batch_seed=batch_seed,noise_seed=107+step,
        next_batch_source_ids=batch.source_ids,parameter_sha256=before["parameters"],optimizer_sha256=before["optimizer"],
        state_grad_rng_invariant=True,incoming_gradient_sha256=incoming_hash,
        direction_convention="detached positive SGD buffer proposal beta*m+clipped_g; actual parameter motion is negative",
        measured=measured,wall_ns=time.perf_counter_ns()-started,
        resources=dict(next_gradient_forward_calls=1,next_gradient_forward_examples=P["batch_size"],
            next_gradient_backward_calls=1,next_gradient_backward_examples=P["batch_size"],
            teacher_forward_calls=1,teacher_forward_examples=P["batch_size"],
            response_probe_forward_calls=len(response),response_probe_forward_examples=response_examples,
            clean_probe_forward_calls=1,clean_probe_forward_examples=clean_examples,
            response_probe_reverse_calls=2,response_probe_reverse_examples=2*response_examples,
            clean_probe_reverse_calls=1,clean_probe_reverse_examples=clean_examples),
        cost_scope="additional five-feature measurement only; original H25/current-value probes and actual future updates excluded",
        derivative_unit="mean probe loss per unit positive v; no Hessian or optimizer-step multiplier included")
    return features, json.loads(json.dumps(receipt,allow_nan=False))

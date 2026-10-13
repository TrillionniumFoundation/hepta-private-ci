"""Candidate-only deep supervision of the EXISTING shared recurrent/readout core.

Same parameters, training rows, SGD minibatch stream and update budget as the
terminal-only reference. Extra readout/loss/backprop work is real and charged;
equal steps are NOT equal training compute. No new model owner or authority.
"""

from copy import deepcopy
import math

import torch
from torch.nn import functional as F

from development_ablation import PhaseClock, RecurrentClassifier, labels_checked
from development_tensors import checked_tensor, parameter_digest


def fit_anytime_candidate(initial, features, labels, *, steps=180, seed=13, lr=.02, depth_weights=None):
    checked_tensor(features, 3, 'frozen training observations')
    if (type(initial) is not RecurrentClassifier or type(steps) is not int or not 1 <= steps <= 1000
            or type(seed) is not int or type(lr) not in (int,float) or not math.isfinite(lr) or not 0 < lr <= 1
            or type(initial.depth) is not int or not 1 <= initial.depth <= initial.recurrence.maximum_depth
            or features.shape[-1] != initial.recurrence.width or features.shape[1] > 1024
            or features.dtype != initial.output.weight.dtype
            or sum(p.numel() for p in initial.parameters()) > 4_194_304):
        raise ValueError('invalid bounded anytime training')
    labels_checked(labels,len(features),initial.output.out_features)
    weights = (1.,)*initial.depth if depth_weights is None else depth_weights
    if (type(weights) is not tuple or len(weights) != initial.depth
            or any(type(w) not in (int,float) or not math.isfinite(w) or not 0 <= w <= 1 for w in weights)
            or sum(weights) <= 0):
        raise ValueError('invalid preregistered exit weights')
    normalizer = sum(weights)
    active = tuple((d,w/normalizer) for d,w in enumerate(weights) if w > 0)
    clock, identity = PhaseClock(), parameter_digest(initial)
    out = deepcopy(initial).train()
    parameters = [p for p in out.parameters() if p.requires_grad]
    if not parameters:
        raise ValueError('no trainable shared parameters')
    optimizer = torch.optim.SGD(parameters,lr=lr)
    rng = torch.Generator(device='cpu').manual_seed(seed)
    processed, first_losses, last_losses = 0, None, None
    for _ in range(steps):
        ids = torch.randperm(len(features),generator=rng)[:32]
        x,y = features[ids].detach().clone(), labels[ids].clone()
        mask = torch.ones(x.shape[:2],dtype=torch.bool)
        state = torch.zeros(len(x),x.shape[-1],dtype=x.dtype)
        _, states = out.recurrence(x,mask,state,depth=out.depth)
        losses = [(F.cross_entropy(out.output(states[d]),y),w) for d,w in active]
        loss = sum(value*weight for value,weight in losses)
        if not torch.isfinite(loss):
            raise ValueError('nonfinite anytime training loss')
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters,1.,error_if_nonfinite=True)
        optimizer.step()
        last_losses = [float(value.detach()) for value,_ in losses]
        if first_losses is None:
            first_losses = last_losses
        processed += len(ids)
    out.eval()
    if parameter_digest(initial) != identity:
        raise RuntimeError('selected model changed during candidate training')
    if any(not torch.isfinite(v).all() for v in out.state_dict().values()):
        raise ValueError('nonfinite learned shared parameters')
    return out, {'steps':steps,'examples_processed':processed,'cell_transitions':processed*out.depth,
                 'readout_rows':processed*len(active),'supervised_depths':[d+1 for d,_ in active],
                 'normalized_exit_weights':[w for _,w in active],
                 'initial_losses':first_losses,'last_losses':last_losses,
                 'trainable_parameters':sum(p.numel() for p in parameters),
                 'parameter_bytes':sum(p.numel()*p.element_size() for p in out.parameters()),
                 'source_model_digest':identity,'candidate_model_digest':parameter_digest(out),
                 'equal_actual_training_compute_claimed':False,**clock.finish(),'production_authorized':False}

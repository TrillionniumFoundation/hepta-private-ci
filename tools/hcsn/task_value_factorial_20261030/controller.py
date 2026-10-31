"""Identical NumPy critics; only the declared continuation target differs.

Both columns use masked Q regression, identical initialization/minibatches and
update counts. Myopic targets end at the current task FIRE; full targets include
the following task after reset/refractory. Neither column is production NDU.
"""
import hashlib
import time

import numpy as np

from .cells import augmented_features

ARMS = ("ordinary_myopic", "ordinary_value", "analytic_myopic", "analytic_value")


def parameters(seed, input_width, width):
    rng = np.random.default_rng(seed)
    return dict(w=rng.normal(0., 1/np.sqrt(input_width), (input_width, width)),
                b=np.zeros(width), v=rng.normal(0., 1/np.sqrt(width), (width, 4)), c=np.zeros(4))


def parameter_hash(weights):
    return hashlib.sha256(b"".join(np.asarray(weights[k], dtype="<f8").tobytes()
                                  for k in ("w", "b", "v", "c"))).hexdigest()


def forward(weights, x):
    hidden = np.tanh(x @ weights["w"]+weights["b"])
    return hidden @ weights["v"]+weights["c"], hidden


def loss_and_gradient(weights, x, target, mask, l2):
    predicted, hidden = forward(weights, x)
    denominator = max(1., float(mask.sum()))
    error = (predicted-target)*mask
    loss = float(np.square(error).sum()/denominator
                 +l2*sum(np.square(v).sum() for v in weights.values()))
    dq = 2*error/denominator
    dh = (dq @ weights["v"].T)*(1-hidden*hidden)
    gradients = dict(w=x.T@dh, b=dh.sum(0), v=hidden.T@dq, c=dq.sum(0))
    return loss, {k:g+2*l2*weights[k] for k,g in gradients.items()}


def normalization(records):
    raw = np.array([r["features"] for r in records], float)
    mean, scale = raw.mean(0), raw.std(0)
    scale[scale < 1e-8] = 1.
    return dict(mean=mean.tolist(), scale=scale.tolist(), split="TRAIN only")


def design(records, family, cell_parameters, norm):
    public = np.asarray([r["features"] for r in records], float)
    public = (public-np.asarray(norm["mean"]))/np.asarray(norm["scale"])
    recurrent = augmented_features(family, cell_parameters, records)
    return np.column_stack((public, (recurrent-.5)*2))


def validation_regret(weights, x, target, valid):
    prediction, _ = forward(weights, x)
    action = np.argmax(np.where(valid, prediction, -np.inf), axis=1)
    optimal = np.max(np.where(valid, target, -np.inf), axis=1)
    return float(np.mean(optimal-target[np.arange(len(target)), action]))


def train_controller(family, mode, seed, train, validation, cell_parameters, norm, protocol):
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    x = design(train, family, cell_parameters, norm)
    vx = design(validation, family, cell_parameters, norm)
    key = "q" if mode == "value" else "q_myopic"
    target = np.array([r[key] for r in train], float)
    valid = np.array([r["feasible"] for r in train], bool)
    vtarget = np.array([r[key] for r in validation], float)
    vvalid = np.array([r["feasible"] for r in validation], bool)
    weights = parameters(seed+protocol["critic_init_seed_base"], x.shape[1], protocol["critic_width"])
    initial_sha = parameter_hash(weights)
    first = {k:np.zeros_like(v) for k,v in weights.items()}
    second = {k:np.zeros_like(v) for k,v in weights.items()}
    rng = np.random.default_rng(seed+protocol["batch_seed_base"])
    losses, candidates, batch_bytes = [], [], bytearray()
    chosen, best = None, float("inf")
    for update in range(1, protocol["critic_updates"]+1):
        batch = rng.integers(0, len(train), protocol["batch_size"])
        batch_bytes.extend(batch.astype("<i8").tobytes())
        loss, gradients = loss_and_gradient(weights, x[batch], target[batch], valid[batch], protocol["critic_l2"])
        if not np.isfinite(loss) or not all(np.all(np.isfinite(g)) for g in gradients.values()):
            raise FloatingPointError("Critic training failed")
        norm_g = np.sqrt(sum(float(np.square(g).sum()) for g in gradients.values()))
        factor = min(1., protocol["gradient_clip"]/max(norm_g, 1e-15))
        for name in weights:
            gradient = gradients[name]*factor
            first[name] = .9*first[name]+.1*gradient
            second[name] = .999*second[name]+.001*gradient*gradient
            weights[name] -= protocol["learning_rate"]*(first[name]/(1-.9**update))/(np.sqrt(second[name]/(1-.999**update))+1e-8)
        losses.append(loss)
        if update in protocol["checkpoint_updates"]:
            regret = validation_regret(weights, vx, vtarget, vvalid)
            candidate = dict(update=update, validation_regret=regret,
                             parameter_sha256=parameter_hash(weights),
                             weights={k:v.tolist() for k,v in weights.items()})
            candidates.append(candidate)
            if regret < best:
                best, chosen = regret, candidate
    if chosen is None:
        raise ValueError("No declared checkpoint")
    result = {k:np.asarray(v, float) for k,v in chosen["weights"].items()}
    return result, dict(family=family, mode=mode, seed=seed,
        parameter_count=sum(v.size for v in weights.values()), initial_sha256=initial_sha,
        minibatch_sha256=hashlib.sha256(batch_bytes).hexdigest(), train_states=len(train),
        validation_states=len(validation), losses=losses, candidates=candidates,
        selected_update=chosen["update"], selected_sha256=chosen["parameter_sha256"],
        selected_validation_regret=best,
        cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall,
        target=key, objective="masked Q mean-square regression", updates=protocol["critic_updates"])


def choose(weights, family, cell_parameters, norm, record):
    x = design([record], family, cell_parameters, norm)
    q, _ = forward(weights, x)
    legal = np.asarray(record["feasible"], bool)
    action = int(np.argmax(np.where(legal, q[0], -np.inf)))
    return action, q[0].tolist()

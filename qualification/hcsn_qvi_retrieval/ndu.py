"""Shared finite retrieval environment with explicit admissible actions and costs."""

import numpy as np


STOP, READ, WAIT = range(3)
PRICE, RATE, RHO = 0.30, 0.40, 0.20


def actions_and_targets(free, paid, label, dt):
    free, paid, label, dt = map(np.asarray, (free, paid, label, dt))
    if (free.ndim != 3 or min(free.shape) < 1 or free.shape != paid.shape
            or free.shape[:2] != dt.shape or label.shape != (len(free),)
            or not np.isfinite(free).all() or not np.isfinite(paid).all()
            or not np.isfinite(dt).all() or (dt <= 0).any() or (label < 0).any()
            or (label >= free.shape[-1]).any()):
        raise ValueError("invalid aligned retrieval observations")
    ranks = np.stack([free.argmax(-1), paid.argmax(-1)], -1)
    correct = ranks == label[:, None, None]
    values = np.empty((*dt.shape, 3), dtype=np.float64)
    values[..., :2] = correct.astype(np.float64) - [0.0, PRICE]
    # At the last prefix WAIT is masked in every policy. A finite terminal
    # training target equal to STOP keeps a common multi-output ridge solve.
    values[:, -1, WAIT] = values[:, -1, STOP]
    for t in range(dt.shape[1] - 2, -1, -1):
        delta = dt[:, t + 1]
        disc = np.exp(-RHO * delta)
        values[:, t, WAIT] = disc * values[:, t+1].max(-1) + RATE * np.expm1(-RHO*delta) / RHO
    return values, correct


def policy_result(q, split):
    q = np.array(q, dtype=float, copy=True)
    if q.shape != (*split["dt"].shape, 3) or not np.isfinite(q).all():
        raise ValueError("invalid policy scores")
    q[:, -1, WAIT] = -np.inf
    act = q.argmax(-1)
    ends = (act != WAIT).argmax(1)
    i = np.arange(len(ends))
    action = act[i, ends]
    assert (action != WAIT).all()
    hit = split["correct"][i, ends, action]
    # The clock starts at the first available observation for every policy.
    times = split["dt"].cumsum(1) - split["dt"][:, :1]
    elapsed = times[i, ends]
    discount = np.exp(-RHO * elapsed)
    utility = discount * (hit.astype(float) - PRICE * (action == READ)) + RATE * np.expm1(-RHO*elapsed)/RHO
    group = np.asarray(split["group"])
    return {
        "utility":float(utility.mean()), "r1":float(hit.mean()),
        "per_actor":{str(k):float(utility[group == k].mean()) for k in np.unique(group)},
        "per_actor_r1":{str(k):float(hit[group == k].mean()) for k in np.unique(group)},
        "episodes":len(i), "reads":int((action == READ).sum()), "wait_steps":int(ends.sum()),
        "episode_utility":utility.tolist(), "hits":hit.astype(int).tolist(),
        "exit_prefix":ends.tolist(), "terminal_action":action.tolist()
    }


def worst_delta(result, reference):
    if result["per_actor"].keys() != reference["per_actor"].keys():
        raise ValueError("actor groups changed")
    return min(u-reference["per_actor"][a] for a,u in result["per_actor"].items())


def controls(split):
    scores = np.zeros_like(split["teacher"])
    scores[..., STOP] = 1
    return {"immediate_stop":policy_result(scores,split),
            "immediate_read":policy_result(scores[..., [1,0,2]],split),
            "hindsight_upper":policy_result(split["teacher"],split),
            "structurally_unretrievable":int((~split["correct"].any(axis=(1,2))).sum())}


class FiniteBellman:
    """TRAIN estimate of the external task intervention surface on observable margins."""

    def __init__(self, train):
        margins = self.margins(train)
        self.edges = np.quantile(margins,[0.25,0.5,0.75])
        bins = np.searchsorted(self.edges,margins)
        horizon=margins.shape[1]
        self.q = np.zeros((horizon,4,3))
        for t in reversed(range(horizon)):
            correct = train["correct"][:, t].astype(float)
            prior = correct.mean(0)
            if t < horizon-1:
                ds = train["dt"][:, t+1]
                discounts = np.exp(-RHO*ds)
                following = discounts*self.q[t+1,bins[:,t+1]].max(-1)+RATE*np.expm1(-RHO*ds)/RHO
            for b in range(4):
                mask = bins[:,t] == b
                self.q[t,b,:2]=(correct[mask].sum(0)+prior)/(mask.sum()+1)-[0,PRICE]
                self.q[t,b,WAIT]=self.q[t,b,STOP] if t==horizon-1 else (
                    following[mask].sum()+following.mean())/(mask.sum()+1)

    @staticmethod
    def margins(s):
        sorted_scores=np.sort(s["scores"],axis=-1)
        return sorted_scores[:,:,-1]-sorted_scores[:,:,-2]

    def predict(self, split):
        idx=np.searchsorted(self.edges,self.margins(split))
        return self.q[np.arange(idx.shape[1])[None,:],idx]

"""R8 width-scaled forward Stem. Inherited world and tree, new shared coefficients."""
from pathlib import Path
import sys
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'continuous'))
from domain import rule, make_problem, evaluate, SCALE
from problem import rollout
DT = torch.float64


class WidePolicy:
    def __init__(self, width, seed=11):
        if width not in (4, 16, 64, 256) or seed < 0:
            raise ValueError('unsupported width/seed')
        self.width = width
        r = np.random.default_rng(seed)
        self.initial = np.r_[r.normal(0, .03, 48), r.normal(0, .3, width*4),
                             r.normal(0, .03, width),
                             r.normal(0, .06*np.sqrt(4/width), 2*width), np.zeros(2)]

    def unpack(self, t):
        w = self.width
        return (t[:48].reshape(3, 2, 2, 4), t[48:48+4*w].reshape(w, 4),
                t[48+4*w:48+5*w], t[48+5*w:48+7*w].reshape(2, w), t[-2:])

    def tree(self, t, p, states):
        K, W, b, V, c = self.unpack(t)
        hidden = []
        def action(s, mode, k, bound):
            z = torch.tanh(s@W.T+b)
            hidden.append(z)
            a = torch.einsum('bij,bj->bi', K[k % 3, mode], s) + z@V.T+c
            return bound*torch.tanh(a/bound)
        result = rollout(t, p, states, policy=action)
        for level, z in zip(result[1], hidden):
            level['z'] = z
        return result

    def value(self, t, p, states, weights):
        v = self.tree(t, p, states)[0].reshape(-1, 2).mean(-1)
        return (v*torch.as_tensor(weights, dtype=DT)).sum()

    def adjoint(self, t, p, states, weights):
        if p.horizon != 3:
            raise ValueError('training horizon must be three')
        value, levels, tilts, terminal, lam = self.tree(t, p, states)
        q = p.tensors(); K, W, b, V, c = self.unpack(t); deltas = []
        for k in reversed(range(3)):
            L = levels[k]
            ex = (tilts[k][..., None]*lam.reshape(-1, 2, 2)).sum(1)
            du = q['action_cost'][L['mode'], None]*L['u'] + p.gamma*ex@q['B']
            d = du*(1-(L['u']/p.bound).square())
            dz = (d@V)*(1-L['z'].square())
            dh = torch.einsum('bi,bij->bj', d, K[k, L['mode'], :, :2])+dz@W[:, :2]
            lam = p.state_cost*L['h']+p.gamma*ex@q['A']+dh
            deltas.append(d)
        alpha = torch.as_tensor(weights, dtype=DT).repeat_interleave(2)/2
        gW, gb, gV, gc = torch.zeros_like(W), torch.zeros_like(b), torch.zeros_like(V), torch.zeros_like(c)
        gK = []
        for k, L in enumerate(levels):
            d = deltas[2-k]*alpha[:, None]
            gK.append(torch.stack([torch.einsum('bi,bj->ij', d*(L['mode']==m)[:, None], L['s']) for m in (0, 1)]))
            dz = (d@V)*(1-L['z'].square())
            gW = gW+dz.T@L['s']; gb = gb+dz.sum(0)
            gV = gV+d.T@L['z']; gc = gc+d.sum(0)
            alpha = (p.gamma*alpha[:, None]*tilts[k]).reshape(-1)
        grad = torch.cat((torch.stack(gK).flatten(), gW.flatten(), gb, gV.flatten(), gc))
        cost = (value.reshape(-1, 2).mean(-1)*torch.as_tensor(weights, dtype=DT)).sum()
        return cost, grad

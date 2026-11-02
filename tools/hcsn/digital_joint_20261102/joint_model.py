"""Complete conditional state, reset-aware forecast bank, and causal neural heads.

The mass is a model's conditional state distribution, not a supplied teacher
posterior. Learned unrestricted generators use projected nonnegative rates;
the physical renewal parameters retain their separate smooth parameterization.
"""
import copy
import hashlib
import json

import numpy as np
import torch
from torch import nn

from .joint_kernel import DifferentiableRenewalCell
from .joint_task import public_features

FAMILIES = ("renewal", "full_markov", "gru")
SCHEMA = "joint-policy-v1"
HEAD_SEED = 916000
CORE_SEED = 917000
THRESHOLDS = (-.5, 0., .5)


def nominal_raw(fit):
    return np.random.default_rng(CORE_SEED+int(fit)).normal(0., .025, 8)


def prior_mass(n_grid, distance):
    u = np.linspace(-1., 1., n_grid+2)[1:-1]
    mass = np.zeros(n_grid+2)
    mass[np.argmin(abs(u-distance))] += .5
    mass[np.argmin(abs(u+distance))] += .5
    return mass


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class FullGenerator(nn.Module):
    """All off-diagonal rates per drive, with an exact common nominal-Q start.

    Forward is linear in the rates. The optimizer projects rates after every
    update; feasible boundary derivatives require one-sided validation.
    """
    def __init__(self, raw, n_grid):
        super().__init__()
        nominal = DifferentiableRenewalCell(raw=raw, n_grid=n_grid)
        n = n_grid+2
        rows, columns = np.where(~np.eye(n, dtype=bool))
        self.register_buffer("rows", torch.as_tensor(rows, dtype=torch.long))
        self.register_buffer("columns", torch.as_tensor(columns, dtype=torch.long))
        self.rates = nn.Parameter(torch.stack([nominal.generator(drive, 1.).detach()[self.rows, self.columns] for drive in (-1, 0, 1)]))
        self.n_grid, self.n_states = n_grid, n

    def generator(self, drive):
        q = self.rates.new_zeros(self.n_states, self.n_states)
        q[self.rows, self.columns] = self.rates[int(drive)+1]
        return q-torch.diag(q.sum(-1))

    def transition(self, dt, drive, reliability=1.):
        return torch.matrix_exp(float(dt)*self.generator(drive))

    def project(self):
        with torch.no_grad():
            self.rates.clamp_min_(0.)


class Policy(nn.Module):
    """43 public + 33 mass + 9 scheduled forecasts -> 48 tanh -> 4 heads."""
    def __init__(self, family, fit, confusion, n_grid=31):
        super().__init__()
        if family not in FAMILIES or n_grid != 31:
            raise ValueError("registered family and 31-node active grid required")
        confusion = np.asarray(confusion, dtype=np.float64)
        if confusion.shape != (2, 2) or np.any(confusion <= 0) or not np.allclose(confusion.sum(1), 1.):
            raise ValueError("positive TRAIN-fitted decoder law required")
        self.family, self.fit, self.n_grid = family, int(fit), n_grid
        self.n_states = n_grid+2
        self.register_buffer("confusion", torch.as_tensor(confusion))
        coordinates = torch.tensor(np.r_[np.linspace(-1., 1., n_grid+2)[1:-1], -1., 1.], dtype=torch.float64)
        self.register_buffer("coordinates", coordinates)
        self.register_buffer("threshold_mask", torch.stack([(coordinates > k).to(torch.float64) for k in THRESHOLDS], -1))
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(HEAD_SEED+self.fit)
            self.head1 = nn.Linear(85, 48, dtype=torch.float64)
            self.head2 = nn.Linear(48, 4, dtype=torch.float64)
        raw = nominal_raw(self.fit)
        if family == "renewal":
            self.core = DifferentiableRenewalCell(raw=raw, n_grid=n_grid)
        elif family == "full_markov":
            self.core = FullGenerator(raw, n_grid)
        else:
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(CORE_SEED+self.fit)
                self.initial_hidden = nn.Linear(self.n_states, 64, dtype=torch.float64)
                self.recurrent = nn.GRUCell(5, 64, dtype=torch.float64)
                self.mass_decoder = nn.Linear(64, self.n_states, dtype=torch.float64)
                self.bank1 = nn.Linear(107, 32, dtype=torch.float64)
                self.bank2 = nn.Linear(32, 12, dtype=torch.float64)

    def emission(self, reliability):
        r = float(reliability)
        noise = self.confusion.new_tensor([[r, 1-r], [1-r, r]])
        return (noise @ self.confusion)[(self.coordinates > 0).long()]

    def transition(self, dt, drive, cache):
        key = float(dt), int(drive)
        tables = cache.setdefault("transitions", {})
        if key not in tables:
            tables[key] = self.core.transition(*key, reliability=1.)
        return tables[key]

    def representation(self, public, state, cache=None):
        cache = {} if cache is None else cache
        prefix = tuple((int(h["observation_tick"]), int(h["observation"]), float(h["reliability"])) for h in state["history"])
        public_array = public_features(public, state)
        key = public["id"], int(state["tick"]), prefix, tuple(public_array)
        complete = cache.setdefault("representations", {})
        if key in complete:
            return complete[key]
        mass = self.confusion.new_tensor(prior_mass(self.n_grid, public["prior_distance"]))
        observations = {h[0]: h[1:] for h in prefix}
        if self.family == "gru":
            hidden = torch.tanh(self.initial_hidden(mass))
        for i in range(state["tick"]):
            observation = observations.get(i+1)
            if self.family == "gru":
                flag = float(observation is not None)
                y, r = observation if observation is not None else (0, .5)
                event = mass.new_tensor([public["duration"][i]/2, public["drive"][i], flag, flag*(2*y-1), flag*(2*r-1)])
                hidden = self.recurrent(event, hidden)
                mass = torch.softmax(self.mass_decoder(hidden), -1)
            else:
                mass = mass @ self.transition(public["duration"][i], public["drive"][i], cache)
                if observation is not None:
                    y, r = observation
                    mass = mass*self.emission(r)[:, y]
                    mass = mass/mass.sum()
        pub = self.confusion.new_tensor(public_array)
        if self.family == "gru":
            bins = torch.softmax(self.bank2(torch.tanh(self.bank1(torch.cat((hidden, pub))))).reshape(3, 4), -1)
            bank = torch.stack((bins[:, 1:].sum(-1), bins[:, 2:].sum(-1), bins[:, 3]), -1).flatten()
        else:
            horizons = (min(state["tick"]+1, 6), min(state["tick"]+2, 6), 6)
            forecasts, future = {state["tick"]: mass @ self.threshold_mask}, mass
            for i in range(state["tick"], 6):
                future = future @ self.transition(public["duration"][i], public["drive"][i], cache)
                if i+1 in horizons:
                    forecasts[i+1] = future @ self.threshold_mask
            bank = torch.cat([forecasts[h] for h in horizons])
        complete[key] = mass, bank, pub
        return complete[key]

    def forward_row(self, public, state, cache=None):
        mass, bank, pub = self.representation(public, state, cache)
        output = self.head2(torch.tanh(self.head1(torch.cat((pub, mass, bank)))))
        p = torch.sigmoid(output[3])
        q = torch.stack((p*0., output[0], output[1], output[2], 1-2*p, 2*p-1))
        return dict(q=q, belief=p, mass=mass, bank=bank, logit=output[3])

    def forward_rows(self, rows):
        cache = {}
        outputs = [self.forward_row(r["public"], r["state"], cache) for r in rows]
        return {k: torch.stack([row[k] for row in outputs]) for k in outputs[0]}

    def project(self):
        if self.family == "full_markov":
            self.core.project()

    def head_identity(self):
        return identity({k: v.detach().tolist() for k, v in self.state_dict().items() if k.startswith("head")})

    def export(self, durations):
        with torch.no_grad():
            result = dict(schema=SCHEMA, family=self.family, fit=self.fit, n_grid=self.n_grid,
                          public_dimensions=43, head_dimensions=[85, 48, 4], coordinates=self.coordinates.tolist(),
                          confusion=self.confusion.tolist(), nominal_raw=nominal_raw(self.fit).tolist(),
                          network={},
                          bank_semantics="no-new-observation predictive state probability at next boundary, two boundaries and deadline6; thresholds normalized(-.5,0,.5), strict>; actual scheduled future drives and durations",
                          target="sign(X_deadline6)>0, including early submit; learned belief is not privileged posterior")
            result["network"] = {"w1": self.head1.weight.tolist(), "b1": self.head1.bias.tolist(), "w2": self.head2.weight.tolist(), "b2": self.head2.bias.tolist()}
            if self.family == "gru":
                result["core"] = dict(kind="gru", weights={k: v.tolist() for k, v in self.state_dict().items() if k.startswith(("initial_hidden", "recurrent", "mass_decoder", "bank1", "bank2"))},
                                      forecast_bank="three horizons, four-bin softmax each; tail sums yield the three ordered threshold probabilities")
            else:
                result["core"] = dict(kind="full_distribution_ctmc", tables=[dict(dt=float(dt), drive=drive,
                    matrix=self.core.transition(dt, drive, reliability=1.).tolist()) for dt in sorted(set(durations)) for drive in (-1, 0, 1)],
                    generators={str(d): (self.core.generator(d, 1.) if self.family == "renewal" else self.core.generator(d)).tolist() for d in (-1, 0, 1)},
                    raw=None if self.family != "renewal" else self.core.raw.tolist(),
                    physical=None if self.family != "renewal" else {k:float(v) for k,v in self.core.physical().items()},
                    optimizer_constraint="smooth bounded physical raw" if self.family == "renewal" else "nonnegative offdiagonal rates, projected AdamW")
            result["parameter_count"] = sum(p.numel() for p in self.parameters())
            return result


class NumpyPolicy:
    """Torch-free execution of the complete exported policy, including GRU gates."""
    def __init__(self, artifact):
        if artifact["schema"] != SCHEMA or artifact["public_dimensions"] != 43 or artifact["head_dimensions"] != [85, 48, 4]:
            raise ValueError("unsupported joint policy")
        self.artifact, self.family, self.n_grid = artifact, artifact["family"], int(artifact["n_grid"])
        self.confusion = np.asarray(artifact["confusion"])
        self.mask = np.stack([np.asarray(artifact["coordinates"]) > k for k in THRESHOLDS], -1)
        self.network = {k: np.asarray(v) for k,v in artifact["network"].items()}
        core = artifact["core"]
        if self.family == "gru":
            self.weights = {k: np.asarray(v) for k,v in core["weights"].items()}
        else:
            self.tables = {(r["dt"], r["drive"]): np.asarray(r["matrix"]) for r in core["tables"]}

    @staticmethod
    def sigmoid(value):
        return 1/(1+np.exp(-np.clip(value, -700, 700)))

    def linear(self, name, value):
        return self.weights[name+".weight"] @ value+self.weights[name+".bias"]

    def represent(self, public, state):
        mass = prior_mass(self.n_grid, public["prior_distance"])
        history = {h["observation_tick"]: h for h in state["history"]}
        if self.family == "gru":
            hidden = np.tanh(self.linear("initial_hidden", mass))
        for i in range(state["tick"]):
            observation = history.get(i+1)
            if self.family == "gru":
                flag = float(observation is not None)
                y, r = (observation["observation"], observation["reliability"]) if observation else (0, .5)
                event = np.array([public["duration"][i]/2, public["drive"][i], flag, flag*(2*y-1), flag*(2*r-1)])
                gi = self.weights["recurrent.weight_ih"] @ event+self.weights["recurrent.bias_ih"]
                gh = self.weights["recurrent.weight_hh"] @ hidden+self.weights["recurrent.bias_hh"]
                ir, iz, inn = np.split(gi, 3); hr, hz, hn = np.split(gh, 3)
                reset, update = self.sigmoid(ir+hr), self.sigmoid(iz+hz)
                candidate = np.tanh(inn+reset*hn); hidden = (1-update)*candidate+update*hidden
                log_mass = self.linear("mass_decoder", hidden)
                mass = np.exp(log_mass-log_mass.max()); mass /= mass.sum()
            else:
                mass = mass @ self.tables[(public["duration"][i], public["drive"][i])]
                if observation:
                    r, y = observation["reliability"], observation["observation"]
                    law = (np.array([[r, 1-r], [1-r, r]]) @ self.confusion)[(np.asarray(self.artifact["coordinates"]) > 0).astype(int)]
                    mass *= law[:, y]; mass /= mass.sum()
        pub = public_features(public, state)
        if self.family == "gru":
            logits = self.linear("bank2", np.tanh(self.linear("bank1", np.r_[hidden, pub]))).reshape(3, 4)
            bins = np.exp(logits-logits.max(-1, keepdims=True)); bins /= bins.sum(-1, keepdims=True)
            bank = np.stack((bins[:, 1:].sum(-1), bins[:, 2:].sum(-1), bins[:, 3]), -1).flatten()
        else:
            horizons = (min(state["tick"]+1, 6), min(state["tick"]+2, 6), 6)
            forecasts, future = {state["tick"]: mass @ self.mask}, mass
            for i in range(state["tick"], 6):
                future = future @ self.tables[(public["duration"][i], public["drive"][i])]
                if i+1 in horizons:
                    forecasts[i+1] = future @ self.mask
            bank = np.concatenate([forecasts[h] for h in horizons])
        return mass, bank, pub

    def predict(self, public, state):
        mass, bank, pub = self.represent(public, state)
        n = self.network
        out = n["w2"] @ np.tanh(n["w1"] @ np.r_[pub, mass, bank]+n["b1"])+n["b2"]
        p = float(self.sigmoid(out[3]))
        return dict(q=[0., *out[:3].tolist(), 1-2*p, 2*p-1], belief=p, mass=mass.tolist(), bank=bank.tolist(), logit=float(out[3]))

"""Torch-free NumPy execution of joint-policy-v1 JSON artifacts."""
import numpy as np
from .joint_task import public_features

SCHEMA = "joint-policy-v1"
THRESHOLDS = (-.5, 0., .5)


def prior_mass(n_grid, distance):
    u = np.linspace(-1., 1., n_grid+2)[1:-1]
    mass = np.zeros(n_grid+2)
    mass[np.argmin(abs(u-distance))] += .5
    mass[np.argmin(abs(u+distance))] += .5
    return mass


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

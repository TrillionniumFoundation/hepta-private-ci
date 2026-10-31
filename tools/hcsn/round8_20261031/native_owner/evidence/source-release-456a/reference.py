"""Independent SciPy matrix-exponential reference for the declared finite law.

The coefficients, active centers, task reset, and Erlang phases match immutable
e67a5e13 tools/hcsn/task_value_factorial_20261030/cells.py and propagation.py.
The Rust implementation uses positive uniformization, not SciPy's expm.
"""
import struct
import numpy as np
from scipy.linalg import expm
from scipy.special import expit


def coefficients(parameters, driver):
    p = np.asarray(parameters)
    h = (1.8 + .4*expit(p[3]))/3
    reset = -.3 + .2*expit(p[4])
    x = (reset+1)/h-.5
    left = int(np.floor(x))
    origin = np.zeros(5)
    origin[left:left+2] = [left+1-x, x-left]
    mu, sigma = .1+.8*expit(p[0]+p[1]*driver), .25+.25*expit(p[2])
    down, up = sigma*sigma/(2*h*h), sigma*sigma/(2*h*h)+mu/h
    q = np.zeros((5, 5))
    for i in range(3):
        if i:
            q[i, i-1] = down
        q[i, 4 if i == 2 else i+1] = up
    recovery = 2/(.3+.5*expit(p[5]))
    q[4, 3] = recovery
    q[3, :3] = recovery*origin[:3]
    q -= np.diag(q.sum(axis=1))
    rate = np.array([0, 0, up, 0, 0])
    return q, rate, origin


def decode(text):
    return struct.unpack(">d", bytes.fromhex(text))[0]


def features(parameters, family, state, driver, horizon):
    p = np.asarray(parameters)
    if family == "ordinary":
        rates = np.logaddexp(0, p[:6].reshape(2, 3) @ np.array([1, driver, driver*driver]))
        raw = np.r_[state, -np.expm1(-rates*horizon)]
    else:
        q, r, _ = coefficients(p, driver)
        a = np.zeros((6, 6)); a[:5, :5], a[:5, 5] = q, r
        count = float(state @ expm(horizon*a)[:5, 5])
        killed = q.copy(); killed[2, 4] = 0
        hit = 1-float(state @ expm(horizon*killed) @ np.ones(5))
        raw = np.array([state[:3] @ np.array([1/6, .5, 5/6]), state[3:].sum(), count/(1+count), hit])
    return np.r_[raw, expit(raw @ p[6:10]+p[10])]


class Reference:
    def __init__(self, parameters, family):
        self.p, self.family = np.asarray(parameters), family
        self.origin = coefficients(self.p, 0)[2]
        self.state = np.array([.5, .5]) if family == "ordinary" else self.origin.copy()
        self.events = 0.

    def advance(self, driver, duration, reset):
        if self.family == "ordinary":
            rates = np.logaddexp(0, self.p[:6].reshape(2, 3) @ np.array([1, driver, driver*driver]))
            retain = np.exp(-rates*duration)
            self.state = retain*self.state + (1-retain)*np.array([expit(2*driver), driver*driver])
            if reset:
                self.state = np.array([.5, .5])
        else:
            q, r, _ = coefficients(self.p, driver)
            a = np.zeros((6, 6)); a[:5, :5], a[:5, 5] = q, r
            flow = expm(duration*a)
            self.events += float(self.state @ flow[:5, 5])
            self.state = self.state @ flow[:5, :5]
            if reset:
                self.state = self.origin.copy()

    def query(self, driver, horizon):
        return features(self.p, self.family, self.state, driver, horizon)

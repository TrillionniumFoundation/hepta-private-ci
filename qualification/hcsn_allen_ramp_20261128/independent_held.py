"""Rebuild all held probabilities from raw waveforms, original spike times and sealed coefficients.

This verifier has no imports from either forecasting program or either compiled model.
It computes killed transition probabilities by differences of Gaussian upper tails.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.special import log_ndtr, ndtr

ROOT = Path(__file__).resolve().parent
DT = .002
EPS = 1.e-10


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get(path):
    return json.loads(path.read_text())


def transition_table(grid):
    """Return the three interior cell probabilities, the tail cell and absorption."""
    dt, sigma = .25, .23
    mu = np.linspace(-5., 5., 4097)[:, None, None]
    x = grid[None, :, None]
    edges = np.r_[0., .5*(grid[1:] + grid[:-1])][None, None, :]
    sd = sigma*math.sqrt(dt)
    alive_tail = ndtr((x + mu*dt - edges)/sd) - np.exp(
        log_ndtr((-x + mu*dt - edges)/sd) - 2.*x*mu/(sigma*sigma)
    )
    mass = np.concatenate((-np.diff(alive_tail, axis=2),
                           alive_tail[:, :, -1:], 1.-alive_tail[:, :, :1]), axis=2)
    assert mass.min() > -4.e-13 and np.max(np.abs(mass.sum(2)-1.)) < 1.e-12
    return np.maximum(0., mass)


def financial(current, count, law, table, arm, scale):
    grid, reset = law["grid"], law["reset"]
    price0, price1 = law["pmid"], law["pd"]
    u = np.tanh(current/scale)
    walls = np.log1p(law["kappa"].item()*u)
    drift = .03355 - .70*u + (np.r_[0., walls[:-1]]-walls)/.25
    centre = float(reset @ grid)
    state = reset.copy()
    equity = loss = 0.
    out = np.zeros(len(u))
    err = 0.
    for t in range(len(out)):
        v = drift[t]
        if arm in ("dual", "equity"):
            v += .65*math.tanh(max(0., equity))*(centre - float(state @ grid))
        if arm in ("dual", "loss"):
            v -= .65*math.tanh(max(0., loss))
        w = (v+5.)*409.6
        i = math.floor(w)
        assert 0 <= i < 4096
        a = w-i
        moved = state @ ((1.-a)*table[i] + a*table[i+1])
        err = max(err, abs(float(moved.sum())-1.))
        refractory = t > 0 and count[t-1] > 0
        h = EPS if refractory else min(1.-EPS, max(EPS, moved[-1]))
        out[t] = math.log(-math.log1p(-h))
        if count[t]:
            state = reset.copy()
            equity = loss = 0.
        else:
            state = reset.copy() if refractory else moved[:4]/moved[:4].sum()
            equity, loss = state @ (price0 + u[t]*price1)
    return out[:, None], err


def filtered(inp, tau):
    d = math.exp(-2./tau)
    out = np.empty(len(inp))
    v = 0.
    for t,k in enumerate(inp):
        v = d*v + (1.-d)*k
        out[t] = v
    return out


def feature(current, count, arm, opt, law, table):
    if arm in ("dual", "equity", "loss", "no_price"):
        return financial(current, count, law, table, arm, opt)
    if arm == "constant":
        return np.empty((len(current), 0)), 0.
    if arm == "glm":
        one = (count > 0).astype(float)
        x = current/100.
        return np.column_stack([x] + [filtered(x,s) for s in (5,20,80)] +
                               [filtered(np.r_[0.,one[:-1]],s) for s in (5,20,80)]), 0.
    assert arm == "lif"
    d = math.exp(-2./opt)
    v, out = 0., np.zeros(len(current))
    for t, k in enumerate(current):
        v = 0. if t and count[t-1] else d*v + (1.-d)*k/100.
        out[t] = v
    return out[:,None], 0.


def open_loop(current, seal):
    d = math.exp(-2./seal["tau"])
    leak = math.exp(-2./6.)
    v, carry, refractory = 0., 0., False
    emitted = np.zeros(len(current), dtype=np.uint8)
    filtered_events = np.empty(len(current))
    for t,k in enumerate(current):
        if refractory:
            v, refractory = 0., False
        else:
            v = d*v+(1.-d)*k
            if v >= seal["threshold"]:
                emitted[t], v, refractory = 1, 0., True
        carry = emitted[t] + leak*carry
        filtered_events[t] = carry
    base,gain = np.exp(seal["log_amplitudes"])
    return np.clip(-np.expm1(-base-gain*filtered_events), EPS, 1.-EPS), emitted


def main():
    src, result, hard = ROOT/"source", ROOT/"results", ROOT/"hard-lif"
    manifest = get(src/"cohort.json")
    seal = get(result/"seal.json")
    hard_seal = get(hard/"seal.json")["selected"]
    original = get(result/"terminal.json")
    hard_original = get(hard/"terminal.json")
    assert sha(src/"cohort.json") == seal["cohort_sha256"]
    assert sha(ROOT/"law4.npz") == seal["law_sha256"]
    with np.load(ROOT/"law4.npz") as z:
        law = dict(z)
    table = transition_table(law["grid"])
    maxp = {a: 0. for a in (*seal["models"],"hard")}
    sumloss = {a:{} for a in maxp}
    bins = sweeps = 0
    mass = 0.
    for sid in manifest["held"]:
        folder = src/str(sid)
        assert sha(folder/"signals-v2.npz") == manifest["input_hashes"][str(sid)]
        with np.load(folder/"signals-v2.npz") as data:
            for i,row in enumerate(get(folder/"attempt-v2.json")["sweeps"]):
                n, number = row["bins"], row["row"]["sweep_number"]
                raw = data["stimulus_native_"+str(i)].astype(np.float64)
                x = (raw.reshape(n,-1).mean(1)*row["current_multiplier_pA"]).astype(np.float32).astype(np.float64)
                s = data["spike_times_s_"+str(i)]
                y = np.bincount((s/DT).astype(int), minlength=n)
                assert len(x) == len(y) == n
                for arm in maxp:
                    if arm == "hard":
                        f = hard/f"{sid}-{number}.npz"
                        assert sha(f) == hard_original["raw_archives"][f.name]
                        p,events = open_loop(x,hard_seal)
                        with np.load(f) as z:
                            assert np.array_equal(events,z["hard_events"])
                    else:
                        reg = seal["models"][arm]["selected"]
                        f = result/f"{arm}-{sid}-{number}.npz"
                        assert sha(f) == original["raw_probability_files"][f.name]
                        X,e = feature(x,y,arm,reg["opt"],law,table);mass=max(mass,e)
                        eta = reg["weights"][0] + ((X-np.array(reg["mean"]))/np.array(reg["sd"])) @ np.array(reg["weights"][1:])
                        p = np.clip(-np.expm1(-np.exp(np.clip(eta,-35.,9.))),EPS,1.-EPS)
                        p[np.r_[False, y[:-1]>0]] = EPS
                    with np.load(f) as z:
                        maxp[arm] = max(maxp[arm],float(np.max(np.abs(p-z["probability"]))))
                    loss = float(-np.where(y>0,np.log(p),np.log1p(-p)).sum())
                    sums = sumloss[arm].setdefault(sid,[0.,0])
                    sums[0] += loss
                    sums[1] += n
                bins += n
                sweeps += 1
    nll_err = {}
    for arm in maxp:
        actual = sum(z[0]/(z[1]*DT) for z in sumloss[arm].values())/len(manifest["held"])
        expect = hard_original["metrics"][0] if arm=="hard" else original["metrics"][arm][0]
        nll_err[arm] = abs(actual-expect)
    assert max(maxp.values())<1.e-8 and max(nll_err.values())<1.e-6 and mass<1.e-11
    values = dict(held_specimens=len(manifest["held"]),sweeps=sweeps,bins_per_model=bins,probabilities=8*bins,
                  max_probability_error=maxp,max_step_mass_error=mass,specimen_balanced_nll_error=nll_err,
                  main_terminal_sha256=sha(result/"terminal.json"),hard_terminal_sha256=sha(hard/"terminal.json"))
    target=ROOT/"independent_verified.json"
    raw=(json.dumps(values,sort_keys=True,indent=2)+"\n").encode()
    if target.exists(): assert raw==target.read_bytes()
    else: target.write_bytes(raw)
    print(values,flush=True)


if __name__ == "__main__":
    main()

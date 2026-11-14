"""Independent true-spike path-likelihood gradient check and small training demo.

Two actual renewal neurons form a delayed count-feedback network. Cell1 emits
over window1; cell2's later drift is base+w*N1 and emits over window2. Both can
spike repeatedly, reset, and have deterministic refractory clocks. Parameters
a1 and w are learned from sampled paths using the score-function gradient.

The independent expectation reference uses the exact renewal identity
 P[N(T)>=k] = F(k*x,T-(k-1)*refractory; distance_drift=-a,sigma),
and a finite double sum over counts. The simulator is the K/S adapter separately
checked pathwise against the frozen v0 event engine. This proves a restricted
two-cell network gradient, not correctness of every future recurrent policy.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
import numpy as np
import torch

from rrsnn_experiments.runtime.event_runtime import first_hit_cdf
from .exact_rollout import ExactIndependentRollout

X = .8
SIGMA = .55
REFRACTORY = .15
HORIZON1 = 1.4
HORIZON2 = 1.6
BASE2 = .4
TARGET = 2.0
OUT = Path(__file__).resolve().parent/"results"


def renewal_count_pmf(drift, horizon):
    max_count = int(math.floor(horizon/REFRACTORY))+1
    tails = [1.0]
    for k in range(1, max_count+1):
        available = horizon-(k-1)*REFRACTORY
        tails.append(first_hit_cdf(k*X, available, -drift, SIGMA))
    tails.append(0.0)
    pmf = np.maximum(np.array(tails[:-1])-np.array(tails[1:]), 0)
    assert abs(pmf.sum()-1) < 1e-12
    return pmf


def exact_objective(a1, weight):
    p1 = renewal_count_pmf(a1, HORIZON1)
    objective = 0.0
    for count1, mass in enumerate(p1):
        p2 = renewal_count_pmf(BASE2+weight*count1, HORIZON2)
        objective += mass*np.dot(p2, (np.arange(len(p2))-TARGET)**2)
    return float(objective)


def finite_difference_objective(a1, weight, epsilon=1e-5):
    return np.array([
        (exact_objective(a1+epsilon,weight)-exact_objective(a1-epsilon,weight))/(2*epsilon),
        (exact_objective(a1,weight+epsilon)-exact_objective(a1,weight-epsilon))/(2*epsilon),
    ])


def sample_paths(drifts, horizon, seed):
    drifts = np.atleast_1d(np.asarray(drifts, dtype=float))
    engine = ExactIndependentRollout(np.zeros(len(drifts)), drift=drifts,
        sigma=SIGMA, threshold=X, reset=0, refractory=REFRACTORY, seed=seed)
    engine.advance_to(horizon)
    last = np.zeros(len(drifts))
    waits, owners = [], []
    for event in engine.emissions:
        previous_active_start = last[event.component]
        waits.append(event.time-previous_active_start)
        owners.append(event.component)
        last[event.component] = event.time+REFRACTORY
    censor = np.maximum(horizon-last, 0)
    assert np.all(np.array(waits) > 0)
    return {"counts": engine.count.copy(), "waits": np.asarray(waits),
            "owners": np.asarray(owners, dtype=np.int64), "censor": censor}


def log_path_likelihood(drift, paths):
    """Joint observed spike-time likelihood with right censoring.

    The terminal endpoint is integrated out, hence logS. If an endpoint is
    included as a latent state, its contribution must be logK instead, not the
    normalized log(K/S) alone. Refractory intervals contribute no random factor.
    """
    waits = torch.as_tensor(paths["waits"], dtype=torch.float64)
    owners = torch.as_tensor(paths["owners"], dtype=torch.int64)
    duration = torch.as_tensor(paths["censor"], dtype=torch.float64)
    d = drift[owners]
    log_density = (math.log(X/SIGMA)-.5*math.log(2*math.pi)-1.5*torch.log(waits)
                   -(X-d*waits)**2/(2*SIGMA**2*waits))
    result = torch.zeros_like(drift).scatter_add(0, owners, log_density)
    safe = duration.clamp(min=1e-12)
    scale = SIGMA*torch.sqrt(safe)
    log_first = torch.special.log_ndtr((-X+drift*safe)/scale)
    log_second = 2*drift*X/SIGMA**2+torch.special.log_ndtr((-X-drift*safe)/scale)
    log_f = torch.logaddexp(log_first, log_second).clamp(max=-1e-14)
    log_survival = torch.log(-torch.expm1(log_f))
    return result+torch.where(duration>0,log_survival,torch.zeros_like(log_survival))


def sample_network(a1, weight, n, seed):
    p1 = sample_paths(np.full(n,a1), HORIZON1, seed)
    p2 = sample_paths(BASE2+weight*p1["counts"], HORIZON2, seed+100_000)
    return p1,p2


def gradient_audit():
    a1, weight, n = .9,.35,32768
    p1,p2 = sample_network(a1,weight,n,73001)
    d1 = torch.full((n,),a1,dtype=torch.float64,requires_grad=True)
    d2 = torch.tensor(BASE2+weight*p1["counts"],dtype=torch.float64,requires_grad=True)
    score1 = torch.autograd.grad(log_path_likelihood(d1,p1).sum(),d1)[0].numpy()
    score2 = torch.autograd.grad(log_path_likelihood(d2,p2).sum(),d2)[0].numpy()
    scores = np.column_stack([score1,score2*p1["counts"]])
    cost = (p2["counts"]-TARGET)**2
    truth = exact_objective(a1,weight)
    # An exact scalar baseline is used only for this gradient diagnostic.
    # Actual training below uses an EMA from preceding batches.
    samples = (cost-truth)[:,None]*scores
    expected_gradient = finite_difference_objective(a1,weight)
    estimate = samples.mean(axis=0)
    se = samples.std(axis=0,ddof=1)/np.sqrt(n)
    z = (estimate-expected_gradient)/se
    assert np.all(np.abs(z)<4), (estimate,expected_gradient,se,z)
    # A pathwise AD/finite-difference check of both parameter directions.
    subset = 64
    q1,q2 = sample_network(a1,weight,subset,74001)
    params = torch.tensor([a1,weight],dtype=torch.float64,requires_grad=True)
    counts1 = torch.as_tensor(q1["counts"],dtype=torch.float64)
    likelihood = (log_path_likelihood(params[0].expand(subset),q1)+
                  log_path_likelihood(BASE2+params[1]*counts1,q2)).mean()
    ad = torch.autograd.grad(likelihood,params)[0].numpy()
    eps = 1e-5
    def held_path_likelihood(av,wv):
        return float((log_path_likelihood(torch.full((subset,),av,dtype=torch.float64),q1)+
            log_path_likelihood(BASE2+wv*counts1,q2)).mean())
    fd = np.array([(held_path_likelihood(a1+eps,weight)-held_path_likelihood(a1-eps,weight))/(2*eps),
                   (held_path_likelihood(a1,weight+eps)-held_path_likelihood(a1,weight-eps))/(2*eps)])
    assert np.max(np.abs(ad-fd)) < 1e-6
    pmf1 = renewal_count_pmf(a1,HORIZON1)
    ref_count1 = float(np.dot(np.arange(len(pmf1)),pmf1))
    count1_se = float(p1["counts"].std(ddof=1)/np.sqrt(n))
    assert abs(p1["counts"].mean()-ref_count1)<4*count1_se
    return {"parameters":{"a1":a1,"weight":weight},"paths":n,
        "exact_expected_cost":truth,"sampled_cost_mean":float(cost.mean()),
        "sampled_cost_standard_error":float(cost.std(ddof=1)/np.sqrt(n)),
        "exact_expectation_gradient_by_finite_difference":expected_gradient.tolist(),
        "path_score_gradient_estimate":estimate.tolist(),"gradient_standard_error":se.tolist(),
        "gradient_z_scores":z.tolist(),"mean_scores":scores.mean(axis=0).tolist(),
        "score_standard_error":(scores.std(axis=0,ddof=1)/np.sqrt(n)).tolist(),
        "held_path_autodiff_gradient":ad.tolist(),"held_path_finite_difference_gradient":fd.tolist(),
        "maximum_held_path_gradient_error":float(np.max(np.abs(ad-fd))),
        "first_cell_count_mean_mc":float(p1["counts"].mean()),
        "first_cell_count_mean_renewal_identity":ref_count1,
        "first_cell_count_mean_standard_error":count1_se,
        "repeat_spike_fraction_first_cell":float(np.mean(p1["counts"]>=2)),
        "repeat_spike_fraction_second_cell":float(np.mean(p2["counts"]>=2)),
        "convergence_prefixes":[{"n":size,"gradient":samples[:size].mean(axis=0).tolist(),
            "standard_error":(samples[:size].std(axis=0,ddof=1)/np.sqrt(size)).tolist()}
            for size in (2048,8192,n)]}


def training_demo(seed, steps=48, batch=512):
    # These bounded parameters define the stochastic physical network; there
    # is no hard-event surrogate or pathwise derivative through integer counts.
    initial_a1, initial_w = .55,.12
    p0 = (initial_a1-.15)/1.5
    w0 = (initial_w-.02)/.6
    theta = torch.tensor([math.log(p0/(1-p0)),math.log(w0/(1-w0))],
                         dtype=torch.float64,requires_grad=True)
    optimizer = torch.optim.Adam([theta],lr=.08)
    baseline = 0.0
    records = []
    finite = True
    for step in range(steps):
        a1 = .15+1.5*torch.sigmoid(theta[0])
        weight = .02+.6*torch.sigmoid(theta[1])
        p1,p2 = sample_network(float(a1.detach()),float(weight.detach()),batch,
                              seed+step*1000)
        costs = torch.as_tensor((p2["counts"]-TARGET)**2,dtype=torch.float64)
        counts1 = torch.as_tensor(p1["counts"],dtype=torch.float64)
        log_probability = (log_path_likelihood(a1.expand(batch),p1)+
                           log_path_likelihood(BASE2+weight*counts1,p2))
        loss = ((costs-baseline).detach()*log_probability).mean()
        optimizer.zero_grad();loss.backward()
        finite = finite and bool(torch.isfinite(theta.grad).all())
        assert finite
        optimizer.step()
        baseline = .9*baseline+.1*float(costs.mean())
        if step==0 or (step+1)%8==0:
            records.append({"step":step+1,"a1":float(a1.detach()),"weight":float(weight.detach()),
                            "sampled_cost":float(costs.mean()),
                            "exact_expected_cost":exact_objective(float(a1.detach()),float(weight.detach()))})
    final_a1 = float((.15+1.5*torch.sigmoid(theta[0])).detach())
    final_w = float((.02+.6*torch.sigmoid(theta[1])).detach())
    initial_cost, final_cost = exact_objective(initial_a1,initial_w),exact_objective(final_a1,final_w)
    assert final_cost<initial_cost
    return {"seed":seed,"steps":steps,"batch_paths":batch,"mode":"sampled true spike paths with score-function gradient",
        "parameters_initial":[initial_a1,initial_w],"parameters_final":[final_a1,final_w],
        "initial_exact_expected_cost":initial_cost,"final_exact_expected_cost":final_cost,
        "all_gradients_finite":finite,"training_history":records,
        "checkpoint_selection":"Fixed final update; no oracle/validation selection.",
        "baseline":"EMA of previous sampled batches; independent of current batch before update."}


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    begun = time.perf_counter()
    OUT.mkdir(parents=True,exist_ok=True)
    audit = gradient_audit()
    print(json.dumps({"stage":"gradient_audit","z_scores":audit["gradient_z_scores"]}),flush=True)
    trains = []
    for seed in (75101,75211,75307):
        result = training_demo(seed)
        trains.append(result)
        print(json.dumps({"stage":"training","seed":seed,
            "initial":result["initial_exact_expected_cost"],"final":result["final_exact_expected_cost"]}),flush=True)
    report = {"schema":"rrsnn.true-spike-path-gradient.v1","gradient_audit":audit,
        "sampled_training":trains,"elapsed_seconds":time.perf_counter()-begun,
        "physical_model":{"distance":X,"sigma":SIGMA,"deterministic_refractory":REFRACTORY,
                          "window1":HORIZON1,"window2":HORIZON2,"base_drift_cell2":BASE2,
                          "connection":"Cell2 later drift=base+weight*actual_count_cell1",
                          "cost":"(actual_count_cell2-2)^2"},
        "limitations":["Two-cell delayed count-feedback toy, not the full resource policy or a generally recurrent continuous synaptic network.",
                       "A path-likelihood estimator can have high variance; passing this test is not a guarantee of efficient large-scale learning.",
                       "The independent expectation identity assumes constant coefficients within each neuron window and fixed reset/refractory.",
                       "Censor log survival uses float64 and clips unresolved F>=1-1e-14; sampled tested cases remain in resolved regimes.",
                       "No claim that density-mean training equals this sampled training objective."]}
    (OUT/"path_score_gradient.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")


if __name__=="__main__":
    main()

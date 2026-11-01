"""Independent gradient, killed-process, and grid-action checks of R12."""

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from scipy.integrate import fixed_quad
from scipy.linalg import expm
from scipy.optimize import brentq
from scipy.special import ndtr

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent
sys.path.insert(0, str(SOURCE))
import contract
import data
import models
from control.controller import plan

torch.set_num_threads(1)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, payload):
    path = ROOT / name
    if path.exists():
        raise ValueError(f"Evidence already exists: {path}")
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")


def prepare():
    if "/ 0.1" not in (SOURCE / "contract.py").read_text():
        raise ValueError("Wait for the fixed physical reset-width implementation")
    write("PROTOCOL.json", dict(
        sources={name: sha(SOURCE / name) for name in ["contract.py", "models.py", "data.py", "control/controller.py"]},
        dtype="torch.float64 throughout; no FP32 or second-order-AD claim",
        gradient_cases=[dict(name="regular", seed=811, length=12, dt=[.15, .45, 1.05], raw_shift=[0., 0., 0.]),
                        dict(name="long_bayes", seed=812, length=64, dt=[.05, .75, 2.1], raw_shift=[1., -1., 1.]),
                        dict(name="near_boundary_reset", seed=813, length=48, dt=[.01, .05, .2], raw_shift=[0., 0., 0.])],
        gradient_steps=[1e-4, 5e-5, 1e-5], gradient_indices=[0, 1, 2, 3, 10], gradient_scaled_gate=2e-6,
        first_hit=dict(grids=[8, 16, 32], means=[.05, .2, .6], width=.03, times=[.05, .45, 2.1, 10.],
                       upper=.8, spectrum_terms=[256, 512], quadrature_nodes=160),
        actions=dict(grids=[8, 16, 32, 64], means=[.04, .2, .6], widths=[.03, .1],
                     bit_probabilities=np.linspace(.5, .95, 19).tolist(), times=[.05, .45, 2.1],
                     horizon=3, budget=2, time_cost=.01),
        scope="Finite mechanistic development scan. No confirmation episodes, no continuous-regret certification."))


def gradients():
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    rows = []
    saved_asset = contract.PROTOCOL["reset_asset"]
    base = contract.initial_raw().numpy()
    logits = np.log(np.array([[.45, .25, .15, .07, .05, .03], [.03, .05, .07, .15, .25, .45]]))
    for case in protocol["gradient_cases"]:
        if case["name"] == "near_boundary_reset":
            with torch.no_grad():
                boundary = float(contract.model_terms(prices=False)["boundary"])
            contract.PROTOCOL["reset_asset"] = boundary * np.exp(1e-7)
        else:
            contract.PROTOCOL["reset_asset"] = saved_asset
        world = contract.true_model()
        batch_raw = data.sequences(case["seed"], 3, world, case["dt"], case["length"])
        batch = data.tensors(batch_raw)
        vector = np.r_[base + case["raw_shift"], logits.ravel()]

        def loss_at(v, derivative=False):
            model = models.DistributionCell()
            with torch.no_grad():
                model.raw.copy_(torch.tensor(v[:3], dtype=torch.float64))
                model.logits.copy_(torch.tensor(v[3:].reshape(2, 6), dtype=torch.float64))
            predicted = model(batch["dt"], batch["tokens"], batch["observed"])
            loss, ce, content = models.objective(predicted, batch)
            grad = torch.autograd.grad(loss, [model.raw, model.logits]) if derivative else None
            return float(loss.detach()), (None if grad is None else np.r_[grad[0].numpy(), grad[1].numpy().ravel()]), dict(
                posterior_ce=float(ce.detach()), content_ce=float(content.detach()),
                probability_min=float(predicted.detach().min()), mass_error=float((predicted.sum(-1) - 1).abs().max().detach()))

        loss, analytic, diagnostics = loss_at(vector, True)
        finite = []
        for h in protocol["gradient_steps"]:
            for i in protocol["gradient_indices"]:
                plus, minus = vector.copy(), vector.copy()
                plus[i] += h
                minus[i] -= h
                fd = (loss_at(plus)[0] - loss_at(minus)[0]) / (2 * h)
                err = abs(fd - analytic[i]) / max(1., abs(fd), abs(analytic[i]))
                finite.append(dict(index=i, step=h, central_difference=fd, analytic=float(analytic[i]), scaled_error=err))
        # Q uses sigma and one boundary/reset location: inspect the rank directly.
        q_columns = []
        for i in range(3):
            plus, minus = vector[:3].copy(), vector[:3].copy()
            plus[i] += 1e-5
            minus[i] -= 1e-5
            qplus = contract.model_terms(torch.tensor(plus), prices=False)["Q"].detach().numpy()
            qminus = contract.model_terms(torch.tensor(minus), prices=False)["Q"].detach().numpy()
            q_columns.append(((qplus - qminus) / 2e-5).ravel())
        singular = np.linalg.svd(np.asarray(q_columns).T, compute_uv=False)
        row = dict(case=case, reset_asset=contract.PROTOCOL["reset_asset"], vector=vector.tolist(),
                   loss=loss, analytic_gradient=analytic.tolist(), finite_differences=finite,
                   Q_parameter_jacobian_singular_values=singular.tolist(), diagnostics=diagnostics,
                   batch={key: value.tolist() for key, value in batch_raw.items()},
                   passed=bool(max(x["scaled_error"] for x in finite) <= protocol["gradient_scaled_gate"]))
        rows.append(row)
        print(case["name"], "gradient", max(x["scaled_error"] for x in finite), "Q singular values", singular, flush=True)
    contract.PROTOCOL["reset_asset"] = saved_asset
    # Directly exercise the ten-input bridge at positive distances close to zero.
    bridge = []
    for x in (1e-8, 1e-4, .2):
        theta = torch.tensor(contract.PROTOCOL["baseline_financial_parameters"], dtype=torch.float64, requires_grad=True)
        state = torch.tensor(x, dtype=torch.float64, requires_grad=True)
        weights = theta.new_tensor([.02, .01, .3, -.2, .02])
        scalar = contract.FinancialOutputs.apply(theta, state) @ weights
        g = torch.autograd.grad(scalar, [theta, state])
        checks = []
        for i in (2, 5, 6, 9):
            h = min(1e-5, x / 4) if i == 9 else 1e-5 * max(.01, abs(float(theta[i].detach())))
            vp, vm = np.r_[theta.detach().numpy(), x], np.r_[theta.detach().numpy(), x]
            vp[i] += h
            vm[i] -= h
            def call(v):
                return float(contract.FinancialOutputs.apply(torch.tensor(v[:9]), torch.tensor(v[-1])) @ weights)
            fd = (call(vp) - call(vm)) / (2 * h)
            analytic = float(g[1] if i == 9 else g[0][i])
            checks.append(dict(index=i, step=h, finite=fd, analytic=analytic,
                               scaled_error=abs(fd - analytic) / max(1., abs(fd), abs(analytic))))
        bridge.append(dict(log_distance=x, checks=checks))
    write("GRADIENTS.json", dict(rows=rows, bridge=bridge, protocol_sha256=sha(ROOT / "PROTOCOL.json"),
          sources_after={name: sha(SOURCE / name) for name in protocol["sources"]}))


def phase_law(n, mean, width, upper=.8):
    edges = np.linspace(0, upper, n + 1)
    mass = np.diff(ndtr((edges - mean) / width))
    return mass / mass.sum()


def physical_average(function, mean, width, upper=.8):
    norm = ndtr((upper - mean) / width) - ndtr(-mean / width)
    return float(fixed_quad(lambda x: function(x) * np.exp(-.5 * ((x - mean) / width) ** 2)
                           / (np.sqrt(2 * np.pi) * width * norm), 0, upper, n=160)[0])


def hit_unbounded(x, t, mu, sigma):
    st = sigma * np.sqrt(t)
    return ndtr((-x - mu * t) / st) + np.exp(-2 * mu * x / sigma ** 2) * ndtr((-x + mu * t) / st)


def reflected_spectrum(mu, sigma, upper, count):
    beta, diffusion = mu / sigma ** 2, sigma ** 2 / 2
    if not 0 < beta * upper < 1:
        raise ValueError("This independent spectrum only covers 0 < beta*L < 1")
    roots = np.array([brentq(lambda z: z / np.tan(z) - beta * upper,
                             j*np.pi + 1e-10, (j+.5)*np.pi - 1e-10, xtol=1e-13)
                      for j in range(count)]) / upper
    norm = upper / 2 - np.sin(2 * roots * upper) / (4 * roots)
    coefficients = roots / ((beta ** 2 + roots ** 2) * norm)
    def hit(x, t):
        xx = np.asarray(x)
        survival = np.exp(-beta * xx) * np.sum((coefficients * np.exp(-diffusion * (roots ** 2 + beta ** 2) * t))[:, None]
                                               * np.sin(roots[:, None] * xx.ravel()[None]), axis=0).reshape(xx.shape)
        return 1 - survival
    return hit


def first_hit():
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    cfg = protocol["first_hit"]
    theta = np.asarray(contract.PROTOCOL["baseline_financial_parameters"])
    sigma, mu = theta[2], theta[0] - theta[1] - theta[2] ** 2 / 2
    spectra = {n: reflected_spectrum(mu, sigma, cfg["upper"], n) for n in cfg["spectrum_terms"]}
    rows = []
    for n in cfg["grids"]:
        world = contract.true_model(n)
        killed = world["Q"][:n, :n]
        spacing = cfg["upper"] / n
        corrected = killed.copy()
        corrected[0, 0] -= sigma ** 2 / (2 * spacing ** 2)
        for t in cfg["times"]:
            finite, candidate = expm(t * killed), expm(t * corrected)
            regenerative = expm(t * world["Q"])
            for mean in cfg["means"]:
                law = phase_law(n, mean, cfg["width"])
                original = 1 - float(law @ finite @ np.ones(n))
                corrected_hit = 1 - float(law @ candidate @ np.ones(n))
                continuum = physical_average(lambda x: spectra[512](x, t), mean, cfg["width"])
                low = physical_average(lambda x: spectra[256](x, t), mean, cfg["width"])
                infinite = physical_average(lambda x: hit_unbounded(x, t, mu, sigma), mean, cfg["width"])
                initial = np.r_[law, np.zeros(2), np.zeros(n+2)]
                indices = [n, n+1, 2*n+2, 2*n+3]
                occupancy = float((initial @ regenerative)[indices].sum())
                rows.append(dict(n_active=n, t=t, physical_mean=mean, physical_width=cfg["width"],
                    finite_killed_hit=original, half_cell_candidate_hit=corrected_hit,
                    reflected_continuum_hit=continuum, unbounded_continuum_hit=infinite,
                    grid_error=original-continuum, half_cell_grid_error=corrected_hit-continuum,
                    upper_domain_error=continuum-infinite, spectral_256_512_difference=abs(low-continuum),
                    regenerative_recovery_occupancy=occupancy))
    write("FIRST_HIT.json", dict(rows=rows, mu=mu, sigma=sigma, source_sha256=sha(SOURCE / "contract.py"),
          boundary_candidate="Only first active diagonal gains D/h^2 killing; actual root Q is unchanged.",
          method="Robin eigenfunction expansion of backward diffusion with absorb0/reflectL; exact Phi unbounded reference"))
    for n in cfg["grids"]:
        part = [r for r in rows if r["n_active"] == n]
        print("grid", n, "max error", max(abs(r["grid_error"]) for r in part), "half-cell", max(abs(r["half_cell_grid_error"]) for r in part), flush=True)


def actions():
    cfg = json.loads((ROOT / "PROTOCOL.json").read_text())["actions"]
    records = []
    for n in cfg["grids"]:
        world = contract.true_model(n)
        for dt in cfg["times"]:
            beliefs, contexts = [], []
            for mean in cfg["means"]:
                for width in cfg["widths"]:
                    phase = np.r_[phase_law(n, mean, width), np.zeros(2)]
                    for p0 in cfg["bit_probabilities"]:
                        contexts.append(dict(dt=dt, mean=mean, width=width, p0=p0))
                        beliefs.append(np.r_[p0 * phase, (1-p0) * phase])
            planned = plan(np.array(beliefs), expm(dt*world["Q"]), world["emission"], world["answer_rewards"], world["read_cost"],
                           horizon=cfg["horizon"], budget=cfg["budget"], time_cost=cfg["time_cost"], dt=dt)
            for i, context in enumerate(contexts):
                records.append(dict(**context, n_active=n, action=int(planned.action[i]), qvalues=planned.qvalues[i].tolist()))
        print("actions done", n, flush=True)
    key = lambda r: (r["dt"], r["mean"], r["width"], r["p0"])
    reference = {key(r): r for r in records if r["n_active"] == 64}
    summaries = []
    for n in cfg["grids"][:-1]:
        mismatches = []
        for row in (r for r in records if r["n_active"] == n):
            fine = reference[key(row)]
            regret = max(fine["qvalues"]) - fine["qvalues"][row["action"]]
            if row["action"] != fine["action"]:
                mismatches.append(dict(context=key(row), coarse_action=row["action"], fine_action=fine["action"],
                    coarse_qvalues=row["qvalues"], fine_qvalues=fine["qvalues"], finite64_action_regret=regret))
        summaries.append(dict(n_active=n, comparisons=len(reference), disagreements=len(mismatches),
                              maximum_finite64_action_regret=max((r["finite64_action_regret"] for r in mismatches), default=0), examples=mismatches))
    write("ACTIONS.json", dict(rows=records, summary=summaries, source_sha256=sha(SOURCE / "contract.py"),
        scope="Same physical truncated-normal initial law and fixed reset width .1. Regret uses N64 finite Q-values, not continuous truth."))
    print(json.dumps([{k:v for k,v in s.items() if k != "examples"} for s in summaries], indent=2))


def extra():
    rows = json.loads((ROOT / "FIRST_HIT.json").read_text())["rows"]
    theta_np = np.asarray(contract.PROTOCOL["baseline_financial_parameters"])
    sigma, mu = theta_np[2], theta_np[0] - theta_np[1] - theta_np[2] ** 2 / 2
    spectrum = reflected_spectrum(mu, sigma, .8, 512)
    nodes, weights = np.polynomial.legendre.leggauss(320)
    x, weights = .4 * (nodes + 1), .4 * weights
    refinement = []
    for row in (r for r in rows if r["n_active"] == 8):
        mean, width, t = row["physical_mean"], row["physical_width"], row["t"]
        norm = ndtr((.8 - mean) / width) - ndtr(-mean / width)
        average = float(np.sum(weights * spectrum(x, t) * np.exp(-.5 * ((x-mean)/width)**2)
                               / (np.sqrt(2*np.pi)*width*norm)))
        refinement.append(dict(mean=mean, t=t, gaussian160=row["reflected_continuum_hit"],
                               gaussian320=average, difference=abs(average-row["reflected_continuum_hit"])))
    sigma0 = np.sqrt(2 * (theta_np[0] - theta_np[1]))
    theta_np[2] = sigma0
    theta = torch.tensor(theta_np, dtype=torch.float64, requires_grad=True)
    scalar = contract.model_terms(theta=theta, prices=False)["Q"][0, 1]
    derivative = float(torch.autograd.grad(scalar, theta)[0][2])
    slopes = []
    for h in (1e-5, 1e-6, 1e-7):
        shifted = []
        for sign in (-1, 1):
            v = theta_np.copy()
            v[2] += sign*h
            shifted.append(float(contract.model_terms(theta=torch.tensor(v), prices=False)["Q"][0, 1]))
        center = float(scalar.detach())
        slopes.append(dict(step=h, left=(center-shifted[0])/h, right=(shifted[1]-center)/h,
                           central=(shifted[1]-shifted[0])/(2*h)))
    write("REFINEMENT_AND_KINK.json", dict(refinement=refinement,
        kink=dict(sigma=sigma0, represented_mu=float(theta_np[0]-theta_np[1]-sigma0**2/2),
                  autograd_sigma=derivative, slopes=slopes),
        scope="Separate nonsmooth drift-splitting limitation, not a failure of the full-HX bridge"))
    print("quadrature refinement", max(x["difference"] for x in refinement), "kink", derivative, slopes, flush=True)


if __name__ == "__main__":
    started = time.perf_counter()
    {"prepare": prepare, "gradients": gradients, "first_hit": first_hit, "actions": actions, "extra": extra}[sys.argv[1]]()
    print("elapsed", time.perf_counter() - started, flush=True)

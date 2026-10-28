"""Independent prefreeze review of all retained calibration checkpoints.

The review rebuilds Gaussian conditioning, gate moments, development losses,
selection and complex-step gradients. It never creates a confirmation sample.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from experiments.analytic_event_neuron import task
from experiments.analytic_event_neuron.round3 import calibration


RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/aen-round3-20261028")
HERE = Path(__file__).resolve()
OUT = HERE.parent / "CALIBRATION_PREFREEZE_REVIEW.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    with np.load(path, allow_pickle=False) as data:
        return {k: data[k].item() if data[k].ndim == 0 else data[k] for k in data.files}


def dense(model, history):
    drift, diffusion, noise = model["parameters"]
    means, variances, logs = [], [], []
    for row in range(len(history["obs"])):
        selected = history["mask"][row] & history["occupied"][row]
        t = history["times"][row, selected]
        y = history["obs"][row, selected] - drift * t
        covariance = 1 + diffusion * np.minimum(t[:, None], t[None, :])
        covariance += np.diag(noise * history["obs_var"][row, selected])
        cross = 1 + diffusion * t
        last = np.max(np.where(history["occupied"][row], history["times"][row], 0))
        solved = np.linalg.solve(covariance, np.column_stack([y, cross]))
        means.append(drift * (last + task.HORIZONS) + cross @ solved[:, 0])
        variances.append(1 + diffusion * (last + task.HORIZONS) - cross @ solved[:, 1])
        _, logdet = np.linalg.slogdet(covariance)
        logs.append(-.5 * (len(t) * np.log(2 * np.pi) + logdet + y @ solved[:, 0]))
    return np.asarray(means), np.asarray(variances), np.asarray(logs)


def components(model, history):
    m0, v0, l0 = dense(model["anchor"], history)
    m1, v1, l1 = dense(model["adaptive"], history)
    x = np.column_stack([np.ones(len(m0)), np.clip((l1 - l0) / 4, -2, 2)])
    return m0, v0, m1, v1, x


def candidate(raw, values):
    m0, v0, m1, v1, x = values
    a = (1 / (1 + np.exp(-(x @ np.asarray(raw[:2])))))[:, None]
    mean = (1 - a) * m0 + a * m1
    # Independent raw second moment expression, not implementation's stable identity.
    second = (1 - a) * (v0 + m0**2) + a * (v1 + m1**2)
    variance = (second - mean**2) * np.exp(raw[2:])
    return mean, variance


def loss(target, mean, variance):
    return .5 * (np.log(2 * np.pi * variance) + (target - mean)**2 / variance)


def review():
    prepared_root = RUN / "calibration_prepared"
    prepared = json.loads((prepared_root / "PREPARED.json").read_text())
    reg = prepared["registration"]
    checks, failures = 0, []
    maxima = {"development_loss_error": 0., "gradient_error": 0., "selected_prediction_error": 0.}

    def check(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    for name, digest in prepared["artifacts_sha256"].items():
        check(sha(prepared_root / name) == digest, "prepared artifact hash: " + name)
    planned = [reg["seed_offset"] + 10000*s + 100*w + k
               for s in reg["seeds"] for w in range(12) for k in (1, 2, 3, 4)]
    planned += [reg["seed_offset"] + 10000*s + 1205 for s in reg["seeds"]]
    check(len(set(planned)) == len(planned) == 245, "calibration dataset coordinates overlap")
    other_seeds = [offset+s for offset in (30000000, 31000000, 32000000, 33000000, 34000000) for s in reg["seeds"]]
    other_seeds += [80000000+100*s+k for s in reg["seeds"] for k in (1, 2, 3)]
    other_seeds += [90000000+s for s in reg["seeds"]]
    check(not set(planned) & set(other_seeds), "calibration/main/feedback/runtime seed collision")
    future_seeds = {reg["seed_offset"]+10000*s+100*w+4 for s in reg["seeds"] for w in range(12)}
    future_seeds |= {reg["seed_offset"]+10000*s+1205 for s in reg["seeds"]}
    observed_seeds, fit_success, checkpoint_count, choices = set(), 0, 0, []
    for seed in reg["seeds"]:
        directory = prepared_root / f"seed_{seed}"
        original = load(directory / "ORIGINAL_TRAIN.npz")
        parent = load(RUN / f"training/seed_{seed}/TRAIN.npz")
        for k in original:
            expected = parent[k][:256] if isinstance(parent[k], np.ndarray) and parent[k].ndim else parent[k]
            check(np.array_equal(original[k], expected), f"original replay prefix {seed}:{k}")
        anchor = json.loads((directory / "ANCHOR.json").read_text())
        previous_hash, prior_online, prior_replay = None, anchor, anchor
        for window in range(12):
            path = directory / f"window_{window:02d}_CHECKPOINT.json"
            checkpoint = json.loads(path.read_text())
            checkpoint_count += 1
            models, selection = checkpoint["models"], checkpoint["selection"]
            check(checkpoint["previous_checkpoint_sha256"] == previous_hash, f"checkpoint ancestry {seed}:{window}")
            check(not checkpoint["holdout_used"] and not checkpoint["prediction_reads_environment_or_window"], "undeclared holdout/regime input")
            check(models["frozen"] == anchor and models["calibrated"]["anchor"] == anchor, "anchor mutated")
            check(checkpoint["training"]["online"]["initial_parameters"] == prior_online["parameters"], "online warm start differs")
            check(checkpoint["training"]["replay"]["initial_parameters"] == prior_replay["parameters"], "replay warm start differs")
            training = load(directory / f"window_{window:02d}_TRAIN.npz")
            olddev = load(directory / f"window_{window:02d}_OLD_DEV.npz")
            newdev = load(directory / f"window_{window:02d}_NEW_DEV.npz")
            for code, data in ((1, training), (2, olddev), (3, newdev)):
                observed_seeds.add(data["seed"])
                check(data["seed"] == reg["seed_offset"]+10000*seed+100*window+code, "data coordinate differs")
                check(data["seed"] not in future_seeds, "future seed generated in preparation")
            old_digest, new_digest = task.dataset_digest(original), task.dataset_digest(training)
            for name, count, digests in (("online",256,[new_digest]),("replay",512,[old_digest,new_digest]),
                                         ("calibration",512,[old_digest,new_digest])):
                fit = checkpoint["training"][name]
                check(fit["training_trajectories"] == count and fit["dataset_digests"] == digests, f"fit budget/digest {seed}:{window}:{name}")
                check(fit["optimizer_success"], f"optimizer unsuccessful {seed}:{window}:{name}")
                fit_success += int(fit["optimizer_success"])
            check(checkpoint["training"]["calibration"]["parameter_l2_change"] > 0, "calibration parameters unchanged")
            model = models["calibrated_unconstrained"]
            check(model["parameters"] == checkpoint["training"]["calibration"]["fitted_parameters"], "fitted parameter binding differs")
            check(model["adaptive"] == models["online"], "adaptive expert differs from online checkpoint")
            check(selection["development_dataset_digests"] == [task.dataset_digest(olddev), task.dataset_digest(newdev)], "development digest binding differs")
            cached, targets = [], []
            for data in (olddev, newdev):
                h = task.history(data)
                part = components(model, h)
                mc, vc = candidate(np.asarray(model["parameters"]), part)
                cached.append((part[0][:, 1:], part[1][:, 1:], mc[:, 1:], vc[:, 1:]))
                targets.append(task.targets(data)[:, 1:])
            anchor_loss = loss(targets[0], *cached[0][:2])
            recalculated = []
            for index, candidate_receipt in enumerate(selection["candidates"]):
                strength, inflation = candidate_receipt["strength"], candidate_receipt["variance_inflation"]
                domain_losses = []
                for domain, ((m0,v0,mc,vc), target) in enumerate(zip(cached, targets)):
                    m = (1-strength)*m0 + strength*mc
                    v = inflation*((1-strength)*(v0+m0*m0)+strength*(vc+mc*mc)-m*m)
                    measured = loss(target,m,v)
                    domain_losses.append(measured)
                    expected = candidate_receipt[("old","new")[domain]]["gaussian_nll"]
                    gap = abs(float(measured.mean())-expected)
                    maxima["development_loss_error"] = max(maxima["development_loss_error"],gap)
                    check(gap < 2e-11, f"candidate loss {seed}:{window}:{index}:{domain}")
                delta = (domain_losses[0]-anchor_loss).mean(1)
                upper = float(delta.mean()+1.645*delta.std(ddof=1)/np.sqrt(len(delta)))
                check(abs(upper-candidate_receipt["old"]["selection_upper_heuristic"]) < 2e-11, "old trajectory SE reserve differs")
                check((upper<=.02) == candidate_receipt["eligible"], "eligibility differs")
                recalculated.append((upper<=.02,float(domain_losses[1].mean())))
            chosen = min((i for i,x in enumerate(recalculated) if x[0]),key=lambda i:(recalculated[i][1],i))
            check(chosen == selection["selected_index"], f"selected index differs {seed}:{window}")
            check(len(selection["candidates"]) == 55, "missing candidate receipts")
            choices.append({"seed":seed,"window":window,"selected_index":chosen})
            h = task.history(training)
            component = components(model,h)
            target = task.targets(training)
            raw = np.asarray(model["parameters"])
            _, declared_gradient = calibration.objective_gradient(raw,component,target)
            numerical = []
            for j in range(6):
                complex_raw = raw.astype(complex)
                complex_raw[j] += 1e-25j
                m,v = candidate(complex_raw,component)
                objective = loss(target,m,v).mean()+.001*np.sum(complex_raw**2)
                numerical.append(objective.imag/1e-25)
            gradient_gap = float(np.max(abs(np.asarray(numerical)-declared_gradient)))
            maxima["gradient_error"] = max(maxima["gradient_error"],gradient_gap)
            check(gradient_gap<2e-11,f"independent complex-step derivative {seed}:{window}")
            probe = task.subset(h,slice(0,8))
            plain = calibration.predict(models["calibrated"],probe)
            part = components(model,probe)
            cm,cv = candidate(raw,part)
            strength = models["calibrated"]["strength"]
            inflation = models["calibrated"]["variance_inflation"]
            expected_m = (1-strength)*part[0]+strength*cm
            expected_v = inflation*((1-strength)*(part[1]+part[0]**2)+strength*(cv+cm**2)-expected_m**2)
            prediction_gap = max(float(np.max(abs(plain[0]-expected_m))),float(np.max(abs(plain[1]-expected_v))))
            maxima["selected_prediction_error"] = max(maxima["selected_prediction_error"],prediction_gap)
            check(prediction_gap<2e-11,"selected moment prediction differs from dense second-moment reference")
            poisoned = deepcopy(probe)
            poisoned["obs"][~poisoned["mask"]] = np.nan
            poisoned["obs_var"][~poisoned["mask"]] = np.nan
            poisoned.update({"future":np.full((8,6),np.nan),"law":"secret","window":-999})
            poisoned["ids"] = np.array(["scrambled"]*8)
            changed = calibration.predict(models["calibrated"],poisoned)
            check(all(np.array_equal(a,b) for a,b in zip(plain,changed)),"private/ID/missing bytes enter inference")
            for name in ("calibrated","calibrated_q24","calibrated_classical","calibrated_q24_classical"):
                check(models[name]["universal_pointwise_retention_guarantee"] is False,"empirical head inherited a false bound")
            previous_hash, prior_online, prior_replay = sha(path),models["online"],models["replay"]
    check(len(observed_seeds)==180 and not observed_seeds&future_seeds,"prepared/future dataset intersection")
    check(checkpoint_count==60 and fit_success==180,"checkpoint/optimizer total mismatch")
    sources = {p.name:sha(p) for p in [HERE,HERE.parent.parent/"calibration.py",HERE.parent.parent/"calibration_study.py",
                                      HERE.parent.parent/"calibration_validation.py"]}
    result = {"schema":"hepta.analytic-event.calibration-prefreeze-review.v1","passed":not failures,
        "checks":checks,"failures":failures,"source_sha256":sources,"prepared_sha256":sha(prepared_root/"PREPARED.json"),
        "artifacts_verified":len(prepared["artifacts_sha256"]),"checkpoints":checkpoint_count,
        "development_candidates_recomputed":60*55,"successful_fit_receipts":fit_success,
        "independent_gradients":60,"maxima":maxima,"selected_indices":choices,
        "planned_dataset_coordinates":245,"prepared_dataset_coordinates":180,"confirmation_generated":False,
        "findings":[{"severity":"interpretation","status":"disclosed",
          "detail":"Replay and calibration fit each use512 labels/window; calibration additionally uses256 development labels for selection while replay uses0. Only fit budget is matched. Classical calibrated control matches the full budget."}],
        "scope_limits":["Read-only evidence/math review; optimizers were not rerun.",
          "Per-horizon Gaussian calibration does not define a new path semigroup.",
          "Empirical retention selection has no pointwise bound; Q24 parameter study does not execute native runtime.",
          "Paired SE reserve is a model-selection heuristic, not a simultaneous confidence bound."]}
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:result[k] for k in ("passed","checks","failures","maxima","checkpoints","development_candidates_recomputed")}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    review()

"""Task utility, remaining-return calibration and fit-level paired inference."""
import math

import numpy as np
from scipy.stats import t as student_t

from .task import Oracle, evaluate_terminal, posterior


def entropy(p):
    return 0. if p in (0, 1) else -p*math.log(p)-(1-p)*math.log(1-p)


def episode_metrics(public, episode, label, confusion):
    outcome = evaluate_terminal(episode["final_state"], label)
    oracle = Oracle(public, confusion)
    regrets, brier, q_errors, information = [], [], [], []
    selected_q, realized_return, event_probs, event_values = [], [], [], []
    for row in episode["decisions"]:
        state, action = row["before"], row["action"]
        qstar = oracle.q(state)
        regrets.append(float(np.max(qstar)-qstar[action]))
        brier.append((row["belief"]-label)**2)
        future_return = outcome["reward"]-(outcome["charges"]-state["charges"])
        prediction = row["q"][action]
        q_errors.append((prediction-future_return)**2)
        selected_q.append(prediction)
        realized_return.append(future_return)
        before_p = posterior(public, state, confusion)
        after_p = posterior(public, row["after"], confusion)
        information.append(entropy(before_p)-entropy(after_p))
        if row["event"]["sampled"]:
            event_probs.append(row["event"]["probability"])
            event_values.append(float(row["event"]["event"]))
    return dict(**outcome, decisions=len(regrets),
                mean_action_regret=float(np.mean(regrets)), sum_action_regret=sum(regrets),
                belief_brier=float(np.mean(brier)), selected_q_remaining_return_mse=float(np.mean(q_errors)),
                selected_q_mean=float(np.mean(selected_q)), remaining_return_mean=float(np.mean(realized_return)),
                information_gain_nats=sum(information), events=sum(event_values),
                predicted_events=sum(event_probs),
                event_brier=float(np.mean((np.asarray(event_values)-event_probs)**2)) if event_values else 0.,
                recovery_count=sum(row["event"]["recovery"] for row in episode["decisions"]),
                failed_reads=sum(row["completion"] is not None and row["completion"].get("failure", False)
                                 for row in episode["decisions"]),
                wall_seconds=episode["wall_seconds"], cpu_seconds=episode["cpu_seconds"])


def paired_interval(deltas, comparisons=4, margin=0.02):
    d = np.asarray(deltas, dtype=np.float64)
    if d.shape != (5,) or not np.all(np.isfinite(d)):
        raise ValueError("all five independent fit differences required")
    mean = float(np.mean(d))
    se = float(np.std(d, ddof=1)/math.sqrt(5))
    radius = float(student_t.ppf(1-0.05/(2*comparisons), 4))*se
    return dict(fit_differences=d.tolist(), n_fits=5, mean=mean, standard_error=se,
                lower=mean-radius, upper=mean+radius, df=4,
                interval_confidence=1-.05/comparisons, practical_margin=margin,
                benefit_gate=mean-radius > margin)


def summarize(rows, protocol):
    groups = {}
    worlds = {}
    expected = {(fit, split, family, controller) for fit in protocol["fits"]
                for split in ("iid", "ood")
                for family in protocol["families"]+[protocol["reference_family"]]
                for controller in protocol["controllers"]}
    for row in rows:
        key = (row["fit"], row["split"], row["family"], row["controller"])
        if row.get("forced", False) or row.get("failure"):
            raise ValueError("forced or failed episode cannot enter confirmation")
        if row["world"] in worlds.setdefault(key, set()):
            raise ValueError("duplicate world in formal group")
        worlds[key].add(row["world"])
        groups.setdefault(key, []).append(row["metrics"])
    if set(groups) != expected:
        raise ValueError("incomplete formal fit/split/family/controller matrix")
    for key in expected:
        fit, split, _, _ = key
        paired = worlds[(fit, split, protocol["families"][0], "fixed")]
        if worlds[key] != paired or len(paired) != protocol[f"{split}_worlds"]:
            raise ValueError("missing or unpaired confirmation worlds")
    means, detailed = {}, []
    for key, records in sorted(groups.items()):
        common = sorted(set.intersection(*(set(r) for r in records)))
        values = {k: float(np.mean([r[k] for r in records])) for k in common
                  if all(isinstance(r[k], (bool, int, float)) for r in records)}
        means[key] = values
        detailed.append(dict(fit=key[0], split=key[1], family=key[2], controller=key[3], count=len(records), metrics=values))
    aggregate = []
    for split, family, controller in sorted(set((k[1], k[2], k[3]) for k in means)):
        records = [means[(fit, split, family, controller)] for fit in protocol["fits"]]
        aggregate.append(dict(split=split, family=family, controller=controller,
                              metrics={k: float(np.mean([r[k] for r in records])) for k in records[0]}))
    contrasts = []
    for contrast in protocol["primary_contrasts"]:
        pf, pc = contrast["positive"].split("/")
        nf, nc = contrast["negative"].split("/")
        for split in ("iid", "ood"):
            deltas = [means[(fit, split, pf, pc)]["utility"]-means[(fit, split, nf, nc)]["utility"] for fit in protocol["fits"]]
            contrasts.append(dict(name=contrast["name"], split=split, **paired_interval(deltas)))
    return dict(aggregate=aggregate, fit_means=detailed, primary_contrasts=contrasts,
                number_of_episodes=len(rows), statistics=protocol["statistics"])

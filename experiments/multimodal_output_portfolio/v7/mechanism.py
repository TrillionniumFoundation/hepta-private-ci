"""Development-only oracle/selection diagnostics over a complete finite table."""

from collections import Counter
import math

import torch

from ..v6.observer import upper_tail
from .control import choose_plan
from .forecast import CONTINUATIONS
from .plans import ALLOCATION_PLAN, PLANS


def _ce(values, gamma):
    if gamma == 0:
        return sum(values) / len(values)
    pivot = max(-gamma * value for value in values)
    return -(pivot + math.log(sum(math.exp(-gamma * value - pivot) for value in values) / len(values))) / gamma


def _outcomes(selected, data):
    rows = [data.rows[index] for index in selected]
    observations = [row["actual_observation"] for row in rows]
    losses = [(1 - item["utility"]) / 2 for item in observations]
    joint = [bool(item.get("caption_valid")) and all(item.get(key) == 0 for key in
             ("text_fact", "relation", "image_fact", "crossmodal_disagreement")) for item in observations]
    mass, counts, contributions = .1 * len(rows), Counter(), Counter()
    for rank, index in enumerate(sorted(range(len(rows)), key=lambda i: losses[i], reverse=True)):
        weight = min(1., max(0., mass - rank))
        if not weight:
            break
        counts[rows[index]["view"]] += weight / mass
        contributions[rows[index]["view"]] += weight * losses[index] / mass
    return {"rows": len(rows), "independent_source_pairs": len({row["pair"] for row in rows}),
            "mean_joint_loss": sum(losses) / len(losses), "cvar90_joint_loss": upper_tail(losses),
            "joint_fact_correct": sum(joint) / len(joint),
            "required_output_completion": sum(bool(item.get("caption_valid")) for item in observations) / len(rows),
            "tail_mass_fraction_by_view": dict(counts), "tail_loss_contribution_by_view": dict(contributions),
            "continuation_counts": dict(Counter("/".join(row["prefix"]) or "stop" for row in rows)),
            "initial_plan_counts": dict(Counter(row["initial_plan_index"] for row in rows)),
            "actual_action_counts": dict(Counter(action for row in rows for action in
                ((ALLOCATION_PLAN if row["initial_plan_index"] == -1 else PLANS[row["initial_plan_index"]]) + tuple(row["prefix"])))),
            "selected_endpoint_indices": selected}


def analyze(data, statistics, *, gammas=(0., 2., 8., 16.), penalty=.002):
    if data.evidence["role"] != "development" or data.evidence["scenarios"] != 4:
        raise ValueError("Mechanism diagnostics require the registered four-noise development census")
    keys = {}
    roots = {}
    for i, row in enumerate(data.rows):
        key = (row["pair"], row["view"], row["initialization"], row["noise_slot"], tuple(row["prefix"]))
        if key in keys:
            raise ValueError("Duplicate endpoint in complete candidate census")
        keys[key] = i
        if not row["prefix"]:
            roots[key[:-2] + (row["noise_slot"],)] = i
    reference, policies = {}, {}
    static_plans = {}
    for initialization in ("full", "allocation"):
        root_ids = [index for index in roots.values() if data.rows[index]["initialization"] == initialization]
        table = data.targets[root_ids]
        valid = torch.isfinite(table).all(0)
        means = table.nanmean(0)
        static_index = max(valid.nonzero().flatten().tolist(),
                           key=lambda i: (float(means[i]) - penalty * len(CONTINUATIONS[i]), -len(CONTINUATIONS[i]), -i))
        static_plans[initialization] = CONTINUATIONS[static_index]
        grouped = {}
        for index in root_ids:
            row = data.rows[index]
            grouped.setdefault((row["pair"], row["view"]), {})[row["noise_slot"]] = data.targets[index]
        gamma_rows = []
        for gamma in gammas:
            disagreements, gains, oracle_over_static = 0, [], []
            for cases in grouped.values():
                if set(cases) != {0, 1, 2, 3}:
                    raise ValueError("Missing common latent-noise scenario")
                actual = torch.stack([cases[i] for i in range(4)])
                legal = torch.isfinite(actual).all(0).nonzero().flatten().tolist()
                mean = {i: float(actual[:, i].mean()) - penalty * len(CONTINUATIONS[i]) for i in legal}
                risk = {i: _ce(actual[:, i].tolist(), gamma) - penalty * len(CONTINUATIONS[i]) for i in legal}
                neutral = max(legal, key=lambda i: (mean[i], -len(CONTINUATIONS[i]), -i))
                chosen = max(legal, key=lambda i: (risk[i], -len(CONTINUATIONS[i]), -i))
                disagreements += chosen != neutral
                gains.append(risk[chosen] - risk[neutral])
                oracle_over_static.append(risk[chosen] - risk[static_index])
            gamma_rows.append({"gamma": gamma, "case_plan_disagreement_from_mean": disagreements / len(grouped),
                               "mean_ce_gain_over_mean_plan": sum(gains) / len(gains),
                               "mean_oracle_ce_gain_over_fixed_static": sum(oracle_over_static) / len(oracle_over_static)})
        reference[initialization] = gamma_rows
        for name in ("static", "router", "risk_neutral", "ndu", "static_pool"):
            selected = []
            for root in root_ids:
                row = data.rows[root]
                key = (row["pair"], row["view"], initialization, row["noise_slot"])
                prefix = ()
                if name == "static":
                    prefix = static_plans[initialization]
                elif name == "static_pool":
                    candidate = keys[key + (static_plans[initialization],)]
                    gain = float(statistics["mean"][candidate, 0] - statistics["mean"][root, 0])
                    if gain > penalty * len(static_plans[initialization]):
                        prefix = static_plans[initialization]
                else:
                    while len(prefix) < 2:
                        current = keys[key + (prefix,)]
                        scores = statistics["mean" if name in {"router", "risk_neutral"} else "ce"][current]
                        plan = choose_plan(scores, 2 + len(prefix), initialization == "full", 2 - len(prefix), penalty)
                        if not plan:
                            break
                        prefix += plan if name == "router" else plan[:1]
                        if name == "router":
                            break
                selected.append(keys[key + (prefix,)])
            policies[f"{initialization}/{name}"] = _outcomes(selected, data)
    neutral = policies["full/risk_neutral"]["selected_endpoint_indices"]
    risk = policies["full/ndu"]["selected_endpoint_indices"]
    agreement = {"pairs": len(risk),
                 "continuation_agreement": sum(tuple(data.rows[a]["prefix"]) == tuple(data.rows[b]["prefix"])
                                                for a, b in zip(neutral, risk)) / len(risk),
                 "raw_byte_agreement": sum(data.rows[a]["actual_observation"]["raw_sha256"] ==
                                            data.rows[b]["actual_observation"]["raw_sha256"]
                                            for a, b in zip(neutral, risk)) / len(risk)}
    return {"schema": "hepta.ndu-v7.development-mechanism.v1", "formal_holdout_opened": False,
            "complete_census": data.evidence, "static_plans": static_plans,
            "static_selection_assessed_in_sample_on_development": True,
            "common_noise_precommitted_plan_oracle": reference,
            "oracle_scope": "fixed true case with four observed initial-noise outcomes; not a true-world conditional Bayes oracle or upper bound on noise-adaptive control",
            "policy_outcomes": policies, "risk_neutral_vs_gamma2": agreement,
            "global_scientific_success": False}

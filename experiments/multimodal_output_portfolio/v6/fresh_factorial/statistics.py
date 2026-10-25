"""Source-paired factorial contrasts and an independent metric-arithmetic check."""

import re

import numpy as np


ARMS = ("b0g0", "b0g1", "b1g0", "b1g1")
CONTRASTS = {
    "base_main_effect": (-.5, -.5, .5, .5),
    "gate_main_effect": (-.5, .5, -.5, .5),
    "interaction": (1., -1., -1., 1.),
}
WEIGHTS = {"text_fact": .30, "relation": .15, "image_fact": .35,
           "crossmodal_disagreement": .10, "pixel_mse": .10}
CAPTION = re.compile(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)")


def score_observation(pixels, caption, image_digits, target_pixels, labels):
    """Independent arithmetic given Audit B's OCR decisions, not new OCR truth."""
    pixels, target = np.asarray(pixels), np.asarray(target_pixels)
    if (pixels.shape != (1, 1, 28, 56) or target.shape != pixels.shape
            or not np.isfinite(pixels).all() or not np.isfinite(target).all()
            or min(float(pixels.min()), float(target.min())) < 0
            or max(float(pixels.max()), float(target.max())) > 1
            or len(image_digits) != 2 or len(labels) != 2
            or any(type(x) is not int or not 0 <= x <= 9 for x in [*image_digits, *labels])):
        raise ValueError("invalid emitted image or digit observation")
    match = CAPTION.fullmatch(caption.strip())
    parsed = [int(match[1]), int(match[2])] if match else None
    relation = "less" if labels[0] < labels[1] else "greater" if labels[0] > labels[1] else "equal"
    fields = {"text_fact": sum(a != b for a, b in zip(parsed, labels)) / 2 if match else 1.,
              "relation": float(match[3] != relation) if match else 1.,
              "image_fact": sum(a != b for a, b in zip(image_digits, labels)) / 2,
              "crossmodal_disagreement": sum(a != b for a, b in zip(parsed, image_digits)) / 2 if match else 1.,
              "pixel_mse": float(np.square(pixels.astype(np.float32) - target.astype(np.float32)).mean(dtype=np.float32))}
    loss = sum(WEIGHTS[name] * fields[name] for name in WEIGHTS)
    return {**fields, "joint_loss": loss, "utility": 1 - 2 * loss, "caption_valid": match is not None,
            "image_digits": image_digits, "caption_digits": parsed, "caption_relation": match[3] if match else None,
            "joint_fact_correct": int(fields["text_fact"] == fields["relation"] == fields["image_fact"] == 0)}


def upper_tail(values, fraction=.1):
    ordered = np.sort(np.asarray(values, dtype=np.float64))[::-1]
    if not len(ordered) or not np.isfinite(ordered).all() or not 0 < fraction <= 1:
        raise ValueError("invalid empirical tail sample")
    mass = len(ordered) * fraction
    whole = int(mass)
    result = float(ordered[:whole].sum())
    if whole < len(ordered):
        result += (mass - whole) * float(ordered[whole])
    return result / mass


def paired_cube(rows, plan):
    cases = [(f"{split}-{item['offset'] + i:04}", split,
              plan["corruptions"][i % 6] if split == "future" else "clean")
             for split in ("future", "retention") for item in [plan["case_ranges"][split]]
             for i in range(item["count"])]
    if len(rows) != plan["expected_rows"] or set(plan["arms"]) != set(ARMS):
        raise ValueError("factorial arm/row census differs")
    expected = {(seed, arm, case_id) for seed in plan["seeds"] for arm in ARMS for case_id, _, _ in cases}
    lookup, metadata = {}, {}
    for row in rows:
        key = row["seed"], row["arm"], row["case_id"]
        if key not in expected or key in lookup:
            raise ValueError("unexpected or repeated seed/arm/source row")
        signature = (row["split"], row["corruption"], tuple(row["source_ids"]))
        if len(signature[2]) != 2 or metadata.setdefault(row["case_id"], signature) != signature:
            raise ValueError("arms/seeds do not share the same paired source observation")
        loss, fact = row["metrics"]["joint_loss"], row["metrics"]["joint_fact_correct"]
        if (not np.isfinite(loss) or not 0 <= loss <= 1 or type(fact) is not int or fact not in (0, 1)):
            raise ValueError("nonfinite loss or invalid factual outcome")
        lookup[key] = (float(loss), float(fact))
    if set(lookup) != expected:
        raise ValueError("incomplete source-paired factorial")
    if len({source for signature in metadata.values() for source in signature[2]}) != 2 * len(cases):
        raise ValueError("source pixels were reused between cases")
    for case_id, split, corruption in cases:
        if metadata[case_id][:2] != (split, corruption):
            raise ValueError("registered corruption/source schedule differs")
    values = np.array([[[lookup[seed, arm, case_id] for arm in ARMS] for seed in plan["seeds"]]
                       for case_id, _, _ in cases], dtype=np.float64)
    return cases, values


def describe(values):
    return {"case_count": len(values), "joint_loss": float(values[:, 0].mean()),
            "joint_fact_correct": float(values[:, 1].mean()),
            "joint_loss_CVaR90": upper_tail(values[:, 0]), "interval": None}


def analyze(rows, plan):
    cases, values = paired_cube(rows, plan)
    primary = plan["primary"]
    if (primary["contrasts"] != list(CONTRASTS) or primary["metric"] != "joint_loss"
            or primary["split"] != "future" or primary["family_size"] != 3
            or primary["fixed_seed_average_first"] is not True or primary["stratify"] != "corruption"):
        raise ValueError("registered primary estimands changed")
    future = np.array([i for i, case in enumerate(cases) if case[1] == "future"])
    # Average the three fitted seeds before bootstrap: they are not 180 independent sources.
    seed_average = values.mean(axis=1)
    coefficients = np.array(list(CONTRASTS.values()), dtype=np.float64).T
    differences = seed_average[future, :, 0] @ coefficients
    manual = np.column_stack((
        (seed_average[future, 2, 0] + seed_average[future, 3, 0]
         - seed_average[future, 0, 0] - seed_average[future, 1, 0]) / 2,
        (seed_average[future, 1, 0] + seed_average[future, 3, 0]
         - seed_average[future, 0, 0] - seed_average[future, 2, 0]) / 2,
        seed_average[future, 3, 0] - seed_average[future, 2, 0]
        - seed_average[future, 1, 0] + seed_average[future, 0, 0]))
    if not np.allclose(differences, manual, rtol=0, atol=1e-15):
        raise ValueError("matrix and expanded factorial contrasts disagree")
    strata = [np.array([i for i, case_index in enumerate(future) if cases[case_index][2] == name])
              for name in plan["corruptions"]]
    if any(len(indices) != 10 for indices in strata):
        raise ValueError("primary design requires six strata of ten independent source pairs")
    rng = np.random.default_rng(primary["bootstrap_seed"])
    draws = np.concatenate([rng.choice(indices, (primary["bootstrap_replicates"], len(indices)), replace=True)
                            for indices in strata], axis=1)
    bootstrap = differences[draws].mean(axis=1)
    tail = primary["alpha"] / (2 * primary["family_size"])
    limits = np.quantile(bootstrap, [tail, 1 - tail], axis=0, method="linear")
    contrasts = {}
    for i, name in enumerate(CONTRASTS):
        lower, upper = map(float, limits[:, i])
        contrasts[name] = {"estimate": float(differences[:, i].mean()), "interval": [lower, upper],
                           "direction": "negative" if upper < 0 else "positive" if lower > 0 else "unresolved",
                           "main_effect_improvement": bool(upper < 0) if name != "interaction" else None}
    secondary = {}
    per_seed = {}
    for split in ("future", "retention"):
        indices = [i for i, case in enumerate(cases) if case[1] == split]
        secondary[split] = {arm: describe(seed_average[indices, j]) for j, arm in enumerate(ARMS)}
        for seed_index, seed in enumerate(plan["seeds"]):
            per_seed[f"{split}-seed{seed}"] = {
                "arms": {arm: describe(values[indices, seed_index, j]) for j, arm in enumerate(ARMS)},
                "effects": dict(zip(CONTRASTS, map(float, (values[indices, seed_index, :, 0] @ coefficients).mean(axis=0))))}
    source_differences = [{"case_id": cases[index][0], "corruption": cases[index][2],
                           "fixed_seed_mean_losses": dict(zip(ARMS, map(float, seed_average[index, :, 0]))),
                           **dict(zip(CONTRASTS, map(float, differences[i])))} for i, index in enumerate(future)]
    return {"schema": "hepta.ndu-fresh-factorial.statistics.v1", "primary": contrasts,
            "bootstrap": {"replicates": primary["bootstrap_replicates"], "seed": primary["bootstrap_seed"],
                          "source_pairs": len(future), "strata": 6, "quantiles": [tail, 1 - tail],
                          "method": "paired source bootstrap within corruption; Bonferroni three two-sided percentile intervals",
                          "scope": "source-sampling uncertainty conditional on these six fitted bases and three fixed seeds; not training-population uncertainty"},
            "secondary": secondary, "per_seed": per_seed, "source_differences": source_differences,
            "secondary_scope": "descriptive; CVaR of per-source fixed-seed mean loss; clean retention is not continual-learning forgetting",
            "authority": "DENY_ALL", "production_authority": False}

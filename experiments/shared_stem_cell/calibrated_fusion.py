"""Calibration-selected checkpoints/late mixing of EXISTING frozen-tower Heads.

Same seeds, raw features, AdamW and final steps as controls.modality_trial.
Only checkpoint selection and a fixed convex output mixture are new; there is
no contextual gate, NDU solver, tower training or deployment authority. Fitting
accepts train/calibration material ONLY. Execute after the selection is sealed.
"""
from copy import deepcopy

import torch
from torch import nn
from torch.nn import functional as F

from experiments.shared_stem_cell.controls import FusionHead, paired_modality_probe
from experiments.shared_stem_cell.execution import InputError, integer, measured, parameters

CHECKPOINTS = (0, 1, 2, 5, 10, 20)
WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)


def validate(inputs, *, shapes=None, labels=None, classes=4):
    if not isinstance(inputs, dict) or not inputs or not set(inputs) <= {"image", "text"}:
        raise InputError("calibrated profile supports image/text only")
    n, actual, storage = None, {}, 0
    for name, item in inputs.items():
        if not isinstance(item, tuple) or len(item) != 3:
            raise InputError("exact feature/mask/time tuple required")
        x, mask, stamp = item
        if (any(not isinstance(v, torch.Tensor) or v.device.type != "cpu" for v in item)
                or x.dtype != torch.float32 or x.ndim != 3 or not bool(torch.isfinite(x).all())
                or not 1 <= len(x) <= 256 or not 1 <= x.shape[1] <= 64 or not 1 <= x.shape[2] <= 8192
                or mask.dtype != torch.bool or mask.shape != x.shape[:2]
                or stamp.dtype != torch.int64 or stamp.shape != mask.shape or bool((stamp < 0).any())):
            raise InputError("bounded finite modality tensors required")
        if n is not None and n != len(x):
            raise InputError("unpaired modalities")
        for row, valid in zip(stamp, mask):
            t = row[valid]
            if len(t) > 1 and not bool((t[1:] > t[:-1]).all()):
                raise InputError("ordered valid slots required")
        n, actual[name] = len(x), tuple(x.shape[1:])
        storage += sum(v.numel() * v.element_size() for v in item)
    if storage > 128 * 1024**2 or (shapes is not None and actual != shapes):
        raise InputError("modality storage budget or feature schema mismatch")
    if labels is not None and (not isinstance(labels, torch.Tensor) or labels.device.type != "cpu"
            or labels.dtype != torch.long or labels.shape != (n,)
            or bool(((labels < 0) | (labels >= classes)).any())):
        raise InputError("bounded calibration/training labels required")
    return actual


def score(probabilities, labels):
    n = len(labels)
    if (probabilities.ndim != 2 or probabilities.shape[0] != n
            or not bool(torch.isfinite(probabilities).all()) or bool((probabilities < 0).any())
            or not torch.allclose(probabilities.sum(1), torch.ones(n), atol=1e-6, rtol=1e-6)):
        raise InputError("invalid calibration probabilities")
    return {"correct": int((probabilities.argmax(-1) == labels).sum()), "cases": n,
            "nll": float(-probabilities[torch.arange(n), labels].clamp_min(1e-9).log().mean())}


def fit_calibrated(train, labels, calibration, calibration_labels, *, classes, steps=20, seed=17):
    """Fit each legacy arm ONCE, keep step0 and final controls, select on calibration."""
    integer(classes, 2, 256, "classes")
    integer(steps, 1, 1000, "steps")
    integer(seed, 0, 2**63 - 1, "seed")
    shapes = validate(train, labels=labels, classes=classes)
    validate(calibration, shapes=shapes, labels=calibration_labels, classes=classes)
    names = sorted(train)
    arms = list(dict.fromkeys([tuple(names), *((name,) for name in names)]))
    checkpoints = sorted({s for s in CHECKPOINTS if s <= steps} | {steps})
    models, traces, costs, identities, cal_selected = {}, {}, {}, {}, {}
    with torch.random.fork_rng(devices=[]), measured() as whole:
        for selected in arms:
            name = "+".join(selected)
            torch.manual_seed(seed)
            model = FusionHead({k: shapes[k] for k in selected}, classes)
            frozen = deepcopy(model).eval().requires_grad_(False)
            fit_x = {k: train[k] for k in selected}
            cal_x = {k: calibration[k] for k in selected}
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0)
            best, history, optimization_ns, calibration_ns = None, [], 0, 0
            with measured() as timing:
                for step in range(steps + 1):
                    if step:
                        with measured() as work:
                            optimizer.zero_grad(set_to_none=True)
                            loss = F.cross_entropy(model(fit_x), labels)
                            if not bool(torch.isfinite(loss)):
                                raise InputError("nonfinite connector loss")
                            loss.backward()
                            nn.utils.clip_grad_norm_(model.parameters(), 1, error_if_nonfinite=True)
                            optimizer.step()
                        optimization_ns += work["wall_ns"]
                    if step in checkpoints:
                        with torch.no_grad(), measured() as work:
                            probabilities = model(cal_x).softmax(-1)
                            metrics = score(probabilities, calibration_labels)
                        calibration_ns += work["wall_ns"]
                        identity = parameters(model)
                        record = {"step": step, **metrics, "model_sha256": identity["sha256"],
                                  "probabilities": probabilities.tolist()}
                        history.append(record)
                        rank = (-metrics["correct"], metrics["nll"], step)
                        if best is None or rank < best:
                            best, chosen_step = rank, step
                            chosen = deepcopy(model).eval().requires_grad_(False)
                            cal_selected[name] = probabilities.detach().clone()
            final = model.eval().requires_grad_(False)
            models[name] = {"frozen": frozen, "selected": chosen, "final": final}
            identities[name] = {role: parameters(m)["sha256"] for role, m in models[name].items()}
            traces[name] = {"checkpoints": history, "selected_step": chosen_step}
            costs[name] = {**timing, "optimizer_steps": steps, "examples_processed": steps * len(labels),
                "optimization_wall_ns": optimization_ns, "calibration_wall_ns": calibration_ns,
                "calibration_forward_calls": len(checkpoints), "parameter_count": parameters(final)["parameters"]}
        # Include every pure selected arm plus fixed-grid image/text convex mixtures.
        specifications = [[(name, 1.0)] for name in models]
        if set(names) == {"image", "text"}:
            specifications += [[("image", w), ("text", 1 - w)] for w in WEIGHTS if 0 < w < 1]
        mixtures = []
        for components in specifications:
            p = sum(weight * cal_selected[name] for name, weight in components)
            mixtures.append({"components": components, **score(p, calibration_labels),
                             "probabilities": p.tolist()})
        winner = min(range(len(mixtures)), key=lambda i: (
            -mixtures[i]["correct"], mixtures[i]["nll"], len(mixtures[i]["components"]), i))
    selection = {"schema": "hepta.calibrated-fusion.v1", "classes": classes, "shapes": shapes,
        "checkpoints": checkpoints, "traces": traces, "model_identities": identities,
        "mixtures": mixtures, "selected_mixture": winner,
        "rule": "calibration_correct_desc,nll_asc,smaller_step_or_component_count,stable_order",
        "same_calibration_reused_for_checkpoints_and_mixture": True,
        "context_dependent_gate": False, "no_holdout_used": True, "production_accepted": False,
        "costs": {"arms": costs, "whole_fitting_and_selection": whole,
                  "actual_optimizer_steps": sum(c["optimizer_steps"] for c in costs.values())}}
    return models, selection


@torch.no_grad()
def execute_calibrated(models, selection, inputs, partitions):
    """No labels; selected policy/model identities must match the sealed caller record."""
    if selection.get("schema") != "hepta.calibrated-fusion.v1":
        raise InputError("unknown calibration profile")
    integer(selection["selected_mixture"], 0, len(selection["mixtures"]) - 1, "mixture index")
    shapes = {k: tuple(v) for k, v in selection["shapes"].items()}
    validate(inputs, shapes=shapes, classes=selection["classes"])
    if (not isinstance(partitions, list) or len(partitions) != len(next(iter(inputs.values()))[0])
            or any(not isinstance(p, str) or not p for p in partitions)):
        raise InputError("complete holdout/retention partitions required")
    if set(models) != set(selection["model_identities"]):
        raise InputError("selected model inventory mismatch")
    for name, roles in models.items():
        if set(roles) != {"frozen", "selected", "final"}:
            raise InputError("complete unchanged/selected/final controls required")
        for role, m in roles.items():
            if (type(m) is not FusionHead or m.training or any(p.requires_grad for p in m.parameters())
                    or parameters(m)["sha256"] != selection["model_identities"][name][role]):
                raise InputError("selected connector identity drift")
    winner = selection["mixtures"][selection["selected_mixture"]]
    components = winner["components"]
    if (not components or len(components) > 2 or len({n for n, _ in components}) != len(components)
            or any(n not in models or type(w) not in (int, float) or not 0 < w <= 1 for n, w in components)
            or abs(sum(w for _, w in components) - 1) > 1e-8):
        raise InputError("invalid frozen mixture")
    cache, spans, predictions, frozen = {}, {}, {}, {}
    with measured() as whole:
        def predict(name, role):
            key = selection["model_identities"][name][role]
            if key not in cache:
                m = models[name][role]
                with measured() as span:
                    value = m({k: inputs[k] for k in m.names}).softmax(-1)
                if not bool(torch.isfinite(value).all()):
                    raise InputError("nonfinite connector prediction")
                cache[key] = value
                spans[key] = {**span, "forward_calls": 1, "cases": len(value)}
            return cache[key]
        for name in models:
            for output, role in ((name, "final"), ("selected:" + name, "selected")):
                predictions[output] = predict(name, role).tolist()
                frozen[output] = predict(name, "frozen").tolist()
        predictions["calibrated_mixture"] = sum(w * predict(n, "selected") for n, w in components).tolist()
        frozen["calibrated_mixture"] = sum(w * predict(n, "frozen") for n, w in components).tolist()
    joint = "+".join(sorted(inputs))
    probes = paired_modality_probe(models[joint]["final"], inputs, partitions)
    return {"predictions": predictions, "frozen_predictions": frozen, "modality_interventions": probes,
        "costs": {"fitting": selection["costs"], "inference": whole, "unique_model_forwards": spans},
        "production_accepted": False}

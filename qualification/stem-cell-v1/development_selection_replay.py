"""Independently recompute structural selection from saved candidate tensors.

This module never imports the fitter or its selection routine. It proves local
arithmetic correspondence, not origin, independent groups, physical execution,
a training trajectory, signed acceptance or production authority.
"""
from __future__ import annotations

import hashlib
import math

import torch

from development_study_data import digest

CONTROLS = ("frozen", "continued", "wider", "more_data")
SELECTION_FIELDS = ("selected_arm", "split_supported_on_calibration", "comparisons",
                    "best_unsplit_control", "independent_groups_authenticated",
                    "production_authorized")


def _same_record(observed, expected):
    if type(expected) is dict:
        if type(observed) is not dict or set(observed) != set(expected):
            return False
        return all(_same_record(observed[k], v) for k, v in expected.items())
    if type(expected) is float:
        return (type(observed) in (int, float) and math.isfinite(observed)
                and math.isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-12))
    return type(observed) is type(expected) and observed == expected


def _tensor_digest(tensors):
    h = hashlib.sha256(b"hepta.stem.development.tensors.v1")
    for name, value in sorted(tensors.items()):
        value = value.detach().cpu().contiguous()
        descriptor = f"{name}:{value.dtype}:{tuple(value.shape)}".encode()
        h.update(len(descriptor).to_bytes(8, "big"))
        h.update(descriptor)
        h.update(value.numpy().tobytes())
    return h.hexdigest()


def verify_selection(selection, tensors, features, inputs, calibration_labels, config, forward):
    """Recheck stored cost/counts, inherited parameters and calibration decisions.

    `forward` is the independent saved-tensor formula, never a fitted runtime
    object. No held-out/future/OOD label is accepted. Timings and group origin
    remain observations, not authenticated measurements. Router training itself
    is not reproduced by this check.
    """
    if (not set(CONTROLS) <= set(tensors) or not set(tensors) <= {*CONTROLS, "split"}
            or len(inputs) != len(features) or not inputs):
        raise ValueError("incomplete selection replay inputs")
    cal = [i for i, row in enumerate(inputs) if row["phase"] == "calibration"]
    if (not cal or calibration_labels.dtype != torch.long
            or calibration_labels.shape != (len(cal),)
            or bool(((calibration_labels < 0) | (calibration_labels >= config.classes)).any())):
        raise ValueError("invalid calibration-only labels")
    training = [r for r in inputs if r["phase"] in {"base", "adapt", "extra", "calibration"}]
    if selection["training_input_digest"] != digest(training):
        raise ValueError("selection training-input digest mismatch")
    costs = selection["costs"]["adaptation"]
    if set(costs) != set(tensors):
        raise ValueError("cost and checkpoint arm census mismatch")
    values, stored = {}, {}
    base = tensors["frozen"]
    for name, state in tensors.items():
        expected_cells = ["parent", "child"] if name == "split" else ["parent"]
        info = selection["checkpoints"][name]
        if (list(info["cell_ids"]) != expected_cells or type(info["generation"]) is not int
                or info["generation"] != config.generation + int(name != "frozen")):
            raise ValueError("checkpoint Cell/generation mismatch")
        logits = forward(state, features[cal], len(expected_cells), config.classes)
        rank = config.rank * (2 if name == "wider" else 1)
        if state["bank.coefficients"].shape[1] != rank:
            raise ValueError("checkpoint rank differs from registered arm")
        for key in ("bank.base.weight", "bank.base.bias", "bank.basis", "bank.gate_axes"):
            actual = state[key]
            if name == "wider" and key in ("bank.basis", "bank.gate_axes"):
                actual = actual[:config.rank]
            if not torch.equal(actual, base[key]):
                raise ValueError("adaptation changed inherited frozen parameters")
        record = costs[name]
        stored[name] = sum(v.numel() for v in state.values())
        private = sum(state[k].numel() for k in ("bank.coefficients", "bank.gates"))
        steps = 0 if name == "frozen" else config.adaptation_steps
        phases = {"adapt", "extra"} if name == "more_data" else {"adapt"}
        n = sum(r["phase"] in phases for r in inputs)
        counted = {"stored_scalars": stored[name], "trainable_parameters": private if steps else 0,
                   "steps": steps, "sample_presentations": steps * min(32, n)}
        if steps:
            counted["training_rows"] = n
        if any(type(record.get(k)) is not int or record[k] != v for k, v in counted.items()):
            raise ValueError("reported parameter/step cost differs from tensors or data")
        if record.get("parameter_digest") != _tensor_digest(state):
            raise ValueError("reported fitted parameter digest differs from checkpoint")
        hits = (logits.argmax(1) == calibration_labels).tolist()
        groups = {}
        for i, hit in zip(cal, hits):
            groups.setdefault(inputs[i]["source_group"], []).append(int(hit))
        values[name] = {g: sum(rows) / len(rows) for g, rows in groups.items()}
    # Keep the registered tie order, not checkpoint JSON's alphabetical order.
    def utility(name):
        return (sum(values[name].values()) / len(values[name])
                - config.scalar_penalty * stored[name])
    best = max(CONTROLS, key=utility)
    comparisons = {}
    accepted = "split" in values and len(values[best]) >= config.minimum_groups
    if "split" in values:
        n = len(values["split"])
        radius = math.sqrt(2 * math.log(len(CONTROLS) / config.alpha) / n)
        for name in CONTROLS:
            delta = sum(values["split"][g] - values[name][g] for g in values[name]) / n
            penalty = config.scalar_penalty * (stored["split"] - stored[name])
            lower = delta - radius - penalty
            comparisons[name] = {"group_count": n, "mean_accuracy_delta": delta,
                                 "hoeffding_radius": radius, "scalar_penalty_delta": penalty,
                                 "net_lower_bound": lower}
            accepted = accepted and lower > 0
    expected = {"selected_arm": "split" if accepted else best,
                "split_supported_on_calibration": accepted, "comparisons": comparisons,
                "best_unsplit_control": best, "independent_groups_authenticated": False,
                "production_authorized": False}
    if not _same_record({k: selection.get(k) for k in SELECTION_FIELDS}, expected):
        raise ValueError("sealed structural selection does not reproduce from calibration")
    return {"schema": "hepta.stem.selection-replay.v1", **expected,
            "calibration_rows": len(cal), "calibration_source_groups": len(values[best]),
            "stored_scalars_recomputed": stored,
            "training_trajectory_replayed": False, "physical_costs_attested": False}

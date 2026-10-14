"""Partial offline consolidation: one shared Head plus explicitly retained Cells.

Use only existing calibration predictions, not new fits or holdout labels. A
fixed per-Cell assignment is NOT a confidence gate, NDU policy or runtime owner.
The bank remains a candidate; count the shared Head ONCE and all retained Heads.
Only selected components are exported/reopened through the existing Head format.
"""
from __future__ import annotations

import torch

from experiments.shared_stem_cell import consolidation as c, execution as e
from experiments.shared_stem_cell.head_artifacts import (
    _binding, _digest, _path, _read, export_head, load_head,
)

SCHEMA = "hepta.partial-consolidation.v1"
MAX_INDEX = 1024**2


def _policy(policy):
    if not isinstance(policy, dict) or set(policy) != {
        "schema", "source_selection_sha256", "student", "profile", "assignment",
        "components", "parameters", "parameter_bytes", "production_accepted"
    } or policy["schema"] != SCHEMA or policy["production_accepted"] is not False:
        raise e.InputError("closed offline partial policy required")
    _digest(policy["source_selection_sha256"])
    profile = policy["profile"]
    if not isinstance(profile, dict) or set(profile) != {"cells", "width", "classes"}:
        raise e.InputError("exact partial profile required")
    cells = e.integer(profile["cells"], 2, 64, "partial Cells")
    e.integer(profile["width"], 1, 8192-cells, "partial width")
    e.integer(profile["classes"], 2, 256, "partial classes")
    assignments = policy["assignment"]
    if (not isinstance(assignments, list) or len(assignments) != cells
            or any(not isinstance(name, str) or name not in {"shared", f"cell-{i}"} for i, name in enumerate(assignments))
            or policy["student"] not in (None, "shared_frozen", *c.STUDENTS)
            or ("shared" in assignments) != (policy["student"] is not None)):
        raise e.InputError("fixed complete Cell-to-component assignment required")
    components = policy["components"]
    if not isinstance(components, dict) or set(components) != set(assignments):
        raise e.InputError("only referenced components may be retained")
    for identity in components.values():
        if not isinstance(identity, dict) or set(identity) != {"sha256", "parameters", "parameter_bytes"}:
            raise e.InputError("exact component identity required")
        _digest(identity["sha256"])
        n = e.integer(identity["parameters"], 1, c.MAX_BYTES//4, "component parameters")
        if type(identity["parameter_bytes"]) is not int or identity["parameter_bytes"] != n*4:
            raise e.InputError("component float32 byte count")
    for key in ("parameters", "parameter_bytes"):
        if type(policy[key]) is not int or policy[key] != sum(v[key] for v in components.values()):
            raise e.InputError("shared-once plus retained-component accounting mismatch")
    if policy["parameter_bytes"] > c.MAX_BYTES:
        raise e.InputError("partial component parameter budget")
    return profile


def select(receipt, calibration_y, calibration_routes):
    """Derive all partial candidates from fixed calibration outputs; no training."""
    cells = e.integer(receipt["route_profile"]["cells"], 2, 64, "partial Cells")
    probabilities = receipt["calibration_probabilities"]
    if set(probabilities) != set(c.ARMS) or len(receipt["teacher_identities"]) != cells:
        raise e.InputError("complete original consolidation comparison required")
    metrics = {k: c.score(p, calibration_y, calibration_routes, cells) for k,p in probabilities.items()}
    if metrics != receipt["calibration_scores"]:
        raise e.InputError("calibration score replay differs")
    bank = torch.tensor(probabilities["bank"], dtype=torch.float32)
    profile = {"cells": cells, "width": receipt["route_profile"]["input_width"], "classes": bank.shape[1]}
    source = e.sha(e.canonical(receipt))
    candidates = {}
    with e.measured() as timing:
        for name in ("bank", "shared_frozen", *c.STUDENTS):
            # Absent calibration coverage never licenses sharing for that Cell.
            shared = [] if name == "bank" else [i for i, (a,b) in enumerate(zip(
                metrics[name]["per_cell"], metrics["bank"]["per_cell"]))
                if a["cases"] > 0 and a["correct"] >= b["correct"]]
            assignment = ["shared" if i in shared else f"cell-{i}" for i in range(cells)]
            identities = {f"cell-{i}": receipt["teacher_identities"][i] for i in range(cells) if i not in shared}
            if shared:
                identities["shared"] = receipt["students"][name]
            policy = {"schema": SCHEMA, "source_selection_sha256": source,
                "student": name if shared else None, "profile": profile, "assignment": assignment,
                "components": identities, "parameters": sum(v["parameters"] for v in identities.values()),
                "parameter_bytes": sum(v["parameter_bytes"] for v in identities.values()),
                "production_accepted": False}
            _policy(policy)
            mask = torch.tensor([i in shared for i in calibration_routes.tolist()])
            p = bank if name == "bank" else torch.where(mask[:, None], torch.tensor(probabilities[name]), bank)
            score = c.score(p.tolist(), calibration_y, calibration_routes, cells)
            smaller = policy["parameters"] < receipt["parameter_counts"]["bank"]
            candidates[name] = {"policy": policy, "calibration_score": score,
                "shared_cells": shared, "retained_cells": [i for i in range(cells) if i not in shared],
                "eligible": name == "bank" or bool(shared and smaller),
                "reason": "baseline" if name == "bank" else "smaller" if shared and smaller else "not_smaller"}
        if candidates["bank"]["policy"]["parameters"] != receipt["parameter_counts"]["bank"]:
            raise e.InputError("original bank parameter inventory drift")
        eligible = [k for k,v in candidates.items() if v["eligible"]]
        selected = min(eligible, key=lambda k: (-candidates[k]["calibration_score"]["correct"],
            candidates[k]["policy"]["parameters"], candidates[k]["calibration_score"]["nll"], k))
    return {"selected": selected, "policy": candidates[selected]["policy"], "candidates": candidates,
        "original_all_or_nothing_selection": receipt["selected"], "selection_cost": timing,
        "additional_optimizer_steps": 0, "independent_evaluation": False, "production_accepted": False}


def _components(components, policy):
    profile = _policy(policy)
    if not isinstance(components, dict) or set(components) != set(policy["components"]):
        raise e.InputError("missing or extra partial component")
    for key, model in components.items():
        width = profile["width"] + (profile["cells"] if key == "shared" else 0)
        if (type(model) is not e.Head or model.kind != "gated" or model.training
                or model.base.in_features != width or model.base.out_features != profile["classes"]
                or any(p.requires_grad or p.device.type != "cpu" or p.dtype != torch.float32
                       or not bool(torch.isfinite(p).all()) for p in model.parameters())
                or e.parameters(model) != policy["components"][key]):
            raise e.InputError("partial component identity or feature profile differs")
    return profile


@torch.no_grad()
def predict(components, policy, x, routes):
    """Execute exactly one assigned component per row, never blend bank/student."""
    with e.measured() as timing:
        profile = _components(components, policy)
        c.observations(x, routes, profile["width"], profile["cells"])
        assigned = [policy["assignment"][i] for i in routes.tolist()]
        logits = torch.empty(len(x), profile["classes"], dtype=torch.float32)
        calls = []
        for name in sorted(set(assigned)):
            ids = torch.tensor([i for i,k in enumerate(assigned) if k == name], dtype=torch.long)
            inputs = c.augment(x[ids], routes[ids], profile["cells"]) if name == "shared" else x[ids]
            values = components[name](inputs)
            if values.shape != (len(ids), profile["classes"]) or not bool(torch.isfinite(values).all()):
                raise e.InputError("invalid partial Head output")
            logits[ids] = values
            calls.append({"component": name, "rows": ids.tolist(), "input_tensor_bytes": inputs.numel()*4})
        p = logits.softmax(-1)
    return {"probabilities": p.tolist(), "execution": {**timing, "calls": calls,
        "rows_processed": sum(len(v["rows"]) for v in calls), "head_forward_calls": len(calls),
        "resident_component_parameters": policy["parameters"], "encoder_calls": 0}}


def export(directory, components, policy, bindings):
    """Reuse existing Head artifacts; no full teacher bank in a partial bundle."""
    _components(components, policy)
    if set(bindings) != set(components):
        raise e.InputError("complete component feature bindings required")
    bindings = {k: _binding(v) for k,v in bindings.items()}
    if any(len({v[key] for v in bindings.values()}) != 1 for key in ("scope", "stem_sha256", "dataset_sha256")):
        raise e.InputError("partial components must share authorized source scope")
    directory = _path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    saved = {k: {**export_head(directory/k, model, bindings[k]), "binding": bindings[k]}
             for k,model in components.items()}
    return e.write_once(directory/"manifest.json", {"policy": policy, "heads": saved})


def reopen(directory, expected_sha256):
    """External bundle hash required. No imports/models beyond existing Head loader."""
    directory = _path(directory)
    raw = _read(directory/"manifest.json", MAX_INDEX)
    if e.sha(raw) != _digest(expected_sha256):
        raise e.InputError("external partial bundle digest mismatch")
    manifest = e.decode(raw)
    if not isinstance(manifest, dict) or set(manifest) != {"policy", "heads"}:
        raise e.InputError("closed partial bundle required")
    _policy(manifest["policy"])
    if (set(manifest["heads"]) != set(manifest["policy"]["components"])
            or {p.name for p in directory.iterdir()} != {"manifest.json", *manifest["heads"]}):
        raise e.InputError("exact minimal component directory required")
    # Validate ALL small Head manifests against the charged policy before allocating any model.
    bindings = {}
    for key, item in manifest["heads"].items():
        bindings[key] = _binding(item["binding"])
        head_raw = _read(directory/key/"manifest.json", 65536)
        if e.sha(head_raw) != _digest(item["manifest_sha256"]):
            raise e.InputError("partial component manifest drift")
        if e.decode(head_raw).get("parameters") != manifest["policy"]["components"][key]:
            raise e.InputError("partial allocation inventory differs from charged components")
    if any(len({v[key] for v in bindings.values()}) != 1 for key in ("scope", "stem_sha256", "dataset_sha256")):
        raise e.InputError("partial source scope mismatch")
    components = {k: load_head(directory/k, v["manifest_sha256"], v["binding"])
                  for k,v in manifest["heads"].items()}
    _components(components, manifest["policy"])
    return components, manifest["policy"]

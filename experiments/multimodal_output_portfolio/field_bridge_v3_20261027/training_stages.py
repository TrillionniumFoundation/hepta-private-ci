"""Paired complete rollouts and the predeclared development selection rule."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .learning import hard_panel, panels, save_hard
from .training_bank import stage_complete
from .training_common import MODES, configuration, file_hash, object_hash, require, write_json
from .training_policy import rollout


def panel_identity(panel):
    rows = []
    for part in panel:
        observation, target = part.batch.observation, part.batch.target
        public = b"".join(tensor.contiguous().numpy().tobytes() for tensor in
                          (observation.pixels, observation.mask, observation.text_tokens))
        truth = b"".join(tensor.contiguous().numpy().tobytes() for tensor in
                         (target.pixels, target.text_tokens, target.labels))
        rows.append({"condition": part.condition, "noise_seed": part.noise_seed,
                     "batch_size": len(part.batch.source_ids), "source_ids": part.batch.source_ids,
                     "public_sha256": hashlib.sha256(public).hexdigest(), "target_sha256": hashlib.sha256(truth).hexdigest()})
    return {"batches": rows, "sha256": object_hash(rows), "independent_of_schedule_id": True}


def run_stage(context, controller_path, out, stage, selection=None):
    p, out, started = configuration(context.protocol), Path(out), time.perf_counter_ns()
    fitted = json.loads(Path(controller_path).read_text())
    require(fitted["seed"] == context.seed and fitted["training_configuration_sha256"] == object_hash(p),
            "Fitted controller scope/configuration mismatch")
    if stage == "development":
        require(context.group == "development", "Development uses its own adaptation roles")
        policies = [{"name": f"ordinary_{index}", "action_index": index} for index in range(4)]
    else:
        require(stage in {"audit", "final"} and selection is not None and selection["passed"],
                "Audit/final requires the frozen successful development selection")
        require(context.group == ("audit" if stage == "audit" else "fit"), "Wrong adaptation-role group")
        policies = [{"name": "ordinary", "action_index": selection["ordinary_action_indices"][str(context.seed)]}]
    policies += [{"name": mode, "controller": fitted["controllers"][mode]} for mode in MODES]
    schedules = [p["final_schedule_id"]] if stage == "final" else p[stage + "_schedule_ids"]
    require(len(schedules) == (1 if stage == "final" else 4) and len(set(schedules)) == len(schedules), "Path schedule count differs")
    endpoints = ({"task": context.probe, "clean": context.guard} if stage == "final" else
                 {"task": panels(context.corpus, stage + "_task", context.seed, p["conditions"], context.protocol),
                  "clean": panels(context.corpus, stage + "_clean", context.seed, ["clean"], context.protocol)})
    observers = list(context.observers)
    require(observers == (["reward"] if stage == "final" else ["reward", "audit"]), "Observer ordering/access differs")
    identities = {name: panel_identity(panel) for name, panel in endpoints.items()}
    originals = {name: hard_panel(context.original, panel, context.observers, context.action, context.protocol,
                                  context.costs, stage + "_original_" + name, retain=True) for name, panel in endpoints.items()}
    for name, score in originals.items():
        save_hard(out / ("original-" + name + ".npz"), score)
    task, clean, paths = [], [], {}
    for policy in policies:
        method_task, method_clean = [], []
        for schedule_id in schedules:
            destination = out / policy["name"] / f"schedule-{schedule_id}"
            scores, record = rollout(context, policy, destination, stage, schedule_id, endpoints)
            for name in ("task", "clean"):
                require(scores[name]["source_ids"] == originals[name]["source_ids"]
                        and scores[name]["conditions"] == originals[name]["conditions"], "Endpoint pair/condition alignment changed")
            method_task.append(np.stack([scores["task"]["values"][name] for name in observers]))
            method_clean.append(np.stack([scores["clean"]["values"][name] for name in observers]))
            paths[f"{policy['name']}/{schedule_id}"] = {"complete_sha256": file_hash(destination / "COMPLETE.json"),
                "checkpoint": str((destination / "checkpoint.pt").relative_to(out)), "checkpoint_sha256": record["checkpoint"]["file_sha256"]}
            print(f"{stage} seed={context.seed} method={policy['name']} path={schedule_id} complete", flush=True)
        task.append(np.stack(method_task))
        clean.append(np.stack(method_clean))
    require({name: panel_identity(panel) for name, panel in endpoints.items()} == identities,
            "A method mutated the common endpoint panel")
    with (out / "ENDPOINTS.npz").open("xb") as stream:
        np.savez_compressed(stream, methods=np.asarray([policy["name"] for policy in policies], dtype=str),
            schedule_ids=np.asarray(schedules), observer_names=np.asarray(observers, dtype=str),
            task_values=np.stack(task), clean_values=np.stack(clean),
            original_task=np.stack([originals["task"]["values"][name] for name in observers]),
            original_clean=np.stack([originals["clean"]["values"][name] for name in observers]),
            task_source_ids=np.asarray(originals["task"]["source_ids"], dtype=str),
            clean_source_ids=np.asarray(originals["clean"]["source_ids"], dtype=str),
            task_conditions=np.asarray(originals["task"]["conditions"], dtype=str),
            clean_conditions=np.asarray(originals["clean"]["conditions"], dtype=str),
            task_panel_identity=np.asarray(identities["task"]["sha256"]), clean_panel_identity=np.asarray(identities["clean"]["sha256"]))
    write_json(out / "ENDPOINT_IDENTITIES.json", identities)
    return stage_complete(out, context, {"stage": stage, "controller_file_sha256": file_hash(controller_path),
        "methods": [policy["name"] for policy in policies], "schedule_ids": schedules, "paths": paths,
        "endpoint_values_sha256": file_hash(out / "ENDPOINTS.npz"), "endpoints_shared_across_paths_and_methods": True,
        "primary_or_final_retention_loaded": False}, started)


def select_development(run_root, protocol):
    """All selection is performed once, with the H12 treatment fixed in advance."""
    p, root = configuration(protocol), Path(run_root)
    gate, per_seed, identities = protocol["training_development_gate"], {}, {}
    ordinary, arrays, method_order = {}, {}, None
    for seed in protocol["seeds"]:
        path = root / "development" / str(seed) / "ENDPOINTS.npz"
        with np.load(path, allow_pickle=False) as loaded:
            data = {key: loaded[key].copy() for key in loaded.files}
        names = data["methods"].tolist()
        require(names == ["ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", *MODES]
                and data["observer_names"].tolist() == ["reward", "audit"], "Development method/observer order changed")
        require(data["schedule_ids"].tolist() == p["development_schedule_ids"], "Development schedules changed")
        task_gain = (data["task_values"] - data["original_task"][None, None]).mean(axis=(1, 3))
        clean_gain = (data["clean_values"] - data["original_clean"][None, None]).mean(axis=(1, 3))
        eligible = [index for index in range(4) if np.all(clean_gain[index] >= p["ordinary_clean_min_delta"])]
        require(eligible, "No eligible ordinary path, including exact no-update control")
        winner = max(eligible, key=lambda index: (float(task_gain[index, 0]), -index))
        ordinary[str(seed)] = winner
        per_seed[str(seed)] = {name: {"task_gain": task_gain[index].tolist(), "clean_gain": clean_gain[index].tolist()}
                               for index, name in enumerate(names)}
        arrays[str(seed)] = (task_gain, clean_gain)
        identities[str(seed)] = file_hash(path)
        method_order = names
    eligible_adaptive = [mode for mode in ("generic", "richer", "h7")
        if all(np.all(arrays[str(seed)][1][method_order.index(mode)] >= gate["each_seed_clean_delta_min"])
               for seed in protocol["seeds"])]
    selected = None if not eligible_adaptive else max(eligible_adaptive,
        key=lambda mode: (float(np.mean([arrays[str(seed)][0][method_order.index(mode), 0] for seed in protocol["seeds"]])),
                          -("generic", "richer", "h7").index(mode)))
    ordinary_gain = np.stack([arrays[str(seed)][0][ordinary[str(seed)]] for seed in protocol["seeds"]])
    field_gain = np.stack([arrays[str(seed)][0][method_order.index("field")] for seed in protocol["seeds"]])
    field_clean = np.stack([arrays[str(seed)][1][method_order.index("field")] for seed in protocol["seeds"]])
    adaptive_gain = None if selected is None else np.stack([arrays[str(seed)][0][method_order.index(selected)] for seed in protocol["seeds"]])
    checks = {
        "ordinary_each_seed_nonnegative": bool(np.all(ordinary_gain >= gate["ordinary_each_seed_gain_min"])),
        "ordinary_pooled_gain": bool(np.all(ordinary_gain.mean(0) >= gate["ordinary_pooled_gain_min"])),
        "field_clean_eligible": bool(np.all(field_clean >= gate["each_seed_clean_delta_min"])),
        "field_over_ordinary": bool(np.all((field_gain - ordinary_gain).mean(0) > gate["field_over_ordinary_pooled_gain_strict_min"])),
        "eligible_adaptive_exists": selected is not None,
        "field_over_selected_adaptive": selected is not None and bool(np.all((field_gain - adaptive_gain).mean(0) >= gate["field_over_selected_adaptive_pooled_gain_min"]))}
    result = {"schema": "hepta.field-bridge.v3.development-selection.1", "passed": all(checks.values()),
        "checks": checks, "ordinary_action_indices": ordinary, "selected_adaptive": selected,
        "eligible_adaptive_methods": eligible_adaptive, "per_seed": per_seed, "endpoint_file_sha256": identities,
        "ordinary_pooled_gain": ordinary_gain.mean(0).tolist(),
        "field_over_ordinary_pooled_gain": (field_gain - ordinary_gain).mean(0).tolist(),
        "field_over_selected_adaptive_pooled_gain": None if selected is None else (field_gain - adaptive_gain).mean(0).tolist(),
        "observers": ["reward", "audit"], "field_family_selection": False,
        "no_fresh_audit_outcomes_used": True, "training_configuration_sha256": object_hash(p)}
    write_json(root / "DEVELOPMENT_SELECTION.json", result)
    return result

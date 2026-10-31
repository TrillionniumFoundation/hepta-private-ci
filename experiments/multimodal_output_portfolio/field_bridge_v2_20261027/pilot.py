"""Frozen-grid development pilot. Never scores test, retention, or audit observer."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import torch

from ..field_bridge_20261027.run import setup, write_json, digest
from ..field_bridge_20261027.adapters import frozen_base_hash, local_parameters, local_hash
from .learning import P, make_model, new_optimizer, gradient_corpus, panel, hard_outputs, train_steps, displacement, save_model


def source_freeze():
    root = Path(__file__).parent
    files = [root / name for name in ("__init__.py", "PILOT_PROTOCOL.json", "learning.py", "pilot.py")]
    files.extend((root.parent / "field_bridge_20261027").glob("*.py"))
    files.extend((root.parent / "v6").glob("*.py"))
    return {str(path.relative_to(root.parent)): digest(path) for path in sorted(files)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--registered-commit", required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources = source_freeze()
    write_json(out / "SOURCE_FREEZE.json", {"files": sources, "registered_commit": args.registered_commit})
    corpus, observers, originals, identities = setup(args)
    observer, data = observers["reward"], gradient_corpus(corpus)
    write_json(out / "ENVIRONMENT.json", {"python": sys.version, "torch": torch.__version__, "numpy": np.__version__,
               "platform": platform.platform(), "models": identities, "corpus": corpus.manifest,
               "audit_observer_loaded": False, "test_retention_scored": False})
    results = {}
    started = time.perf_counter_ns()
    for seed in P["seeds"]:
        original = originals[seed]
        root = out / str(seed)
        root.mkdir()
        response = panel(corpus, P["response_panel"], seed)
        clean = panel(corpus, P["clean_probe"], seed)
        selection = panel(corpus, P["selection_panel"], seed)
        actions = [hard_outputs(original, selection, observer, a) for a in range(5)]
        action = int(np.argmax([x["value"] for x in actions]))
        original_response = hard_outputs(original, response, observer, action)
        original_clean = hard_outputs(original, clean, observer, action)
        write_json(root / "BASELINE.json", {"action": action, "actions": actions, "response": original_response,
                    "clean": original_clean, "source_ids": {"response": response[0][1].source_ids,
                     "clean": clean[0][1].source_ids, "selection": selection[0][1].source_ids}})
        candidates = []
        for recipe in P["candidates"]:
            try:
                then = time.perf_counter_ns()
                model = make_model(original, seed, recipe)
                optimizer = new_optimizer(model, recipe)
                base_hash = frozen_base_hash(model)
                initial = hard_outputs(model, response, observer, action)
                if initial != original_response:
                    raise RuntimeError("Zero adapter changed initial decoded outputs")
                history = [{"step": 0, "response_value": initial["value"], "operator_displacement": displacement(model, recipe)}]
                cursor = 0
                while cursor < recipe["steps"]:
                    count = min(P["checkpoint_frequency"], recipe["steps"] - cursor)
                    train_steps(model, original, optimizer, data, action, recipe, seed, 0, cursor, count)
                    cursor += count
                    current = hard_outputs(model, response, observer, action)
                    history.append({"step": cursor, "response_value": current["value"],
                                    "operator_displacement": displacement(model, recipe), "local_sha256": local_hash(model)})
                final = hard_outputs(model, selection, observer, action)
                clean_final = hard_outputs(model, clean, observer, action)
                if base_hash != frozen_base_hash(model):
                    raise RuntimeError("Frozen generator changed")
                changed = float(np.mean([a != b for a, b in zip(current["decisions"], original_response["decisions"])]))
                result = {"recipe": recipe, "history": history, "response": current, "selection": final,
                          "clean": clean_final, "development_gain": final["value"] - actions[action]["value"],
                          "development_clean_change": final["by_condition"]["clean"] - actions[action]["by_condition"]["clean"],
                          "clean_probe_change": clean_final["value"] - original_clean["value"],
                          "response_decision_change_fraction": changed,
                          "trainable_parameters": sum(p.numel() for p in local_parameters(model)),
                          "zero_effect_initialization_exact": True, "base_unchanged": True,
                          "wall_ns": time.perf_counter_ns() - then, "gradient_examples": recipe["steps"] * P["batch_size"]}
                save_model(root / (recipe["name"] + ".pt"), model, optimizer, recipe,
                           {"seed": seed, "base_identity": identities[seed], "phase": "development_actuator_pilot"})
                write_json(root / (recipe["name"] + ".json"), result)
                print(f"seed={seed} {recipe['name']}: gain={result['development_gain']:.6f} clean={result['development_clean_change']:.6f} changed={changed:.3f}", flush=True)
            except FloatingPointError as error:
                result = {"recipe": recipe, "failed": True, "error": str(error), "stage": "numerical_training_failure"}
                write_json(root / (recipe["name"] + ".FAILED.json"), result)
                print(f"seed={seed} {recipe['name']}: NUMERICAL FAILURE {error}", flush=True)
            candidates.append(result)
        results[str(seed)] = {"action": action, "baseline_value": actions[action]["value"], "candidates": candidates,
                             "response_candidate_range": float(np.ptp([original_response["value"], *[x["response"]["value"] for x in candidates if not x.get("failed")]]))}
    rankings = []
    ordinary_gate, actuator_gate = P["ordinary_gate"], P["actuator_gate"]
    for index, recipe in enumerate(P["candidates"]):
        chosen = [results[str(seed)]["candidates"][index] for seed in P["seeds"]]
        eligible = all(not x.get("failed") and x["development_gain"] >= ordinary_gate["minimum_each_seed_gain"] and
                       x["development_clean_change"] >= ordinary_gate["minimum_each_seed_development_clean_change"] for x in chosen)
        rankings.append({"name": recipe["name"], "index": index, "eligible": eligible,
                         "mean_gain": float(np.mean([x["development_gain"] for x in chosen])) if not any(x.get("failed") for x in chosen) else None})
    eligible = [x for x in rankings if x["eligible"]]
    selected = max(eligible, key=lambda x: (x["mean_gain"], -x["index"])) if eligible else None
    actuator = selected is not None and all(
        r["response_candidate_range"] >= actuator_gate["minimum_per_seed_candidate_value_range"] and
        r["candidates"][selected["index"]]["response_decision_change_fraction"] >=
        actuator_gate["minimum_per_seed_selected_semantic_or_image_decision_change_fraction"] for r in results.values())
    ordinary = selected is not None and selected["mean_gain"] >= ordinary_gate["minimum_pooled_development_gain"]
    summary = {"schema": "hepta.field-bridge.v2.pilot-result.1", "results": results, "rankings": rankings,
               "selected": selected, "actuator_identified": bool(actuator), "ordinary_qualified": bool(ordinary),
               "allowed_to_fit_field": bool(actuator and ordinary), "allowed_to_open_new_test": False,
               "wall_ns": time.perf_counter_ns() - started, "audit_observer_loaded": False,
               "test_retention_scored": False, "protocol_sha256": digest(Path(__file__).with_name("PILOT_PROTOCOL.json"))}
    if source_freeze() != sources:
        raise RuntimeError("Source changed during actuator pilot")
    write_json(out / "PILOT_RESULT.json", summary)
    print(json.dumps({k: summary[k] for k in ("selected", "actuator_identified", "ordinary_qualified", "allowed_to_fit_field")}))


if __name__ == "__main__":
    main()

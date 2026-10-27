"""Actual-output readout fitting and independent-source validation."""

import argparse
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch

from ...continuation_20261027.control.client import Native, Q, continuation
from ...continuation_20261027.control.training import prefix
from ...continuation_20261027.joint.data import historical_corpus
from ...continuation_20261027.joint.run import reference_observer
from .adapter import Generator, generic_memory, scalar_feedback, score
from .critic import select_pooling
from .protocol import PROTOCOL as P, digest, preserve_sources, sha, write
from .tasks import make_tasks, persist_tasks


def sample_states(native, root, model, calibration, examples):
    features = []
    for row in examples:
        index = row["index"]
        directory = root / "readout-trajectories" / f"case-{index:03}"
        directory.mkdir(parents=True)
        native.open(directory / "owner", f"semantic-fit.{index}", 64, model, calibration)
        prefix(native, 0)
        evidence = {"actual_delivery": row["initial_delivery"], "feedback": row["feedback"]}
        ticks = continuation(native, row["feedback"], evidence)
        native.close()
        write(directory / "TRANSCRIPT.json", native.transcript)
        x = [1.0] + [value / Q for value in ticks[-1]["eligibility_before_q24"]]
        features.append(x)
        row["owner_features"] = x
        row["owner_final_state"] = ticks[-1]
    return np.asarray(features)


def fit_heads(rows, features):
    target = np.asarray([np.exp(-P["gamma"] * row["initial"]["utility"])
        - np.exp(-P["gamma"] * (row["alternate"]["utility"]
            - P["generator_call_charge"] - P["delivery_charge"])) for row in rows])
    generic = np.asarray([generic_memory(row["feedback"]) for row in rows])
    weights = np.linalg.solve(features.T @ features + P["readout_ridge"] * np.eye(11), features.T @ target)
    generic_weights = np.linalg.solve(generic.T @ generic + P["readout_ridge"] * np.eye(11), generic.T @ target)
    history = {str(symbol): float(target[[r["feedback"] == symbol for r in rows]].mean()) for symbol in (-1, 0, 1)}
    if any(not any(r["feedback"] == symbol for r in rows) for symbol in (-1, 0, 1)):
        raise ValueError("Readout fitting lacks a declared scalar support point")
    return {"native_weights": weights.tolist(), "linear_weights": generic_weights.tolist(),
        "history_moment_difference": history, "target_moment_difference": target.tolist(),
        "fit_feature_sha256": digest(features.tolist()), "fit_generic_feature_sha256": digest(generic.tolist()),
        "examples": len(rows), "trainable_coefficients_per_state_head": 11,
        "fit_native_mse": float(np.mean((features @ weights - target) ** 2)),
        "fit_generic_mse": float(np.mean((generic @ generic_weights - target) ** 2)),
        "fits_terminal_actual_output_difference": True, "generator_updated_in_this_study": False}


def state_table(native, root, model, calibration):
    result = {}
    for symbol in (-1, 0, 1):
        directory = root / "frozen-state-table" / f"symbol-{symbol}"
        directory.mkdir(parents=True)
        native.open(directory / "owner", f"semantic-symbol.{symbol}", 64, model, calibration)
        prefix(native, 0)
        ticks = continuation(native, symbol, {"finite_public_symbol": symbol})
        native.close()
        write(directory / "TRANSCRIPT.json", native.transcript)
        result[str(symbol)] = {"proposal": ticks[-1]["proposed_repair"], "readout_logit": ticks[-1]["readout_logit"],
            "eligibility_before_q24": ticks[-1]["eligibility_before_q24"]}
    return result


def deliver_dataset(tasks, directory, generator, reward):
    records = []
    for task in tasks:
        root = directory / f"pair-{task['index']:04}"
        root.mkdir(parents=True)
        initial, pixels = generator.deliver(task["public"], 0, root / "initial")
        feedback = scalar_feedback(initial["caption"], task["private"].labels[0].tolist())
        feedback_at = time.monotonic_ns()
        initial_score = score(reward, initial, pixels, task["private"])
        alternate, other_pixels = generator.deliver(task["public"], 1, root / "alternate-training-probe")
        other_score = score(reward, alternate, other_pixels, task["private"])
        row = {k: task[k] for k in ("index", "condition", "source_ids", "preference")}
        row.update(initial=initial_score, alternate=other_score, feedback=feedback,
            initial_delivery=initial, alternate_delivery=alternate, feedback_monotonic_ns=feedback_at,
            both_actions_are_training_probes=True, private_truth_in_generator=False)
        write(root / "RECORD.json", row)
        records.append(row)
    return records


def run(assets, generator_path, binary, output):
    output.mkdir(parents=True, exist_ok=False)
    if sha(binary) != P["native_binary_sha256"]:
        raise ValueError("Original native binary changed")
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    write(output / "PROTOCOL.json", P)
    sources = preserve_sources(output / "executed-source")
    corpus = historical_corpus(assets)
    write(output / "HISTORICAL_CORPUS.json", corpus.manifest)
    model_path = output / "UNTRAINED_MODEL.json"
    write(model_path, {"schema": "hepta.continuation.owner-readout.v1", "weights": [0.0] * 11})
    calibration = output / "ENCODER_DOMAIN_PROOF.json"
    old = Path(__file__).parents[2] / "continuation_20261027/control/evidence/RUN002_ENCODER_DOMAIN_PROOF.json"
    shutil.copyfile(old, calibration)
    generator, reward = Generator(generator_path), reference_observer(assets, "reward")
    fit_tasks = make_tasks(corpus, "train", P["fit_pairs"])
    validation_tasks = make_tasks(corpus, "validation", P["validation_pairs"], offset=384)
    persist_tasks(fit_tasks, output / "fit-inputs")
    persist_tasks(validation_tasks, output / "validation-inputs")
    fit = deliver_dataset(fit_tasks, output / "fit", generator, reward)
    validation = deliver_dataset(validation_tasks, output / "validation", generator, reward)
    native = Native(binary)
    selected = fit[:P["readout_examples"]]
    features = sample_states(native, output, model_path, calibration, selected)
    heads = fit_heads(selected, features)
    model_path = output / "MODEL.json"
    write(model_path, {"schema": "hepta.continuation.owner-readout.v1", "weights": heads["native_weights"]})
    heads["native_by_feedback"] = state_table(native, output, model_path, calibration)
    native.finish()
    write(output / "FIT.json", fit)
    write(output / "VALIDATION.json", validation)
    write(output / "READOUT_FIT.json", heads)
    selection = select_pooling(fit, validation, heads)
    write(output / "CRITIC_SELECTION.json", selection)
    write(output / "FROZEN.json", {"protocol_sha256": sha(output / "PROTOCOL.json"),
        "source_sha256": sources, "generator_sha256": sha(generator_path), "binary_sha256": sha(binary),
        "model_sha256": sha(model_path), "readout_fit_sha256": sha(output / "READOUT_FIT.json"),
        "fit_sha256": sha(output / "FIT.json"), "critic_selection_sha256": sha(output / "CRITIC_SELECTION.json"),
        "audit_observer_loaded": False, "qualification_outputs_computed": False})
    print(json.dumps({"heads": heads["native_by_feedback"], "critic": selection}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--generator", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.output)

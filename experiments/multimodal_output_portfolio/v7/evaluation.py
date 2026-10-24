"""Strict raw-output observations; insufficient cases remain in every total."""

import hashlib
import json
from pathlib import Path
import time

import torch

from ..v6.data import Observation, render_tokens
from ..v6.neural import parameter_hash, read_checkpoint
from ..v6.observer import (METRIC_DIGEST, Recognizer, observe_tensors, read_bundle,
                           upper_tail, write_bundle)
from .data import SUFFICIENT_VIEWS, VIEWS, make_batch


def load_reward(path, expected_file_sha256=None):
    record = read_checkpoint(path, expected_file_sha256)
    if record.get("schema") != "hepta.ndu-v7.reward-observer.v1" or record["metric_sha256"] != METRIC_DIGEST:
        raise ValueError("Unsupported reward observer/metric")
    model = Recognizer()
    model.load_state_dict(record["state_dict"], strict=True)
    model.eval().requires_grad_(False)
    if parameter_hash(model) != record["parameter_sha256"]:
        raise ValueError("Observer parameter hash mismatch")
    return model, record


def summarize(rows):
    if not rows:
        raise ValueError("A scientific summary cannot omit its census")
    return {
        "count": len(rows),
        "joint_loss": sum(row["joint_loss"] for row in rows) / len(rows),
        "cvar90_joint_loss": upper_tail([row["joint_loss"] for row in rows]),
        "joint_fact_correct": sum(row["joint_fact_correct"] for row in rows) / len(rows),
        "required_output_completion": sum(row["required_output_complete"] for row in rows) / len(rows),
        "image_digit_accuracy": 1 - sum(row["image_fact"] for row in rows) / len(rows),
        "text_digit_accuracy": 1 - sum(row["text_fact"] for row in rows) / len(rows),
        "unordered_caption_correct": sum(row["unordered_caption_correct"] for row in rows) / len(rows),
        "duplicated_image_digits": sum(row["duplicated_image_digits"] for row in rows) / len(rows),
    }


def evaluate_development(snapshot, corpus, observer, directory, *, pairs=128, offset=0,
                         actions=("refine_image", "refine_text"), seed=424242):
    """Only the named development role. Batch timing is not deployment timing."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    snapshot.verify_integrity()
    observer_hash = parameter_hash(observer)
    rows, positive_control = [], []
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    for view in VIEWS:
        batch = make_batch(corpus, "development", pairs, seed, view=view, offset=offset)
        if view == "clean":
            observed = observe_tensors(observer, batch.target.pixels,
                                       [render_tokens(tokens) for tokens in batch.target.text_tokens],
                                       batch.target.pixels, batch.target.labels)
            positive_control = [dict(item, joint_fact_correct=all(item[key] == 0 for key in
                                    ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
                                for item in observed]
        for start in range(0, pairs, 64):
            stop = min(start + 64, pairs)
            observation = Observation(*(value[start:stop] for value in
                                        (batch.observation.pixels, batch.observation.mask,
                                         batch.observation.text_tokens)))
            state = snapshot.encode(observation, noise_seed=seed + start)
            for action in actions:
                state = snapshot.step(state, action)
            output = snapshot.decode(state)
            pixels, captions, hashes = [], [], []
            for local, tokens in enumerate(output.token_ids):
                paths = write_bundle(directory / "raw" / view / f"{start + local:04d}",
                                     render_tokens(tokens), output.image_logits[local].sigmoid())
                raw_pixels, caption, raw_hashes = read_bundle(paths)
                pixels.append(raw_pixels[0])
                captions.append(caption)
                hashes.append(raw_hashes)
            observed = observe_tensors(observer, torch.stack(pixels), captions,
                                       batch.target.pixels[start:stop], batch.target.labels[start:stop])
            for local, score in enumerate(observed):
                i = start + local
                correct = all(score[key] == 0 for key in
                              ("text_fact", "relation", "image_fact", "crossmodal_disagreement"))
                row = {
                    "case": offset + i, "view": view, "source_ids": batch.source_ids[i],
                    "information_sufficient": batch.information_sufficient[i],
                    "untrusted_hint_correct": batch.untrusted_hint_correct[i],
                    "snapshot_sha256": snapshot.fingerprint, "raw_sha256": hashes[local],
                    "actions": actions, "step_count": state.step_count,
                    "joint_fact_correct": bool(correct and score["caption_valid"]),
                    "required_output_complete": bool(score["caption_valid"]),
                    "unordered_caption_correct": bool(score["caption_digits"] is not None and
                        sorted(score["caption_digits"]) == sorted(batch.target.labels[i].tolist())),
                    "duplicated_image_digits": score["image_digits"][0] == score["image_digits"][1],
                    **score,
                }
                rows.append(row)
    with (directory / "rows.jsonl").open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    report = {
        "schema": "hepta.ndu-v7.development-competence.v1", "role": "development",
        "formal_holdout_opened": False, "pairs": pairs, "pair_offset": offset,
        "census_views": VIEWS, "rows": len(rows), "actions": actions, "seed": seed,
        "source_manifest_sha256": corpus.manifest["manifest_sha256"],
        "snapshot_sha256": snapshot.fingerprint, "observer_sha256": observer_hash,
        "metric_sha256": METRIC_DIGEST, "strict_full_census": summarize(rows),
        "per_view": {view: summarize([row for row in rows if row["view"] == view]) for view in VIEWS},
        "sufficient_diagnostic": summarize([row for row in rows if row["view"] in SUFFICIENT_VIEWS]),
        "insufficient_diagnostic": summarize([row for row in rows if row["view"] not in SUFFICIENT_VIEWS]),
        "untrusted_correct_hint_diagnostic": summarize([row for row in rows if row["untrusted_hint_correct"] is True]),
        "untrusted_wrong_hint_diagnostic": summarize([row for row in rows if row["untrusted_hint_correct"] is False]),
        "positive_control_true_target_joint_correct": sum(row["joint_fact_correct"] for row in positive_control) / pairs,
        "positive_control_true_target_joint_loss": sum(row["joint_loss"] for row in positive_control) / pairs,
        "batch64_wall_ns": time.perf_counter_ns() - wall,
        "batch64_cpu_ns": time.process_time_ns() - cpu,
        "timing_is_matched_deployment_cost": False,
        "rows_file_sha256": hashlib.sha256((directory / "rows.jsonl").read_bytes()).hexdigest(),
    }
    snapshot.verify_integrity()
    if observer_hash != parameter_hash(observer):
        raise RuntimeError("Frozen observer changed")
    (directory / "summary.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report

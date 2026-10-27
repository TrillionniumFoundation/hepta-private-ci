"""Freeze a public head, then calibrate on disjoint historical source pairs."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...continuation_20261027.control.client import Native, continuation
from ...continuation_20261027.control.training import prefix
from ...continuation_20261027.joint.data import historical_corpus
from ...continuation_20261027.joint.run import reference_observer
from .acceptance_features import observed_semantics
from .acceptance_head import predicted, public_vector
from .adapter import Generator, scalar_feedback
from .protocol import PROTOCOL as OWNER_SPEC, digest, preserve_sources, sha, write
from .selective_data import tasks
from .selective_metrics import confidence, final_choice, summarize
from .selective_protocol import SPEC
from .tasks import persist_tasks
from .verify_media import independent_score


def public_category(features, head_probability, threshold, minimum_public_probability=0.0):
    if features["declared_both_missing"]:
        return "declared_ood"
    if not features["feedback_known"]:
        return "unknown_preference"
    if not features["caption_matches_inferred_order"]:
        return "caption_inconsistent"
    if (features["public_image_argmax_agrees"] and head_probability >= threshold
            and features["minimum_inferred_digit_probability"] >= minimum_public_probability):
        return "selected_by_public_head"
    return "other_known_candidate"


def real_state_table(binary, development, output):
    native, table = Native(binary), {}
    for expiry in (6, 7):
        for scalar in (-1, 0, 1):
            directory = output / "native-readout-table" / f"expiry-{expiry}-scalar-{scalar}"
            directory.mkdir(parents=True)
            native.open(directory / "owner", f"acceptance.calibration.{expiry}.{scalar}", expiry,
                        development / "MODEL.json", development / "ENCODER_DOMAIN_PROOF.json")
            prefix(native, 0)
            ticks = continuation(native, scalar, {"declared_public_scalar": scalar})
            native.close()
            write(directory / "TRANSCRIPT.json", native.transcript)
            table[f"{expiry}:{scalar}"] = {"proposed": ticks[-1]["proposed_repair"],
                "admissible": not any(t["native_abstain"] for t in ticks),
                "eligibility_before_q24": ticks[-1]["eligibility_before_q24"], "readout_logit": ticks[-1]["readout_logit"]}
    native.finish()
    write(output / "NATIVE_READOUT_TABLE.json", table)
    return table


def run(assets, generator_path, binary, development, acceptance_development, head_development, output,
        specification=None, selector_path=None, retired_calibration=None):
    spec = SPEC if specification is None else specification
    outcome_head = head_development / "SELECTED_MODEL.json"
    model = json.loads(outcome_head.read_text())
    selector = json.loads(selector_path.read_text()) if selector_path else None
    if selector and selector["head_model_sha256"] != sha(outcome_head):
        raise ValueError("Frozen public selector was fitted to a different head")
    source_feature_rows = acceptance_development / "FEATURE_ROWS.json"
    if sha(source_feature_rows) != model["source_feature_rows_sha256"]:
        raise ValueError("The outcome head's historical evidence identity changed")
    if sha(generator_path) != OWNER_SPEC["generator_sha256"] or sha(binary) != OWNER_SPEC["native_binary_sha256"]:
        raise ValueError("Frozen generation or native state law changed")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    write(output / "PROTOCOL.json", spec)
    corpus = historical_corpus(assets)
    slices = spec.get("source_slices", {"calibration_id": ["validation", 512], "calibration_ood": ["train", 2000]})
    groups = {role: tasks(corpus, *slices[role][:1], spec[role + "_pairs"], slices[role][1], role,
        role == "calibration_ood", seed=spec["new_random_namespaces"][role]) for role in ("calibration_id", "calibration_ood")}
    excluded = {identifier.rsplit(":", 1)[1] for row in json.loads(source_feature_rows.read_text()) for identifier in row["source_ids"]}
    if retired_calibration:
        excluded.update(identifier.rsplit(":", 1)[1]
            for row in json.loads((retired_calibration / "ROWS.json").read_text()) for identifier in row["source_ids"])
    source_records, seen = {}, set()
    for name, items in groups.items():
        hashes = [identifier.rsplit(":", 1)[1] for task in items for identifier in task["source_ids"]]
        if set(hashes) & (excluded | seen) or len(hashes) != len(set(hashes)):
            raise ValueError("Acceptance head/calibration source identities overlap")
        seen.update(hashes)
        persist_tasks(items, output / f"{name}-inputs")
        source_records[name] = {"pairs": len(items), "source_ids": [identifier for task in items for identifier in task["source_ids"]],
            "public_input_sha256": sha(output / f"{name}-inputs/PUBLIC.pt"), "private_input_sha256": sha(output / f"{name}-inputs/PRIVATE.pt")}
    write(output / "SOURCE_MANIFEST.json", {"splits": source_records, "head_fit_validation_excluded_pixel_hashes": sorted(excluded),
        "overlap": 0, "source_manifest_sha256": corpus.manifest["manifest_sha256"], "fresh_qualification_not_allocated": True})
    sources = preserve_sources(output / "executed-source")
    write(output / "CALIBRATION_SEAL.json", {"protocol_sha256": sha(output / "PROTOCOL.json"),
        "source_manifest_sha256": sha(output / "SOURCE_MANIFEST.json"), "head_model_sha256": sha(outcome_head),
        "owner_readout_sha256": sha(development / "MODEL.json"), "generator_sha256": sha(generator_path),
        "binary_sha256": sha(binary), "selector_sha256": sha(selector_path) if selector_path else None,
        "retired_calibration_rows_sha256": sha(retired_calibration / "ROWS.json") if retired_calibration else None,
        "source_sha256": sources, "calibration_outputs_computed": False,
        "fresh_qualification_outputs_computed": False})
    native_table = real_state_table(binary, development, output)
    generator = Generator(generator_path)
    public_observer, private_observer = reference_observer(assets, "reward"), reference_observer(assets, "audit")
    records = []
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    for name, items in groups.items():
        for task in items:
            directory = output / "candidates" / name / f"pair-{task['index']:04}"
            directory.mkdir(parents=True)
            initial, _ = generator.deliver(task["public"], 0, directory / "initial")
            scalar = scalar_feedback(initial["caption"], task["private"].labels[0].tolist())
            feedback_at = time.monotonic_ns()
            native = native_table[f"{task['expires']}:{scalar}"]
            correction = bool(native["proposed"] and native["admissible"] and task["budget"] >= 2)
            candidate = generator.deliver(task["public"], 1, directory / "candidate")[0] if correction else initial
            features = observed_semantics(initial, candidate, scalar, task["public"].observation, public_observer)
            vector = public_vector(candidate, features, public_observer)
            raw_probability = float(predicted(model, vector[None])[0])
            category = public_category(features, raw_probability,
                selector["head_threshold"] if selector else model["threshold"],
                selector["minimum_public_digit_probability"] if selector else 0.0)
            features_at = time.monotonic_ns()
            grade = independent_score(private_observer, candidate, task["private"].pixels.numpy(), task["private"].labels[0].tolist())
            row = {"role": name, "index": task["index"], "source_ids": task["source_ids"], "declared_ood": task["declared_ood"],
                "expires": task["expires"], "budget": task["budget"], "initial": initial, "feedback": scalar,
                "candidate": candidate, "actual_correction": correction, "native_state_table_key": f"{task['expires']}:{scalar}",
                "public_features": features, "public_vector": vector.tolist(), "raw_head_probability": raw_probability,
                "category": category, "strict_success": grade["strict_success"], "private_grade": grade,
                "chronology": {"initial_delivery": initial["delivered_monotonic_ns"], "scalar_arrived": feedback_at,
                    "candidate_readback": candidate["delivered_monotonic_ns"], "public_features_finalized": features_at,
                    "private_grade": time.monotonic_ns()},
                "per_case_native_execution": False, "offline_calibration_candidate": True}
            write(directory / "RECORD.json", row)
            records.append(row)
        print(f"completed independent calibration source role {name}: {len(items)}", flush=True)
    categories = {}
    for name in spec["categories"]:
        selected = [row for row in records if row["category"] == name]
        if not selected:
            raise ValueError("Frozen probability category lacks calibration support")
        successes = sum(row["strict_success"] for row in selected)
        if name == "caption_inconsistent" and successes:
            raise ValueError("Logical caption/arrived-feedback boundary contradicted private scoring")
        probability = 0.0 if name == "caption_inconsistent" else (successes + .5) / (len(selected) + 1)
        categories[name] = {"n": len(selected), "successes": successes, "probability": probability}
    calibrator = {"categories": categories, "head_model_sha256": sha(outcome_head),
        "head_model": model, "native_readout_sha256": sha(development / "MODEL.json"),
        "selector": selector, "selector_sha256": sha(selector_path) if selector_path else None,
        "generator_checkpoint_sha256": sha(generator_path), "native_binary_sha256": sha(binary),
        "native_calibration_sha256": sha(development / "ENCODER_DOMAIN_PROOF.json"),
        "decoder_contract": "public-observation-order-command-two-transitions-greedy-png-utf8.v1",
        "probability_event": spec["score_event"], "protocol_sha256": sha(output / "PROTOCOL.json"),
        "native_semantic_calibration": False}
    write(output / "CALIBRATOR.json", calibrator)
    for row in records:
        probability = categories[row["category"]]["probability"]
        commit, moment = final_choice(probability, row["category"])
        row.update(probability=probability, confidence_ppm=confidence(probability), commit=commit,
            predicted_commit_moment=moment, fitted_probability_uses_this_calibration_cohort=True)
    write(output / "ROWS.json", records)
    result = summarize(records)
    result.update(calibration_fit_metrics_not_heldout_qualification=True, source_identities_do_not_overlap_head_development=True,
        actual_native_state_paths=6, actual_native_kernel_executions=42,
        actual_generator_calls=sum(1 + r["actual_correction"] for r in records),
        actual_media_files=2 * sum(1 + r["actual_correction"] for r in records),
        wall_ns=time.perf_counter_ns() - started, python_cpu_ns=time.process_time_ns() - cpu,
        rows_sha256=sha(output / "ROWS.json"), calibrator_sha256=sha(output / "CALIBRATOR.json"))
    write(output / "RESULT.json", result)
    write(output / "FROZEN_CALIBRATOR.json", {"calibrator_sha256": sha(output / "CALIBRATOR.json"),
        "result_sha256": sha(output / "RESULT.json"), "protocol_sha256": sha(output / "PROTOCOL.json"),
        "qualification_sources_allocated": False, "qualification_outputs_computed": False})
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "generator", "binary", "development", "acceptance-development", "head-development", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.development, args.acceptance_development, args.head_development, args.output)

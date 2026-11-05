"""Selection-only training of raw and value-free slot semantic routing arms."""

from dataclasses import asdict
from pathlib import Path
import time

import numpy as np

from .numeric_graph import INTENTS, SERIES_NAMES
from .route_language import DESCRIPTIONS, language_rows, router_training_rows
from .route_metrics import literal_route, route_summary
from .semantic_router import REJECT, SemanticRouter, canonical, digest


L2_GRID = (0.0001, 0.0003, 0.001)
ALIAS_GRID = (0, 3, 6)


def slot_text(row):
    """Replace only explicit identity values; preserve all predicate language."""
    name = row.get("training_source_alias", SERIES_NAMES[row["domain"]])
    if name not in row["utterance"] or row["date"] not in row["utterance"]:
        raise ValueError("declared query slots do not occur in the full utterance")
    return row["utterance"].replace(name, "[series]").replace(row["date"], "[date]")


def selection_key(record):
    selected = record["calibration"]["selected"]
    return (
        record["calibration"]["risk_feasible"],
        -selected["unsupported_false_accept_rate"]
        if not record["calibration"]["risk_feasible"]
        else 0,
        selected["known_correct_accepted_rate"],
        -record["fit"]["rows"] * record["fit"]["steps"],
        -record["l2"],
    )


def train_routing(encoder, source, directory, *, seed, source_commit, support_digest):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=False)
    train_rows = router_training_rows(source, seed)
    base_rows = language_rows(source, seed, "train")
    selection_rows = language_rows(source, seed, "selection")
    started = time.perf_counter()
    raw_train = encoder.encode([row["utterance"] for row in train_rows])
    raw_selection = encoder.encode([row["utterance"] for row in selection_rows])
    slot_train = encoder.encode([slot_text(row) for row in base_rows])
    slot_selection = encoder.encode([slot_text(row) for row in selection_rows])
    descriptions = encoder.encode(list(DESCRIPTIONS.values()))
    encoder_seconds = time.perf_counter() - started
    candidates, selected_models = [], {}
    for mode in ("raw", "slot"):
        local = []
        for aliases in ALIAS_GRID if mode == "raw" else (0,):
            count = len(base_rows) * (aliases + 1)
            features = raw_train[:count] if mode == "raw" else slot_train
            selected_features = raw_selection if mode == "raw" else slot_selection
            labels = [
                row["intent"]
                for row in (train_rows[:count] if mode == "raw" else base_rows)
            ]
            for l2 in L2_GRID:
                model, fit = SemanticRouter.fit(
                    features,
                    labels,
                    classes=(*INTENTS, REJECT),
                    encoder_digest=encoder.digest,
                    seed=seed,
                    steps=600,
                    l2=l2,
                )
                calibration = model.calibrate(
                    selected_features, [row["intent"] for row in selection_rows]
                )
                candidate_path = (
                    path / "candidates" / f"{mode}-aliases{aliases}-l2{l2:g}"
                )
                persist_started = time.perf_counter()
                candidate_manifest = model.save(
                    candidate_path,
                    source_commit=source_commit,
                    support_digest=support_digest,
                )
                candidate_files = {}
                for filename in ("weights.bin", "manifest.json"):
                    payload = (candidate_path / filename).read_bytes()
                    candidate_files[filename] = {
                        "bytes": len(payload),
                        "sha256": digest(payload),
                    }
                record = {
                    "mode": mode,
                    "alias_count": aliases,
                    "l2": l2,
                    "fit": fit,
                    "calibration": calibration,
                    "artifact": {
                        "path": candidate_path.relative_to(path).as_posix(),
                        "files": candidate_files,
                        "bytes": sum(
                            info["bytes"] for info in candidate_files.values()
                        ),
                        "inventory_sha256": digest(canonical(candidate_files)),
                        "manifest_sha256": candidate_manifest["manifest_sha256"],
                    },
                    "artifact_persist_seconds": time.perf_counter() - persist_started,
                }
                local.append((record, model))
                candidates.append(record)
        chosen, model = max(local, key=lambda pair: selection_key(pair[0]))
        manifest = model.save(
            path / mode, source_commit=source_commit, support_digest=support_digest
        )
        loaded, _ = SemanticRouter.load(
            path / mode,
            expected_encoder_digest=encoder.digest,
            expected_manifest_digest=manifest["manifest_sha256"],
        )
        features = raw_selection if mode == "raw" else slot_selection
        if not np.array_equal(
            model.probabilities(features), loaded.probabilities(features)
        ):
            raise AssertionError("router save/load changed selection predictions")
        selected_models[mode] = loaded
        chosen["selected_manifest"] = manifest
        chosen["selection_save_load_parity"] = True
        chosen["selected_copy_artifact_bytes"] = sum(
            item.stat().st_size for item in (path / mode).iterdir()
        )
    # Explicit family selection is also based only on the NOAA selection fold.
    chosen_records = {
        mode: next(
            row
            for row in candidates
            if row["mode"] == mode and "selected_manifest" in row
        )
        for mode in selected_models
    }
    selected_mode = max(
        chosen_records,
        key=lambda mode: (selection_key(chosen_records[mode]), mode == "raw"),
    )
    receipt = {
        "schema": "memory-cell-v3.router-selection-study.v1",
        "training_domain": source["domain"],
        "selection_domain": source["domain"],
        "partition_used_for_selection": "selection",
        "candidates": candidates,
        "selected": chosen_records,
        "selected_primary_mode": selected_mode,
        "all_candidate_optimizer_steps": sum(row["fit"]["steps"] for row in candidates),
        "all_candidate_train_seconds": sum(
            row["fit"]["train_seconds"] for row in candidates
        ),
        "all_candidate_artifacts_retained": True,
        "all_candidate_artifact_bytes": sum(
            row["artifact"]["bytes"] for row in candidates
        ),
        "all_candidate_artifact_persist_seconds": sum(
            row["artifact_persist_seconds"] for row in candidates
        ),
        "selected_copy_artifact_bytes": {
            mode: row["selected_copy_artifact_bytes"]
            for mode, row in chosen_records.items()
        },
        "research_model_artifact_bytes_including_selected_copies": sum(
            row["artifact"]["bytes"] for row in candidates
        )
        + sum(row["selected_copy_artifact_bytes"] for row in chosen_records.values()),
        "actual_encoder_calls": len(train_rows)
        + 2 * len(selection_rows)
        + len(base_rows)
        + len(DESCRIPTIONS),
        "actual_encoder_seconds": encoder_seconds,
        "alias_augmentation": "same NOAA source under generic names; no transfer-domain labels",
        "raw_features": "the complete original utterance without identity removal",
        "slot_features": "complete utterance after replacing supplied display_name and date values only",
        "slot_is_intent_white_list": False,
        "calibration_grid_combinations_per_candidate": 35,
        "selection_order": "empirical OOD false acceptance <=5%; correct known coverage; actual example-update count; fixed L2/name order",
        "selection_ood_query_count": sum(
            row["intent"] == REJECT for row in selection_rows
        ),
        "selection_ood_template_count": len(
            {row["template_index"] for row in selection_rows if row["intent"] == REJECT}
        ),
        "zero_error_one_sided_95_percent_template_upper_bound": 1
        - 0.05
        ** (
            1
            / len(
                {
                    row["template_index"]
                    for row in selection_rows
                    if row["intent"] == REJECT
                }
            )
        ),
        "empirical_risk_threshold_is_not_a_population_guarantee": True,
    }
    (path / "selection-receipt.json").write_bytes(canonical(receipt) + b"\n")
    with (path / "training-utterances.jsonl").open("xb") as stream:
        for row in train_rows:
            stream.write(canonical(row) + b"\n")
    with (path / "selection-utterances.jsonl").open("xb") as stream:
        for row in selection_rows:
            stream.write(canonical(row) + b"\n")
    return selected_models, descriptions, receipt


def routing_evaluation(encoder, models, primary_mode, rows, descriptions):
    started = time.perf_counter()
    raw = encoder.encode([row["utterance"] for row in rows])
    slots = encoder.encode([slot_text(row) for row in rows])
    encoder_seconds = time.perf_counter() - started
    decisions = {
        "raw": models["raw"].decisions(raw),
        "slot": models["slot"].decisions(slots),
    }
    classes = tuple(DESCRIPTIONS)
    nearest = np.argmax(raw @ descriptions.T, axis=1)
    routes = {
        "semantic": [value.route for value in decisions[primary_mode]],
        "raw_semantic": [value.route for value in decisions["raw"]],
        "slot_semantic": [value.route for value in decisions["slot"]],
        "raw_without_risk_abstention": [
            None if value.raw_route == REJECT else value.raw_route
            for value in decisions["raw"]
        ],
        "zero_shot_description": [
            None if classes[index] == REJECT else classes[index] for index in nearest
        ],
        "literal": [literal_route(row["utterance"]) for row in rows],
        "oracle": [None if row["intent"] == REJECT else row["intent"] for row in rows],
    }
    records = [
        {
            "query": row,
            "normalized_slot_utterance": slot_text(row),
            "raw_semantic": asdict(decisions["raw"][i]),
            "slot_semantic": asdict(decisions["slot"][i]),
            "primary_mode": primary_mode,
            "zero_shot_description": routes["zero_shot_description"][i],
            "literal": routes["literal"][i],
        }
        for i, row in enumerate(rows)
    ]
    return (
        routes,
        records,
        {
            "raw_full_utterance_encoder_calls": len(rows),
            "slot_full_utterance_encoder_calls": len(rows),
            "all_encoder_seconds": encoder_seconds,
            "primary_mode_selected_on_noaa_selection": primary_mode,
            "routes": {
                name: route_summary(rows, values) for name, values in routes.items()
            },
        },
    )


def policies_digest(models):
    return digest(
        b"".join(
            models[mode].weights.tobytes()
            + models[mode].bias.tobytes()
            + canonical(
                {
                    "threshold": models[mode].threshold,
                    "margin": models[mode].margin,
                    "reject_all": models[mode].reject_all,
                }
            )
            for mode in sorted(models)
        )
    )

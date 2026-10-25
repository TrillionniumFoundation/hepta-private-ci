"""Prospectively fixed causal content/context interventions on the same sources."""

import gzip
import json
from pathlib import Path
import time
import traceback

import torch

from ..v6.data import Observation, Target
from ..v6.neural import parameter_hash
from ..v6.observer import observe_tensors
from ..v7.data import VIEWS, make_batch
from .emission import output_digests
from .episodes import fixed_intervention
from .media import RawMediaArchive, reopen_archive_records
from .training_run import file_sha, write_json
from .trees import METRICS, stable_seed


@torch.inference_mode()
def evaluate_intervention(snapshot, corpus, observers, directory, reference, profile):
    """Execute one fixed H=2 intervention; never select its path using outcomes."""
    allowed = {
        "shared_state_clamp_semantic_couple": (("refine_semantic", "couple"), {"shared_mode": "clamped_initial"}),
        "encoder_initial_only_fixed": (("refine_image", "refine_text"), {"context_mode": "initial_only_context_intervention"}),
    }
    if profile not in allowed or reference["role"] != "development" or reference["pair_start"] != 608:
        raise ValueError("Unregistered intervention or source interval")
    path, kwargs = allowed[profile]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = {name: parameter_hash(model) for name, model in observers.items()}
    snapshot.verify_integrity()
    count, scenarios, seed = reference["pair_count"], reference["scenarios_per_source"], reference["training_seed"]
    metadata = {key: reference[key] for key in
                ("role", "pair_start", "pair_count", "scenarios_per_source", "training_seed", "snapshot_sha256")}
    write_json(directory / "registration.json", {**metadata, "profile": profile, "path": path,
               "interventions": kwargs, "reference_source_ids": reference["source_ids"],
               "primary_and_secondary_parameter_sha256": before,
               "path_selected_using_evaluation": False})
    result = {**metadata, "cases": [], "views": [], "scenarios": [], "source_ids": [],
              "metrics": {name: {metric: [] for metric in METRICS} for name in observers},
              "profile": profile, "path": list(path)}
    initial_matches = []
    try:
        with gzip.open(directory / "raw-rows.jsonl.gz", "xt", encoding="utf-8") as stream:
            for view_index, view in enumerate(VIEWS):
                batch = make_batch(corpus, "development", count, stable_seed("observation", "development", 608),
                                   view=view, offset=608)
                observation = Observation(*(value.repeat_interleave(scenarios, 0) for value in
                    (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
                target = Target(*(value.repeat_interleave(scenarios, 0) for value in
                    (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                run, initial = fixed_intervention(snapshot._model, observation, path=path,
                    actual_stream_key=("development", 608, seed, view), **kwargs)
                initial_sha = output_digests(initial.pixels, initial.tokens)
                expected = reference["root_emission_sha256"][view_index * count * scenarios:(view_index + 1) * count * scenarios]
                matches = [a == b for a, b in zip(initial_sha, expected)]
                initial_matches.extend(matches)
                if profile == "shared_state_clamp_semantic_couple" and not all(matches):
                    raise RuntimeError("Shared-state intervention changed its common initial draft")
                archive_name = f"media/{view}.zip"
                with RawMediaArchive(directory / archive_name) as archive:
                    _, _, raw = archive.append(run.pixels, run.tokens)
                pixels, captions = reopen_archive_records(directory / archive_name, raw)
                values = {name: observe_tensors(model, pixels, captions, target.pixels, target.labels)
                          for name, model in observers.items()}
                write_json(directory / f"ledger-{view}.json", list(run.ledger))
                for row_index in range(count * scenarios):
                    case_local, scenario = divmod(row_index, scenarios)
                    row = {"row_index": view_index * count * scenarios + row_index,
                           "case": 608 + case_local, "view": view, "scenario": scenario,
                           "source_ids": batch.source_ids[case_local], "path": path,
                           "view_archive": archive_name, "initial_output_sha256": initial_sha[row_index],
                           "initial_matches_reference": matches[row_index],
                           "token_path": run.tokens[row_index].tolist(), **raw[row_index], "observer_scores": {}}
                    for name, scores in values.items():
                        score = scores[row_index]
                        score["joint_fact_correct"] = bool(score["caption_valid"] and all(score[key] == 0 for key in
                            ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
                        score["required_output_complete"] = raw[row_index]["required_output_complete"]
                        row["observer_scores"][name] = score
                        for metric in METRICS:
                            result["metrics"][name][metric].append(float(score[metric]))
                    for key in ("cases", "views", "scenarios", "source_ids"):
                        value = {"cases": row["case"], "views": view, "scenarios": scenario,
                                 "source_ids": row["source_ids"]}[key]
                        result[key].append(value)
                    stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        for name in observers:
            for metric in METRICS:
                result["metrics"][name][metric] = torch.tensor(result["metrics"][name][metric])
        if any(result[key] != reference[key] for key in ("cases", "views", "scenarios", "source_ids")):
            raise RuntimeError("Intervention census is not paired with its reference")
        snapshot.verify_integrity()
        if before != {name: parameter_hash(model) for name, model in observers.items()}:
            raise RuntimeError("Intervention changed a frozen observer")
        with (directory / "data.pt").open("xb") as stream:
            torch.save(result, stream)
        write_json(directory / "summary.json", {"status": "completed", "rows": len(result["cases"]),
                   "profile": profile, "fixed_path": path, "initial_matches_reference": sum(initial_matches),
                   "data_file_sha256": file_sha(directory / "data.pt"),
                   "raw_rows_sha256": file_sha(directory / "raw-rows.jsonl.gz"),
                   "archive_sha256": {view: file_sha(directory / "media" / f"{view}.zip") for view in VIEWS},
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                   "fixed_context_intervention_is_matched_architecture_training": False})
        return result
    except BaseException as error:
        write_json(directory / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise

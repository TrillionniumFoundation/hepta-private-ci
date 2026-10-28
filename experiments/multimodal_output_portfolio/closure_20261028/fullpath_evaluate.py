"""Same-law and strong-prior actual deployments and frozen retention selection."""

from pathlib import Path
import shutil
import time
import zipfile

import torch

from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from ..unified_20261028.fullpath_evaluate import (brief, identities, repeated_target,
                                                source_paired_difference, audit)
from ..unified_20261028.profile import digest
from .fullpath_model import actual_outputs, emit, file_sha, final_state, load_model, repeat_state
from .fullpath_protocol import P, write_json


@torch.inference_mode()
def evaluate(model, reference, corpus, observer, profile, seed, directory,
             split="validation", retain=False, deterministic=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    parameter = parameter_hash(model)
    if deterministic and parameter != parameter_hash(reference._base._model):
        raise ValueError("Only the exact strong frozen prior may take the greedy route")
    policy_binding = {"model_parameters_sha256": parameter,
                      "reference_snapshot_sha256": reference.fingerprint,
                      "emission_mode": "greedy_prior" if deterministic else "stochastic",
                      "profile_sha256": profile.digest}
    policy_sha = digest(policy_binding)
    timing = {"generation_cpu_ns": 0, "generation_wall_ns": 0,
              "codec_observer_cpu_ns": 0, "codec_observer_wall_ns": 0,
              "actual_bundles": 0, "files_written_and_reopened": 0}
    groups, k = {}, P["qualification_emissions"]
    specs = (("quality", P["validation_pairs"] if split == "validation" else P["qualification_pairs"], P["conditions"]),
             ("retention", P["validation_retention_pairs"] if split == "validation" else P["retention_pairs"], ["clean"]))
    for scope, count, conditions in specs:
        rows = []
        for c, condition in enumerate(conditions):
            for start in range(0, count, P["batch_size"]):
                n = min(P["batch_size"], count - start)
                offset = (512 if scope == "quality" else 640) + start if split == "validation" else start
                source_split = "validation" if split == "validation" else "test" if scope == "quality" else "retention"
                batch_seed = (28260401 if split == "validation" else 28260901) + start + c * 10007
                batch = make_batch(corpus, source_split, n, batch_seed, corruption=condition, offset=offset)
                rng = torch.Generator().manual_seed(seed * 1033 + batch_seed)
                cpu, wall = time.process_time_ns(), time.perf_counter_ns()
                state, _ = final_state(model, reference, batch.observation,
                                       torch.randn(n, model.hidden, generator=rng))
                sample = emit(model, repeat_state(state, k), rng, deterministic=deterministic)
                timing["generation_cpu_ns"] += time.process_time_ns() - cpu
                timing["generation_wall_ns"] += time.perf_counter_ns() - wall
                name = f"{scope}-{condition}-{start:04d}"
                _, batch_rows, measured = actual_outputs(sample, repeated_target(batch.target, k), observer,
                    profile, directory / name, identities(batch, condition, start, k, seed), retain=retain)
                for key, value in measured.items():
                    timing[key] += value
                for index, row in enumerate(batch_rows):
                    row.update(scope=scope, condition=condition, source_split=source_split,
                               policy_sha256=policy_sha, batch_seed=batch_seed, source_offset=offset + index % n,
                               seed=seed, archive=name + ".zip", source_ids=batch.source_ids[index % n],
                               target_labels=batch.target.labels[index % n].tolist(),
                               target_swap=bool(batch.observation.text_tokens[index % n, 1] == 10))
                if retain:
                    with zipfile.ZipFile(directory / (name + ".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
                        for path in sorted((directory / name).rglob("*")):
                            if path.is_file():
                                archive.write(path, path.relative_to(directory / name))
                    shutil.rmtree(directory / name)
                rows.extend(batch_rows)
        groups[scope] = {"summary": brief(rows, profile), "rows": rows}
    result = {"profile_sha256": profile.digest, "policy_sha256": policy_sha, "policy_binding": policy_binding,
              "seed": seed, "deterministic": deterministic, "groups": groups, "timing": timing,
              "inference_target_access": False, "soft_proxy_used_for_evaluation": False,
              "physical_CPU_certificate": False}
    write_json(directory / "EVALUATION.json", result)
    return result


def select(model_paths, reference, corpus, observer, training_profile, primary, seed, directory):
    candidates = []
    for stage, deterministic in (("prior_greedy", True), ("prior_stochastic", False)):
        score = evaluate(reference._base._model, reference, corpus, observer, primary, seed,
                         directory / stage, deterministic=deterministic)
        candidate = {"stage": stage, "path": None, "deterministic": deterministic,
                     "quality_ce": score["groups"]["quality"]["summary"]["value"],
                     "retention_ce": score["groups"]["retention"]["summary"]["value"]}
        candidate["eligible"] = not candidates or candidate["retention_ce"] >= candidates[0]["retention_ce"] - P["retention_tolerance"]
        candidates.append(candidate)
    best = max((row for row in candidates if row["eligible"]), key=lambda row: row["quality_ce"])
    for stage, path in model_paths:
        model, _ = load_model(path, training_profile)
        scores = evaluate(model, reference, corpus, observer, primary, seed, directory / stage)
        candidate = {"stage": stage, "path": str(path), "checkpoint_sha256": file_sha(path), "deterministic": False,
                     "quality_ce": scores["groups"]["quality"]["summary"]["value"],
                     "retention_ce": scores["groups"]["retention"]["summary"]["value"]}
        candidate["eligible"] = candidate["retention_ce"] >= candidates[0]["retention_ce"] - P["retention_tolerance"]
        candidates.append(candidate)
        if candidate["eligible"] and candidate["quality_ce"] > best["quality_ce"]:
            best = candidate
    result = {"seed": seed, "selected": best, "candidates": candidates,
              "primary_profile_sha256": primary.digest, "training_profile_sha256": training_profile.digest,
              "audit_observer_used": False, "qualification_used": False,
              "retention_constraint": "actual primary observer CE >= exact strong prior CE - .005"}
    write_json(directory / "SELECTION.json", result)
    return result

"""Actual serialized deployment, paired development selection and source audit."""

import io
import json
from pathlib import Path
import shutil
import time
import zipfile

import numpy as np
from PIL import Image
import torch

from ..v6.data import make_batch, Target
from ..v6.observer import observe_tensors
from ..v6.neural import parameter_hash
from .generator import (actual_outputs, emit, file_sha, final_state, load_model,
                        repeat_state)
from .fullpath_protocol import P, write_json
from .profile import aggregate, digest, certainty_equivalent


def repeated_target(target, k):
    return Target(*(getattr(target, field).repeat(k, *([1] * (getattr(target, field).ndim - 1)))
                    for field in ("pixels", "text_tokens", "labels")))


def pair_identity(pair):
    return digest({"original_pixel_sources": sorted(pair)})


def identities(batch, condition, start, k, seed):
    return [(f"{condition}:{pair_identity(pair)}", f"seed-{seed}:draw-{draw}", pair_identity(pair))
            for draw in range(k) for pair in batch.source_ids]


def brief(rows, profile):
    by_context = {}
    for row in rows:
        by_context.setdefault(row["context_id"], []).append(row["net_return"])
    summary = aggregate(profile, by_context)
    summary.pop("contexts")
    summary["bundles"] = len(rows)
    return summary


@torch.inference_mode()
def evaluate(model, reference, corpus, observer, profile, seed, directory,
             split="validation", retain=False, deterministic=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    model_hash = parameter_hash(model)
    if deterministic and model_hash != parameter_hash(reference._base._model):
        raise ValueError("The deterministic route is reserved for the exact strong prior/fallback")
    policy_binding = {"model_parameters_sha256": model_hash,
                      "reference_snapshot_sha256": reference.fingerprint,
                      "emission_mode": "prior_deterministic" if deterministic else "fullpath_stochastic",
                      "profile_sha256": profile.digest}
    policy_sha256 = digest(policy_binding)
    groups, timing = {}, {"generation_cpu_ns": 0, "generation_wall_ns": 0,
                          "codec_observer_cpu_ns": 0, "codec_observer_wall_ns": 0,
                          "actual_bundles": 0, "files_written_and_reopened": 0}
    k = P["qualification_emissions"]
    specifications = (("quality", P["validation_pairs"] if split == "validation" else P["qualification_pairs"],
                       P["conditions"]),
                      ("retention", P["validation_retention_pairs"] if split == "validation" else P["retention_pairs"], ["clean"]))
    for scope, count, conditions in specifications:
        rows = []
        for c, condition in enumerate(conditions):
            for start in range(0, count, P["batch_size"]):
                n = min(P["batch_size"], count - start)
                offset = (512 if scope == "quality" else 640) + start if split == "validation" else start
                source_split = "validation" if split == "validation" else ("test" if scope == "quality" else "retention")
                batch_seed = (28171303 if split == "validation" else 28199131) + start + c * 10007
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
                    row.update(scope=scope, condition=condition, source_split=source_split, policy_sha256=policy_sha256,
                               batch_seed=batch_seed, source_offset=offset + index % n,
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
    result = {"profile_sha256": profile.digest, "policy_sha256": policy_sha256, "policy_binding": policy_binding,
              "seed": seed, "deterministic": deterministic,
              "groups": groups, "timing": timing, "inference_target_access": False}
    write_json(directory / "EVALUATION.json", result)
    return result


def select(model_paths, reference, corpus, observer, training_profile, primary, seed, directory):
    candidates = []
    baseline = evaluate(reference._base._model, reference, corpus, observer, primary, seed,
                        directory / "original", deterministic=True)
    best = {"stage": "original", "path": None, "eligible": True,
            "quality_ce": baseline["groups"]["quality"]["summary"]["value"],
            "retention_ce": baseline["groups"]["retention"]["summary"]["value"]}
    candidates.append(best)
    for stage, path in model_paths:
        model, _ = load_model(path, training_profile)
        scores = evaluate(model, reference, corpus, observer, primary, seed, directory / stage)
        candidate = {"stage": stage, "path": str(path), "checkpoint_sha256": file_sha(path),
            "quality_ce": scores["groups"]["quality"]["summary"]["value"],
            "retention_ce": scores["groups"]["retention"]["summary"]["value"]}
        candidate["eligible"] = candidate["retention_ce"] >= candidates[0]["retention_ce"] - P["retention_tolerance"]
        candidates.append(candidate)
        if candidate["eligible"] and candidate["quality_ce"] > best["quality_ce"]:
            best = candidate
    result = {"seed": seed, "selected": best, "candidates": candidates,
              "primary_profile_sha256": primary.digest, "training_profile_sha256": training_profile.digest,
              "audit_observer_used": False, "qualification_used": False}
    write_json(directory / "SELECTION.json", result)
    return result


def source_paired_difference(left, right, gamma=2., draws=2000):
    def groups(rows):
        result = {}
        for row in rows:
            result.setdefault(row["source_cluster_id"], []).append(row["net_return"])
        return result
    a, b = groups(left), groups(right)
    if set(a) != set(b):
        raise ValueError("A paired contrast needs identical original source clusters")
    ids = sorted(a)
    if any(len(a[i]) != len(b[i]) for i in ids):
        raise ValueError("Unmatched rollout and task condition counts")
    aa, bb = np.array([a[i] for i in ids]), np.array([b[i] for i in ids])
    def ce(x):
        if gamma == 0:
            return x.mean(axis=(-1, -2))
        z = -gamma * x
        maximum = z.max(axis=(-1, -2), keepdims=True)
        return -(np.log(np.exp(z - maximum).mean(axis=(-1, -2))) + maximum[..., 0, 0]) / gamma
    rng = np.random.default_rng(28103913)
    results = []
    for start in range(0, draws, 100):
        selected = rng.integers(len(ids), size=(min(100, draws - start), len(ids)))
        results.extend((ce(aa[selected]) - ce(bb[selected])).tolist())
    return {"difference": float(ce(aa) - ce(bb)), "ci95": np.quantile(results, [.025, .975]).tolist(),
            "source_pairs": len(ids), "bootstrap_draws": draws,
            "scope": "conditional on trained checkpoints and declared original pixel-pair clusters; writer independence unproved"}


@torch.inference_mode()
def audit(directory, corpus, observer, primary):
    record = json.loads((Path(directory) / "EVALUATION.json").read_text())
    if record["profile_sha256"] != primary.digest:
        raise ValueError("Audit profile mismatch")
    errors, count = [], 0
    for group in record["groups"].values():
        for row in group["rows"]:
            with zipfile.ZipFile(Path(directory) / row["archive"]) as archive:
                raw_image = archive.read(row["artifacts"]["image"])
                raw_text = archive.read(row["artifacts"]["text"])
            import hashlib
            if (hashlib.sha256(raw_image).hexdigest() != row["artifact_sha256"]["image"]
                    or hashlib.sha256(raw_text).hexdigest() != row["artifact_sha256"]["text"]):
                raise ValueError("Archived delivered output changed")
            with Image.open(io.BytesIO(raw_image)) as image:
                pixels = torch.from_numpy(np.array(image, copy=True)).float()[None, None] / 255
            # Reconstruct private target from pinned sources and recorded public command.
            expected_labels = row["target_labels"]
            source = corpus.splits[row["source_split"]]
            i = 2 * row["source_offset"]
            original = torch.cat((source.images[i], source.images[i + 1]), dim=2).float()[None] / 255
            labels = source.labels[i:i + 2]
            if row["target_swap"]:
                original = torch.cat((original[:, :, :, 28:], original[:, :, :, :28]), dim=3)
                labels = labels.flip(0)
            if labels.tolist() != expected_labels:
                raise ValueError("Private target/source binding differs")
            score = observe_tensors(observer, pixels, [raw_text.decode("utf-8")], original, labels[None])[0]
            recomputed = score["utility"] - sum(e["amount"] for e in row["costs"])
            errors.append(abs(recomputed - row["net_return"]))
            count += 1
    return {"bundles_reopened": count, "maximum_return_discrepancy": max(errors, default=0.),
            "generator_calls": 0, "profile_sha256": primary.digest}

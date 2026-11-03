"""Research-only observed-output portfolio risk verification.

The caller provides a frozen generation function and an *external* assessor.
A calibrated linear mixture of standalone losses can never authorize an output:
actual mixed latent/logit generation must be decoded then scored again.

No authentication, signature, future-window attestation or authority is provided.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np


class OutputEvidenceError(ValueError):
    """Refuse incomplete or mismatched decoded evidence."""


@dataclass(frozen=True)
class Criterion:
    max_cvar90: float
    max_ambiguity: float
    min_quality: float
    max_inconsistency: float
    max_wall_seconds_per_episode: float
    max_quality_drop: float = 0.0
    max_cvar_increase: float = 0.0

    def validate(self) -> None:
        if any(not math.isfinite(v) for v in asdict(self).values()):
            raise OutputEvidenceError("nonfinite risk/quality constraint")
        if not (self.max_cvar90 >= 0 and 0 <= self.max_ambiguity <= 1
                and 0 <= self.min_quality <= 1 and 0 <= self.max_inconsistency <= 1
                and self.max_wall_seconds_per_episode > 0
                and self.max_quality_drop >= 0 and self.max_cvar_increase >= 0):
            raise OutputEvidenceError("invalid risk/quality constraint")


def cvar90(values: Sequence[float]) -> float:
    """Equal-probability upper-tail CVaR using exactly 10% scenario mass."""
    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 1 or x.size < 10 or not np.isfinite(x).all() or (x < 0).any():
        raise OutputEvidenceError("insufficient or invalid independent episodes")
    ordered = np.sort(x)[::-1]
    mass = 0.1 * len(ordered)
    full = math.floor(mass)
    frac = mass - full
    total = float(ordered[:full].sum(dtype=np.float64))
    if frac > 0:
        total += frac * float(ordered[full])
    return total / mass


def _validate_decoded(raw: Any, required_modalities: Sequence[str], count: int) -> None:
    if not isinstance(raw, Mapping) or not required_modalities or len(set(required_modalities)) != len(required_modalities):
        raise OutputEvidenceError("raw output modality contract missing")
    if not set(required_modalities).issubset(raw):
        raise OutputEvidenceError("missing decoded output modality")
    for name in required_modalities:
        a = np.asarray(raw[name])
        if a.ndim < 1 or a.shape[0] != count or not np.issubdtype(a.dtype, np.number) or not np.isfinite(a).all():
            raise OutputEvidenceError("invalid raw decoded output for " + name)


def _vectors(raw: Mapping[str, Any], episodes: int, draws_per_episode: int):
    if not isinstance(raw, Mapping) or set(raw) != {"loss", "quality", "ambiguity", "inconsistency"}:
        raise OutputEvidenceError("external assessor must provide all four metrics")
    expect = episodes * draws_per_episode
    vectors = {}
    for name, v in raw.items():
        a = np.asarray(v, dtype=np.float64)
        if a.shape != (expect,) or not np.isfinite(a).all():
            raise OutputEvidenceError("external assessor shape or finite mismatch for " + name)
        if name == "loss" and np.any(a < 0):
            raise OutputEvidenceError("negative external semantic loss")
        if name != "loss" and (np.any(a < 0) or np.any(a > 1)):
            raise OutputEvidenceError("invalid external fraction for " + name)
        vectors[name] = a.reshape(episodes, draws_per_episode).mean(axis=1)
    return vectors


def _digest_metrics(aggregate: Mapping[str, np.ndarray]) -> str:
    digest = sha256(b"hepta.mgp.observed-decoded-risk.v1\x00")
    for key in sorted(aggregate):
        payload = np.ascontiguousarray(aggregate[key], dtype="<f8")
        digest.update(key.encode("ascii") + b"\x00")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload.tobytes())
    return digest.hexdigest()


def _evaluate(metrics: Mapping[str, np.ndarray], generation_elapsed: float,
              n_episodes: int) -> dict:
    return {
        "cvar90": cvar90(metrics["loss"]),
        "mean_loss": float(metrics["loss"].mean()),
        "mean_quality": float(metrics["quality"].mean()),
        "ambiguity_rate": float(metrics["ambiguity"].mean()),
        "inconsistency_rate": float(metrics["inconsistency"].mean()),
        "generation_wall_seconds": generation_elapsed,
        "wall_seconds_per_episode": generation_elapsed / n_episodes,
        "scored_episode_count": n_episodes,
        "scoring_digest": _digest_metrics(metrics),
    }


def compare_actual_decoded_output(*,
                                  public_inputs: Any,
                                  independent_targets: Any,
                                  episode_ids: Sequence[str],
                                  draw_episode_ids: Sequence[str],
                                  draws_per_episode: int,
                                  weights: Sequence[float],
                                  generate: Callable[[Any, tuple[float, ...]], Any],
                                  external_score: Callable[[Any, Any], Mapping[str, Any]],
                                  objective_digest: str,
                                  frozen_model_digest: str,
                                  input_cohort_digest: str,
                                  criteria: Criterion,
                                  required_modalities: Sequence[str] = ("text", "audio", "image", "video")) -> dict:
    """Generate baseline and mixed output with identical public inputs, then score.

    Independent labels never appear in ``generate`` arguments. Python callbacks
    may nevertheless close over untrusted information: this is a structural
    boundary only, not a provably independent observer or leakage certificate.
    Generation is measured using wall-clock (not GPU-synchronized); offline
    training/calibration/evaluation costs and device energy are not covered.
    """
    criteria.validate()
    if not (objective_digest and frozen_model_digest and input_cohort_digest):
        raise OutputEvidenceError("missing immutable evaluation identifiers")
    if (not isinstance(draws_per_episode, int) or draws_per_episode < 1
            or len(episode_ids) < 10):
        raise OutputEvidenceError("episode support too small")
    if any(not isinstance(x, str) or not x for x in episode_ids) or len(set(episode_ids)) != len(episode_ids):
        raise OutputEvidenceError("episode identities missing or duplicated")
    # The assessor produces one row per draw. Without exact row↔episode
    # association, CVaR after within-episode averaging is unidentifiable.
    expected = [episode for episode in episode_ids for _ in range(draws_per_episode)]
    if list(draw_episode_ids) != expected:
        raise OutputEvidenceError("unaligned or missing per-draw episode identities")
    if (len(weights) > 128 or any(not math.isfinite(float(w)) or float(w) < 0 or float(w) > 1 for w in weights)
            or sum(float(w) for w in weights) > 1 + 1e-12):
        raise OutputEvidenceError("incompatible or overbudget continuous portfolio")
    if not callable(generate) or not callable(external_score):
        raise OutputEvidenceError("missing generation or independent scorer")
    n = len(episode_ids)
    # These are real generated output paths; no scalar-loss blending occurs.
    baseline_weights = tuple(0.0 for _ in weights)
    selected_weights = tuple(float(w) for w in weights)
    t0 = time.perf_counter()
    baseline_decoded = generate(public_inputs, baseline_weights)
    baseline_elapsed = time.perf_counter() - t0
    t1 = time.perf_counter()
    selected_decoded = generate(public_inputs, selected_weights)
    selected_elapsed = time.perf_counter() - t1
    # Reject bare risk/loss vectors masquerading as raw decoded output.
    _validate_decoded(baseline_decoded, required_modalities, n * draws_per_episode)
    _validate_decoded(selected_decoded, required_modalities, n * draws_per_episode)
    # Raw tensor/media values must be scored, not a caller-supplied risk number.
    baseline_raw = external_score(baseline_decoded, independent_targets)
    selected_raw = external_score(selected_decoded, independent_targets)
    baseline = _evaluate(_vectors(baseline_raw, n, draws_per_episode), baseline_elapsed, n)
    selected = _evaluate(_vectors(selected_raw, n, draws_per_episode), selected_elapsed, n)
    satisfied = {
        "hard_tail": selected["cvar90"] <= criteria.max_cvar90,
        "hard_quality": selected["mean_quality"] >= criteria.min_quality,
        "hard_ambiguity": selected["ambiguity_rate"] <= criteria.max_ambiguity,
        "hard_inconsistency": selected["inconsistency_rate"] <= criteria.max_inconsistency,
        "hard_generation_wall": selected["wall_seconds_per_episode"] <= criteria.max_wall_seconds_per_episode,
        "relative_quality": selected["mean_quality"] >= baseline["mean_quality"] - criteria.max_quality_drop,
        "relative_tail": selected["cvar90"] <= baseline["cvar90"] + criteria.max_cvar_increase,
    }
    # An observed violation requires rejecting the *proposal*, not raising and
    # thereby dropping negative evidence from the report.
    record = {
        "schema": "hepta-mgp-observed-decoded-risk-v1",
        "status": "ADVISORY_ONLY" if all(satisfied.values()) else "REJECT_OBSERVED_OUTPUT",
        "authority": "DENY_ALL",
        "scientific_superiority_proven": False,
        "independent_evidence_authenticated": False,
        "execution_tier": "LOCAL_RESEARCH",
        "objective_digest": objective_digest,
        "frozen_model_digest": frozen_model_digest,
        "input_cohort_digest": input_cohort_digest,
        "episode_count": n,
        "draws_per_episode": draws_per_episode,
        "cell_weights": list(selected_weights),
        "observed_modalities": list(required_modalities),
        "criteria": asdict(criteria),
        "baseline": baseline,
        "selected": selected,
        "passed_local_checks": satisfied,
        "observed_evaluation_limits": [
            "Source/model/observer provenance is caller-supplied and not authenticated",
            "No prospective future-window, native runtime, or permission grants",
            "Real clock covers generator only; other physical resources unmeasured",
            "No claim of independent full-modality foundation-model generation",
        ],
    }
    return record

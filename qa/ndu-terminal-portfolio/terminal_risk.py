"""Shadow-only terminal-loss portfolio statistics with strict source/proposal custody.

This fits covariance of paired, independently OBSERVED terminal loss improvements.
It does not assume that a weighted logit mixture has linear terminal reward.
All outputs are advisory and cannot authorize production model/tool actions.
"""
from collections import defaultdict
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

HEX = re.compile(r"[a-f0-9]{64}\Z")
SCHEMA = "hepta.ndu-terminal-risk-cohort.v1"
ARMS = ("nochange", "semantic", "horizontal", "vertical", "completion")
MAIN_KEYS = {"schema", "split", "cohort_digest", "model_digest", "objective_digest", "budget_seconds", "rows"}
ROW_KEYS = {"source_id", "image_digest", "seed", "arm", "proposal_digest", "loss", "covered", "wall_seconds", "overrun"}


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _strict_pairs(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON member {key}")
        output[key] = value
    return output


def load_json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=_strict_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON constant")))


def _hexdigest(s):
    return type(s) is str and bool(HEX.fullmatch(s)) and s != "0" * 64


def _positive(v):
    return type(v) in (int, float) and math.isfinite(v) and v > 0


def _unit(v):
    return type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1


def validate(cohort, min_source_groups=32, min_seeds=2):
    """Require an exact source x seed x arm matrix and identical measured budget.

    The hashes bind supplied values, but aren't cryptographic source signatures.
    A separate independent custodian must attest original images/outcomes.
    """
    if not isinstance(cohort, dict) or set(cohort) != MAIN_KEYS or cohort["schema"] != SCHEMA:
        raise ValueError("unknown cohort schema or hidden fields")
    if cohort["split"] not in ("train", "dev", "test"):
        raise ValueError("unknown source role")
    if not all(_hexdigest(cohort[k]) for k in ("cohort_digest", "model_digest", "objective_digest")):
        raise ValueError("unbound cohort/model/objective identity")
    budget = cohort["budget_seconds"]
    if not _positive(budget):
        raise ValueError("invalid positive real budget")
    rows = cohort["rows"]
    if not isinstance(rows, list) or not rows or len(rows) > 100_000:
        raise ValueError("bounded nonempty rows required")
    entries, image_owner, source_by_image, proposal_owner, arm_proposal, roster = {}, {}, {}, {}, {}, defaultdict(set)
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise ValueError("hidden or missing row fields")
        source, image, arm, proposal, seed = (row[k] for k in ("source_id", "image_digest", "arm", "proposal_digest", "seed"))
        if (not isinstance(source, str) or not 1 <= len(source) <= 160 or not _hexdigest(image)
                or arm not in ARMS or not _hexdigest(proposal)
                or type(seed) is not int or not 0 <= seed < 2**31):
            raise ValueError("invalid source, arm, proposal, seed or digest")
        if (not _unit(row["loss"]) or type(row["covered"]) is not bool
                or not _positive(row["wall_seconds"]) or type(row["overrun"]) is not bool):
            raise ValueError("invalid terminal observation/cost")
        if row["overrun"] != (row["wall_seconds"] > budget):
            raise ValueError("overrun must reflect actual measured wall time")
        if (not row["covered"] or row["overrun"]) and row["loss"] != 1.0:
            raise ValueError("failed/abstained/over-budget outputs must retain full loss")
        if source in image_owner and image_owner[source] != image:
            raise ValueError("one source ID maps to multiple image digests")
        if image in source_by_image and source_by_image[image] != source:
            raise ValueError("relabelled image digest reused as a different source")
        image_owner[source] = image
        source_by_image[image] = source
        if arm in arm_proposal and arm_proposal[arm] != proposal:
            raise ValueError("one arm changed immutable proposal digest mid-cohort")
        if proposal in proposal_owner and proposal_owner[proposal] != arm:
            raise ValueError("two arms repackage the same immutable proposal")
        arm_proposal[arm], proposal_owner[proposal] = proposal, arm
        key = (source, seed, arm)
        if key in entries:
            raise ValueError("duplicate source/seed/arm measurement")
        entries[key] = row
        roster[source].add(seed)
    if set(arm_proposal) != set(ARMS):
        raise ValueError("missing mandatory baseline or one of four Cells")
    if len(roster) < min_source_groups or any(len(seeds) < min_seeds for seeds in roster.values()):
        raise ValueError("insufficient independent source groups or repeated seeds")
    for source, seeds in roster.items():
        for seed in seeds:
            if any((source, seed, arm) not in entries for arm in ARMS):
                raise ValueError("incomplete paired arm matrix for a source/seed")
    return {"entries": entries, "sources": tuple(sorted(roster)),
            "image_by_source": image_owner, "proposal_by_arm": arm_proposal,
            "roster": roster, "identity_digest": digest({k: cohort[k] for k in MAIN_KEYS - {"rows"}}),
            "observations_digest": digest(rows)}


def _paired_vectors(valid):
    """Source-level mean across repeated seeds, then covariance across sources."""
    baseline_loss, improvement, latency, coverage = [], [], [], []
    for source in valid["sources"]:
        seeds = sorted(valid["roster"][source])
        baseline = np.mean([valid["entries"][(source, seed, "nochange")]["loss"] for seed in seeds])
        gains, times, covered = [], [], []
        for arm in ARMS[1:]:
            rows = [valid["entries"][(source, seed, arm)] for seed in seeds]
            gains.append(float(baseline - np.mean([r["loss"] for r in rows])))
            times.append(float(np.mean([r["wall_seconds"] for r in rows])))
            covered.append(float(np.mean([r["covered"] and not r["overrun"] for r in rows])))
        baseline_loss.append(baseline)
        improvement.append(gains)
        latency.append(times)
        coverage.append(covered)
    return (np.array(baseline_loss), np.array(improvement),
            np.array(latency), np.array(coverage))


def fit(cohort, *, shrinkage=0.15, min_source_groups=32):
    """Fit on TRAIN only. No evaluation/test labels may shape the portfolio."""
    if cohort.get("split") != "train":
        raise ValueError("terminal covariance fitting is TRAIN ONLY")
    if type(shrinkage) not in (float, int) or not math.isfinite(shrinkage) or not 0 <= shrinkage <= 1:
        raise ValueError("shrinkage must be in [0,1]")
    valid = validate(cohort, min_source_groups=min_source_groups)
    base, gains, times, coverage = _paired_vectors(valid)
    covariance = np.cov(gains, rowvar=False, ddof=1)
    covariance = (1-shrinkage)*covariance + shrinkage*np.diag(np.diag(covariance))
    covariance = (covariance + covariance.T)*0.5
    if not np.isfinite(covariance).all() or np.linalg.eigvalsh(covariance).min() < -1e-10:
        raise ValueError("nonfinite or indefinite estimated covariance")
    result = {"schema": "hepta.ndu-terminal-risk-fit.v1",
              "fit_role": "train", "fit_cohort_digest": cohort["cohort_digest"],
              "model_digest": cohort["model_digest"], "objective_digest": cohort["objective_digest"],
              "budget_seconds": cohort["budget_seconds"], "data_digest": valid["observations_digest"],
              "source_groups": len(valid["sources"]), "source_images": valid["image_by_source"],
              "cell_proposals": {k: valid["proposal_by_arm"][k] for k in ARMS[1:]},
              "baseline_proposal": valid["proposal_by_arm"]["nochange"],
              "mean_base_loss": float(np.mean(base)), "mean_gains": gains.mean(axis=0).tolist(),
              "terminal_gain_covariance": covariance.tolist(),
              "mean_cell_cost_seconds": times.mean(axis=0).tolist(), "mean_cell_coverage": coverage.mean(axis=0).tolist(),
              "shrinkage": float(shrinkage),
              "risk_quantity": "source-macro covariance of paired terminal-loss improvements (baseline minus individual Cell)",
              "portfolio_model": "linear additive surrogate only, not measured mixture outputs",
              "production_authority": "DENY_ALL", "real_model_quality_claim": False,
              "independent_source_attestation_present": False,
              "boundary": "No terminal covariance evidence for Cell combinations, no FBSDE optimality or runtime authority"}
    result["digest"] = digest(result)
    return result


def evaluate_frozen(frozen, holdout, *, min_source_groups=32):
    """Evaluate only on a source-disjoint DEV or TEST cohort; never refit."""
    if holdout.get("split") not in ("dev", "test"):
        raise ValueError("holdout must be DEV or TEST")
    if digest({k:v for k,v in frozen.items() if k != "digest"}) != frozen.get("digest"):
        raise ValueError("tampered training covariance artifact")
    valid = validate(holdout, min_source_groups=min_source_groups)
    if (holdout["model_digest"] != frozen["model_digest"] or
        holdout["objective_digest"] != frozen["objective_digest"] or
        holdout["budget_seconds"] != frozen["budget_seconds"] or
        holdout["cohort_digest"] == frozen["fit_cohort_digest"]):
        raise ValueError("changed objective/model/budget or reused fit cohort")
    if any(v in frozen["source_images"].values() or k in frozen["source_images"]
           for k,v in valid["image_by_source"].items()):
        raise ValueError("train/holdout source or image overlap")
    if any(valid["proposal_by_arm"][arm] != frozen["cell_proposals"][arm] for arm in ARMS[1:]) or \
       valid["proposal_by_arm"]["nochange"] != frozen["baseline_proposal"]:
        raise ValueError("model proposal changed after train fit")
    _, gains, times, coverage = _paired_vectors(valid)
    holdout_cov = np.cov(gains, rowvar=False, ddof=1)
    fitted = np.array(frozen["terminal_gain_covariance"])
    means = np.array(frozen["mean_gains"])
    return {"schema": "hepta.ndu-terminal-risk-holdout.v1", "role": holdout["split"],
            "sources": len(valid["sources"]), "observed_mean_gains": gains.mean(0).tolist(),
            "frozen_fit_mean_gains": means.tolist(), "gain_prediction_mae": float(np.abs(gains.mean(0)-means).mean()),
            "holdout_terminal_gain_covariance": holdout_cov.tolist(),
            "frozen_fit_covariance": fitted.tolist(),
            "covariance_frobenius_error": float(np.linalg.norm(holdout_cov-fitted)),
            "mean_cell_cost_seconds": times.mean(0).tolist(), "mean_cell_coverage": coverage.mean(0).tolist(),
            "production_authority": "DENY_ALL", "regeneration_performed": False,
            "scope": "observed individual Cell terminal outcomes only; no mixture performance claim"}


def surrogate_portfolio(frozen, *, risk_weight, switch_cost=0.0, grid=4):
    """Grid-search a *surrogate* w>=0, sum(w)<=1, with once-per-admission costs."""
    if type(risk_weight) not in (int,float) or not math.isfinite(risk_weight) or risk_weight < 0:
        raise ValueError("invalid risk weight")
    if type(switch_cost) not in (int,float) or not math.isfinite(switch_cost) or switch_cost < 0:
        raise ValueError("invalid switch cost")
    if type(grid) is not int or not 1 <= grid <= 16:
        raise ValueError("bounded integer simplex grid required")
    if digest({k:v for k,v in frozen.items() if k != "digest"}) != frozen.get("digest"):
        raise ValueError("tampered frozen fit artifact")
    means=np.array(frozen["mean_gains"],dtype=float)
    cov=np.array(frozen["terminal_gain_covariance"],dtype=float)
    if means.shape!=(4,) or cov.shape!=(4,4) or np.linalg.eigvalsh(cov).min() < -1e-10:
        raise ValueError("invalid fitted gains/covariance")
    best_score, best_weights = 0.0, [0.,0.,0.,0.]
    for a in range(grid+1):
      for b in range(grid-a+1):
       for c in range(grid-a-b+1):
        for d in range(grid-a-b-c+1):
         w=np.array([a,b,c,d],dtype=float)/grid
         score=float(w@means - 0.5*risk_weight*(w@cov@w) - switch_cost*np.count_nonzero(w))
         if score > best_score + 1e-12:
          best_score, best_weights=score,w.tolist()
    return {"weights": best_weights, "baseline_residual": 1-sum(best_weights),
            "surrogate_objective": best_score, "risk_weight":risk_weight,"fixed_cost_per_admitted_cell":switch_cost,
            "is_empirical_efficient_frontier":False, "production_authority":"DENY_ALL"}

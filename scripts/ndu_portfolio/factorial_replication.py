"""Balanced crossed training-fit/source inference beside the frozen v1 auditor.

Episode seeds are averaged within source clusters, never counted as training
fits. Each declared fit has a separate execution receipt and fitted identities.
The product (pigeonhole) bootstrap resamples fits and source clusters separately;
it is approximate, conditional on the locked validation selections and training
data. Bonferroni adjusts nominal tails, not actual finite-sample coverage.

This complete-matrix API rejects missing fits, including failed fits without a
complete terminal matrix. Such failures remain campaign evidence, not an excuse
to reduce the registered fit list. Hash/identity checks are not authentication or
proof of independent training. Scientific and adoption gates always remain HOLD.
CLI failures bind the unchanged input bundle's bytes; callers must archive that
bundle alongside the error report to retain failed fits and their cost receipts.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np

from . import factorial as f

MAX_BOOTSTRAP_VALUES = 250_000_000


def _fields(value, names, label):
    f._need(
        isinstance(value, dict) and set(value) == set(names.split()),
        f"invalid {label} fields",
    )


def _finite_snapshot(value):
    """Detach a complete report only after checking every derived numeric value."""

    def check(item):
        if isinstance(item, dict):
            for child in item.values():
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)
        elif type(item) in (int, float):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            f._need(finite, "nonfinite derived audit value")

    check(value)
    return json.loads(json.dumps(value, allow_nan=False))


def design_digest(protocol):
    """Prospective common design, excluding fitted identities/observed charges."""
    omitted = {
        "model_digest",
        "policy_digest",
        "initial_content_digest",
        "training_actual",
        "research_costs",
    }
    return f.canonical_digest(
        {
            **protocol,
            "registered_at": None,
            "profiles": {
                key: {k: v for k, v in profile.items() if k not in omitted}
                for key, profile in protocol["profiles"].items()
            },
        }
    )


def planning_power(power, fits, clusters, alpha):
    """Known-variance normal planning approximation for a single contrast.

    Components must prospectively bound the relevant 20 contrasts: variance of
    a mean is fit_variance/R + source_variance/C + interaction_variance/(R*C).
    The effect is ABOVE that contrast's decision margin. This is not achieved
    power, simultaneous family power, a variance estimator, or a coverage proof.
    """
    _fields(
        power,
        "effect_above_margin target_power fit_variance source_variance "
        "interaction_variance variance_evidence_digest",
        "power plan",
    )
    f._need(
        type(fits) is int and fits >= 2 and type(clusters) is int and clusters >= 20,
        "power plan needs declared fits and source clusters",
    )
    f._need(0 < f._number(alpha, "alpha") < 0.5, "invalid alpha")
    f._need(f._hash(power["variance_evidence_digest"]), "missing variance evidence pin")
    effect = f._number(
        power["effect_above_margin"], "effect above margin", minimum=1e-30
    )
    target = f._number(power["target_power"], "target power")
    f._need(0.5 < target < 1, "target power outside (.5,1)")
    a, b, c = (
        f._number(power[key], key)
        for key in ("fit_variance", "source_variance", "interaction_variance")
    )
    variance = a / fits + b / clusters + c / (fits * clusters)
    f._need(
        math.isfinite(variance) and variance > 0, "positive planning variance required"
    )
    critical = NormalDist().inv_cdf(1 - alpha / 40)
    predicted = NormalDist().cdf(effect / math.sqrt(variance) - critical)
    return {
        "method": "known-variance normal approximation; 20 nominal comparisons",
        "variance_of_mean": variance,
        "fits": fits,
        "source_clusters": clusters,
        "approximate_per_contrast_power": predicted,
        "target_power": target,
        "meets_target": predicted >= target,
        "achieved_power_verified": False,
    }


def _validate(plan, fits, splits):
    _fields(plan, "schema registered_at design_digest fits power", "replication plan")
    f._need(
        plan["schema"] == "ndu-factorial-replication-v1", "unsupported replication plan"
    )
    registered = f._time(plan["registered_at"])
    f._need(f._hash(plan["design_digest"]), "missing common design pin")
    f._need(
        isinstance(plan["fits"], list) and len(plan["fits"]) >= 2,
        "at least two declared training fits required; episode seeds are not fits",
    )
    ids, seeds = [], []
    for item in plan["fits"]:
        _fields(item, "fit_id training_seed", "fit plan")
        f._need(
            isinstance(item["fit_id"], str) and item["fit_id"], "invalid fit identity"
        )
        f._need(
            type(item["training_seed"]) is int and item["training_seed"] >= 0,
            "invalid training seed",
        )
        ids.append(item["fit_id"])
        seeds.append(item["training_seed"])
    f._need(
        len(set(ids)) == len(ids) and len(set(seeds)) == len(seeds),
        "reused fit identity or training seed",
    )
    f._need(
        isinstance(fits, dict) and set(fits) == set(ids),
        "incomplete declared fit registry",
    )
    contexts, seen, receipts, unknowns, findings = {}, set(), set(), [], []
    for fit_id, seed in zip(ids, seeds, strict=True):
        fit = fits[fit_id]
        _fields(fit, "protocol execution rows", "fit bundle")
        protocol, execution, rows = fit["protocol"], fit["execution"], fit["rows"]
        tasks, indexed, unknown = f._validate_rows(protocol, rows, splits)
        f._need(
            design_digest(protocol) == plan["design_digest"], "common design mismatch"
        )
        f._need(
            registered <= f._time(protocol["registered_at"]),
            "fit protocol precedes plan",
        )
        _fields(
            execution,
            "run_id receipt_digest training_seed started_at finished_at "
            "attempt_ids failed_attempts protocol_digest",
            "training execution",
        )
        f._need(execution["training_seed"] == seed, "training seed mismatch")
        f._need(
            execution["protocol_digest"] == f.protocol_digest(protocol),
            "training receipt does not bind fitted protocol identities",
        )
        receipt = execution["receipt_digest"]
        f._need(
            f._hash(receipt) and receipt not in receipts,
            "reused or invalid training receipt",
        )
        receipts.add(receipt)
        attempts = execution["attempt_ids"]
        f._need(isinstance(attempts, list) and attempts, "missing training attempts")
        failed = execution["failed_attempts"]
        f._need(
            type(failed) is int and 0 <= failed < len(attempts),
            "no completed training attempt; retain failed fit outside complete-matrix inference",
        )
        start, end = f._time(execution["started_at"]), f._time(execution["finished_at"])
        f._need(
            registered < start <= end
            and all(end < f._time(r["started_at"]) for r in rows),
            "training must follow plan and finish before evaluation",
        )
        identities = [execution["run_id"], *attempts]
        for row in rows:
            f._need(row.get("fit_id") == fit_id, "episode fit identity mismatch")
            identities.extend([row["run_id"], *row["attempt_ids"]])
        f._need(
            all(isinstance(x, str) and x for x in identities)
            and len(set(identities)) == len(identities)
            and not seen.intersection(identities),
            "reused training/episode run or attempt identity across fits",
        )
        seen.update(identities)
        unknowns.extend(f"{fit_id}:{value}" for value in unknown)
        budget, integrity = f._observation_findings(protocol, rows)
        findings.extend({"fit_id": fit_id, **value} for value in budget + integrity)
        contexts[fit_id] = (tasks, indexed)
    protocol = fits[ids[0]]["protocol"]
    tasks = contexts[ids[0]][0]
    counts = {
        cohort: len(
            {
                t["cluster_id"]
                for t in tasks.values()
                if t["split"] == "test" and t["cohort"] == cohort
            }
        )
        for cohort in ("new", "retention")
    }
    work = (
        len(ids)
        * protocol["bootstrap_samples"]
        * (16 * counts["new"] + 4 * counts["retention"])
    )
    f._need(
        work <= MAX_BOOTSTRAP_VALUES, "crossed bootstrap exceeds bounded work profile"
    )
    power = planning_power(
        plan["power"], len(ids), min(counts.values()), protocol["alpha"]
    )
    return ids, contexts, unknowns, findings, power


def select_replicated(plan, fits, locked_at):
    """Lock every fit's validation choice and training/search receipts together."""
    ids, _, _, _, _ = _validate(plan, fits, {"validation"})
    locks = {
        key: f.select_comparators(fits[key]["protocol"], fits[key]["rows"], locked_at)
        for key in ids
    }
    body = {
        "schema": "ndu-replication-lock-v1",
        "plan_digest": f.canonical_digest(plan),
        "locked_at": locked_at,
        "fits": locks,
        "training_executions": {key: fits[key]["execution"] for key in ids},
    }
    # Detach from mutable input: a caller retaining the lock cannot edit it by
    # mutating an execution receipt through a shared Python dictionary reference.
    return json.loads(
        json.dumps({**body, "digest": f.canonical_digest(body)}, allow_nan=False)
    )


def _definitions(selection):
    definitions = {}
    for regime in f.REGIMES:
        for name, weights in (
            ("B-A", {"B": 1, "A": -1}),
            ("D-C", {"D": 1, "C": -1}),
            ("D-B", {"D": 1, "B": -1}),
            ("interaction", {"D": 1, "C": -1, "B": -1, "A": 1}),
        ):
            definitions[f"{regime}:{name}"] = (
                "new",
                [(regime, a, w) for a, w in weights.items()],
                True,
            )
        for arm, pool in (("B", "ordinary"), ("D", "complete")):
            definitions[f"{regime}:{arm}-strongest"] = (
                "new",
                [(regime, arm, 1), (regime, selection["choices"][regime][pool], -1)],
                True,
            )
    for arm in f.CELLS:
        terms = [("joint", arm, 1), ("frozen", arm, -1)]
        definitions[f"joint-frozen:{arm}"] = ("new", terms, True)
        definitions[f"retention:{arm}"] = ("retention", terms, False)
    return definitions


def _crossed_interval(values, draws, tail, rng):
    repetitions, clusters = values.shape
    boot = np.empty(draws)
    for start in range(0, draws, 128):
        count = min(128, draws - start)
        a = rng.integers(repetitions, size=(count, repetitions, 1))
        b = rng.integers(clusters, size=(count, 1, clusters))
        boot[start : start + count] = values[a, b].mean(axis=(1, 2))
    f._need(np.isfinite(boot).all(), "nonfinite derived bootstrap mean")
    interval = np.quantile(boot, [tail, 1 - tail])
    f._need(np.isfinite(interval).all(), "nonfinite derived confidence interval")
    return [float(value) for value in interval]


def audit_replication(plan, fits, selection):
    """Audit a balanced fit/source matrix; all provenance/adoption gates stay HOLD."""
    ids, contexts, unknowns, findings, power = _validate(
        plan, fits, {"validation", "test"}
    )
    f._need(isinstance(selection, dict), "missing replication lock")
    validation = {
        key: {**fit, "rows": [r for r in fit["rows"] if r["split"] == "validation"]}
        for key, fit in fits.items()
    }
    expected = select_replicated(plan, validation, selection.get("locked_at"))
    f._need(
        selection == expected,
        "replication lock differs from fitted identities/receipts/validation",
    )
    f._need(
        all(
            f._time(row["started_at"]) > f._time(selection["locked_at"])
            for fit in fits.values()
            for row in fit["rows"]
            if row["split"] == "test"
        ),
        "test precedes global replication lock",
    )
    protocol = fits[ids[0]]["protocol"]
    blocked = bool(
        unknowns
        or findings
        or protocol["evidence_kind"] != "real"
        or not power["meets_target"]
    )
    rng, tail = (
        np.random.default_rng(protocol["bootstrap_seed"]),
        protocol["alpha"] / 40,
    )
    definitions = {key: _definitions(selection["fits"][key]) for key in ids}
    contrasts = {}
    for name in definitions[ids[0]]:
        values = []
        for key in ids:
            cohort, terms, net = definitions[key][name]
            values.append(
                f._cluster_values(
                    fits[key]["protocol"], *contexts[key], "test", cohort, terms, net
                )
            )
        threshold = (
            -protocol["retention_margin"]
            if name.startswith("retention:")
            else protocol["net_margin"]
        )
        result = {
            "estimate": None,
            "ci": None,
            "gate": "HOLD",
            "statistical_gate": "HOLD",
            "conditional_gate_on_verified_receipts": "HOLD",
            "threshold": threshold,
        }
        if all(value is not None for value in values):
            matrix = np.stack(values)
            f._need(np.isfinite(matrix).all(), f"nonfinite derived contrast {name}")
            ci = _crossed_interval(matrix, protocol["bootstrap_samples"], tail, rng)
            passed = (
                ci[0] >= threshold
                if name.startswith("retention:")
                else ci[0] > threshold
            )
            statistical = "PASS" if passed else "NOT_ESTABLISHED"
            result.update(
                estimate=float(matrix.mean()),
                ci=ci,
                declared_fits=matrix.shape[0],
                source_clusters=matrix.shape[1],
                fit_estimates=dict(zip(ids, matrix.mean(axis=1).tolist())),
                statistical_gate=statistical,
                conditional_gate_on_verified_receipts="HOLD"
                if blocked
                else statistical,
            )
        contrasts[name] = result
    costs = {
        key: {
            name: profile["research_costs"]
            for name, profile in fit["protocol"]["profiles"].items()
        }
        for key, fit in fits.items()
    }
    charges = [
        value
        for profiles in costs.values()
        for components in profiles.values()
        for value in components.values()
    ]
    rows = [row for fit in fits.values() for row in fit["rows"]]
    return _finite_snapshot(
        {
            "schema": "ndu-replication-audit-v1",
            "plan_digest": f.canonical_digest(plan),
            "selection_digest": selection["digest"],
            "evidence_digest": f.canonical_digest(fits),
            "evidence_kind": protocol["evidence_kind"],
            "matrix_complete": True,
            "declared_training_fits": len(ids),
            "episode_seeds_per_fit": len(protocol["seeds"]),
            "episode_count": len(rows),
            "comparators_by_fit": {
                key: selection["fits"][key]["choices"] for key in ids
            },
            "contrasts": contrasts,
            "unknowns": unknowns,
            "findings": findings,
            "planning": power,
            "research_costs_by_fit": costs,
            "study_research_total": None
            if any(v is None for v in charges)
            else sum(charges),
            "inference_cost_ledger": f.cost_ledger(rows),
            "failed_training_attempts": sum(
                fit["execution"]["failed_attempts"] for fit in fits.values()
            ),
            "multiplicity": {
                "method": "crossed fit/source percentile bootstrap; Bonferroni nominal tails",
                "family_size": 20,
                "alpha": protocol["alpha"],
                "tail": tail,
                "finite_sample_coverage_guaranteed": False,
            },
            "native_receipt_verification": "NOT_IMPLEMENTED",
            "independent_training_runs_verified": False,
            "scientific_gates": {"all": "HOLD"},
            "adoption_authorized": False,
            "scope": "Balanced crossed fit/source arithmetic, conditional on fixed training data and validation selections; receipt hashes do not authenticate executions.",
        }
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", type=Path, required=True, help="JSON object with plan and fits"
    )
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--locked-at")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for source in (args.bundle, args.selection):
        if source is not None and (
            args.output.resolve() == source.resolve()
            or (
                args.output.exists()
                and source.exists()
                and args.output.samefile(source)
            )
        ):
            parser.error(
                "--output must not overwrite an input bundle or selection lock"
            )
    input_binding = {"path": str(args.bundle.resolve()), "sha256": None, "bytes": None}
    try:
        raw = args.bundle.read_bytes()
        input_binding.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        bundle = json.loads(raw)
        if args.select:
            result = select_replicated(bundle["plan"], bundle["fits"], args.locked_at)
        else:
            f._need(args.selection is not None, "--selection required")
            result = audit_replication(
                bundle["plan"], bundle["fits"], json.loads(args.selection.read_text())
            )
        rendered = json.dumps(result, indent=2, allow_nan=False) + "\n"
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
        OSError,
    ) as error:
        args.output.write_text(
            json.dumps(
                {
                    "schema": "ndu-replication-audit-v1",
                    "error": str(error),
                    "input_bundle": input_binding,
                    "input_bundle_must_be_retained": True,
                    "matrix_complete": False,
                    "scientific_gates": {"all": "HOLD"},
                    "adoption_authorized": False,
                },
                indent=2,
            )
            + "\n"
        )
        raise SystemExit(2) from error
    args.output.write_text(rendered)


if __name__ == "__main__":
    main()

"""Strict completed-rollout census, paired summaries, and native NDU export.

This module never selects a live generation action. Heldout truth stays in
post-execution observation. Local hashes and clocks do not authenticate an
external evaluator or establish foundation-model/production efficacy.
"""

from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

from .joint_contract import PROFILE as JOINT_CONTRACT_PROFILE
from .joint_contract import bind_v6_output, require_v6_capabilities


Q32 = 1 << 32
WEIGHTS = {"text_fact": .30, "relation": .15, "image_fact": .35,
           "crossmodal_disagreement": .10, "pixel_mse": .10}
TRAININGS = ("supervised", "terminal_entropic_ndu")
POLICIES = ("fixed", "fixed_dev_tuned", "learned_router", "greedy",
            "risk_neutral_mpc", "risk_aware_recursive", "allocation_only")
STRONG_BASELINES = ("learned_router", "greedy", "risk_neutral_mpc", "allocation_only")
COST_FIELDS = ("wall_ns", "cpu_ns", "encode_ns", "controller_ns", "execute_ns",
               "decode_ns", "observer_ns", "modeled_work", "search_units", "execution_units")


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _hex(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0" * 64:
        raise ValueError("Expected nonzero lowercase SHA-256")
    return value


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a real numeric observation")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Nonfinite or out-of-bound observation")
    return float(value)


def _source_key(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("Invalid original source identity")
    suffix = value.rsplit(":", 1)[-1]
    return suffix if re.fullmatch(r"[0-9a-f]{64}", suffix) else value


def _validate_row(row):
    required = {"seed", "training", "policy", "split", "case_id", "budget", "source_ids",
                "corruption", "metrics", "cost", "actions", "snapshot_sha256", "forecast_sha256",
                "output_hashes", "output_paths", "receipt_sha256"}
    if not isinstance(row, dict) or not required <= row.keys():
        raise ValueError("Incomplete rollout receipt")
    if type(row["seed"]) is not int or type(row["budget"]) is not int or row["budget"] <= 0:
        raise ValueError("Invalid seed or budget")
    if (row["training"] not in TRAININGS or row["policy"] not in POLICIES
            or row["split"] not in ("future", "retention")):
        raise ValueError("Unregistered training, policy or split")
    if not isinstance(row["case_id"], str) or not row["case_id"]:
        raise ValueError("Missing case identity")
    if not isinstance(row["corruption"], str) or not row["corruption"]:
        raise ValueError("Missing corruption stratum")
    sources = row["source_ids"]
    if not isinstance(sources, (list, tuple)) or len(sources) != 2:
        raise ValueError("A case must bind exactly two original sources")
    if len({_source_key(source) for source in sources}) != 2:
        raise ValueError("A source is reused within a pair")
    _hex(row["snapshot_sha256"])
    _hex(row["forecast_sha256"])
    for name in ("snapshot_file_sha256", "forecast_file_sha256"):
        if name in row:
            _hex(row[name])
    if "observer_sha256" in row or "reward_observer_sha256" in row:
        audit = _hex(row.get("observer_sha256"))
        reward = _hex(row.get("reward_observer_sha256"))
        if audit == reward:
            raise ValueError("Audit and reward observer artifacts must differ")
    supplied = _hex(row["receipt_sha256"])
    if canonical_sha256({key: value for key, value in row.items() if key != "receipt_sha256"}) != supplied:
        raise ValueError("Rollout receipt digest mismatch")
    metrics, cost = row["metrics"], row["cost"]
    if not isinstance(metrics, dict) or not (set(WEIGHTS) | {"joint_loss", "utility", "caption_valid"}) <= metrics.keys():
        raise ValueError("Incomplete external metrics")
    for name in (*WEIGHTS, "joint_loss"):
        _number(metrics[name], 0, 1)
    _number(metrics["utility"], -1, 1)
    if type(metrics["caption_valid"]) is not bool:
        raise ValueError("Caption validity must be observed boolean")
    reconstructed = math.fsum(WEIGHTS[name] * metrics[name] for name in WEIGHTS)
    if (not math.isclose(reconstructed, metrics["joint_loss"], rel_tol=0, abs_tol=1e-9)
            or not math.isclose(1 - 2 * reconstructed, metrics["utility"], rel_tol=0, abs_tol=1e-9)):
        raise ValueError("External metric or utility identity changed")
    if not isinstance(cost, dict) or not set(COST_FIELDS) <= cost.keys():
        raise ValueError("Incomplete measured/modeled cost")
    for name in COST_FIELDS:
        _number(cost[name], 0, 86_400_000_000_000 if name.endswith("_ns") else 1_000_000)
        if name.endswith("_ns") and type(cost[name]) is not int:
            raise ValueError("Physical nanoseconds must be exact integers")
    if "backend_setup_ns" in cost:
        _number(cost["backend_setup_ns"], 0, 86_400_000_000_000)
        if type(cost["backend_setup_ns"]) is not int:
            raise ValueError("Physical backend setup nanoseconds must be exact integers")
    if cost["wall_ns"] <= 0 or cost["modeled_work"] > row["budget"] + 1e-9:
        raise ValueError("Unmeasured rollout or modeled budget breach")
    if cost["search_units"] + cost["execution_units"] > cost["modeled_work"] + 1e-9:
        raise ValueError("Controller/execution work omitted from total")
    if not isinstance(row["actions"], list) or not all(isinstance(action, str) for action in row["actions"]):
        raise ValueError("Missing action trace")
    if set(row["output_hashes"]) != {"text", "image"} or set(row["output_paths"]) != {"text", "image"}:
        raise ValueError("Both actual outputs are mandatory")
    for modality in ("text", "image"):
        expected = _hex(row["output_hashes"][modality])
        path = Path(row["output_paths"][modality])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("Unavailable or oversized original output")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Original output bytes differ from receipt")
        if modality == "text":
            raw.decode("utf-8")
        elif not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Original image does not have PNG signature")


def upper_tail90(values):
    """Exact fractional empirical upper 10% mean, including boundary mass."""
    if not values:
        raise ValueError("Empty tail sample")
    ordered = sorted((_number(value, 0, 1) for value in values), reverse=True)
    if len(ordered) <= 10:
        return ordered[0]
    whole, tenths = divmod(len(ordered), 10)
    numerator = 10 * math.fsum(ordered[:whole])
    if tenths:
        numerator += tenths * ordered[whole]
    return numerator / len(ordered)


def _quantile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def _stats(rows):
    loss = [row["metrics"]["joint_loss"] for row in rows]
    return {
        "mean_loss": statistics.fmean(loss), "cvar90_loss": upper_tail90(loss),
        "mean_utility": statistics.fmean(row["metrics"]["utility"] for row in rows),
        "mean_wall_ns": statistics.fmean(row["cost"]["wall_ns"] for row in rows),
        "mean_modeled_work": statistics.fmean(row["cost"]["modeled_work"] for row in rows),
    }


def _aggregate_rows(rows, seeds):
    per_seed = [{"seed": seed, **_stats([row for row in rows if row["seed"] == seed])}
                for seed in seeds]
    wall = [row["cost"]["wall_ns"] for row in rows]
    cost_fields = (*COST_FIELDS, *(name for name in ("backend_setup_ns",)
                                  if all(name in row["cost"] for row in rows)))
    return {
        "rows": len(rows), "independent_source_cases": len(rows) // len(seeds),
        "per_seed": per_seed,
        "seed_mean": {name: statistics.fmean(item[name] for item in per_seed)
                      for name in per_seed[0] if name != "seed"},
        "wall_ns": {f"p{int(p * 100)}": _quantile(wall, p) for p in (.50, .95, .99)},
        "mean_cost": {name: statistics.fmean(row["cost"][name] for row in rows) for name in cost_fields},
        "mean_metrics": {name: statistics.fmean(row["metrics"][name] for row in rows) for name in WEIGHTS},
        "caption_valid_rate": statistics.fmean(row["metrics"]["caption_valid"] for row in rows),
        "joint_fact_correct_rate": statistics.fmean(
            row["metrics"]["caption_valid"] and all(row["metrics"][name] == 0 for name in
            ("text_fact", "relation", "image_fact", "crossmodal_disagreement")) for row in rows),
    }


def summarize(rows, protocol):
    """Validate the full registered census before any favorable aggregation."""
    rows = list(rows)
    required = (require_v6_capabilities(protocol["hard_output_modalities"])
                if "hard_output_modalities" in protocol else None)
    bind_joint = "joint_contract" in protocol
    bind_artifacts = protocol.get("require_artifact_file_pins", False)
    if type(bind_artifacts) is not bool:
        raise ValueError("Artifact pin requirement must be explicit boolean")
    if bind_joint and (protocol["joint_contract"] != JOINT_CONTRACT_PROFILE or required is None):
        raise ValueError("Joint output profile or requirements differ from the contract")
    seeds, trainings, policies, budgets = (protocol[key] for key in
                                         ("seeds", "trainings", "policies", "budgets"))
    for values in (seeds, trainings, policies, budgets):
        if not isinstance(values, list) or not values or len(set(values)) != len(values):
            raise ValueError("Empty or repeated protocol census axis")
    if (any(type(seed) is not int for seed in seeds)
            or any(type(budget) is not int or budget <= 0 for budget in budgets)
            or set(trainings) != set(TRAININGS) or set(policies) != set(POLICIES)):
        raise ValueError("Incomplete factorial or strong-control protocol")
    metric = protocol["metric"]
    if metric["weights"] != WEIGHTS or metric["utility"] != "1 - 2 * joint_loss":
        raise ValueError("Frozen metric profile differs from reporting contract")
    if canonical_sha256(metric) != _hex(protocol["metric_sha256"]):
        raise ValueError("Metric manifest digest mismatch")
    if type(protocol.get("require_distinct_observers", False)) is not bool:
        raise ValueError("Observer requirement must be explicit boolean")
    bind_observers = protocol.get("require_distinct_observers", False) or any(
        "observer_sha256" in row or "reward_observer_sha256" in row for row in rows)
    observer_identities = set()
    cases, source_owner = {}, {}
    excluded_sources = set()
    if "prior_heldout_exclusion" in protocol:
        exclusion = protocol["prior_heldout_exclusion"]
        _hex(exclusion.get("protocol_sha256"))
        supplied = exclusion.get("source_pixel_sha256", [])
        excluded_sources = {_hex(value) for value in supplied}
        if not excluded_sources or len(excluded_sources) != len(supplied):
            raise ValueError("Invalid prior heldout source exclusion")
    if set(protocol["cases"]) != {"future", "retention"}:
        raise ValueError("Future and retention cohorts are mandatory")
    for split, entries in protocol["cases"].items():
        if not entries:
            raise ValueError("Empty case cohort")
        for entry in entries:
            key = (split, entry["case_id"])
            if key in cases or any(prior[1] == key[1] for prior in cases):
                raise ValueError("Repeated case identity")
            if len(entry["source_ids"]) != 2:
                raise ValueError("Invalid registered original-source pair")
            for source in entry["source_ids"]:
                identity = _source_key(source)
                if identity in excluded_sources:
                    raise ValueError("Registered evaluation reuses a previously evaluated source")
                if identity in source_owner:
                    raise ValueError("Original source reused across cases or splits")
                source_owner[identity] = key
            cases[key] = entry
    expected = {(seed, training, policy, budget, split, case_id)
                for seed, training, policy, budget in itertools.product(seeds, trainings, policies, budgets)
                for split, case_id in cases}
    seen, receipts, snapshots, forecasts, strata = {}, set(), {}, {}, {}
    checkpoint_files = {}
    groups, corruption_groups = defaultdict(list), defaultdict(list)
    for row in rows:
        _validate_row(row)
        if bind_joint:
            try:
                expected_joint = bind_v6_output(
                    required, row["snapshot_sha256"], row["final_state_sha256"],
                    row["latent_sha256"], row["output_hashes"], row["case_id"])
            except (KeyError, TypeError) as error:
                raise ValueError("Missing or malformed joint state binding") from error
            if row.get("joint_output_contract") != expected_joint:
                raise ValueError("Missing or changed joint output contract")
        elif "joint_output_contract" in row:
            raise ValueError("Unannounced joint output contract")
        if bind_observers:
            observer_identities.add((_hex(row.get("observer_sha256")),
                                     _hex(row.get("reward_observer_sha256"))))
        key = tuple(row[name] for name in ("seed", "training", "policy", "budget", "split", "case_id"))
        if key in seen or key not in expected or row["receipt_sha256"] in receipts:
            raise ValueError("Duplicated or unregistered rollout")
        case_key = (row["split"], row["case_id"])
        if list(row["source_ids"]) != list(cases[case_key]["source_ids"]):
            raise ValueError("Paired original-source identity changed")
        if "corruption" in cases[case_key] and cases[case_key]["corruption"] != row["corruption"]:
            raise ValueError("Registered corruption stratum changed")
        if strata.setdefault(case_key, row["corruption"]) != row["corruption"]:
            raise ValueError("Paired corruption stratum changed")
        snapshot_key = (row["seed"], row["training"])
        if snapshots.setdefault(snapshot_key, row["snapshot_sha256"]) != row["snapshot_sha256"]:
            raise ValueError("Model snapshot changed within an inference comparison")
        if forecasts.setdefault(snapshot_key, row["forecast_sha256"]) != row["forecast_sha256"]:
            raise ValueError("Forecast snapshot changed within an inference comparison")
        if bind_artifacts:
            label = f"seed-{row['seed']}-{row['training']}"
            pins = {name: _hex(row.get(name)) for name in
                    ("snapshot_file_sha256", "forecast_file_sha256")}
            if label in checkpoint_files:
                if checkpoint_files[label] != pins:
                    raise ValueError("Checkpoint file pins changed within an inference comparison")
            else:
                for kind, suffix in (("snapshot", ""), ("forecast", "-forecast")):
                    path = Path(f"{label}{suffix}.pt")
                    if (path.is_symlink() or not path.is_file()
                            or path.stat().st_size > 128 * 1024 * 1024
                            or hashlib.sha256(path.read_bytes()).hexdigest() != pins[f"{kind}_file_sha256"]):
                        raise ValueError("Pinned checkpoint file is missing, changed, or oversized")
                checkpoint_files[label] = pins
        seen[key] = row
        receipts.add(row["receipt_sha256"])
        groups[(row["training"], row["policy"], row["split"], row["budget"])].append(row)
        corruption_groups[(row["training"], row["policy"], row["split"],
                           row["budget"], row["corruption"])].append(row)
    if set(seen) != expected:
        raise ValueError(f"Incomplete rollout census: missing {len(expected - set(seen))}")
    if bind_observers and len(observer_identities) != 1:
        raise ValueError("Observer artifacts changed within paired evaluation")
    observer_binding = {"artifact_identities_supplied": bind_observers,
                        "external_observer_authenticated": False}
    if bind_observers:
        audit, reward = next(iter(observer_identities))
        observer_binding.update(audit_artifact_sha256=audit, reward_artifact_sha256=reward,
                                distinct_artifact_identities=True)
    aggregates, seed_stats = [], {}
    for (training, policy, split, budget), group in sorted(groups.items()):
        aggregate = _aggregate_rows(group, seeds)
        for values in aggregate["per_seed"]:
            seed_stats[(values["seed"], training, policy, split, budget)] = {
                name: value for name, value in values.items() if name != "seed"}
        aggregates.append({
            "training": training, "policy": policy, "split": split, "budget": budget,
            **aggregate,
        })
    corruption_aggregates = [{
        "training": training, "policy": policy, "split": split, "budget": budget,
        "corruption": corruption, **_aggregate_rows(group, seeds),
    } for (training, policy, split, budget, corruption), group in sorted(corruption_groups.items())]
    factorial = _factorial(seed_stats, seeds, budgets)
    comparisons = _paired_contrasts(seen, seeds, trainings, budgets, cases)
    return {
        "schema": "hepta.ndu-v6.completed-rollout-summary.v1",
        "protocol_sha256": canonical_sha256(protocol), "rows": len(rows),
        "independent_training_seeds": len(seeds), "original_source_cases": len(cases),
        "observer_binding": observer_binding,
        "checkpoint_files": checkpoint_files,
        "small_seed_warning": "Training-seed count is small; seed means are descriptive. Rows and repeated source cases are not independent training replicates.",
        "aggregation": "Each CVaR is computed within one seed and then averaged across seeds; latency quantiles pool actual executions as diagnostics.",
        "aggregates": aggregates, "corruption_aggregates": corruption_aggregates,
        "corruption_scope": "Diagnostic preregistered input strata; small within-stratum source counts are reported and no subgroup superiority decision is issued.",
        "factorial": factorial, "strong_paired_contrasts": comparisons,
        "evidence": {"complete_registered_census": True, "original_output_hashes_verified": True,
                     "checkpoint_file_pins_verified": bind_artifacts,
                     "prior_heldout_exclusion_verified": bool(excluded_sources),
                     "frozen_forecast_identities_verified": True,
                     "local_measured_cost_fields_present": True, "external_observer_authenticated": False,
                     "production_authority": False, "confirmatory_superiority_decision": "not issued"},
    }


def _factorial(seed_stats, seeds, budgets):
    result = []
    arms = {"SS": ("supervised", "fixed_dev_tuned"), "SN": ("supervised", "risk_aware_recursive"),
            "NS": ("terminal_entropic_ndu", "fixed_dev_tuned"), "NN": ("terminal_entropic_ndu", "risk_aware_recursive")}
    for split, budget in itertools.product(("future", "retention"), budgets):
        per_seed = []
        for seed in seeds:
            values = {arm: seed_stats[(seed, training, policy, split, budget)]
                      for arm, (training, policy) in arms.items()}
            contrasts = {}
            for metric in values["SS"]:
                ss, sn, ns, nn = (values[arm][metric] for arm in arms)
                contrasts[metric] = {"training_at_static": ns - ss, "inference_at_supervised": sn - ss,
                                     "inference_at_ndu": nn - ns, "total": nn - ss,
                                     "interaction": (nn - ns) - (sn - ss)}
            per_seed.append({"seed": seed, "arms": values, "contrasts": contrasts})
        result.append({"split": split, "budget": budget, "per_seed": per_seed,
                       "seed_mean_contrasts": {metric: {name: statistics.fmean(
                           item["contrasts"][metric][name] for item in per_seed)
                           for name in per_seed[0]["contrasts"][metric]}
                           for metric in per_seed[0]["contrasts"]}})
    return result


def _paired_contrasts(seen, seeds, trainings, budgets, cases):
    result = []
    family = len(trainings) * len(budgets) * 2 * len(STRONG_BASELINES)
    for training, budget, split, baseline in itertools.product(trainings, budgets, ("future", "retention"), STRONG_BASELINES):
        case_deltas, seed_deltas = [], defaultdict(list)
        costs, work = [], []
        for candidate_split, case_id in cases:
            if candidate_split != split:
                continue
            deltas = []
            for seed in seeds:
                active = seen[(seed, training, "risk_aware_recursive", budget, split, case_id)]
                reference = seen[(seed, training, baseline, budget, split, case_id)]
                delta = active["metrics"]["joint_loss"] - reference["metrics"]["joint_loss"]
                deltas.append(delta)
                seed_deltas[seed].append(delta)
                costs.append(active["cost"]["wall_ns"] - reference["cost"]["wall_ns"])
                work.append(active["cost"]["modeled_work"] - reference["cost"]["modeled_work"])
            case_deltas.append(statistics.fmean(deltas))
        mean = statistics.fmean(case_deltas)
        radius = math.sqrt(2 * math.log(2 * family / .05) / len(case_deltas))
        result.append({"training": training, "split": split, "budget": budget,
                       "contrast": f"risk_aware_recursive-minus-{baseline}",
                       "mean_paired_loss_difference": mean, "source_case_differences": case_deltas,
                       "per_seed_mean_difference": {str(seed): statistics.fmean(values)
                                                    for seed, values in seed_deltas.items()},
                       "mean_paired_wall_ns_difference": statistics.fmean(costs),
                       "mean_paired_modeled_work_difference": statistics.fmean(work),
                       "conditional_hoeffding_interval_95": [max(-1., mean - radius), min(1., mean + radius)],
                       "interval_scope": "Simultaneous bounded-loss interval ONLY if original source cases are independent draws, conditional on all frozen trained models; no coverage for training-seed uncertainty.",
                       "family_comparisons": family, "independent_source_cases": len(case_deltas)})
    return result


def owner_tsv(rows, objective_digest, source_digest, metric_digest, modeled_cap, wallcap):
    """Export one paired episode/snapshot after outcomes have been observed.

    Risk is the conservative known normalized-loss bound one, not an estimated
    probability or a missing-risk zero. Utility is the frozen 1-2*loss score.
    """
    rows = list(rows)
    for digest in (objective_digest, source_digest, metric_digest):
        _hex(digest)
    if (not rows or type(modeled_cap) is not int or not 1 <= modeled_cap <= 1_000_000
            or type(wallcap) is not int or not 1 <= wallcap <= 86_400_000_000_000):
        raise ValueError("Invalid native export envelope")
    for row in rows:
        _validate_row(row)
    grouping = ("seed", "training", "split", "case_id", "budget", "snapshot_sha256", "corruption")
    identities = {tuple(row[key] for key in grouping) for row in rows}
    if len(identities) != 1 or len({row["policy"] for row in rows}) != len(rows):
        raise ValueError("Native candidates must share one episode and snapshot")
    if len({tuple(row["source_ids"]) for row in rows}) != 1:
        raise ValueError("Native candidates have different original inputs")
    snapshot = rows[0]["snapshot_sha256"]
    episode = "episode:v6:" + canonical_sha256(list(next(iter(identities))))
    scope = "\t".join(map(str, ("scope", objective_digest, source_digest, snapshot,
                                episode, 1, 3, modeled_cap, wallcap, Q32, metric_digest)))
    scope_digest = hashlib.sha256(scope.encode()).hexdigest()
    empty = hashlib.sha256(b"").hexdigest()
    lines = ["hepta.ndu.generation-rollout.v1", scope,
             f"candidate\tabstain\t0\tfeasible\t0\t0\t0\t0\t{empty}\t{scope_digest}"]
    for row in sorted(rows, key=lambda item: item["policy"]):
        lines.append("\t".join(map(str, ("candidate", "policy:" + row["policy"], 3, "feasible",
                                        round(row["metrics"]["utility"] * Q32), Q32,
                                        math.ceil(row["cost"]["modeled_work"]), row["cost"]["wall_ns"],
                                        row["receipt_sha256"], scope_digest))))
    tsv = "\n".join(lines) + "\n"
    return {"tsv": tsv, "pins": [objective_digest, source_digest, snapshot],
            "scope_sha256": scope_digest, "input_sha256": hashlib.sha256(tsv.encode()).hexdigest(),
            "risk_semantics": "known normalized loss bound 1; no covariance/probability inference"}


def evaluate_native(export, binary):
    """Execute the actual owner binary; verify returned identity/authority."""
    result = subprocess.run([str(binary), *export["pins"]], input=export["tsv"],
                            text=True, capture_output=True, check=True, timeout=60)
    receipt = json.loads(result.stdout)
    if (receipt["input_digest"] != export["input_sha256"]
            or [receipt[name] for name in ("objective_digest", "source_bundle_digest", "model_snapshot_digest")] != export["pins"]
            or receipt["native_policy_evaluator"] is not True
            or receipt["observation_attestation_verified"] is not False
            or receipt["production_authority"] is not False or receipt["authority"] != "DENY_ALL"):
        raise ValueError("Native receipt binding or authority mismatch")
    _hex(receipt["evaluation_digest_v2"])
    return receipt

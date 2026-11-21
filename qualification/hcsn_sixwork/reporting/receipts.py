"""Read-only campaign evidence normalization; no learner imports or data creation."""
import hashlib
import json
import math
from pathlib import Path

SEEDS = [1907341, 4812467, 8629119]
TASKS = ("first_passage", "burst", "asynchronous", "association")
ARMS = {
    "readout": ("direct", "local_bp", "semantic_program", "program_then_bp"),
    "joint": ("conditional_direct", "joint_bp", "semantic_program", "program_then_bp"),
    "architecture": ("hcsn_finite", "gru", "diagonal_linear_ct_ssm", "lif_surrogate", "causal_transformer", "official_cfc"),
    "feature": ("same_generator", "drop_value_risk", "ordinary_tanh"),
    "boundary": ("howard_qvi", "lookup_gate_bp", "never_reset"),
}
PREFIXES = {s: f"hcsn-{s}-confirmatory-v1/" for s in ARMS}
PREFIXES["readout"] = "hcsn-confirmatory-v1/"
SUFFIX = "20261121-e29f-independent-01"
SUCCESS = {"selected", "no_update", "reference"}


def finite(x):
    return type(x) in (int, float) and math.isfinite(x)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_digest(data):
    return digest(json.dumps(data, sort_keys=True, allow_nan=False).encode())


def parsed_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def read(path, inventory, issues, required=True):
    path = Path(path)
    try:
        data = path.read_bytes()
        inventory[str(path)] = digest(data)
        return json.loads(data, parse_float=parsed_float,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (OSError, ValueError) as error:
        if required or path.exists():
            issues.append(f"{path}: {error}")
        return None


def normalize(stage, cfg, selection, final):
    """Keep one row per expected seed-cell, including every missing/failed cell."""
    rows, issues, used = [], [], set()
    cases, outcomes = (selection or {}).get("cases", {}), (final or {}).get("results", [])
    expected_keys = set()
    for task in (("finite_control",) if stage == "boundary" else TASKS):
        for seed in cfg["seeds"]:
            key = str(seed) if stage == "boundary" else f"{task}/{seed}"
            for method in ARMS[stage]:
                case_key = f"{key}/{method}" if stage == "architecture" else key
                expected_keys.add(case_key)
                case = cases.get(case_key, {})
                fit = case if stage == "architecture" else case.get("methods", {}).get(method, case)
                status = fit.get("status", "missing")
                base = fit.get("zero_dev_mse", case.get("base_dev_mse", case.get("base_dev_return")))
                candidate = fit.get("dev_mse", fit.get("candidate_dev_mse", fit.get("candidate_dev_return")))
                common = case.get("common_setup_seconds", case.get("complete_feature_bank_seconds"))
                template = {"stage": stage, "task": task, "seed": seed, "method": method,
                            "incumbent_dev": base, "fit_status": status,
                            "tau": max(1e-6, .01 * base) if stage in ("readout", "joint") and finite(base) else None,
                            "common_setup_seconds": common,
                            "adaptation_wall_seconds": fit.get("adaptation_wall_seconds"),
                            "standalone_wall_lower_bound": fit.get("standalone_wall_lower_bound"),
                            "whole_fit_case_wall_seconds": case.get("whole_fit_case_wall_seconds"),
                            "eligible_parameters": case.get("eligible_parameters", case.get("architecture", {}).get("parameters")),
                            "eligible_mask": case.get("eligible_mask", case.get("architecture", {}).get("trainable_names")),
                            "actually_edited_names": fit.get("edited_names"),
                            "optimizer_steps_completed": fit.get("optimizer_steps_completed", fit.get("optimizer_steps",
                                (fit.get("fit_progress") or {}).get("optimizer_steps_completed"))),
                            "diagnostics": fit.get("diagnostics", fit.get("completed_work")),
                            "selected_probability": fit.get("selected_probability")}
                valid = status in SUCCESS and finite(candidate) and finite(base)
                rows.append({**template, "phase": "fit", "split": "development", "status": status,
                             "metric": "candidate_dev_return" if stage == "boundary" else "candidate_dev_mse",
                             "value": candidate, "selected_dev_value": base if status in ("no_update", "reference") else candidate,
                             "cell_valid": valid, "error": fit.get("error", case.get("error"))})
                for split in (("final",) if stage == "boundary" else ("final_iid", "final_clock")):
                    if stage == "boundary":
                        matches = [(i, x) for i, x in enumerate(outcomes) if x.get("seed") == seed]
                    else:
                        matches = [(i, x) for i, x in enumerate(outcomes) if x.get("case") == case_key
                                   and (stage == "architecture" or x.get("method") == method)
                                   and (x.get("split") == split or (stage == "architecture" and method == "official_cfc"
                                        and x.get("status") == "UNAVAILABLE" and "split" not in x))]
                    if len(matches) == 1:
                        index, record = matches[0]
                        used.add(index)
                        arm = record.get("methods", {}).get(method, record) if stage == "boundary" else record
                    else:
                        record, arm = {}, {"status": "missing" if not matches else "duplicate"}
                    values = arm.get("sample_squared_errors", arm.get("measured_returns"))
                    metric = arm.get("mse", arm.get("mean_full_return"))
                    status = arm.get("status", "missing")
                    valid = (status in SUCCESS and isinstance(values, list) and len(values) == cfg["final"]
                             and all(finite(x) for x in values) and finite(metric)
                             and math.isclose(sum(values) / len(values), metric, rel_tol=1e-9, abs_tol=1e-10))
                    signature = None
                    if valid and stage != "boundary":
                        prediction, target, ids = arm.get("prediction", []), arm.get("target", []), arm.get("ids", [])
                        valid = (len(prediction) == len(target) == len(ids) == len(values) and len(set(ids)) == len(ids)
                                 and all(finite(p) and finite(y) and math.isclose((p-y)**2, v, rel_tol=1e-9, abs_tol=1e-10)
                                         for p, y, v in zip(prediction, target, values)) and bool(arm.get("data_sha256")))
                        signature = json_digest([arm.get("data_sha256"), ids, target])
                    elif valid:
                        observed = record.get("reward_observations", [])
                        valid = (len(observed) == cfg["final"] and bool(record.get("reward_sha256"))
                                 and all(len(x) == 6 and all(finite(y) for y in x) for x in observed)
                                 and arm.get("reset_probability") == fit.get("selected_probability"))
                        signature = json_digest([record.get("reward_sha256"), observed])
                    rows.append({**template, "phase": "final", "split": split, "status": status,
                                 "metric": "mean_full_return" if stage == "boundary" else "mse", "value": metric,
                                 "cell_valid": valid, "data_signature": signature,
                                 "error": arm.get("error", record.get("error")),
                                 "final_reset_probability": arm.get("reset_probability"),
                                 "evaluation_linear_solves": arm.get("evaluation_linear_solves")})
    if set(cases) != expected_keys:
        issues.append("fit case keys differ from the frozen grid")
    if stage != "architecture" and any(set(x.get("methods", {})) != set(ARMS[stage]) for x in cases.values()):
        issues.append("fit method keys differ from the frozen grid")
    if len(used) != len(outcomes):
        issues.append("unplanned or duplicate final rows exist")
    signatures = {}
    for row in rows:
        if row["phase"] == "final" and row["cell_valid"]:
            key = (row["task"], row["seed"], row["split"])
            signatures.setdefault(key, set()).add(row["data_signature"])
    mismatches = {k for k, values in signatures.items() if len(values) != 1}
    if mismatches:
        issues.append("paired methods have unequal final data")
        for row in rows:
            if (row["task"], row["seed"], row["split"]) in mismatches:
                row["cell_valid"] = False
    return rows, issues


def costs(attempt, cfg, identity, inventory, issues):
    path = Path(attempt) / "cost.jsonl"
    tail, pending, totals, wall, operations, failed = "0" * 64, None, {}, 0., [], 0
    states = {}
    try:
        raw = path.read_bytes()
        inventory[str(path)] = digest(raw)
        for line in raw.splitlines():
            record = json.loads(line)
            actual = record.pop("hash")
            if (actual != digest(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
                    or record["previous"] != tail or record["identity"] != identity or record["budget"] != cfg["budget"]):
                raise ValueError("ledger chain/identity/budget mismatch")
            if record["kind"] == "reserve":
                if pending is not None:
                    raise ValueError("overlapping reserve")
                pending = record
                for name, charge in record["charge"].items():
                    if type(charge) is not int or charge < 0:
                        raise ValueError("invalid reserved work")
                    totals[name] = totals.get(name, 0) + charge
            elif record["kind"] == "settle":
                if pending is None or pending["operation"] != record["operation"] or record["status"] not in ("completed", "failed"):
                    raise ValueError("unmatched settlement")
                current = record["cumulative_wall_seconds"]
                if not finite(current) or current < wall:
                    raise ValueError("nonfinite/decreasing wall")
                operations.append({"name": pending.get("name"), "charge": pending["charge"], "status": record["status"],
                                   "cumulative_wall_seconds": current, "inter_settlement_wall_seconds": current-wall,
                                   "error": record.get("error")})
                wall, failed, pending = current, failed + int(record["status"] == "failed"), None
            else:
                raise ValueError("unknown ledger kind")
            tail = actual
            states[tail] = {"wall_seconds": wall, "reserved_work": dict(totals), "pending": pending is not None}
        if pending is not None or not totals:
            raise ValueError("pending or empty ledger")
        if wall > cfg["budget"]["wall_seconds"] or any(v > cfg["budget"][k] for k, v in totals.items()):
            raise ValueError("ledger budget exceeded")
    except (OSError, ValueError, KeyError, TypeError) as error:
        issues.append(f"{path}: {error}")
    sidecars = {}
    for phase, name in (("fit", "selection"), ("final", "final")):
        value = read(Path(attempt) / (name + ".cost.json"), inventory, issues,
                     required=(Path(attempt) / (name + ".json")).is_file())
        if value is not None:
            sidecars[phase] = value
            matched = states.get(value.get("tail"), {})
            if (not matched or matched.get("pending") or value.get("pending") is not None
                    or value.get("wall_overrun_seconds") != 0 or not finite(value.get("wall_seconds"))
                    or not matched.get("wall_seconds", math.inf) <= value["wall_seconds"] <= cfg["budget"]["wall_seconds"]
                    or any(value.get(k) != v for k, v in matched.get("reserved_work", {}).items())):
                issues.append(f"{phase} cost sidecar mismatch")
    return {"cumulative_ledger_wall_seconds": wall, "reserved_work": totals, "failed_operations": failed,
            "pending": pending, "sidecars": sidecars, "operations": operations,
            "accounting": "sidecars are cumulative snapshots, never added to each other; reserved work may exceed completed work"}


def registry_evidence(registry, stage, cfg, identity, selection_hash, final_hash, inventory, issues):
    if registry is None:
        return {"admitted": False, "reason": "no outer registry evidence supplied; complete process cost unknown"}
    root = Path(registry)
    key = digest(cfg["namespace"].encode())
    record = read(root / (key + ".json"), inventory, issues) or {}
    folder = root / key
    phases = {p: read(folder / (p + ".finished.json"), inventory, issues) for p in ("freeze", "fit", "final")}
    frozen = read(folder / "frozen.json", inventory, issues) or {}
    registration = read(root / ("registration-" + record.get("plan_sha256", "MISSING") + ".finished.json"), inventory, issues) or {}
    external = read(folder / "final.reserved.json", inventory, issues) or {}
    admitted = True
    try:
        if (record["stage"] != stage or record["namespace"] != cfg["namespace"] or record["seeds"] != SEEDS
                or frozen["manifest_sha256"] != identity or frozen["attempt"] != record["attempt"]
                or frozen["registry_sha256"] != inventory[str(root / (key + ".json"))]
                or registration["plan_sha256"] != record["plan_sha256"] or set(registration["registered"]) != set(ARMS)
                or any(record["source_files"].get(p) != h for p, h in cfg["sources"].items())):
            raise ValueError("registry/source/allocation binding mismatch")
        for p, phase in phases.items():
            if (phase["status"] not in ("complete", "unavailable") or phase["process"]["returncode"] != 0
                    or phase["process"]["timed_out"] or phase["source_git_sha"] != record["source_git_sha"]
                    or phase["manifest_sha256"] != identity or not finite(phase["process"]["wall_seconds"])
                    or phase["process"]["wall_seconds"] < 0):
                raise ValueError(f"{p} failed, unknown, timed out or unbound")
            if p != "freeze" and not phase["validation"]["integrity_ok"]:
                raise ValueError(f"{p} grid/cost integrity failed")
        if (phases["fit"]["validated_selection_sha256"] != selection_hash
                or phases["fit"]["validation"]["receipt_sha256"] != selection_hash
                or phases["final"]["validation"]["receipt_sha256"] != final_hash
                or external["selection_sha256"] != selection_hash):
            raise ValueError("fit/final original byte binding mismatch")
        combined = phases["fit"]["process"]["wall_seconds"] + phases["final"]["process"]["wall_seconds"]
        if (not finite(combined) or not 0 <= combined <= cfg["budget"]["wall_seconds"]
                or not math.isclose(combined, phases["final"]["cumulative_fit_final_child_wall_seconds"], abs_tol=1e-8)):
            raise ValueError("outer cumulative process budget mismatch")
    except (KeyError, ValueError, TypeError) as error:
        admitted = False
        issues.append(f"outer registry: {error}")
    return {"admitted": admitted, "record": record, "frozen": frozen, "phases": phases,
            "registration": registration, "external_final_reservation": external,
            "scope": "local auditable registry; not a tamper-proof external authority"}

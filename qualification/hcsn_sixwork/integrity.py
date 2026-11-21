"""Stdlib validation of receipts; never imports a learner or generates examples."""
import hashlib
import json
import math
from pathlib import Path

SCHEMAS = {
    "readout": "hepta.hcsn-confirmatory.v1",
    "joint": "hepta.hcsn-joint-confirmatory.v1",
    "architecture": "hepta.hcsn-architecture-confirmatory.v1",
    "feature": "hepta.hcsn-feature-confirmatory.v1",
    "boundary": "hepta.hcsn-boundary-confirmatory.v1",
}
TASKS = ("first_passage", "burst", "asynchronous", "association")
ARMS = {
    "readout": ("direct", "local_bp", "semantic_program", "program_then_bp"),
    "joint": ("conditional_direct", "joint_bp", "semantic_program", "program_then_bp"),
    "architecture": ("hcsn_finite", "gru", "diagonal_linear_ct_ssm", "lif_surrogate", "causal_transformer", "official_cfc"),
    "feature": ("same_generator", "drop_value_risk", "ordinary_tanh"),
    "boundary": ("howard_qvi", "lookup_gate_bp", "never_reset"),
}


def parse(data):
    return json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def load(path):
    return parse(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def size(value):
    return sum(size(x) for x in value) if isinstance(value, list) else 1


def state_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def ledger_check(path, identity, budget):
    pending, tail, wall, failed, totals = None, "0" * 64, 0., 0, {}
    for line in Path(path).read_text().splitlines():
        item = json.loads(line)
        recorded = item.pop("hash")
        actual = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if actual != recorded or item["previous"] != tail or item["identity"] != identity or item["budget"] != budget:
            raise ValueError("ledger hash/identity/budget mismatch")
        if item["kind"] == "reserve":
            if pending is not None:
                raise ValueError("overlapping ledger reservation")
            pending = item["operation"]
            for name, charge in item["charge"].items():
                if type(charge) is not int or charge < 0:
                    raise ValueError("invalid work reservation")
                totals[name] = totals.get(name, 0) + charge
        elif item["kind"] == "settle":
            if pending != item["operation"] or item["status"] not in ("completed", "failed"):
                raise ValueError("unpaired or invalid ledger settlement")
            pending = None
            next_wall = item["cumulative_wall_seconds"]
            if not finite(next_wall) or next_wall < wall:
                raise ValueError("nonfinite/decreasing cumulative wall")
            wall, failed = next_wall, failed + int(item["status"] == "failed")
        else:
            raise ValueError("unexpected ledger record kind")
        tail = recorded
    if pending is not None or not totals:
        raise ValueError("unsettled or empty cost ledger")
    if wall > budget["wall_seconds"] or any(v > budget[k] for k, v in totals.items()):
        raise ValueError("cumulative ledger budget exceeded")
    return {"wall_seconds": wall, "reserved_work": totals, "failed_operations": failed, "tail": tail}


def validate(attempt, cfg, stage, phase, identity, selection_sha=None):
    attempt, defects, unavailable, passed = Path(attempt), [], 0, 0
    path = attempt / ("selection.json" if phase == "fit" else "final.json")
    raw = path.read_bytes()
    receipt, receipt_digest = parse(raw), hashlib.sha256(raw).hexdigest()
    if receipt["manifest_sha256"] != identity or receipt["phase"] != phase:
        raise ValueError("receipt phase/manifest mismatch")
    if phase == "final" and ((attempt / "FINAL_CONSUMED").read_text() != selection_sha
                             or sha(attempt / "selection.json") != selection_sha):
        raise ValueError("final consumption/selection binding mismatch")
    ledger = ledger_check(attempt / "cost.jsonl", identity, cfg["budget"])
    cost = load(path.with_suffix(".cost.json"))
    if (cost["tail"] != ledger["tail"] or cost["pending"] is not None or cost["wall_overrun_seconds"] != 0
            or not finite(cost["wall_seconds"]) or not ledger["wall_seconds"] <= cost["wall_seconds"] <= cfg["budget"]["wall_seconds"]
            or any(cost.get(k) != v for k, v in ledger["reserved_work"].items())):
        raise ValueError("cost sidecar does not settle the current ledger")
    optional = stage == "architecture" and cfg["official_ncps"]["status"] == "UNAVAILABLE"
    expected_failures = len(TASKS) * len(cfg["seeds"]) if optional else 0
    if ledger["failed_operations"] != expected_failures:
        defects.append("failed ledger operations are not exactly explained by predeclared unavailable CfC")
    final_rows = receipt.get("results", [])
    seen_data, used_rows = {}, set()
    if phase == "fit":
        expected = {str(s) if stage == "boundary" else f"{t}/{s}"
                    for t in (("finite_control",) if stage == "boundary" else TASKS) for s in cfg["seeds"]}
        if stage == "architecture":
            expected = {f"{k}/{m}" for k in expected for m in ARMS[stage]}
        if set(receipt["cases"]) != expected:
            defects.append("fit cases differ from the exact frozen grid")
        if stage != "architecture" and any(set(r.get("methods", {})) != set(ARMS[stage]) for r in receipt["cases"].values()):
            defects.append("fit contains missing or unplanned arms")
    for task in (("finite_control",) if stage == "boundary" else TASKS):
        for seed in cfg["seeds"]:
            key = str(seed) if stage == "boundary" else f"{task}/{seed}"
            for method in ARMS[stage]:
                splits = ("fit",) if phase == "fit" else (("final",) if stage == "boundary" else ("final_iid", "final_clock"))
                for split in splits:
                    label = f"{task}/{seed}/{method}/{split}"
                    try:
                        if phase == "fit":
                            case_key = f"{key}/{method}" if stage == "architecture" else key
                            record = receipt["cases"][case_key]
                            arm = record if stage == "architecture" else record["methods"][method]
                        elif stage == "boundary":
                            matches = [(i, r) for i, r in enumerate(final_rows) if r.get("seed") == seed]
                            if len(matches) != 1:
                                raise ValueError("missing/duplicate boundary case")
                            used_rows.add(matches[0][0])
                            record, arm = matches[0][1], matches[0][1]["methods"][method]
                            if set(record["methods"]) != set(ARMS[stage]):
                                raise ValueError("unplanned boundary arms")
                        else:
                            case_key = f"{key}/{method}" if stage == "architecture" else key
                            matches = [(i, r) for i, r in enumerate(final_rows) if r.get("case") == case_key
                                       and (stage == "architecture" or r.get("method") == method)
                                       and (r.get("split") == split or
                                            (optional and method == "official_cfc" and "split" not in r
                                             and r.get("status") == "UNAVAILABLE"))]
                            if len(matches) != 1:
                                raise ValueError("missing/duplicate final cell")
                            used_rows.add(matches[0][0])
                            record = arm = matches[0][1]
                        status = arm["status"]
                        if status == "UNAVAILABLE" and optional and method == "official_cfc":
                            unavailable += 1
                            continue
                        if status not in ("selected", "no_update", "reference"):
                            raise ValueError(f"non-success cell: {status}")
                        if phase == "fit":
                            metric = arm.get("dev_mse", arm.get("candidate_dev_mse", arm.get("candidate_dev_return")))
                            if not finite(metric):
                                raise ValueError("missing/nonfinite development metric")
                            if stage in ("readout", "feature") and status == "no_update":
                                if arm["bias"] != 0 or any(v != 0 for v in arm["weight"]):
                                    raise ValueError("NoUpdate changed zero incumbent")
                            if stage in ("joint", "architecture"):
                                state = arm["selected_state"]
                                if state_sha(state) != arm["selected_sha256"]:
                                    raise ValueError("selected parameter hash mismatch")
                                if status == "no_update" and arm["selected_sha256"] != record["base_sha256"]:
                                    raise ValueError("NoUpdate changed fitted incumbent")
                                names = record["architecture"]["trainable_names"] if stage == "architecture" else record["eligible_mask"]
                                count = record["architecture"]["parameters"] if stage == "architecture" else record["eligible_parameters"]
                                if sum(size(state[n]) for n in names) != count:
                                    raise ValueError("actual state parameter count does not match declared mask")
                                if stage == "architecture" and not 238 <= count <= 322:
                                    raise ValueError("architecture parameter band violated")
                            if stage == "boundary" and status in ("no_update", "reference"):
                                if any(v != 0 for v in arm["selected_probability"]):
                                    raise ValueError("NoUpdate changed never-reset policy")
                        else:
                            values = arm.get("sample_squared_errors", arm.get("measured_returns"))
                            metric = arm.get("mse", arm.get("mean_full_return"))
                            if (not isinstance(values, list) or len(values) != cfg["final"]
                                    or not all(finite(v) for v in values) or not finite(metric)
                                    or not math.isclose(sum(values) / len(values), metric, rel_tol=1e-9, abs_tol=1e-10)):
                                raise ValueError("incomplete/nonfinite/inconsistent final metric")
                            if stage != "boundary":
                                if len(arm["prediction"]) != len(values) or len(arm["target"]) != len(values) or len(set(arm["ids"])) != len(values):
                                    raise ValueError("incomplete prediction/target/ID arrays")
                                if any(not finite(a) or not finite(b) or not math.isclose((a-b)**2, e, rel_tol=1e-9, abs_tol=1e-10)
                                       for a, b, e in zip(arm["prediction"], arm["target"], values)):
                                    raise ValueError("squared errors do not match predictions and targets")
                                data_key = (task, seed, split)
                                signature = (arm["data_sha256"], arm["ids"], arm["target"])
                                if data_key in seen_data and seen_data[data_key] != signature:
                                    raise ValueError("paired methods did not receive identical final data")
                                seen_data[data_key] = signature
                        passed += 1
                    except (KeyError, TypeError, ValueError) as error:
                        defects.append(f"{label}: {error}")
    if phase == "final" and len(used_rows) != len(final_rows):
        defects.append("unplanned or duplicate final rows were not part of the frozen grid")
    return {"integrity_ok": not defects, "passed": not defects and unavailable == 0,
            "receipt_sha256": receipt_digest,
            "valid_cells": passed, "unavailable_cells": unavailable, "defects": defects, "ledger": ledger}


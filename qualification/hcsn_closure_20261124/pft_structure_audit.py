"""Read saved HCSN evidence without training, model loading, or test selection.

The independent scalar reconstruction uses only the standard library. Hash
verification binds bytes; it does not replay physical dynamics or authenticate
the original experiment's authorization. Existing evidence is never modified.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import time


EXPECTED = {"main": 63, "baselines": 27, "joint": 9, "communication": 21}
LIMIT = 64 * 1024 * 1024


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def identity(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def read(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        raw = handle.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("JSON exceeds bounded audit size")

    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, parse_constant=constant)


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("evidence path escapes declared study root")
    return path


def reconstruct(logits, payload):
    labels, sources, late = (payload[key] for key in ("labels", "source", "late_step"))
    count, ticks = len(labels), len(logits)
    if (
        not count
        or ticks < 2
        or len(sources) != count
        or len(late) != count
        or any(type(y) is not int or y not in (0, 1) for y in labels)
        or any(type(t) is not int or not 1 <= t < ticks for t in late)
    ):
        raise ValueError("invalid labels, source roster or causal late indices")
    if (
        len(payload["ids"]) != count
        or len(set(payload["ids"])) != count
        or any(len(row) != count for row in logits)
    ):
        raise ValueError("prediction IDs or time/batch shape mismatch")
    probabilities, predictions = [], []
    for frame in logits:
        probs, pred = [], []
        for pair in frame:
            if len(pair) != 2 or not all(math.isfinite(v) for v in pair):
                raise ValueError("finite two-class logits required")
            maximum = max(pair)
            values = [math.exp(v - maximum) for v in pair]
            probs.append(values[1] / sum(values))
            pred.append(int(pair[1] > pair[0]))  # argmax chooses class zero on ties.
        probabilities.append(probs)
        predictions.append(pred)
    correct = [int(predictions[-1][i] == y) for i, y in enumerate(labels)]
    by_source = defaultdict(list)
    for source, hit in zip(sources, correct):
        by_source[str(source)].append(hit)
    stopping = [
        next(
            t
            for t in range(ticks)
            if t == ticks - 1
            or max(probabilities[t][i], 1 - probabilities[t][i]) >= 0.8
        )
        for i in range(count)
    ]
    stopped = [int(predictions[t][i] == labels[i]) for i, t in enumerate(stopping)]
    losses = []
    for pair, label in zip(logits[-1], labels):
        maximum = max(pair)
        losses.append(
            math.log(sum(math.exp(v - maximum) for v in pair)) + (maximum - pair[label])
        )
    result = {
        "accuracy": statistics.mean(correct),
        "brier": statistics.mean(
            2 * (p - y) ** 2 for p, y in zip(probabilities[-1], labels)
        ),
        "cross_entropy": statistics.mean(losses),
        "early_accuracy": statistics.mean(
            predictions[0][i] == y for i, y in enumerate(labels)
        ),
        "pre_late_accuracy": statistics.mean(
            predictions[late[i] - 1][i] == y for i, y in enumerate(labels)
        ),
        "stop_accuracy": statistics.mean(stopped),
        "mean_stop_step": statistics.mean(stopping),
        "stopping_utility": statistics.mean(
            hit - 0.04 * t / (ticks - 1) for hit, t in zip(stopped, stopping)
        ),
        "stop_before_late_fraction": statistics.mean(
            t < arrival for t, arrival in zip(stopping, late)
        ),
        "source_accuracy": {
            key: statistics.mean(value) for key, value in by_source.items()
        },
        "examples": count,
        "sources": len(by_source),
    }
    result["worst_source_accuracy"] = min(result["source_accuracy"].values())
    return result


def metric_error(actual, reported):
    errors = []
    for key, value in actual.items():
        if key not in reported:
            raise ValueError("reported metric is missing: " + key)
        if isinstance(value, dict):
            if set(value) != set(reported[key]):
                raise ValueError("reported source roster mismatch")
            errors.extend(abs(x - reported[key][name]) for name, x in value.items())
        else:
            errors.append(abs(value - reported[key]))
    if not all(math.isfinite(v) for v in errors):
        raise ValueError("nonfinite metric discrepancy")
    return max(errors, default=0.0)


def receipts(directory):
    names = (
        "parent_cost.json",
        "test_parent_cost.json",
        "worker_cost.json",
        "test_worker_cost.json",
        "fit_launch_cost.json",
        "test_launch_cost.json",
        "fit_worker_cost.json",
    )
    return {
        name: {"sha256": digest(directory / name), "record": read(directory / name)}
        for name in names
        if (directory / name).is_file()
    }


def audit_slot(root, protocol, slot, sealed_files):
    directory = inside(root, slot["id"])
    for name, expected in sealed_files.items():
        if digest(inside(directory, name)) != expected:
            raise ValueError("sealed bytes changed: " + name)
    if not {"result.json", "history.json"}.issubset(sealed_files):
        raise ValueError("seal does not bind training result and selection history")
    result = read(directory / "result.json")
    if (
        result["slot"] != slot
        or result["protocol_sha256"] != identity(protocol)
        or result.get("smoke") is not False
        or result["status"] not in ("completed", "censored_cpu", "failed")
    ):
        raise ValueError("training record identity/status mismatch")
    costs = receipts(directory)
    for names, expected in (
        (("worker_cost.json", "fit_worker_cost.json"), result["status"]),
        (("parent_cost.json", "fit_launch_cost.json"), None),
    ):
        available = [name for name in names if name in costs and name in sealed_files]
        if len(available) != 1:
            raise ValueError("one sealed worker and one launcher receipt required")
        record = costs[available[0]]["record"]
        if (
            record.get("error") is not None
            or record.get("timed_out", False)
            or (expected is not None and record["status"] != expected)
            or (
                expected is None
                and record["returncode"] != (1 if result["status"] == "failed" else 0)
            )
        ):
            raise ValueError("training process status differs from result")
    row = {
        "slot": slot,
        "training_status": result["status"],
        "updates": result["updates"],
        "selected_step": result["selected_step"],
        "parameters": result.get("parameter_accounting"),
        "train_data_sha256": result.get("train_data_sha256"),
        "dev_data_sha256": result.get("dev_data_sha256"),
        "cost_receipts": costs,
        "test_status": "missing",
        "metrics": {},
        "complete_equal_update_fit": result["status"] == "completed"
        and result["updates"] == protocol["training"]["max_updates"],
    }
    checkpoint = result.get("checkpoint_sha256")
    if result["status"] != "failed" and checkpoint is None:
        raise ValueError("successful/censored training lacks a sealed checkpoint")
    if checkpoint is not None and (
        sealed_files.get("checkpoint.pt") != checkpoint
        or digest(directory / "checkpoint.pt") != checkpoint
    ):
        raise ValueError("checkpoint is not bound to training result and seal")
    tested = read(directory / "test_result.json")
    if tested["slot"] != slot:
        raise ValueError("test slot differs from frozen roster")
    row["test_status"] = tested["status"]
    test_worker = costs.get("test_worker_cost.json", {}).get("record", {})
    launchers = [
        costs[name]["record"]
        for name in ("test_parent_cost.json", "test_launch_cost.json")
        if name in costs
    ]
    if (
        test_worker.get("status") != tested["status"]
        or test_worker.get("error") is not None
        or len(launchers) != 1
        or launchers[0].get("returncode") != 0
        or launchers[0].get("error") is not None
        or launchers[0].get("timed_out", False)
    ):
        raise ValueError("missing/failed terminal test worker or launcher receipt")
    if tested["status"] == "unavailable":
        if result["status"] != "failed":
            raise ValueError("unavailable test lacks failed training record")
        row["failure"] = result.get("error")
        return row
    if tested["status"] != "evaluated" or result["status"] == "failed":
        raise ValueError("inconsistent training/test status")
    path = directory / "test_predictions.json.gz"
    if digest(path) != tested["predictions_sha256"]:
        raise ValueError("test prediction digest mismatch")
    payload = read(path)
    if (
        payload["slot"] != slot
        or payload["protocol_sha256"] != identity(protocol)
        or payload["data_sha256"] != tested["data_sha256"]
    ):
        raise ValueError("raw prediction identity differs from test result")
    if set(payload["source"]) != set(protocol["data"]["test_sources"]):
        raise ValueError("test source identities differ from protocol")
    if set(Counter(payload["source"]).values()) != {
        protocol["data"]["test_per_source"]
    }:
        raise ValueError("incomplete per-source prediction roster")
    if set(payload["prefix_logits"]) != {"selected", "initial", "cpu_prefix"}:
        raise ValueError("unexpected evaluated checkpoint roster")
    error = 0.0
    for name, logits in payload["prefix_logits"].items():
        if len(logits) != protocol["data"]["length"]:
            raise ValueError("prediction clock differs from protocol")
        score = reconstruct(logits, payload)
        error = max(error, metric_error(score, tested["metrics"][name]))
        row["metrics"][name] = score
    if error > 1e-10:
        raise ValueError("raw metric reconstruction exceeds tolerance: " + str(error))
    limits = protocol["validation"]
    selected, initial = row["metrics"]["selected"], row["metrics"]["initial"]
    passed = (
        selected["accuracy"] >= limits["min_final_accuracy"]
        and selected["accuracy"] - initial["accuracy"]
        >= limits["min_gain_over_initial"]
        and selected["accuracy"] - selected["pre_late_accuracy"]
        >= limits["min_gain_over_prelate"]
    )
    if passed != tested["learning_gate"]:
        raise ValueError("saved learning gate differs from independent reconstruction")
    row.update(
        learning_gate=passed,
        max_metric_error=error,
        predictions_sha256=digest(path),
        test_data_sha256=payload["data_sha256"],
        physical_mass_error_reported=tested["metrics"]["selected"].get(
            "max_probability_balance_error"
        ),
    )
    return row


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        slot = row["slot"]
        key = "/".join(
            str(slot.get(k, "-"))
            for k in (
                "kind",
                "neurons",
                "reference_neurons",
                "boundary",
                "features",
                "precision",
                "variant",
                "arm",
            )
        )
        groups[key].append(row)
    result = {}
    for key, members in groups.items():
        valid = [r for r in members if r.get("metrics")]
        metrics = {}
        for name in (
            "accuracy",
            "brier",
            "cross_entropy",
            "pre_late_accuracy",
            "worst_source_accuracy",
        ):
            values = [r["metrics"]["selected"][name] for r in valid]
            metrics[name] = {
                "values": values,
                "mean": statistics.mean(values) if values else None,
                "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
            }
        launch_costs = {}
        for phase, names in (
            ("fit", ("parent_cost.json", "fit_launch_cost.json")),
            ("test", ("test_parent_cost.json", "test_launch_cost.json")),
        ):
            launch_costs[phase] = [
                next(
                    (
                        r["cost_receipts"][name]["record"].get(
                            "launch_through_exit_wall_seconds",
                            r["cost_receipts"][name]["record"].get(
                                "launch_to_exit_wall_seconds"
                            ),
                        )
                        for name in names
                        if name in r.get("cost_receipts", {})
                    ),
                    None,
                )
                for r in members
            ]
        result[key] = {
            "declared_denominator": len(members),
            "audited_evaluations": len(valid),
            "learning_gate_count": sum(r.get("learning_gate", False) for r in members),
            "complete_equal_update_fits": sum(
                r.get("complete_equal_update_fit", False) for r in members
            ),
            "seeds": [r["slot"]["seed"] for r in members],
            "metrics": metrics,
            "parameters_by_seed": [r.get("parameters") for r in members],
            "selected_steps": [r.get("selected_step") for r in members],
            "complete_launch_wall_seconds_by_seed": launch_costs,
        }
    return result


def audit_study(root, expected_slots):
    root = Path(root).resolve()
    protocol, seal = read(root / "PROTOCOL.json"), read(root / "SEAL.json")
    slots = protocol["slots"]
    identifiers = [slot["id"] for slot in slots]
    if (
        len(slots) != expected_slots
        or len(set(identifiers)) != len(slots)
        or set(seal["attempts"]) != set(identifiers)
        or seal["protocol_sha256"] != identity(protocol)
    ):
        raise ValueError("incomplete/duplicate study roster or changed protocol")
    split_sources = [
        set(protocol["data"][name + "_sources"]) for name in ("train", "dev", "test")
    ]
    if any(split_sources[a] & split_sources[b] for a, b in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("source identity overlap across train/dev/test")
    claim = read(root / "TEST_CLAIM.json")
    if claim != {
        "seal_sha256": digest(root / "SEAL.json"),
        "protocol_sha256": identity(protocol),
    }:
        raise ValueError("test claim does not bind full frozen seal")
    rows = []
    for slot in slots:
        try:
            rows.append(audit_slot(root, protocol, slot, seal["attempts"][slot["id"]]))
        except (OSError, KeyError, TypeError, ValueError) as error:
            rows.append(
                {"slot": slot, "audit_error": str(error), "test_status": "unverified"}
            )
    stages = {
        name: {"sha256": digest(root / name), "record": read(root / name)}
        for name in (
            "FIT_EXECUTION.json",
            "TEST_EXECUTION.json",
            "CAMPAIGN_RECEIPT.json",
            "OUTER_RECEIPT.json",
            "EXECUTION.json",
            "JOINT_TEST_SEAL.json",
            "CAMPAIGN_TERMINAL.json",
        )
        if (root / name).is_file()
    }
    return {
        "root": str(root),
        "protocol_sha256": identity(protocol),
        "seal_sha256": digest(root / "SEAL.json"),
        "declared_slots": expected_slots,
        "audit_errors": sum("audit_error" in row for row in rows),
        "status_counts": dict(Counter(row["test_status"] for row in rows)),
        "groups": summarize(rows),
        "training_policy": protocol["training"],
        "data_policy": protocol["data"],
        "source_hashes": protocol.get("source_hashes", protocol.get("implementation")),
        "stage_receipts": stages,
        "rows": rows,
    }


def comparisons(studies):
    result = {
        "main_features": {
            "matched": [
                "allocated state",
                "readout dimension",
                "signed message channel",
                "data and update policy",
            ],
            "unmatched": [
                "nonlinear feature map and arithmetic",
                "functional capacity unproved",
            ],
            "meaning": "within signed HCSN; tanh is not a conventional recurrent network",
        },
        "main_boundaries": {
            "matched": [
                "physical state dimension",
                "message channel",
                "data and update policy",
            ],
            "unmatched": [
                "learned boundary adds N trainable scalars",
                "fixed/QVI/learned policy restrictions",
            ],
        },
        "joint": {
            "matched": [
                "allocated tensors and physical state",
                "QVI/value-risk",
                "unsigned disabled",
            ],
            "unmatched": [
                "joint doubles active recurrent entries relative to a single channel"
            ],
        },
        "communication": {
            "matched": ["N32 physical kernel and task family"],
            "unmatched": [
                "unsigned adds active weights",
                "accumulate/hold adds input memory",
                "observer cost included",
            ],
        },
        "baseline": {
            "matched": ["approximately matched parameter count"],
            "unmatched": [
                "zero versus random physical initial state",
                "architecture/state/dtype/arithmetic",
                "different persistent KV growth",
            ],
        },
    }
    if "main" in studies and "baselines" in studies:
        left, right = studies["main"], studies["baselines"]
        fields = ("train_data_sha256", "dev_data_sha256", "test_data_sha256")
        result["baseline"]["observed_data_identity"] = {
            field: sorted({r.get(field) for r in left["rows"] if r.get(field)})
            == sorted({r.get(field) for r in right["rows"] if r.get(field)})
            and bool({r.get(field) for r in left["rows"] if r.get(field)})
            for field in fields
        }
        result["baseline"]["identical_training_policy"] = (
            left["training_policy"] == right["training_policy"]
        )
        joint = (
            right["stage_receipts"].get("JOINT_TEST_SEAL.json", {}).get("record", {})
        )
        result["baseline"]["joint_main_seal_matches_supplied_original"] = (
            joint.get("main_seal_sha256") == left["seal_sha256"]
        )
    result["all"] = {
        "selected_model": "development-selected checkpoint; fixed last-update test is absent",
        "cost": "stage wall, summed child CPU, individual launch wall and nested body costs are distinct; never sum nested scopes",
        "sources": "independent synthetic source identities in one generator family; no real user adoption",
        "statistics": "all declared seeds remain denominators; sample SD is not a confidence interval",
    }
    return result


def circuit_plan():
    return {
        "scope": "existing E4 Circuit question",
        "full_confirmation_admission": "BLOCKED",
        "reason": "Freezing recurrent weights changes the editable parameter domain. Learning topology adds structure-selection freedom. The current studies do not supply a matched-capacity complete Circuit comparison.",
        "required_controls": [
            "learned",
            "fixed",
            "random",
            "single_equal_budget",
            "edge_deleted",
            "message_shuffled",
        ],
        "required_equalities": [
            "training data and source split",
            "editable parameter domain",
            "active parameter count",
            "persistent state capacity",
            "training/validation/communication resource vector",
        ],
        "minimal_causal_followup": {
            "arms": [
                "unchanged frozen candidate",
                "cross-cell edges zeroed",
                "within-role messages permuted",
            ],
            "purpose": "necessity of the existing learned communication on new sources",
            "limitation": "causal interventions, not equal-training-budget learned-versus-fixed superiority",
            "selection": "all prespecified parents and all failures; no test-driven parent selection",
            "run_in_this_module": False,
        },
        "new_training_launched": False,
        "old_experiments_reexecuted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "circuit-plan"))
    parser.add_argument("--input", action="append", default=[], metavar="NAME=ROOT")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start, cpu = time.perf_counter(), time.process_time()
    if args.output.exists():
        raise FileExistsError("audit output is create-only")
    studies, errors, input_roots = {}, {}, []
    for value in args.input:
        name, root = value.split("=", 1)
        if name not in EXPECTED or name in studies or name in errors:
            raise ValueError("unique known study name required")
        input_roots.append(Path(root).resolve())
        try:
            studies[name] = audit_study(root, EXPECTED[name])
        except (OSError, KeyError, TypeError, ValueError) as error:
            errors[name] = str(error)
    if any(args.output.resolve().is_relative_to(root) for root in input_roots):
        raise ValueError("audit output must be outside every original evidence root")
    if args.action == "audit" and not args.input:
        raise ValueError("at least one original evidence root required")
    result = {
        "schema": "hepta.pft.structure-audit.v1",
        "module_sha256": digest(__file__),
        "studies": studies,
        "study_errors": errors,
        "comparisons": comparisons(studies),
        "circuit_confirmation": circuit_plan(),
        "audit_cpu_seconds": time.process_time() - cpu,
        "audit_wall_seconds": time.perf_counter() - start,
        "verification_scope": "saved byte bindings and independently reconstructed metrics; no checkpoint deserialization, new data construction, training, physical replay, or proof of source execution",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    failures = len(errors) + sum(s["audit_errors"] for s in studies.values())
    print(
        json.dumps(
            {
                "output": str(args.output),
                "studies": len(studies),
                "audit_errors": failures,
                "full_circuit_confirmation": "BLOCKED",
                "new_training": False,
            }
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

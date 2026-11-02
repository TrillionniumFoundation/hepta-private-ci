"""Independent artifact/record audit; no candidate selection or model fitting.

Run only after the experiment's frozen confirmation run. This script reads
recorded outcomes; it never generates a test set or reruns a trained policy.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
REQUIRED = ("prediction", "read_count", "fee", "utility", "labels", "group",
            "ids", "elapsed", "dt", "prob")
ORDINARY = "ordinary_distribution"
ANALYTICAL = "analytic_distribution"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state_hash(state):
    result = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        array = tensor.detach().cpu().contiguous().numpy()
        result.update(name.encode())
        result.update(str((array.shape, array.dtype.str)).encode())
        result.update(array.tobytes())
    return result.hexdigest()


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes its declared root: " + relative)
    return path


class Audit:
    def __init__(self):
        self.checks = 0
        self.failures = []
        self.notes = []

    def require(self, condition, name, detail=None):
        self.checks += 1
        if not bool(condition):
            row = {"check": name}
            if detail is not None:
                row["detail"] = detail
            self.failures.append(row)
        return bool(condition)

    def close(self, actual, expected, name, tolerance=3e-6):
        actual, expected = np.asarray(actual), np.asarray(expected)
        if actual.shape != expected.shape:
            return self.require(False, name, {"actual_shape": list(actual.shape),
                                              "expected_shape": list(expected.shape)})
        error = float(np.max(np.abs(actual - expected))) if actual.size else 0.0
        return self.require(np.isfinite(error) and error <= tolerance, name,
                            {"maximum_absolute_error": error, "tolerance": tolerance})


def check_arrays(audit, data, row, fees):
    """Reconstruct outcome and acquisition arithmetic without experiment code."""
    tag = "/".join(str(row[k]) for k in
                   ("task", "seed", "family", "train_mode", "exec_mode", "domain"))
    if not audit.require(all(k in data for k in REQUIRED), tag + ":required_arrays"):
        return False
    n = len(data["labels"])
    if not audit.require(n > 0 and data["dt"].ndim == 2, tag + ":nonempty_time_grid"):
        return False
    length = data["dt"].shape[1]
    shape_ok = all(data[k].shape == (n,) for k in REQUIRED if k not in ("dt", "prob"))
    shape_ok &= data["dt"].shape[0] == n and data["prob"].ndim == 2 and data["prob"].shape[0] == n
    if not audit.require(shape_ok, tag + ":record_shapes"):
        return False
    finite = all(np.isfinite(data[k]).all() for k in REQUIRED)
    if not audit.require(finite, tag + ":finite_records"):
        return False
    integer_keys = ("prediction", "read_count", "labels", "ids", "group")
    integer_ok = all(np.issubdtype(data[k].dtype, np.integer) for k in integer_keys)
    if not audit.require(integer_ok, tag + ":integer_identifiers_actions"):
        return False
    audit.require(len(np.unique(data["ids"])) == n, tag + ":unique_object_ids")
    reads = data["read_count"]
    legal = (reads >= 0).all() and (reads <= length).all() and (data["dt"] >= 0).all()
    if not audit.require(legal, tag + ":legal_reads_and_time"):
        return False
    time = np.c_[np.zeros(n), np.cumsum(data["dt"].astype(np.float64), axis=1)]
    elapsed = time[np.arange(n), reads]
    expected_fee = fees[0] * reads + fees[1] * elapsed
    correct = (data["prediction"] == data["labels"]).astype(np.float64)
    audit.close(data["elapsed"], elapsed, tag + ":elapsed_from_paid_prefix")
    audit.close(data["fee"], expected_fee, tag + ":all_actual_fees")
    audit.close(data["utility"], correct - expected_fee, tag + ":actual_utility")
    audit.require((data["prob"] >= 0).all() and (data["prob"] <= 1).all(), tag + ":probability_range")
    audit.close(data["prob"].sum(1), np.ones(n), tag + ":probability_sum")
    audit.require(np.array_equal(data["prediction"], data["prob"].argmax(1)), tag + ":prediction_from_actual_probabilities")
    if row["exec_mode"] == "light":
        audit.require(np.all(reads == length), tag + ":light_reads_all")
    if np.any(reads == 0):
        audit.close(data["fee"][reads == 0], np.zeros(int(np.sum(reads == 0))), tag + ":initial_stop_has_zero_acquisition_fee")
        audit.close(data["prob"][reads == 0], np.broadcast_to(data["prob"][reads == 0][0], data["prob"][reads == 0].shape),
                    tag + ":initial_stop_has_no_object_payload")
    return True


def check_training(audit, run, protocol):
    import torch

    index = json.loads((run / "TRAINING_INDEX.json").read_text())
    groups = index["groups"] if isinstance(index, dict) else index
    table, paths = {}, []
    families = set(protocol["families"])
    for entry in groups:
        key = (entry["task"], entry["seed"], entry["train_mode"])
        tag = "training/" + "/".join(map(str, key))
        audit.require(key not in table, tag + ":unique_group")
        table[key] = entry
        path = contained(run, entry["checkpoint_path"])
        paths.append(str(path))
        audit.require(path.is_file(), tag + ":checkpoint_present")
        if not path.is_file():
            continue
        audit.require(sha(path) == entry["checkpoint_sha256"], tag + ":checkpoint_identity")
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        audit.require(set(checkpoint["models"]) == families, tag + ":all_model_families")
        audit.require(set(entry["initial_hashes"]) == families and set(entry["model_hashes"]) == families,
                      tag + ":complete_initial_final_identities")
        audit.require(entry["training_cpu_seconds"] > 0, tag + ":actual_training_cpu_recorded")
        audit.require(int(entry["selected_step"]) >= 0, tag + ":legal_selected_step")
        if "updates" in entry:
            audit.require(entry["updates"] == protocol["updates"], tag + ":registered_update_budget")
        for family in families:
            config = checkpoint["models"][family]["config"]
            audit.require(config["family"] == family and config["task"] == entry["task"],
                          tag + ":model_config_identity/" + family)
            state = checkpoint["models"][family]["state"]
            audit.require(state_hash(state) == entry["model_hashes"][family], tag + ":model_state_identity/" + family)
        if entry["train_mode"] == "value":
            audit.require(state_hash(checkpoint["controller"]) == entry["controller_hash"], tag + ":shared_controller_identity")
        else:
            audit.require(entry["controller_hash"] is None, tag + ":light_has_no_trained_value_controller")
        p, s = entry.get("parameters", {}), entry.get("state_scalar_count", {})
        audit.require(ORDINARY in p and ANALYTICAL in p and p[ORDINARY] == p[ANALYTICAL], tag + ":matched_active_parameters")
        audit.require(ORDINARY in s and ANALYTICAL in s and s[ORDINARY] == s[ANALYTICAL], tag + ":matched_dynamic_state_capacity")
    expected = set(itertools.product(protocol["tasks"], protocol["seeds"], ("light", "value")))
    audit.require(set(table) == expected, "training:registered_group_coverage",
                  {"expected": len(expected), "actual": len(table)})
    audit.require(len(paths) == len(set(paths)), "training:separate_checkpoint_paths")
    for task, seed in itertools.product(protocol["tasks"], protocol["seeds"]):
        light, value = table.get((task, seed, "light")), table.get((task, seed, "value"))
        if light is None or value is None:
            continue
        audit.require(light["initial_hashes"] == value["initial_hashes"], f"training:{task}/{seed}:paired_initialization")
        same = [name for name in families if light["model_hashes"][name] == value["model_hashes"][name]]
        if same:
            audit.notes.append({"same_selected_state_across_independent_training": same, "task": task, "seed": seed})
    return table


def audit_run(run):
    run = Path(run).resolve()
    audit = Audit()
    protocol = json.loads((run / "PROTOCOL.json").read_text())
    frozen = json.loads((run / "SOURCE_FREEZE.json").read_text())
    audit.require(sha(run / "PROTOCOL.json") == frozen["protocol_sha256"], "freeze:protocol_identity")
    audit.require(bool(frozen["files"]), "freeze:nonempty_source_inventory")
    for relative, digest in frozen["files"].items():
        path = contained(REPO, relative)
        audit.require(path.is_file() and sha(path) == digest, "freeze:source_identity/" + relative)
    audit.require(frozen.get("heldout_opened") is False, "freeze:declares_no_heldout_access_at_freeze")
    context_manifest = run / "TRAINING_DATA_CONTEXTS.json"
    audit.require(sha(context_manifest) == frozen.get("training_data_contexts_sha256"),
                  "freeze:training_context_manifest_identity")
    contexts = json.loads(context_manifest.read_text())
    for task in protocol["tasks"]:
        for first, second in itertools.combinations(("train", "val", "development"), 2):
            for field in ("context_ids", "partition_ids"):
                audit.require(not (set(contexts[task][first][field]) & set(contexts[task][second][field])),
                              f"data:{task}/{field}:{first}_{second}_disjoint")
    audit.notes.append("Freeze declaration/hash verification is not a proof of access chronology; retain execution receipts.")
    training = check_training(audit, run, protocol)
    index = json.loads((run / "EVALUATION_INDEX.json").read_text())
    rows = index["records"] if isinstance(index, dict) else index
    fee_config = protocol.get("fees", {})
    fees = (float(fee_config.get("read", protocol.get("read_fee"))),
            float(fee_config.get("time", protocol.get("time_fee"))))
    records, identity, summaries, flow_identity, posterior_failures = {}, {}, [], {}, []
    for row in rows:
        key = tuple(row[k] for k in ("task", "seed", "family", "train_mode", "exec_mode", "domain"))
        audit.require(key not in records, "evaluation:unique_condition/" + str(key))
        path = contained(run, row["path"])
        if not audit.require(path.is_file(), "evaluation:record_present/" + row["path"]):
            continue
        audit.require(sha(path) == row["sha256"], "evaluation:record_identity/" + row["path"])
        with np.load(path, allow_pickle=False) as archive:
            data = {name: archive[name] for name in archive.files}
        if not check_arrays(audit, data, row, fees):
            continue
        if row["family"] in (ORDINARY, ANALYTICAL):
            trace_names = ("upper_loss_prefix", "mass_error_prefix", "minimum_probability_prefix")
            shape = (len(data["ids"]), data["dt"].shape[1] + 1)
            trace_ok = all(name in data and data[name].shape == shape and
                           np.isfinite(data[name]).all() for name in trace_names)
            audit.require(trace_ok, "posterior:complete_finite_prefix_traces/" + str(key))
            if trace_ok:
                upper, mass_error, minimum = (data[name] for name in trace_names)
                occupied = np.arange(shape[1])[None] <= data["read_count"][:, None]
                actual = dict(all_prefix_maximum_upper_loss=float(upper.max()),
                              occupied_maximum_upper_loss=float(upper[occupied].max()),
                              maximum_mass_error=float(mass_error.max()),
                              minimum_probability=float(minimum.min()),
                              all_prefix_upper_loss_pass=bool(upper.max() <= 1e-7))
                declared = row.get("posterior_qualification", {})
                audit.require(set(actual).issubset(declared), "posterior:declared_statistics_present/" + str(key))
                for name in actual:
                    if name in declared:
                        if isinstance(actual[name], bool):
                            audit.require(declared[name] == actual[name], "posterior:reported_gate/" + str(key))
                        else:
                            audit.close(declared[name], actual[name], "posterior:statistic/" + str(key) + "/" + name, 1e-14)
                audit.require(upper.min() >= -1e-12 and upper.max() <= 1 + 1e-9 and
                              mass_error.min() >= 0 and minimum.min() >= -1e-12,
                              "posterior:legal_mass_trace/" + str(key))
                audit.require(np.diff(upper, axis=1).min() >= -1e-12,
                              "posterior:cemetery_mass_is_not_silently_removed/" + str(key))
                flow_key = (row["task"], row["seed"], row["family"], row["train_mode"], row["domain"])
                if flow_key in flow_identity:
                    for name in trace_names:
                        audit.close(data[name], flow_identity[flow_key][name],
                                    "posterior:same_weights_same_full_prefix_flow/" + str(key) + "/" + name, 1e-12)
                else:
                    flow_identity[flow_key] = {name: data[name] for name in trace_names}
                if not actual["all_prefix_upper_loss_pass"]:
                    posterior_failures.append({"condition": list(key), **actual})
        fields = ("context_ids", "partition_ids")
        has_context = all(field in data and data[field].shape == data["ids"].shape for field in fields)
        audit.require(has_context, "evaluation:complete_context_identity/" + str(key))
        if has_context:
            for field in fields:
                unseen = set(data[field].tolist())
                for split in ("train", "val", "development"):
                    audit.require(not unseen.intersection(contexts[row["task"]][split][field]),
                                  f"evaluation:{key}:{field}_unseen_in_{split}")
            buckets = np.array([int(value[:16], 16) % 20 for value in data["partition_ids"]])
            audit.require(np.all((buckets >= 13) & (buckets < 18)), "evaluation:registered_test_partition/" + str(key))
        training_key = (row["task"], row["seed"], row["train_mode"])
        entry = training.get(training_key)
        if audit.require(entry is not None, "evaluation:has_frozen_training_group/" + str(key)):
            audit.require(row["model_hash"] == entry["model_hashes"][row["family"]], "evaluation:uses_selected_model/" + str(key))
            expected_controller = entry["controller_hash"] if row["exec_mode"] == "value" else None
            audit.require(row["controller_hash"] == expected_controller, "evaluation:uses_shared_selected_controller/" + str(key))
        data_key = (row["task"], row["seed"], row["domain"])
        if data_key in identity:
            for field in ("labels", "ids", "group", "dt") + (fields if has_context else ()):
                audit.require(np.array_equal(data[field], identity[data_key][field]), "evaluation:paired_inputs/" + str(key) + "/" + field)
        else:
            identity[data_key] = {field: data[field] for field in ("labels", "ids", "group", "dt") + (fields if has_context else ())}
        records[key] = data
        groups = np.unique(data["group"])
        group_utility = [float(data["utility"][data["group"] == group].mean()) for group in groups]
        summaries.append({**{k: row[k] for k in ("task", "seed", "family", "train_mode", "exec_mode", "domain")},
                          "objects": len(data["ids"]), "contexts": len(groups),
                          "partition_units": len(np.unique(data["partition_ids"])) if has_context else None,
                          "utility": float(data["utility"].mean()), "context_mean_utility": float(np.mean(group_utility)),
                          "accuracy": float((data["prediction"] == data["labels"]).mean()),
                          "fee": float(data["fee"].mean()), "reads": float(data["read_count"].mean())})
    expected = set()
    for task, seed, family in itertools.product(protocol["tasks"], protocol["seeds"], protocol["families"]):
        for domain, (train, execute) in itertools.product(protocol["domains"][task], (("light", "light"), ("value", "value"), ("value", "light"))):
            expected.add((task, seed, family, train, execute, domain))
    audit.require(expected.issubset(records), "evaluation:all_registered_conditions",
                  {"expected": len(expected), "actual": len(records), "missing": [list(x) for x in sorted(expected - set(records))][:30]})
    effects = []
    for task, seed in itertools.product(protocol["tasks"], protocol["seeds"]):
        for domain in protocol["domains"][task]:
            keys = [(task, seed, family, train, execute, domain) for family, train, execute in
                    ((ORDINARY, "light", "light"), (ORDINARY, "value", "value"),
                     (ANALYTICAL, "light", "light"), (ANALYTICAL, "value", "value"),
                     (ORDINARY, "value", "light"), (ANALYTICAL, "value", "light"))]
            if not all(key in records for key in keys):
                continue
            a, b, c, d, av, cv = [records[key]["utility"].astype(np.float64) for key in keys]
            values = {"B-A": b-a, "D-C": d-c, "C-A": c-a, "D-B": d-b,
                      "interaction": (d-c)-(b-a), "value_weight_B-A": b-av,
                      "value_weight_D-C": d-cv, "value_weight_interaction": (d-cv)-(b-av)}
            effects.append({"task": task, "seed": seed, "domain": domain,
                            "total_effects": {name: float(value.mean()) for name, value in values.items() if not name.startswith("value_weight")},
                            "conditional_execution_effects": {name: float(value.mean()) for name, value in values.items() if name.startswith("value_weight")}})
    return {"schema": "hcsn-r15.independent-audit.v1", "run": str(run),
            "passed": not audit.failures, "checks": audit.checks, "failures": audit.failures,
            "notes": audit.notes, "conditions": summaries, "recomputed_effects": effects,
            "posterior_upper_loss_gate_failures": posterior_failures,
            "posterior_scope": "Actual learned finite-law traces and honest reporting only. A small cemetery loss and conserved mass do not establish continuum discretization accuracy for every posterior.",
            "foundation_core_acceptance": False, "all_user_requirements_closed": False,
            "acceptance_boundary": "Arithmetic, coverage and recorded identities only; finite synthetic CPU profile. No GPU, physical-energy, real-service, learned-boundary or general-benefit certification."}


def self_check():
    row = dict(task="binding", seed=1, family=ORDINARY, train_mode="value", exec_mode="value", domain="development_fixture")
    data = dict(prediction=np.array([1, 0]), read_count=np.array([0, 2]),
                labels=np.array([1, 1]), ids=np.arange(2), group=np.arange(2),
                elapsed=np.array([0., 2.]), dt=np.ones((2, 2)),
                fee=np.array([0., .006]), utility=np.array([1., -.006]),
                prob=np.array([[.2, .8], [.7, .3]]))
    audit = Audit()
    check_arrays(audit, data, row, (.0025, .0005))
    if audit.failures:
        raise AssertionError(audit.failures)
    bad = {**data, "fee": data["fee"] + .01}
    rejected = Audit()
    check_arrays(rejected, bad, row, (.0025, .0005))
    if not any("all_actual_fees" in x["check"] for x in rejected.failures):
        raise AssertionError("Fee corruption was not rejected")
    print(json.dumps({"self_check": "passed", "checks": audit.checks,
                      "tampered_fee_rejected": True, "confirmation_data_read": False}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if args.run is None or args.output is None:
        parser.error("--run and --output are required without --self-check")
    result = audit_run(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"],
                      "failures": len(result["failures"]), "output": str(args.output)}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

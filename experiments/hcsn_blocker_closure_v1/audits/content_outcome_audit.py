"""Independent arithmetic audit of preserved HCSN worker summaries.

This deliberately imports no experimental model, training, metrics or analysis
module. Inputs are the exact registered design/protocol, job specifications,
individual RESULT.json objects, RUN wait4 ledgers, selection lock and original
ANALYSIS.json. Prediction tensors are not required; consequently this audit
does not claim an independent tensor replay or model-output recomputation.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import t as student_t


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paired(values):
    values = np.array(values, dtype=np.float64)
    n = len(values)
    mean = float(np.sum(values) / n)
    variance = float(np.sum(np.square(values - mean)) / (n - 1))
    radius = float(student_t.ppf(.975, n - 1)) * (variance / n) ** .5
    sign_means = []
    for bits in itertools.product((0, 1), repeat=n):
        signs = np.array([2 * bit - 1 for bit in bits])
        sign_means.append(float(np.sum(signs * values) / n))
    sign_means = np.array(sign_means)
    return dict(n=n, differences=values.tolist(), mean=mean, sample_sd=variance ** .5,
        ci95=[mean - radius, mean + radius],
        one_sided_sign_flip_p=float(np.mean(sign_means >= mean - 1e-14)),
        two_sided_sign_flip_p=float(np.mean(np.abs(sign_means) >= abs(mean) - 1e-14)))


def holm(rows):
    order = sorted(range(len(rows)), key=lambda i: rows[i]["one_sided_sign_flip_p"])
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(rows) - rank) * rows[index]["one_sided_sign_flip_p"]))
        rows[index]["holm_one_sided_p"] = running


def audit(root, output):
    started = time.process_time()
    source_files, checks, failures = {}, [], []

    def load(relative):
        path = root / relative
        source_files[str(relative)] = dict(bytes=path.stat().st_size, sha256=digest(path))
        return read(path)

    def check(name, passed, actual=None, expected=None):
        row = dict(name=name, passed=bool(passed))
        if not passed or actual is not None:
            row.update(actual=actual, expected=expected)
        checks.append(row)
        if not passed:
            failures.append(row)

    def close(name, actual, expected, tolerance=5e-12):
        a, b = np.asarray(actual), np.asarray(expected)
        passed = a.shape == b.shape and bool(np.isfinite(a).all()) and bool(np.isfinite(b).all())
        passed = passed and bool(np.all(np.abs(a - b) <= tolerance))
        check(name, passed, actual if not passed else None, expected if not passed else None)

    protocol = load(Path("PROTOCOL.json"))
    selection = load(Path("SELECTION_LOCK.json"))
    original = load(Path("ANALYSIS.json"))
    design = protocol["design"]
    check("registered protocol", protocol["status"] == "registered")
    check("original analysis integrity", original["complete"] is True and original["errors"] == [])
    check("selection binds protocol bytes", selection["protocol_sha256"] == source_files["PROTOCOL.json"]["sha256"])
    check("analysis binds protocol and selection", original["protocol_sha256"] == source_files["PROTOCOL.json"]["sha256"]
          and original["selection_lock_sha256"] == source_files["SELECTION_LOCK.json"]["sha256"])
    rows, costs, ledgers, job_counts = {}, {}, {}, {}
    expected_counts = dict(development=76, fixed=304, equal_cpu=64)
    for stage in ("development", "fixed", "equal_cpu"):
        specs = load(Path("jobs_" + stage + ".json"))
        ledger = load(Path("RUN_" + stage + ".json"))
        ledgers[stage] = ledger
        job_counts[stage] = len(specs)
        check(stage + ": expected registered count", len(specs) == expected_counts[stage], len(specs), expected_counts[stage])
        check(stage + ": no failed or omitted attempts", ledger["complete"] and ledger["failed"] == 0
              and len(ledger["jobs"]) == len(specs) and all(row["exit_code"] == 0 for row in ledger["jobs"]))
        check(stage + ": exact ledger membership", sorted(row["id"] for row in ledger["jobs"]) == sorted(row["id"] for row in specs))
        close(stage + ": disjoint child cost sum", ledger["child_cpu_seconds"],
              sum(row["child_cpu_seconds"] for row in ledger["jobs"]), 1e-8)
        for row in ledger["jobs"]:
            costs[stage, row["id"]] = row["child_cpu_seconds"]
        expected = []
        for task in design["tasks"]:
            arms = selection["equal_cpu_arms"][task] if stage == "equal_cpu" else design["arms"]
            for arm in arms:
                seeds = [design["development_seed"]] if stage == "development" else design["formal_seeds"]
                lrs = design["learning_rates"] if stage == "development" else [selection["choices"][task][arm]["learning_rate"]]
                expected += [(task, arm, seed, lr) for seed in seeds for lr in lrs]
        actual = [(job["task"], job["arm"], job["seed"], job["learning_rate"]) for job in specs]
        check(stage + ": full factorial independently reconstructed", sorted(expected) == sorted(actual))
        for job in specs:
            path = Path(stage) / job["id"] / "RESULT.json"
            row = load(path)
            key = stage, job["task"], job["arm"], job["seed"], job["learning_rate"]
            check(str(path) + ": unique complete exact job", key not in rows and row["status"] == "complete" and row["job"] == job)
            rows[key] = row
            check(str(path) + ": source protocol", row["protocol_sha256"] == source_files["PROTOCOL.json"]["sha256"])
            check(str(path) + ": complete child contains training and self CPU", costs[stage, job["id"]] + .001 >=
                  row["complete_process_cpu_seconds"] >= row["training_cpu_seconds"])
            best = min(row["validations"], key=lambda item: (item["cross_entropy"], item["step"]))
            check(str(path) + ": selected minimum validation checkpoint", row["selected"]["step"] == best["step"]
                  and row["selected"]["cross_entropy"] == best["cross_entropy"])
            if stage == "equal_cpu":
                check(str(path) + ": full CPU budget", row["training_cpu_seconds"] >= design["equal_cpu_seconds"])
                close(str(path) + ": reported overrun", row["training_cpu_budget_overrun_seconds"],
                      row["training_cpu_seconds"] - design["equal_cpu_seconds"])
            else:
                check(str(path) + ": exact update budget", row["updates"] == job["updates"])
            if job["arm"].startswith("freeze_"):
                group = job["arm"].removeprefix("freeze_")
                check(str(path) + ": zero frozen update summaries", row["final_update_groups"][group]["nonzero"] == 0
                      and row["selected_update_groups"][group]["nonzero"] == 0)
            if stage != "development":
                check(str(path) + ": exactly ID and OOD reports", set(row["evaluation"]) == {"test", "ood"})
                for split, item in row["evaluation"].items():
                    check(str(path) + ": supervised position count " + split, item["positions"] == design["data_sizes"][split] * 4)
                    close(str(path) + ": accuracy exact count ratio " + split, item["accuracy"], item["correct"] / item["positions"])
    check("all444results retained", len(rows) == 444 == original["valid_results"])

    for task in design["tasks"]:
        scores = {}
        for arm in design["arms"]:
            candidates = [rows["development", task, arm, design["development_seed"], lr] for lr in design["learning_rates"]]
            best = min(candidates, key=lambda row: (row["selected"]["cross_entropy"], row["selected"]["step"], row["job"]["learning_rate"]))
            chosen = selection["choices"][task][arm]
            expected_path = Path("development") / best["job"]["id"] / "RESULT.json"
            check(task + "/" + arm + ": independently selected LR", chosen["learning_rate"] == best["job"]["learning_rate"]
                  and chosen["development_cross_entropy"] == best["selected"]["cross_entropy"]
                  and chosen["result_file"] == expected_path.as_posix()
                  and chosen["result_sha256"] == source_files[str(expected_path)]["sha256"])
            scores[arm] = best["selected"]["cross_entropy"]
        eligible = [arm for arm in design["arms"] if arm.startswith(("value_", "fixed_", "learned_"))]
        expected_arm = min(eligible, key=lambda arm: (scores[arm], arm))
        check(task + ": independently selected equal-CPU family", selection["equal_cpu_arms"][task] ==
              [expected_arm, "two_gates", "transformer", "lif_snn"])

    def result(stage, task, arm, seed):
        return rows[stage, task, arm, seed, selection["choices"][task][arm]["learning_rate"]]

    for task in design["tasks"]:
        for seed in design["formal_seeds"]:
            values = [result("fixed", task, arm, seed) for arm in design["arms"]]
            check(f"{task}/{seed}: paired common initialization", len({row["common_initial_hash"] for row in values}) == 1)
            check(f"{task}/{seed}: paired identical batch stream", len({row["batch_stream_sha256"] for row in values}) == 1)
    counts = [row["counts"]["backbone"] for key, row in rows.items() if key[0] == "fixed" and not key[2].startswith("freeze_")]
    check("all active backbone spread within3%", (max(counts) - min(counts)) / max(counts) <= .03)

    families = {"freeze": ["freeze_content", "freeze_dynamics", "freeze_boundary", "freeze_reset", "freeze_refractory"],
                "boundary": ["fixed_jg", "learned_jg"],
                "channel": ["value_margin", "value_j", "value_g", "value_fh", "value_ordinary"]}
    mechanism = {}
    for family, controls in families.items():
        values = []
        for control in controls:
            differences = {metric: [float(np.mean([
                result("fixed", task, "value_jg", seed)["evaluation"]["test"][metric]
                - result("fixed", task, control, seed)["evaluation"]["test"][metric]
                for task in design["tasks"]])) for seed in design["formal_seeds"]]
                for metric in ("accuracy", "brier", "ece")}
            values.append(dict(control=control, **paired(differences["accuracy"]),
                mean_brier_difference=float(np.mean(differences["brier"])),
                mean_ece_difference=float(np.mean(differences["ece"]))))
        holm(values)
        for row in values:
            row["positive_gate"] = bool(row["mean"] >= .005 and row["ci95"][0] > 0
                and row["holm_one_sided_p"] < .05 and row["mean_brier_difference"] <= .01 and row["mean_ece_difference"] <= .02)
        mechanism[family] = values
    interactions = []
    for boundary in ("fixed", "learned"):
        values = []
        for seed in design["formal_seeds"]:
            tasks = []
            for task in design["tasks"]:
                fetch = lambda arm: result("fixed", task, arm, seed)["evaluation"]["test"]["accuracy"]
                tasks.append(fetch("value_jg") - fetch("value_ordinary") - fetch(boundary + "_jg") + fetch(boundary + "_ordinary"))
            values.append(float(np.mean(tasks)))
        interactions.append(dict(boundary_control=boundary, **paired(values)))
    holm(interactions)
    for row in interactions:
        row["positive_gate"] = bool(row["mean"] >= .005 and row["ci95"][0] > 0 and row["holm_one_sided_p"] < .05)
    mechanism["boundary_channel_interaction"] = interactions
    for family, values in mechanism.items():
        reported = original["mechanism_families"][family]
        check(family + ": exact contrast count", len(values) == len(reported))
        for index, row in enumerate(values):
            other = reported[index]
            for key, value in row.items():
                name = family + "/" + str(index) + "/" + key
                if isinstance(value, (str, bool)):
                    check(name, value == other[key])
                else:
                    close(name, value, other[key])

    external = []
    for task in design["tasks"]:
        selected_arm = selection["equal_cpu_arms"][task][0]
        for split in ("test", "ood"):
            for control in selection["equal_cpu_arms"][task][1:]:
                a = [result("equal_cpu", task, selected_arm, seed) for seed in design["formal_seeds"]]
                b = [result("equal_cpu", task, control, seed) for seed in design["formal_seeds"]]
                paired_rows = list(zip(a, b, strict=True))
                row = dict(task=task, split=split, selected_hcsn=selected_arm, control=control,
                    **paired([x["evaluation"][split]["accuracy"] - y["evaluation"][split]["accuracy"] for x, y in paired_rows]))
                for metric in ("brier", "ece"):
                    row["mean_" + metric + "_difference"] = float(np.mean([
                        x["evaluation"][split][metric] - y["evaluation"][split][metric] for x, y in paired_rows]))
                row["whole_process_cpu_ratio_hcsn_over_control"] = float(np.exp(np.mean([
                    np.log(costs["equal_cpu", x["job"]["id"]] / costs["equal_cpu", y["job"]["id"]]) for x, y in paired_rows])))
                row["inference_wall_ratio_hcsn_over_control"] = float(np.exp(np.mean([
                    np.log(x["inference"]["median_wall_seconds"] / y["inference"]["median_wall_seconds"]) for x, y in paired_rows])))
                external.append(row)
    holm(external)
    for index, row in enumerate(external):
        row["positive_gate"] = bool(row["mean"] >= .02 and row["ci95"][0] > 0 and row["holm_one_sided_p"] < .05
            and row["mean_brier_difference"] <= .01 and row["mean_ece_difference"] <= .02)
        reported = original["equal_cpu_external"][index]
        for key, value in row.items():
            name = "external/" + str(index) + "/" + key
            if isinstance(value, (str, bool)):
                check(name, value == reported[key])
            else:
                close(name, value, reported[key])
    for summary in original["summaries"]:
        stage, task, arm = (summary[key] for key in ("stage", "task", "arm"))
        values = [result(stage, task, arm, seed) for seed in design["formal_seeds"]]
        prefix = stage + "/" + task + "/" + arm
        close(prefix + ": mean updates", summary["mean_updates"], np.mean([row["updates"] for row in values]))
        close(prefix + ": mean training CPU", summary["mean_training_cpu_seconds"], np.mean([row["training_cpu_seconds"] for row in values]))
        close(prefix + ": mean complete wait4 CPU", summary["mean_whole_process_cpu_seconds"], np.mean([costs[stage, row["job"]["id"]] for row in values]))
        for split in ("test", "ood"):
            for metric in ("accuracy", "cross_entropy", "brier", "ece"):
                vector = np.array([row["evaluation"][split][metric] for row in values])
                close(prefix + "/" + split + "/" + metric + ": mean", summary["evaluation"][split][metric]["mean"], np.mean(vector))
                close(prefix + "/" + split + "/" + metric + ": sample SD", summary["evaluation"][split][metric]["sample_sd"], np.std(vector, ddof=1))
    mechanism_positive = sum(row["positive_gate"] for group in mechanism.values() for row in group)
    external_positive = sum(row["positive_gate"] for row in external)
    check("mechanism gate count", mechanism_positive == original["mechanism_positive_count"])
    check("external gate count", external_positive == original["external_positive_count"] and len(external) == original["external_contrasts"] == 12)
    totals = dict(child_cpu_seconds=sum(ledger["child_cpu_seconds"] for ledger in ledgers.values()),
        coordinator_cpu_seconds=sum(ledger["coordinator_cpu_seconds"] for ledger in ledgers.values()),
        worker_training_cpu_seconds=sum(row["training_cpu_seconds"] for row in rows.values()))
    for key, value in totals.items():
        close("nonoverlapping cost scope / " + key, value, original["costs_nonoverlap"][key], 1e-8)
    result = dict(schema="hcsn-independent-content-outcome-audit.v1", passed=not failures,
        check_count=len(checks),
        checks=checks, failed_checks=failures, input_files=source_files,
        audit_source_sha256=digest(Path(__file__)), worker_counts=job_counts,
        independent_mechanism_families=mechanism, independent_external_contrasts=external,
        independent_gate_counts=dict(mechanism=mechanism_positive, external=external_positive),
        cost_totals=totals, cpu_seconds=time.process_time() - started,
        scope="Independent recomputation from444worker RESULT summaries and exact wait4ledgers. No import of original analysis/metrics/model. Prediction tensors not replayed by this audit.",
        limitations=["Raw tensor/label identity and selected checkpoint bytes are verified by the original analysis, not independently rerun here",
                     "Seed-only uncertainty is conditional on fixed tasks/datasets",
                     "Exact sign-flip inference assumes sign exchangeability or symmetry under its null",
                     "No positive result is inferred from an audit passing"])
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode()) > 480000:
        shards = []
        for index, offset in enumerate(range(0, len(checks), 500)):
            path = output.with_name(output.stem + f"_checks_{index:03d}.json")
            body = json.dumps(checks[offset:offset + 500], indent=2, sort_keys=True, allow_nan=False) + "\n"
            if len(body.encode()) > 480000:
                raise RuntimeError("Audit check shard exceeds publication budget")
            path.write_text(body)
            shards.append(dict(path=path.name, bytes=path.stat().st_size, sha256=digest(path),
                               checks=len(checks[offset:offset + 500])))
        result.pop("checks")
        result["check_shards"] = shards
        encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode()) > 480000:
        raise RuntimeError("Audit main record exceeds publication budget")
    output.write_text(encoded)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.output)
    print(json.dumps(dict(passed=result["passed"], checks=result["check_count"],
                         failures=len(result["failed_checks"]), **result["independent_gate_counts"])))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

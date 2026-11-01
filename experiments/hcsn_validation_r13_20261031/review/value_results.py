"""Independent bounded raw-record audit; no imports from the experimental model."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np


BASE = Path(__file__).resolve().parents[1] / "value"
SAMPLES = ("ordinary_s11/confirm13_a", "analytic_s11/confirm13_a")
ERRORS = defaultdict(float)
INPUTS = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    INPUTS[str(path.relative_to(BASE))] = sha(path)
    return json.loads(path.read_text())


def check(ok, label):
    if not ok:
        raise AssertionError(label)


def close(actual, expected, label, tol=2e-10):
    difference = abs(float(actual) - float(expected))
    ERRORS[label] = max(ERRORS[label], difference)
    check(np.isfinite(difference) and difference <= tol, (label, actual, expected))


def parts(folder, result, kind):
    rows = []
    for part in result["evidence_parts"][kind]:
        path = folder / part["file"]
        check(sha(path) == part["sha256"], ("part hash", path))
        INPUTS[str(path.relative_to(BASE))] = sha(path)
        with gzip.open(path, "rt") as stream:
            values = [json.loads(line) for line in stream]
        check(len(values) == part["rows"], ("part row count", path))
        rows.extend(values)
    return rows


def likelihoods(config):
    tables = []
    for modality in config["modalities"]:
        q = config["q_a"] if modality == "A" else config["q_b"]
        table = np.array([[q, 1-q], [1-q, q]], dtype=float)
        tables.append(table if modality == "A" else np.repeat(table / 2, 2, axis=1))
    return tables


def posterior(history, config, tables):
    weights = np.array([1-config["prior"], config["prior"]], dtype=float)
    for slot, outcome in enumerate(history):
        if outcome >= 0:
            weights *= tables[slot][:, outcome]
    return weights / weights.sum()


def expected_raw(modality, outcome):
    raw = np.zeros(12)
    if modality == "A":
        raw[outcome] = 1
        raw[10] = 1
    else:
        sign, noise = ((-1, -1), (-1, 1), (1, -1), (1, 1))[outcome]
        raw[2:10] = sign * np.array([1, 1, -1, -1, 1, 1, -1, -1]) * .7
        raw[2:10] += noise * np.array([1, -1, 1, -1, 1, -1, 1, -1]) * .4
        raw[11] = 1
    return raw


def state_digest(record, history, config):
    features = np.asarray(record["public_features"], dtype="<f8")
    width = len(features) - 2 - 8 - 2*len(config["dts"])
    budget = config["budget"] - sum(v >= 0 for v in history)
    close(features[width+2], len(history)/len(config["dts"]), "public_slot")
    close(features[width+3], budget/max(config["budget"], 1), "public_budget")
    digest = hashlib.sha256(features[:width].tobytes())
    digest.update(json.dumps([len(history), budget, float(features[width+4])]).encode())
    check(digest.hexdigest() == record["state_sha256"], "Public state hash reconstruction")
    return int(features[width:width+2].argmax())


def policy_algebra(states, result):
    config = result["config"]
    tables = likelihoods(config)
    policies = tuple(result["policies"])
    dynamic = {name: {} for name in policies}
    optimal, edges = {}, {}
    for history in sorted(states, key=len, reverse=True):
        row = states[history]
        prediction = state_digest(row, history, config)
        probabilities = posterior(history, config, tables)
        stop = float(probabilities[prediction])
        legal, outgoing = ["STOP"], {}
        if len(history) < len(config["dts"]):
            legal.append("SKIP")
            outgoing["SKIP"] = [(1., history + (-1,))]
            if sum(v >= 0 for v in history) < config["budget"]:
                legal.append("READ")
                mixture = probabilities @ tables[len(history)]
                outgoing["READ"] = [(float(p), history+(i,)) for i, p in enumerate(mixture)]
        edges[history] = outgoing
        qstar = {"STOP": stop}
        for action, successors in outgoing.items():
            qstar[action] = -config[action.lower()+"_cost"] + sum(p*optimal[h] for p, h in successors)
        check(set(qstar) == set(row["qstar"]), "All legal actions recorded")
        for action, value in qstar.items():
            close(row["qstar"][action], value, "independent_qstar")
        optimal[history] = max(qstar.values())
        for name in policies:
            recorded = row["policies"][name]
            chosen = recorded["chosen"]
            check(chosen in legal, "Legal recorded policy action")
            qpi = {"STOP": stop}
            for action, successors in outgoing.items():
                qpi[action] = -config[action.lower()+"_cost"] + sum(p*dynamic[name][h]["value"] for p, h in successors)
            for action, value in qpi.items():
                close(recorded["qpi"][action], value, "independent_qpi")
            continuation = dict(reads=0., skips=0., correctness=stop)
            if chosen != "STOP":
                continuation = {key: sum(p*dynamic[name][h][key] for p, h in outgoing[chosen])
                                for key in continuation}
                continuation["reads"] += chosen == "READ"
                continuation["skips"] += chosen == "SKIP"
            for key, value in continuation.items():
                close(recorded["continuation_statistics"][key], value, "continuation_"+key)
            dynamic[name][history] = dict(value=qpi[chosen], q=qpi, **continuation)
    for name in policies:
        occupancy, terminal, regret = {(): 1.}, 0., 0.
        for history in sorted(states, key=len):
            row, mass = states[history], occupancy.get(history, 0.)
            chosen = row["policies"][name]["chosen"]
            close(row["policies"][name]["occupancy"], mass, "policy_occupancy")
            regret += mass*(optimal[history]-row["qstar"][chosen])
            terminal += mass*(chosen == "STOP")
            for p, child in edges[history].get(chosen, []):
                occupancy[child] = occupancy.get(child, 0.) + mass*p
        close(terminal, 1, "terminal_mass")
        exact = result["policies"][name]["exact"]
        root = dynamic[name][()]
        for actual_key, own_key in (("return", "value"), ("expected_reads", "reads"), ("expected_skips", "skips")):
            close(exact[actual_key], root[own_key], "root_"+own_key)
        close(result["policies"][name]["correctness"], root["correctness"], "root_correctness")
        close(exact["gap"], optimal[()]-root["value"], "oracle_gap")
        close(exact["regret_sum"], regret, "regret_sum")
        for history in states:
            if name.endswith("_tailstop"):
                base = name[:-9]
                left, right = dynamic[base][history], dynamic[name][history]
                close(left["reads"], right["reads"], "all_history_reads_preserved")
                close(left["correctness"], right["correctness"], "all_history_correctness_preserved")
                close(right["value"]-left["value"], (left["skips"]-right["skips"])*config["skip_cost"], "all_history_fee_dominance")
                check(right["value"] >= left["value"]-2e-10, "All-history nonnegative improvement")
                check(states[history]["policies"][name]["scores"] == states[history]["policies"][base]["scores"], "Original critic scores retained")
    return dynamic


def lookahead(states, history, name):
    base = name[:-9]
    action, depth = states[history]["policies"][base]["chosen"], 0
    cursor = history
    while action == "SKIP":
        cursor += (-1,)
        depth += 1
        action = states[cursor]["policies"][base]["chosen"]
    original = states[history]["policies"][base]["chosen"]
    replacement = original == "SKIP" and action == "STOP"
    return ("STOP" if replacement else original), depth, replacement


def actual_execution(execution, source, states, config, controller=None):
    history, fee, reads = (), 0., []
    for index, step in enumerate(execution["steps"]):
        check(not step["guard_rejected"], "Illegal action guard fallback")
        check(step["state_before_sha256"] == states[history]["state_sha256"], "Actual prefix identity")
        action, slot = step["executed"], len(history)
        check(step["slot"] == slot, "Actual public slot")
        if controller:
            check(action == states[history]["policies"][controller]["chosen"], "Actual policy choice")
        if action == "READ":
            outcome = source["outcomes"][slot]
            check(step["raw_outcome_index"] == outcome, "Actual source outcome")
            check(np.array_equal(np.asarray(step["raw_observation"]), expected_raw(config["modalities"][slot], outcome)), "Raw observation bytes")
            history += (outcome,)
            reads.append(slot)
            fee += config["read_cost"]
        elif action == "SKIP":
            check(step["raw_observation"] is None and not step["raw_accessed"], "SKIP accessed raw data")
            history += (-1,)
            fee += config["skip_cost"]
        else:
            check(action == "STOP" and index == len(execution["steps"])-1, "Termination")
        close(step["cumulative_fee"], fee, "step_fee")
        check(step["state_after_sha256"] == states[history]["state_sha256"], "Actual successor identity")
    check(reads == execution["raw_accesses"], "Actual raw accesses")
    check(tuple(execution["final_history"]) == history, "Final history")
    correct = float(execution["prediction"] == source["label"])
    close(execution["correct"], correct, "actual_correctness")
    close(execution["fee"], fee, "actual_complete_fee")
    close(execution["return"], correct-fee, "actual_return")
    check(all(v >= 0 for v in execution["phase_cpu_seconds"].values()), "Negative phase CPU")
    check(sum(execution["phase_cpu_seconds"].values()) <= execution["total_cpu_seconds"]+1e-8, "Nested CPU accounting")


def audit_case(folder, result):
    state_rows = parts(folder, result, "states")
    states = {tuple(row["history"]): row for row in state_rows}
    check(len(states) == len(state_rows) == result["histories"], "Unique state histories")
    dynamic = policy_algebra(states, result)
    paired, forced = parts(folder, result, "paired"), parts(folder, result, "forced")
    grouped, worlds, counts = defaultdict(list), defaultdict(dict), {}
    for name in result["policies"]:
        if name.endswith("_tailstop"):
            counts[name] = dict(actor_calls=0, base_calls=0, simulated_skips=0, replacements=0, max_simulated_skips=0)
    for row in paired:
        name, execution = row["controller"], row["execution"]
        source = row["source"]
        actual_execution(execution, dict(label=source["hidden_label_evaluator_only"], outcomes=source["outcomes_evaluator_only"]),
                         states, result["config"], name)
        worlds[source["world_id"]][name] = row
        grouped[name].append(execution)
        if name in counts:
            history = ()
            for step in execution["steps"]:
                choice, depth, replacement = lookahead(states, history, name)
                check(choice == step["executed"], "Independent TailStop choice")
                c = counts[name]
                c["actor_calls"] += 1
                c["base_calls"] += 1+depth
                c["simulated_skips"] += depth
                c["replacements"] += replacement
                c["max_simulated_skips"] = max(c["max_simulated_skips"], depth)
                if step["executed"] != "STOP":
                    history += ((step["raw_outcome_index"] if step["executed"] == "READ" else -1),)
    check(counts == result["wrapper_counts"]["paired"], "Extra wrapper calls independently counted")
    for name, executions in grouped.items():
        measured = result["policies"][name]["actual_paired"]
        for plural, field in (("returns", "return"), ("correctness", "correct"), ("fees", "fee")):
            check(measured[plural] == [r[field] for r in executions], "Paired arrays")
        close(measured["actor_cpu"], sum(r["total_cpu_seconds"] for r in executions), "actual_actor_cpu")
        for phase, value in measured["stages_cpu"].items():
            close(value, sum(r["phase_cpu_seconds"].get(phase, 0.) for r in executions), "actual_phase_cpu")
    for world in worlds.values():
        check(len(world) == 8, "Eight policies on every paired world")
        check(all(row["source"] == next(iter(world.values()))["source"] for row in world.values()), "Same paired raw world")
        for name in counts:
            original, guarded = world[name[:-9]]["execution"], world[name]["execution"]
            check([r for r in original["steps"] if r["executed"] == "READ"] ==
                  [r for r in guarded["steps"] if r["executed"] == "READ"], "Pathwise READ preservation")
            check((original["prediction"], original["correct"], original["raw_accesses"]) ==
                  (guarded["prediction"], guarded["correct"], guarded["raw_accesses"]), "Pathwise terminal preservation")
    conditional = defaultdict(lambda: dict(mass=0., value=0., correct=0., fee=0., rows=0))
    tables = likelihoods(result["config"])
    for row in forced:
        history, action, name = tuple(row["prefix"]), row["forced_action"], row["controller"]
        label, outcomes = row["label_evaluator_only"], row["assigned_outcomes_evaluator_only"]
        actual_execution(row["execution"], dict(label=label, outcomes=outcomes), states, result["config"])
        check(tuple(row["execution"]["final_history"][:len(history)]) == history, "Actual forced prefix")
        prefix_fee = sum(result["config"]["skip_cost"] if outcome < 0 else result["config"]["read_cost"]
                         for outcome in history)
        close(row["prefix_fee"], prefix_fee, "independent_prefix_fee")
        close(row["suffix_return"], row["execution"]["return"]+prefix_fee, "independent_suffix_return")
        weight = float(posterior(history, result["config"], tables)[label])
        for slot in range(len(history), len(outcomes)):
            if outcomes[slot] >= 0:
                weight *= tables[slot][label, outcomes[slot]]
        close(row["conditional_weight"], weight, "independent_conditional_weight")
        check(row["execution"]["steps"][len(history)]["executed"] == action, "Actual forced first action")
        total = conditional[(name, history, action)]
        total["mass"] += weight
        total["value"] += weight*row["suffix_return"]
        total["correct"] += weight*row["execution"]["correct"]
        total["fee"] += weight*(row["execution"]["fee"]-row["prefix_fee"])
        total["rows"] += 1
    for row in result["forced_checks"]:
        key = (row["controller"], tuple(row["prefix"]), row["forced_action"])
        total = conditional[key]
        close(total["mass"], 1., "forced_mass")
        close(total["value"], dynamic[key[0]][key[1]]["q"][key[2]], "forced_qpi")
        close(total["value"], row["actual_suffix_return"], "forced_summary")
        close(total["value"], total["correct"]-total["fee"], "forced_fee_identity")
    return dict(histories=len(states), policies=8, paired_raw_rows=len(paired), paired_worlds=len(worlds),
        forced_raw_rows=len(forced), forced_groups=len(conditional), wrapper_counts=counts,
        worlds={key: next(iter(rows.values()))["source"] for key, rows in worlds.items()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=BASE / "evidence/confirmation_01")
    parser.add_argument("--output", type=Path, default=BASE / "INDEPENDENT_RESULT_REVIEW.json")
    args = parser.parse_args()
    cpu, wall = time.process_time(), time.perf_counter()
    summary = read(args.results / "SUMMARY.json")
    result_rows = {}
    for name, digest in summary["input_results"].items():
        path = args.results / name
        check(sha(path) == digest, "Overall result hash")
        result_rows[str(path.parent.relative_to(args.results))] = read(path)
    check(len(result_rows) == 24, "24 completed fixed cases")
    group_means = {}
    for name, recorded in summary["groups"].items():
        family, control = name.split("/")
        rows = [r["policies"][control] for r in result_rows.values() if r["family"] == family]
        measured = dict(return_mean=float(np.mean([r["exact"]["return"] for r in rows])),
            correctness=float(np.mean([r["correctness"] for r in rows])),
            reads=float(np.mean([r["exact"]["expected_reads"] for r in rows])),
            skips=float(np.mean([r["exact"]["expected_skips"] for r in rows])),
            actor_cpu_ms_per_trajectory=1000*sum(r["actual_paired"]["actor_cpu"] for r in rows)/
                sum(len(r["actual_paired"]["returns"]) for r in rows))
        for key, value in measured.items():
            close(recorded[key], value, "all_json_group_"+key)
        group_means[name] = measured
    for name, factorial in summary["factorials"].items():
        suffix = "_tailstop" if name.endswith("_tailstop") else ""
        controller = name[:-9] if suffix else name
        for seed, fit in factorial["by_seed"].items():
            def mean(family, control):
                return float(np.mean([r["policies"][control+suffix]["exact"]["return"] for r in result_rows.values()
                                      if r["family"] == family and r["seed"] == int(seed)]))
            a, b = mean("ordinary", "lightweight"), mean("ordinary", controller)
            c, d = mean("analytic", "lightweight"), mean("analytic", controller)
            for key, value in dict(A=a, B=b, C=c, D=d, **{"B-A":b-a, "D-C":d-c, "C-A":c-a, "D-B":d-b, "interaction":d-c-b+a}).items():
                close(fit[key], value, "factorial_from_all_result_json")
        for effect, descriptive in factorial["descriptive"].items():
            values = [fit[effect] for fit in factorial["by_seed"].values()]
            for key, value in dict(mean=float(np.mean(values)), minimum_seed_mean=min(values),
                                   maximum_seed_mean=max(values)).items():
                close(descriptive[key], value, "factorial_descriptive")
    sampled = {name: audit_case(args.results / name, result_rows[name]) for name in SAMPLES}
    check(sampled[SAMPLES[0]]["worlds"] == sampled[SAMPLES[1]]["worlds"], "Cross-core paired raw worlds")
    for record in sampled.values():
        del record["worlds"]
    freeze = read(BASE / "SOURCE_FREEZE.json")
    check(sha(BASE / "SOURCE_FREEZE.json") == summary["source_freeze_sha256"], "Result source freeze")
    for path, digest in freeze["source_sha256"].items():
        check(sha(BASE.parents[2] / path) == digest, "Current source binding")
    receipt = read(BASE / "confirmation_01_PROCESS.json")
    check(receipt["exit_code"] == 0, "Confirmation process completed")
    for path, record in receipt["logs"].items():
        check(sha(BASE.parents[2] / path) == record["sha256"], "Process log identity")
    record = dict(schema="hcsn.r13.value.independent-results.v1", reviewer="/root/cost_baselines",
        recorded_at_utc=datetime.now(timezone.utc).isoformat(), passed=True,
        source_freeze_sha256=summary["source_freeze_sha256"], reviewer_script_sha256=sha(Path(__file__)),
        complete_result_json_count=len(result_rows), raw_case_selection=list(SAMPLES), raw_coverage=sampled,
        independently_aggregated_groups=group_means,
        maximum_absolute_errors=dict(ERRORS), input_sha256=INPUTS,
        own_cpu_seconds=time.process_time()-cpu, own_wall_seconds=time.perf_counter()-wall,
        method="Independent NumPy/JSON/gzip algebra; no imports from R12/R13 executor/model/calibration or new training.",
        limitations="All 24 summary hashes/factorial arithmetic checked; complete raw records only for the two named cases. Content transitions/critic weights were not re-executed, remaining 22 raw cases were not audited, and this is not a rerun or population superiority test.")
    with args.output.open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=True, sampled_cases=list(sampled), maximum_error=max(ERRORS.values()))))


if __name__ == "__main__":
    main()

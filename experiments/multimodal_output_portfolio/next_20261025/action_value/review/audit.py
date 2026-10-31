"""Independent actual counterfactual journal, stop identity and value audit."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path


ACTIONS = ("stop", "refine_semantic", "refine_image", "refine_text", "couple")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024): value.update(block)
    return value.hexdigest()


def key(row):
    return tuple(row[x] for x in ("seed", "case", "view", "draw"))


def read_rows(path):
    with gzip.open(path, "rt") as stream:
        yield from map(json.loads, stream)


def average(values):
    return math.fsum(values) / len(values)


def certainty_equivalent(values):
    scaled = [-2 * u for u in values]; largest = max(scaled)
    return -.5 * (largest + math.log(average([math.exp(u - largest) for u in scaled])))


def run(directory, output):
    if output.exists(): raise FileExistsError("Never overwrite an independent audit")
    completion = json.loads((directory / "completion.json").read_text())
    primary = json.loads((directory / "analysis.json").read_text())
    spec = json.loads((directory / "registration.json").read_text())["spec"]
    if completion["failures"] or primary["failures"]: raise ValueError("Incomplete actual study")
    for filename, expected in completion["files_sha256"].items():
        if sha(directory / filename) != expected: raise ValueError("Changed closed evidence")
    allocation_path = Path(spec["source"]["allocation"])
    if sha(allocation_path) != spec["source_allocation_sha256"]: raise ValueError("Changed source identity")
    allocation = json.loads(allocation_path.read_text())
    requests, by_policy, views, writers = {}, defaultdict(list), set(), Counter()
    referenced_offsets, media_references = set(), 0
    with (directory / "media.bin").open("rb") as media:
        def verify_media(saved):
            nonlocal media_references
            if saved["offset"] < 0 or saved["offset"] % 204: raise ValueError("Invalid media block offset")
            media.seek(saved["offset"]); raw = media.read(204)
            if len(raw) != 204 or hashlib.sha256(raw).hexdigest() != saved["sha256"]:
                raise ValueError("Actual media bytes changed")
            referenced_offsets.add(saved["offset"]); media_references += 1

        for row in read_rows(directory / "requests.jsonl.gz"):
            identity = (*key(row), row["policy"])
            if identity in requests or row["status"] != "completed": raise ValueError("Repeated or failed actual request")
            sources = allocation["source_records"][2 * row["case"]:2 * row["case"] + 2]
            if row["source_ids"] != [x["source_id"] for x in sources]: raise ValueError("Actual source mismatch")
            verify_media(row["terminal"]); verify_media(row["root_stop"])
            requests[identity] = row; by_policy[row["policy"]].append(row)
            views.add(row["view"]); writers[allocation["pair_writer_ids"][row["case"]]] += 1
        if len(requests) != 49152 or len(writers) != 256 or set(writers.values()) != {192} or len(views) != 8:
            raise ValueError("Actual writer/request census changed")
        initial_pairs, same_path_pairs = 0, 0
        for identity, teacher in requests.items():
            if identity[-1] != "cached_teacher": continue
            candidate = requests[(*identity[:-1], "rich_paired")]
            if (teacher["root_stop"]["sha256"] != candidate["root_stop"]["sha256"] or
                    teacher["decisions"][0]["public_sha256"] != candidate["decisions"][0]["public_sha256"]):
                raise ValueError("Two actual policies did not start at the same real draft")
            initial_pairs += 1
            if teacher["path"] == candidate["path"]:
                if teacher["terminal"]["sha256"] != candidate["terminal"]["sha256"]: raise ValueError("Path media differs")
                same_path_pairs += 1
        diagnostics, journal, differences = {}, defaultdict(list), []
        for row in read_rows(directory / "counterfactuals.jsonl.gz"):
            identity = key(row)
            if identity in diagnostics: raise ValueError("Repeated diagnostic parent")
            selected = requests[(*identity, "rich_paired")]; last = selected["decisions"][-1]
            if (last["remaining"] != 1 or last["public_sha256"] != row["parent_public_sha256"] or
                    last["action"] != row["selected_action"] or not row["not_visible_to_policy"]):
                raise ValueError("Diagnostic parent/choice differs")
            if [x["action"] for x in row["alternatives"]] != list(ACTIONS): raise ValueError("Wrong action census")
            for alternative in row["alternatives"]:
                verify_media(alternative["media"])
                chosen = alternative["action"] == row["selected_action"]
                if alternative["reused_actual_selected_result"] != chosen: raise ValueError("Wrong selected-result reuse")
                if chosen and alternative["media"] != selected["terminal"]: raise ValueError("Selected result was not reused")
            if row["alternatives"][0]["media"]["sha256"] != row["alternatives"][1]["media"]["sha256"]:
                raise ValueError("H1 semantic refinement did not preserve the stopped draft")
            diagnostics[identity] = row
        expected = {key(r) for r in by_policy["rich_paired"] if r["decisions"][-1]["remaining"] == 1}
        if set(diagnostics) != expected: raise ValueError("Missing selected-state finite-action diagnostic")
        for row in read_rows(directory / "diagnostic-commitments.jsonl.gz"):
            identity = key(row); parent = diagnostics[identity]
            if (row["phase"] != "offline_counterfactual_action_committed" or
                    row["parent_public_sha256"] != parent["parent_public_sha256"] or
                    not row["actual_selected_action_already_completed"]):
                raise ValueError("Diagnostic commitment parent/phase differs")
            journal[identity].append(row["action"])
        if set(journal) != expected or any(journal[k] != [a for a in ACTIONS if a != v["selected_action"]] for k, v in diagnostics.items()):
            raise ValueError("Offline future-action commitment journal is incomplete")
        scored_nodes = set()
        for row in read_rows(directory / "counterfactual-scored.jsonl.gz"):
            identity = key(row)
            if identity in scored_nodes: raise ValueError("Repeated scored diagnostic")
            original = {k: v for k, v in row.items() if k != "outcomes"}
            if original != diagnostics[identity]: raise ValueError("Scoring changed pre-scoring counterfactual record")
            scored_nodes.add(identity)
            utility = [x["scores"]["primary"]["utility"] for x in row["outcomes"]]
            delta = [math.exp(-2 * (u - (.002 if i else 0))) - math.exp(-2 * utility[0]) for i, u in enumerate(utility)]
            selected = ACTIONS.index(row["selected_action"])
            prediction, old = row["prediction"], row["old_teacher_prediction_same_public_state"]
            if prediction[0] != 0 or delta[0] != 0 or selected == 1: raise ValueError("Stop identity or H1 action mask violated")
            differences.append({"selected_actual": delta[selected], "selected_prediction": prediction[selected], "nonstop": selected != 0,
                "candidate_MSE": average([(prediction[i] - delta[i]) ** 2 for i in (2, 3, 4)]),
                "teacher_MSE": average([(old[i] - delta[i]) ** 2 for i in (2, 3, 4)]),
                "zero_MSE": average([delta[i] ** 2 for i in (2, 3, 4)])})
        if scored_nodes != expected: raise ValueError("Incomplete actual diagnostic scoring")
        size = (directory / "media.bin").stat().st_size
        if size % 204 or referenced_offsets != set(range(0, size, 204)): raise ValueError("Unreferenced or missing actual media blocks")
    utilities, successes = defaultdict(list), defaultdict(list)
    seed_utility, seed_success = defaultdict(list), defaultdict(list)
    score_keys = set()
    for row in read_rows(directory / "scored.jsonl.gz"):
        identity = (*key(row), row["policy"])
        if identity in score_keys or identity not in requests: raise ValueError("Wrong primary score identity")
        score_keys.add(identity); utilities[row["policy"]].append(row["scores"]["primary"]["utility"])
        successes[row["policy"]].append(row["scores"]["primary"]["joint_fact_correct"])
        seed_utility[row["policy"], row["seed"]].append(row["scores"]["primary"]["utility"])
        seed_success[row["policy"], row["seed"]].append(row["scores"]["primary"]["joint_fact_correct"])
    if score_keys != set(requests): raise ValueError("Incomplete primary scoring")
    errors, recomputed = [], {}
    for policy, values in utilities.items():
        metrics = {"raw_CE": certainty_equivalent(values), "success": average(successes[policy]),
                   "mean_wall_ms": average([r["wall_ns"] / 1e6 for r in by_policy[policy]])}
        recomputed[policy] = metrics
        errors.extend(abs(value - primary["policies"][policy][name]) for name, value in metrics.items())
    per_seed = {policy: {str(seed): {"raw_CE": certainty_equivalent(seed_utility[policy, seed]),
        "success": average(seed_success[policy, seed]),
        "mean_wall_ms": average([r["wall_ns"] / 1e6 for r in by_policy[policy] if r["seed"] == seed]),
        "mean_continuation_actions": average([len(r["path"]) for r in by_policy[policy] if r["seed"] == seed])}
        for seed in (17, 29, 43)} for policy in by_policy}
    actual = primary["action_value_diagnostics"]
    value_metrics = {name: average([r[name] for r in differences]) for name in ("candidate_MSE", "teacher_MSE", "zero_MSE")}
    errors.extend(abs(value - actual[name]) for name, value in value_metrics.items())
    non_stop = [r for r in differences if r["nonstop"]]
    if non_stop:
        gain = average([r["selected_actual"] for r in non_stop])
        bias = average([r["selected_prediction"] - r["selected_actual"] for r in non_stop])
        errors += [abs(gain - actual["nonstop_only"]["actual_action_minus_stop_moment"]["estimate"]),
                   abs(bias - actual["nonstop_only"]["prediction_bias"]["estimate"])]
    if max(errors) > 1e-10: raise ValueError("Independent arithmetic differs")
    result = {"schema": "hepta.next.action-value-independent-audit.v1", "status": "passed",
        "requests": len(requests), "writers": len(writers), "same_actual_root_pairs": initial_pairs,
        "same_path_actual_media_pairs": same_path_pairs, "actual_media_references_verified": media_references,
        "unique_physical_media_blocks_verified": len(referenced_offsets), "H1_nodes": len(diagnostics),
        "offline_future_action_commitments_verified": sum(map(len, journal.values())),
        "H1_semantic_actual_stop_media_identity_verified": len(diagnostics),
        "maximum_independent_arithmetic_error": max(errors), "recomputed_policies": recomputed,
        "per_seed_descriptive": per_seed,
        "recomputed_action_value_MSE": value_metrics, "audit_source_sha256": sha(__file__),
        "closed_inputs_sha256": {p.name: sha(p) for p in directory.iterdir() if p.is_file()},
        "scope": "Independent byte, identity, journal and arithmetic checks. Offline causal ordering also relies on frozen owner code; this audit does not convert finite realized regret into a deployable policy or certify bootstrap coverage."}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream: json.dump(result, stream, sort_keys=True, indent=2); stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "closed_inputs_sha256"}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.directory, a.output)

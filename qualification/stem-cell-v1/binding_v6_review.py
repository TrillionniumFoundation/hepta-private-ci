"""Stdlib, independent score/schedule audit of the V6 train-only receipt bundle.

It does NOT attest real Torch execution, model checkpoint tensors, wall clocks,
source independence, or prospective quality. A PASS is evidence consistency only.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
import random
from pathlib import Path

PROTOCOL = "hepta.binding.cross-fact-bridge.v6"
ARMS = ("cross_fact", "global_pool", "local")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate JSON property")
            result[k] = v
        return result
    return json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(
        ValueError("nonfinite JSON constant")), object_pairs_hook=unique)


def _truth(case_id):
    identity = json.loads(case_id)
    if (not isinstance(identity, list) or len(identity) != 4
            or identity[0] != "train" or identity[2] != "0"
            or identity[3] not in ("0", "1")
            or not identity[1].startswith("binding-v4/train/41/")):
        raise ValueError("unregistered V5 training case")
    group, sep, world = identity[1].rpartition("/world-")
    if not sep or world not in ("0", "1"):
        raise ValueError("invalid paired world")
    return (group, world, identity[3], int(identity[3] == world))


def score(panel):
    ids, labels, probs = panel["case_ids"], panel["targets"], panel["metrics"]["probabilities"]
    if (len(ids) != len(labels) or len(ids) != len(probs) or len(ids) != 128
            or len(set(ids)) != len(ids) or len(panel["source_groups"]) != len(ids)):
        raise ValueError("incomplete or duplicate train-only cohort")
    groups = defaultdict(dict)
    correct = paired = switched = 0
    predictions = []
    for pos, (case_id, label, probability) in enumerate(zip(ids, labels, probs)):
        group, world, candidate, expected = _truth(case_id)
        if (type(label) is not int or label != expected
                or not isinstance(probability, (int, float)) or not math.isfinite(probability)
                or not 0 <= probability <= 1 or (world, candidate) in groups[group]):
            raise ValueError("invalid probability, target, or duplicate world")
        prediction = int(probability > .5)
        predictions.append(prediction)
        correct += prediction == expected
        groups[group][(world, candidate)] = (prediction, panel["source_groups"][pos])
    if len(groups) != 32:
        raise ValueError("exactly 32 complete world groups required")
    for members in groups.values():
        if set(members) != {(w, a) for w in ("0", "1") for a in ("0", "1")}:
            raise ValueError("missing group/world/candidate")
        for w in ("0", "1"):
            if members[(w, "0")][1] != members[(w, "1")][1]:
                raise ValueError("same evidence world changes source identity")
        if members[("0", "0")][1] == members[("1", "0")][1]:
            raise ValueError("opposite worlds must differ in source")
        for a in ("0", "1"):
            p0, p1 = members[("0", a)][0], members[("1", a)][0]
            paired += p0 == int(a == "0") and p1 == int(a == "1")
            switched += p0 != p1
    expected_metrics = panel["metrics"]
    if (expected_metrics["n"] != 128 or expected_metrics["predictions"] != predictions
            or abs(expected_metrics["accuracy"] - correct / 128) > 1e-12
            or abs(expected_metrics["both_worlds_correct"] - paired / 64) > 1e-12
            or abs(expected_metrics["evidence_switch_rate"] - switched / 64) > 1e-12
            or panel["labels_entered_inference"] is not False):
        raise ValueError("self-scored metrics or inference contract mismatched")
    return correct, paired, switched


def replay_fixed_schedule(seed, panel, receipt):
    """Independent stdlib reconstruction of whole-group minibatches and their digests."""
    identifiers = panel["case_ids"]
    group_members = {}
    for index, case_id in enumerate(identifiers):
        group, world, candidate, _ = _truth(case_id)
        group_members.setdefault(group, {})[(world, candidate)] = index
    groups = [tuple(rows[(world, answer)] for world in ("0", "1")
                    for answer in ("0", "1")) for rows in group_members.values()]
    if len(groups) != 32 or any(len(g) != 4 for g in groups):
        raise ValueError("invalid world groups for deterministic schedule")
    rng = random.Random(seed)
    order, position, batches = [], len(groups), []
    for step_index in range(receipt["requested_steps"]):
        if position == len(groups):
            order = list(range(len(groups)))
            rng.shuffle(order)
            position = 0
        indices = [index for g in order[position:position + 4] for index in groups[g]]
        position += 4
        case_ids = [identifiers[index] for index in indices]
        if step_index < len(receipt["updates"]):
            step = receipt["updates"][step_index]
            if (step["indices"] != indices or step["case_ids"] != case_ids
                    or step["sample_sha256"] != sha256(json.dumps(case_ids,
                        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()):
                raise ValueError("actual minibatch differs from seed-bound complete-group stream")
        batches.append(indices)
    if sha256(json.dumps(batches, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()).hexdigest() != receipt["schedule_sha256"]:
        raise ValueError("committed full schedule digest mismatched")
    return len(receipt["updates"])


def review(root):
    root = Path(root)
    protocol, result = read(root / "protocol.json"), read(root / "result.json")
    if (protocol["schema"] != PROTOCOL or result["schema"] != PROTOCOL
            or result["protocol_sha256"] != digest(root / "protocol.json")
            or tuple(protocol["arms"]) != ARMS or result["model_selection_authorized"] is not False
            or result["fresh_scoring_authorized"] is not False
            or result["production_authorized"] is not False
            or protocol["official_validation_scored"] is not False
            or protocol["fresh_source_scored"] is not False
            or protocol["source_inventory"] != result["source_inventory"]):
        raise ValueError("V6 protocol or research denial altered")
    out = {}
    for seed in protocol["seeds"]:
        arms = result["outcomes"][str(seed)]
        if set(arms) != set(ARMS):
            raise ValueError("incomplete equal-parameter arms")
        checkpoints, schedules, params, exposures = set(), set(), set(), set()
        for arm in ARMS:
            row = arms[arm]
            if row["status"] == "failed":
                if row.get("gate_passed") is not False or row.get("failure_receipt_sha256") is None:
                    raise ValueError("failed arm has no retained failure receipt")
                path = root / f"seed-{seed}" / f"{arm}-failure.json"
                if digest(path) != row["failure_receipt_sha256"]:
                    raise ValueError("failure receipt bytes changed")
                continue
            folder = root / f"seed-{seed}"
            panel_path = folder / f"{arm}-train.json"
            receipt_path = folder / f"{arm}-training.json"
            if (digest(panel_path) != row["score_file_sha256"]
                    or digest(receipt_path) != row["training_receipt_sha256"]):
                raise ValueError("scored material or training receipts changed")
            panel, receipt = read(panel_path), read(receipt_path)
            correct, paired, switched = score(panel)
            replay_fixed_schedule(seed, panel, receipt)
            if (correct != row["correct"] or row["accuracy"] != correct / 128
                    or receipt["requested_steps"] != protocol["updates"]
                    or receipt["selection_rule"] != "none_fixed_budget"
                    or receipt["initial_model_sha256"] != row["initial_sha256"]
                    or receipt["model_sha256"] != row["model_sha256"]
                    or panel["model_sha256"] != row["model_sha256"]
                    or receipt["completed_steps"] != row["completed_updates"]
                    or receipt["actual_training_exposures"] != row["actual_training_exposures"]
                    or receipt["schedule_sha256"] != row["schedule_sha256"]
                    or receipt["parameter_count"] != row["parameter_count"]
                    or row["parameter_count"] != 42562
                    or row["completed_updates"] * 16 != row["actual_training_exposures"]
                    or row["gate_passed"] != receipt["train_gate_passed"]
                    or row["full_budget_completed"] != receipt["full_budget_completed"]
                    or receipt["official_validation_evaluated"] is not False
                    or any(step["step"] != i or step["exposures"] != 16
                           for i, step in enumerate(receipt["updates"], 1))
                    or len(receipt["updates"]) != row["completed_updates"]):
                raise ValueError("training schedule, full-fit, parameters, or scored results drift")
            for key in ("cpu_ns", "wall_ns"):
                if type(row[key]) is not int or row[key] <= 0 or row[key] != receipt[key]:
                    raise ValueError("missing or inconsistent observed cost")
            checkpoints.add(row["initial_sha256"])
            schedules.add(row["schedule_sha256"])
            params.add(row["parameter_count"])
            exposures.add(row["actual_training_exposures"])
            out[f"{seed}/{arm}"] = dict(correct=correct, paired=paired, switches=switched,
                completed_updates=row["completed_updates"], full_fit_gate=row["gate_passed"])
        if any(len(group) != 1 for group in (checkpoints, schedules, params, exposures)):
            raise ValueError("initial weights, sampling, or update budgets not matched")
    return dict(schema="hepta.binding.bridge-independent-review.v6", audited=out,
        evidence_consistent=True, real_model_execution_attested=False,
        future_generalization_established=False, production_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("independent reviewer must not overwrite evidence")
    args.output.write_text(json.dumps(review(args.results), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

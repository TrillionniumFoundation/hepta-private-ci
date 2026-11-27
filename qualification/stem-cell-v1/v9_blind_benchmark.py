"""Separated public-prediction / postseal-score benchmark for controlled long chains.

This worker has no model loader, no model training, no real pretrained calls and
no authorization path. Every arm is a deterministic, explicitly named control.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

from v9_typed_graph import RejectGraph, digest, solve, verify_proof

ARMS = ("full_graph", "two_hop_only", "constant_false")


def write_once(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf8") as stream:
        json.dump(content, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def prepare(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    # The inference-only action never imports the hidden target generator.
    from v9_source_panels import dataset_design
    design, public, truth = dataset_design()
    write_once(root / "design.json", design)
    write_once(root / "public.json", public)
    # This file MUST remain outside the prediction worker's visible input folder.
    write_once(root / "truth-restricted.json", truth)
    return design


def predict(public_path, prediction_path):
    """Inference only: sole input is a public question/evidence JSON file."""
    public = read(public_path)
    if (type(public) is not list or not public or len(public) > 20000
            or any(type(c) is not dict or set(c) != {
                "case_id", "source_group", "facts", "question", "candidate"} for c in public)):
        raise ValueError("bounded complete PUBLIC input required, no labels or hidden fields")
    seen, predictions = set(), {}
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    for c in public:
        case_id = c["case_id"]
        if type(case_id) is not str or case_id in seen:
            raise ValueError("unique public case identity required")
        seen.add(case_id)
        row = {}
        for arm in ARMS:
            start = time.process_time_ns()
            if arm == "constant_false":
                answer, proof = False, None
            else:
                try:
                    result = solve(c["facts"], c["question"], c["candidate"],
                                   max_hops=2 if arm == "two_hop_only" else 6)
                    answer, proof = result.claim, result.receipt()
                    if not verify_proof(c["facts"], c["question"], c["candidate"], proof):
                        raise RuntimeError("proof verification failed")
                except RejectGraph:
                    answer, proof = None, None
            row[arm] = dict(answer=answer, proof=proof,
                            cpu_ns=time.process_time_ns() - start,
                            fact_scan_count=0 if arm == "constant_false" else len(c["facts"]),
                            proof_hops=0 if proof is None else len(proof["hops"]))
        predictions[case_id] = row
    snapshot = dict(schema="hepta.v9.blind-prediction.v1", source_sha256=digest(public),
                    arms=list(ARMS), cases=len(public), predictions=predictions,
                    measured_cpu_ns=time.process_time_ns() - started_cpu,
                    measured_wall_ns=time.perf_counter_ns() - started_wall,
                    actual_optimizer_updates=0, pretrained_encoder_forwards=0,
                    input_has_labels=False, independent_human_review=False,
                    authority="DENY_ALL", production_accepted=False)
    snapshot["prediction_data_sha256"] = digest(predictions)
    write_once(prediction_path, snapshot)
    return snapshot


def basic_metrics(public, truth, predicted):
    groups, pairs = defaultdict(list), defaultdict(list)
    stats = defaultdict(lambda: dict(n=0, right=0, abstain=0, scan=0, hops=0, cpu_ns=0))
    for c in public:
        case_id = c["case_id"]
        fields = case_id.split("/")
        if len(fields) != 5 or fields[0] not in ("train", "held_known", "held_novel"):
            raise ValueError("registered source IDs required")
        role, depth = fields[0], int(fields[1])
        group = c["source_group"]
        groups[(role, depth, group)].append(case_id)
        pairs[(role, depth, group, fields[4])].append(case_id)
        gold = truth[case_id]
        for arm in ARMS:
            output = predicted[case_id][arm]
            key = (role, depth, arm)
            record = stats[key]
            record["n"] += 1
            record["right"] += output["answer"] is not None and int(output["answer"]) == gold
            record["abstain"] += output["answer"] is None
            record["scan"] += output["fact_scan_count"]
            record["hops"] += output["proof_hops"]
            record["cpu_ns"] += output["cpu_ns"]
    group_sizes = [len(ids) for ids in groups.values()]
    if any(n != 4 for n in group_sizes) or any(len(ids) != 2 for ids in pairs.values()):
        raise ValueError("complete world/candidate grouping required")
    for (role, depth, group), ids in groups.items():
        facts = [next(c["facts"] for c in public if c["case_id"] == cid) for cid in ids]
        if facts[0] != facts[1] or facts[2] != facts[3]:
            raise ValueError("same-world fact mismatch")
        from collections import Counter
        if Counter(" ".join(facts[0]).split()) != Counter(" ".join(facts[2]).split()):
            raise ValueError("world word inventories differ")
    result = []
    for (role, depth, arm), record in sorted(stats.items()):
        eligible = [(a, ids) for (r, d, g, a), ids in pairs.items() if (r, d) == (role, depth)]
        paired_correct = sum(all(predicted[cid][arm]["answer"] is not None and
                                 int(predicted[cid][arm]["answer"]) == truth[cid] for cid in ids)
                             for _, ids in eligible)
        result.append(dict(role=role, depth=depth, arm=arm, **record,
                           accuracy_with_abstain_as_failure=record["right"] / record["n"],
                           source_groups=record["n"] // 4,
                           paired_candidates=len(eligible), both_worlds_correct=paired_correct))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("--output", type=Path, required=True)
    b = sub.add_parser("predict")
    b.add_argument("--public", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.output)
        print(json.dumps({"prepared_cases": result["public_cases"],
                          "groups": result["independent_groups"], "sha256": result["public_sha256"]}))
    else:
        result = predict(args.public, args.output)
        print(json.dumps({"sealed_predictions": result["cases"],
                          "sha256": result["prediction_data_sha256"],
                          "cpu_ns": result["measured_cpu_ns"],
                          "model_forwards": result["pretrained_encoder_forwards"]}))


if __name__ == "__main__":
    main()

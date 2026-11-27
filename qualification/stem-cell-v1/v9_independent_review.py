"""Independent postseal verifier; input truth is NEVER supplied to the predictor."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

from v9_typed_graph import digest, verify_proof, RejectGraph

TYPES = ("object", "person", "box", "shelf", "room", "building", "district")
from v9_blind_benchmark import read, write_once, ARMS

# A second independently expressed grammar based on literal sentence structure.
# It does not import v9_typed_graph.PATTERNS or call the primary solver.
_FACTS = (
    r"The ([a-z]+) belongs to ([A-Z][a-z]+)\.",
    r"([A-Z][a-z]+) stores all their possessions in the ([a-z]+) box\.",
    r"The ([a-z]+) box is on the ([a-z]+) shelf\.",
    r"The ([a-z]+) shelf is in the ([a-z]+) room\.",
    r"The ([a-z]+) room is in the ([a-z]+) building\.",
    r"The ([a-z]+) building is in the ([a-z]+) district\."
)


def reference_semantics(case):
    text = case["question"]
    matched = re.fullmatch(r"Where is the ([a-z]+) at the (box|shelf|room|building|district) level\?", text)
    target = re.fullmatch(r"The ([a-z]+) (box|shelf|room|building|district)\.", case["candidate"])
    if matched is None or target is None or matched[2] != target[2]:
        raise ValueError("invalid held public query")
    d = TYPES.index(matched[2])
    graph = [{} for _ in range(6)]
    for sentence in case["facts"]:
        matches = [(i, re.fullmatch(pat, sentence)) for i, pat in enumerate(_FACTS)]
        present = [(i, m) for i, m in matches if m is not None]
        if len(present) != 1:
            raise ValueError("unrecognized or ambiguous source fact")
        i, m = present[0]
        a, b = m.groups()
        if a in graph[i]:
            raise ValueError("duplicate reference origin")
        graph[i][a] = b
    node = matched[1]
    for i in range(d):
        if node not in graph[i]:
            raise ValueError("incomplete reference chain")
        node = graph[i][node]
    return int(node == target[1])


def independent_metrics(public, truth, predictions):
    """Original-label postseal score recomputed without importing producer scorer."""
    from collections import Counter
    groups = defaultdict(list)
    for c in public:
        ident = c["case_id"].split("/")
        if len(ident) != 5:
            raise ValueError("five-field identity required")
        groups[(ident[0], int(ident[1]), c["source_group"])].append(c)
    scores = {}
    for (role, depth, group), cases in groups.items():
        if (len(cases) != 4 or len({c["case_id"] for c in cases}) != 4
                or sorted(truth[c["case_id"]] for c in cases) != [0, 0, 1, 1]):
            raise ValueError("complete source group and balanced truth required")
        # Group by candidate, not by predicted outcome or world label.
        by_candidate = defaultdict(list)
        for c in cases:
            ident = c["case_id"].split("/")
            by_candidate[ident[-1]].append(c)
        if set(by_candidate) != {"candidate-0", "candidate-1"}:
            raise ValueError("the two public candidates must remain complete")
        worlds = defaultdict(list)
        for c in cases:
            worlds[c["case_id"].split("/")[-2]].append(c)
        if set(worlds) != {"world-0", "world-1"} or any(len(v) != 2 for v in worlds.values()):
            raise ValueError("both public worlds required")
        left, right = (worlds[world] for world in ("world-0", "world-1"))
        if (left[0]["facts"] != left[1]["facts"] or right[0]["facts"] != right[1]["facts"]
                or Counter(" ".join(left[0]["facts"]).split()) !=
                   Counter(" ".join(right[0]["facts"]).split())):
            raise ValueError("matched source facts and world word bag required")
        for arm in ARMS:
            k = role, depth, arm
            row = scores.setdefault(k, dict(role=role, depth=depth, arm=arm,
                n=0, right=0, abstain=0, scan=0, hops=0, cpu_ns=0,
                source_groups=0, paired_candidates=0, both_worlds_correct=0))
            row["source_groups"] += 1
            row["paired_candidates"] += 2
            for c in cases:
                result = predictions[c["case_id"]][arm]
                row["n"] += 1
                row["right"] += result["answer"] is not None and result["answer"] == bool(truth[c["case_id"]])
                row["abstain"] += result["answer"] is None
                row["scan"] += result["fact_scan_count"]
                row["hops"] += result["proof_hops"]
                row["cpu_ns"] += result["cpu_ns"]
            row["both_worlds_correct"] += sum(
                all(predictions[c["case_id"]][arm]["answer"] is not None and
                    predictions[c["case_id"]][arm]["answer"] == bool(truth[c["case_id"]])
                    for c in pair) for pair in by_candidate.values())
    return [dict(row, accuracy_with_abstain_as_failure=row["right"] / row["n"])
            for _, row in sorted(scores.items())]


def review(design_path, public_path, truth_path, prediction_path, output_path):
    design, public, truth, blind = (read(p) for p in (
        design_path, public_path, truth_path, prediction_path))
    if (design.get("schema") != "hepta.v9.multihop-controlled.v1"
            or design.get("public_sha256") != digest(public)
            or design.get("labels_sha256") != digest(truth)
            or blind.get("source_sha256") != digest(public)
            or blind.get("prediction_data_sha256") != digest(blind["predictions"])
            or blind.get("arms") != list(ARMS)
            or blind.get("cases") != len(public)
            or blind.get("actual_optimizer_updates") != 0
            or blind.get("pretrained_encoder_forwards") != 0
            or blind.get("authority") != "DENY_ALL"
            or blind.get("production_accepted") is not False):
        raise ValueError("manifest, prediction seal or DENY_ALL changed")
    identifiers = [c["case_id"] for c in public]
    if (len(set(identifiers)) != len(public) or set(identifiers) != set(truth)
            or set(identifiers) != set(blind["predictions"])):
        raise ValueError("complete fixed public/secret/prediction universe required")
    verification_count = 0
    for c in public:
        case_id = c["case_id"]
        if type(truth[case_id]) is not int or truth[case_id] not in (0, 1):
            raise ValueError("binary source truth required")
        independently_derived = reference_semantics(c)
        if independently_derived != truth[case_id]:
            raise ValueError("hidden label conflicts with independent public semantics")
        row = blind["predictions"][case_id]
        if set(row) != set(ARMS):
            raise ValueError("exact fixed arms required")
        for arm, candidate in row.items():
            if (set(candidate) != {"answer", "proof", "cpu_ns", "fact_scan_count", "proof_hops"}
                    or type(candidate["cpu_ns"]) is not int or candidate["cpu_ns"] < 0
                    or type(candidate["fact_scan_count"]) is not int or candidate["fact_scan_count"] < 0
                    or type(candidate["proof_hops"]) is not int or candidate["proof_hops"] < 0):
                raise ValueError("bounded measured compute and output fields required")
            if arm == "constant_false":
                if candidate["answer"] is not False or candidate["proof"] is not None:
                    raise ValueError("constant baseline changed")
            elif arm == "two_hop_only" and TYPES.index(re.fullmatch(r"Where is the ([a-z]+) at the (box|shelf|room|building|district) level\?", c["question"])[2]) > 2:
                if candidate["answer"] is not None or candidate["proof"] is not None:
                    raise ValueError("limited two-hop control illegally answered deeper question")
            elif candidate["answer"] is None:
                if candidate["proof"] is not None or candidate["proof_hops"] != 0:
                    raise ValueError("abstention cannot include a fabricated proof")
            else:
                if (type(candidate["answer"]) is not bool or candidate["proof"] is None
                        or candidate["answer"] != candidate["proof"].get("claim")):
                    raise ValueError("boolean decision and supported proof required")
                try:
                    verify_proof(c["facts"], c["question"], c["candidate"], candidate["proof"])
                except RejectGraph as error:
                    raise ValueError("invalid independent grounded proof") from error
                if candidate["proof_hops"] != len(candidate["proof"]["hops"]):
                    raise ValueError("incorrect proof-work count")
                verification_count += 1
                if candidate["answer"] != bool(independently_derived):
                    raise ValueError("contradiction between decision and public ground truth")
    results = independent_metrics(public, truth, blind["predictions"])
    audit = dict(schema="hepta.v9.independent-postseal.v1", result_rows=results,
                 input_source_sha256=design["public_sha256"],
                 truth_sha256=design["labels_sha256"],
                 prediction_sha256=blind["prediction_data_sha256"],
                 verified_proofs=verification_count,
                 unique_cases=len(public), independent_source_groups=design["independent_groups"],
                 controls_are_synthetic_grammar=True,
                 natural_relation_generalization=False,
                 source_disjoint_is_not_time_disjoint=True,
                 original_V7_joint_gate_passed=False,
                 real_granite_forwards=0,
                 production_accepted=False, authority="DENY_ALL")
    write_once(output_path, audit)
    return audit


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("design", "public", "truth", "predictions", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    x = review(args.design, args.public, args.truth, args.predictions, args.output)
    print(json.dumps({"verified_proofs": x["verified_proofs"],
                      "cases": x["unique_cases"], "groups": x["independent_source_groups"],
                      "authority": x["authority"],
                      "result_sha256": digest(x["result_rows"])}))


if __name__ == "__main__":
    main()

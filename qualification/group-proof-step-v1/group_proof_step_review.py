"""Independent stdlib replay of bounded proof-step sources, interventions and scores.

Do NOT import the trainer, its oracle, or Torch. Hash binding is a consistency
check, not authenticated producer evidence, real future chronology or capability.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re

SCHEMA = "hepta.group.proof-step-three-seed.v1"
HEADER = re.compile(r"Start at (n[0-9]{1,4}) and follow every link\. What is the endpoint class\? Answer one of A B C D E F G H\.")
LINK = re.compile(r"(n[0-9]{1,4}) links to (n[0-9]{1,4})\.")
LABEL = re.compile(r"(n[0-9]{1,4}) has class ([A-H])\.")
ARMS = ("full", "question_only", "critical_removed", "distractor_removed", "truth_flipped")
POLICIES = ("untrained", "trained")

class Invalid(ValueError):
    pass


def sha(text):
    return sha256(text.encode()).hexdigest()


def strict_json(raw):
    def object_pairs(pairs):
        doc = {}
        for key, val in pairs:
            if key in doc:
                raise Invalid("duplicate JSON key")
            doc[key] = val
        return doc
    return json.loads(raw, object_pairs_hook=object_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(Invalid("nonfinite JSON")))


def parse(text):
    if not isinstance(text, str) or not 1 <= len(text.encode()) <= 65_536:
        raise Invalid("bounded public source required")
    lines = text.splitlines()
    if not 1 <= len(lines) <= 64 or (m := HEADER.fullmatch(lines[0])) is None:
        raise Invalid("unknown source grammar")
    facts, occupied = [], set()
    for i, line in enumerate(lines[1:]):
        if mlink := LINK.fullmatch(line):
            fact = ("link", *mlink.groups())
        elif mlabel := LABEL.fullmatch(line):
            fact = ("label", *mlabel.groups())
        else:
            raise Invalid("unsupported source fact")
        if fact[:2] in occupied:
            raise Invalid("ambiguous source evidence")
        occupied.add(fact[:2])
        facts.append(fact)
    canonical = json.dumps({"start": m.group(1), "facts": sorted(facts)},
                           sort_keys=True, separators=(",", ":"))
    return m.group(1), facts, sha(canonical)


def reference(text):
    start, facts, _ = parse(text)
    links = {s: (v, i) for i, (k, s, v) in enumerate(facts) if k == "link"}
    labels = {s: (v, i) for i, (k, s, v) in enumerate(facts) if k == "label"}
    node, visited, path = start, set(), []
    for _ in range(32):
        if node in visited:
            return None, path
        visited.add(node)
        if node in links:
            node, index = links[node]
            path.append(index)
        elif node in labels:
            value, index = labels[node]
            path.append(index)
            return value, path
        else:
            return None, path
    return None, path


def interventions(text):
    start, facts, _ = parse(text)
    answer, path = reference(text)
    if answer is None:
        raise Invalid("full source missing independent reference answer")
    def render(excluded=(), replace=None):
        replace = replace or {}
        lines = [f"Start at {start} and follow every link. What is the endpoint class? Answer one of A B C D E F G H."]
        for i, (kind, source, value) in enumerate(facts):
            if i in excluded:
                continue
            value = replace.get(i, value)
            lines.append(f"{source} links to {value}." if kind == "link" else f"{source} has class {value}.")
        return "\n".join(lines)
    critical = next((i for i in path if reference(render((i,)))[0] != answer), None)
    irrelevant = next((i for i in range(len(facts)) if i not in path and reference(render((i,)))[0] == answer), None)
    if critical is None or irrelevant is None or not path or facts[path[-1]][0] != "label":
        raise Invalid("incomplete causal panel")
    terminal = path[-1]
    flipped = chr(65 + (ord(facts[terminal][2]) - 64) % 8)
    return {"full": text, "question_only": render(range(len(facts))),
            "critical_removed": render((critical,)),
            "distractor_removed": render((irrelevant,)),
            "truth_flipped": render(replace={terminal: flipped})}


def audit(report):
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA or
            report.get("production_promotion_permitted") is not False or
            not isinstance(report.get("runs"), list) or len(report["runs"]) != 3):
        raise Invalid("not a deny-all, three-seed original bundle")
    receipts = []
    if [r.get("seed") for r in report["runs"]] != [41, 47, 53]:
        raise Invalid("required seeds changed")
    for run in report["runs"]:
        if (run.get("authority") != "DENY_ALL" or run.get("production_promotion_permitted") is not False
                or run.get("stem_encoder_forwards") != 0 or run.get("encoder_work_not_qualified") is not True
                or run.get("natural_reasoning_emergence_established") is not False
                or run.get("actual_native_effects") is not False):
            raise Invalid("unsupported authority or real-model claim")
        training, tests = run.get("train_groups"), run.get("test_groups")
        if (not isinstance(training, list) or not isinstance(tests, list)
                or len(training) != 128 or len(tests) != 64
                or training != sorted(set(training)) or tests != sorted(set(tests))
                or set(training) & set(tests)):
            raise Invalid("training/test source inventory mismatch")
        if (any(not isinstance(h, str) or not re.fullmatch(r"[a-f0-9]{64}", h) for h in training + tests)):
            raise Invalid("source digest shape")
        learning = run.get("training", {})
        if (learning.get("train_source_count") != 128 or type(learning.get("completed_updates")) is not int
                or learning["completed_updates"] <= 0 or type(learning.get("trained_weights")) not in (tuple, list)
                or len(learning["trained_weights"]) != 5
                or any(type(w) not in (float, int) or not math.isfinite(w) for w in learning["trained_weights"])):
            raise Invalid("fitting metadata invalid")
        commitment = json.dumps({"weights": list(learning["trained_weights"]), "sources": training,
                                 "updates": learning["completed_updates"]},
                                sort_keys=True, separators=(",", ":"))
        if sha(commitment) != learning.get("policy_sha256"):
            raise Invalid("frozen training identity does not bind the source inventory")
        source = run.get("source_cases")
        if not isinstance(source, list) or len(source) != 64:
            raise Invalid("raw independent source case census unavailable")
        by_group, expected_hashes, expected = {}, {}, {}
        for row in source:
            if set(row) != {"source_text", "source_group", "constructor_label", "depth"}:
                raise Invalid("source case shape")
            start, facts, group = parse(row["source_text"])
            if (row["source_group"] != group or group in by_group
                    or not isinstance(row["depth"], int) or not 2 <= row["depth"] <= 6):
                raise Invalid("source duplicate or edited")
            gold, path = reference(row["source_text"])
            if gold != row["constructor_label"]:
                raise Invalid("constructor label differs from independent public reference")
            by_group[group] = row
            controls = interventions(row["source_text"])
            for arm, candidate in controls.items():
                expected_hashes[(group, arm)] = sha(candidate)
                expected[(group, arm)] = reference(candidate)[0]
            if (expected[(group, "full")] != expected[(group, "distractor_removed")] or
                    expected[(group, "full")] == expected[(group, "truth_flipped")] or
                    expected[(group, "critical_removed")] == expected[(group, "full")] or
                    expected[(group, "question_only")] is not None):
                raise Invalid("causal controls are non-discriminative")
        if sorted(by_group) != tests:
            raise Invalid("source cases do not cover the heldout test groups")
        observations = run.get("observations")
        if not isinstance(observations, list) or len(observations) != 64 * 5 * 2:
            raise Invalid("incomplete raw observations")
        tallies = {policy: {arm: dict(n=0, correct=0, abstain=0, steps=0, candidate_scores=0, wall_ns=0)
                             for arm in ARMS} for policy in POLICIES}
        seen = set()
        for row in observations:
            if set(row) != {"group", "depth", "policy", "arm", "expected", "answer", "status",
                            "source_sha256", "steps", "candidate_scores", "wall_ns"}:
                raise Invalid("observation member changed")
            group, arm, policy = row["group"], row["arm"], row["policy"]
            key = (group, arm, policy)
            if (group not in by_group or arm not in ARMS or policy not in POLICIES
                    or key in seen or row["source_sha256"] != expected_hashes.get((group, arm))
                    or row["expected"] != expected.get((group, arm))
                    or row["depth"] != by_group[group]["depth"]):
                raise Invalid("wrong raw source identity/causal arm/repeated score")
            seen.add(key)
            if (row["answer"] is not None and row["answer"] not in "ABCDEFGH") or (
                    (row["status"] == "supported") != (row["answer"] is not None)):
                raise Invalid("answer/status inconsistency")
            for field in ("steps", "candidate_scores", "wall_ns"):
                if type(row[field]) is not int or row[field] < 0:
                    raise Invalid("invalid work/clock observation")
            tally = tallies[policy][arm]
            tally["n"] += 1
            tally["correct"] += int(row["answer"] == row["expected"])
            tally["abstain"] += int(row["answer"] is None)
            for field in ("steps", "candidate_scores", "wall_ns"):
                tally[field] += row[field]
        if tallies != run.get("summary"):
            raise Invalid("self-reported summary does not match independent case replay")
        receipts.append({"seed": run["seed"], "cases": len(by_group),
                         "observations": len(observations), "scores": tallies,
                         "source_group_independence": "hash_partition_only_not_future_time",
                         "real_pretrained_stem_verified": False})
    return {"schema": "hepta.group.proof-step-independent-consistency.v1", "runs": receipts,
            "external_original_source_authentication": False,
            "model_execution_attestation": False, "real_multimodal_or_NDU_gain": False,
            "production_promotion_permitted": False, "authority": "DENY_ALL"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    raw = Path(args.input).read_bytes()
    if not 0 < len(raw) <= 16 * 1024 * 1024:
        raise Invalid("unbounded input")
    result = audit(strict_json(raw))
    out = Path(args.output)
    if out.exists():
        raise Invalid("write-once independent output required")
    out.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")))
    print(json.dumps({"review_sha256": sha(out.read_text()), "source_sha256": sha256(raw).hexdigest(),
                      "independently_reviewed": len(result["runs"])}))


if __name__ == "__main__":
    main()

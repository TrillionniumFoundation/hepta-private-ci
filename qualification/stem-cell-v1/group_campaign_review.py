"""Standard-library-only replay of symbolic labels and campaign bookkeeping.

This checks recorded predictions against independently parsed public evidence.
It does not attest that model execution produced those recorded predictions.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


ARMS = ("static", "wide", "fixed", "adaptive", "ndu", "no_verifier", "reset_state", "split")
CORE_ARMS = {"fixed", "adaptive", "ndu", "no_verifier", "reset_state"}
INVALID_STATUSES = {"budget_exhausted", "callback_failed", "resource_budget_stop",
                    "ndu_stop:expired_policy", "ndu_stop:continuation_support_violated"}
COMPOSITION_PROMPT = "Combine LEFT and RIGHT: solve each task, map A=0 B=1 C=2 D=3 E=4 F=5 G=6 H=7, add modulo 8, and return the resulting class."


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _parse(case, missing=False, check_source=True):
    lines = case["text"].splitlines()
    if not lines:
        raise ValueError("empty public case")
    family, facts, canonical = case["family"], [], None
    if family == "composition":
        if lines[0] != COMPOSITION_PROMPT or case["text"].count("\n[LEFT]\n") != 1 or case["text"].count("\n[RIGHT]\n") != 1:
            raise ValueError("unrecognized composition query")
        left, right = case["text"].split("\n[LEFT]\n", 1)[1].split("\n[RIGHT]\n")
        children = []
        for text in (left, right):
            child_family = "dependency" if text.startswith("Start at ") else "constraint" if text.startswith("Which class ") else "temporal"
            children.append(_parse(dict(family=child_family, text=text), check_source=False))
        if children[0][1][0] == children[1][1][0]:
            raise ValueError("composition must combine different task families")
        query = ("sum_mod", 8)
        answer = chr(65 + (children[0][0] + children[1][0]) % 8)
        canonical = json.dumps([family, query, [["test/" + source[:20], source]
                                               for _, _, source in children]], separators=(",", ":"))
    elif family == "dependency":
        match = re.fullmatch(r"Start at (n\d+) and follow every link\. What is the endpoint class\? Answer one of A B C D E F G H\.", lines[0])
        if not match:
            raise ValueError("unrecognized dependency query")
        query = ("follow", match[1])
        for line in lines[1:]:
            link = re.fullmatch(r"(n\d+) links to (n\d+)\.", line)
            label = re.fullmatch(r"(n\d+) has class ([A-H])\.", line)
            if not link and not label:
                raise ValueError("unrecognized dependency fact")
            facts.append(("link", link[1], link[2]) if link else ("label", label[1], label[2]))
        links = {a: b for kind, a, b in facts if kind == "link"}
        labels = {a: b for kind, a, b in facts if kind == "label"}
        node, seen = query[1], set()
        while node in links and node not in seen:
            seen.add(node)
            node = links[node]
        answer = labels.get(node) if node not in seen else None
    elif family == "constraint":
        if lines[0] != "Which class satisfies every allowed-class constraint? Answer one of A B C D E F G H.":
            raise ValueError("unrecognized constraint query")
        query = ("intersection",)
        for line in lines[1:]:
            match = re.fullmatch(r"Constraint (\d+) allows ([A-H](?: [A-H])*)\.", line)
            if not match:
                raise ValueError("unrecognized constraint fact")
            facts.append(("allow", match[1], tuple(match[2].split())))
        allowed = [set(values) for _, _, values in facts]
        common = set.intersection(*allowed) if allowed else set()
        answer = next(iter(common)) if len(common) == 1 else None
    elif family == "temporal":
        match = re.fullmatch(r"What is the class of the last event for (sensor\d+) by time\? Answer one of A B C D E F G H\.", lines[0])
        if not match:
            raise ValueError("unrecognized temporal query")
        query = ("latest", match[1])
        for line in lines[1:]:
            event = re.fullmatch(r"At time (\d+), (sensor\d+) has class ([A-H])\.", line)
            if not event:
                raise ValueError("unrecognized temporal fact")
            facts.append((event[2], int(event[1]), event[3]))
        events = [(time, label) for entity, time, label in facts if entity == query[1]]
        answer = max(events)[1] if events else None
    else:
        raise ValueError("unknown public task family")
    if missing:
        if facts or answer is not None:
            raise ValueError("deleted-evidence input retained evidence")
        return None, query, None
    if answer is None:
        raise ValueError("public evidence does not uniquely support a label")
    if canonical is None:
        canonical = json.dumps([family, query, sorted(facts)], separators=(",", ":"))
    source = hashlib.sha256(canonical.encode()).hexdigest()
    if check_source and source != case["source_group"]:
        raise ValueError("public case source digest differs from parsed evidence")
    return ord(answer) - 65, query, source


def _summary(rows):
    times = sorted(r["wall_ns"] for r in rows)
    return dict(n=len(rows), correct=sum(r["success"] for r in rows),
                verifier_calls=sum(r["verifier_calls"] for r in rows), steps=sum(r["steps"] for r in rows),
                cpu_ns=sum(r["cpu_ns"] for r in rows), wall_ns=sum(times),
                observed_p50_ns=times[len(times) // 2],
                observed_p95_ns=times[min(len(times) - 1, int(.95 * len(times)))],
                tail_quantiles_are_target_host_certification=False,
                statuses=dict(Counter(r["status"] for r in rows)))


def review(root):
    root = Path(root)
    protocol, rows, report = [json.loads((root / name).read_text()) for name in
                              ("protocol.json", "observations.json", "report.json")]
    if report["protocol_sha256"] != _digest(protocol):
        raise ValueError("protocol/report digest mismatch")
    public = protocol["public_cases"]
    if set(public) != {"train", "validation", "selection", "test", "long", "deleted", "composition"}:
        raise ValueError("complete public cohorts required")
    cases, labels, queries, groups = {}, {}, {}, {}
    for cohort, entries in public.items():
        cases[cohort] = {case["case_id"]: case for case in entries}
        if not entries or len(cases[cohort]) != len(entries):
            raise ValueError("empty or duplicate public cases")
        groups[cohort] = {case["source_group"] for case in entries}
        if len(groups[cohort]) != len(entries) or sorted(groups[cohort]) != sorted(protocol["source_groups"][cohort]):
            raise ValueError("source-group membership differs")
        labels[cohort], queries[cohort] = {}, {}
        for case in entries:
            answer, query, _ = _parse(case, cohort == "deleted")
            labels[cohort][case["case_id"]], queries[cohort][case["case_id"]] = answer, query
    original = [name for name in public if name != "deleted"]
    if any(groups[a] & groups[b] for i, a in enumerate(original) for b in original[i + 1:]):
        raise ValueError("source group crossed independent cohorts")
    if set(cases["deleted"]) != set(cases["test"]):
        raise ValueError("deleted cohort is not paired to original test")
    for case_id, deleted in cases["deleted"].items():
        source = cases["test"][case_id]
        if (deleted["source_group"] != source["source_group"] or deleted["family"] != source["family"]
                or queries["deleted"][case_id] != queries["test"][case_id]):
            raise ValueError("deleted cohort changed its original task")
    expected = {(cohort, arm, case_id) for cohort in ("selection", "test", "long", "deleted", "composition")
                for arm in (("fixed", "split") if cohort == "selection" else ARMS) for case_id in cases[cohort]}
    seen, grouped, model_hashes, features = set(), {}, {}, {}
    for row in rows:
        key = row["cohort"], row["arm"], row["case_id"]
        if key not in expected or key in seen:
            raise ValueError("unexpected or duplicate cohort/arm/case row")
        seen.add(key)
        cohort, arm, case_id = key
        case = cases[cohort][case_id]
        if row["source_group"] != case["source_group"] or row["family"] != case["family"]:
            raise ValueError("row changed public case membership")
        for field in ("wall_ns", "cpu_ns", "steps", "search_formula_work"):
            if type(row[field]) is not int or row[field] <= 0:
                raise ValueError("each prediction needs nonzero actual timing/work/counts")
        if type(row["verifier_calls"]) is not int or row["verifier_calls"] < 0:
            raise ValueError("raw verifier callback count required")
        if type(row["prediction"]) is not int or not -1 <= row["prediction"] < 8 or type(row["success"]) is not bool:
            raise ValueError("typed prediction and success required")
        target = labels["test" if cohort == "deleted" else cohort][case_id]
        correct = row["prediction"] == target
        valid = row["status"] not in INVALID_STATUSES
        if (type(row["candidate_correct"]) is not bool or type(row["valid_execution"]) is not bool
                or row["candidate_correct"] != correct or row["valid_execution"] != valid
                or row["success"] != (correct and valid)):
            raise ValueError("recorded success differs from independent symbolic replay")
        model_key = "core" if arm in CORE_ARMS else arm
        model_hashes.setdefault(model_key, set()).add(row["model_sha256"])
        features.setdefault((cohort, case_id), set()).add(row["feature_sha256"])
        grouped.setdefault(f"{cohort}.{arm}", []).append(row)
    if seen != expected or any(len(values) != 1 for values in (*model_hashes.values(), *features.values())):
        raise ValueError("missing arm/case rows or changed model/feature bindings")
    for case_id in cases["test"]:
        if features[("test", case_id)] == features[("deleted", case_id)]:
            raise ValueError("deleted-evidence execution reused original feature binding")
    summaries = {key: _summary(values) for key, values in grouped.items()}
    if report["summaries"] != summaries:
        raise ValueError("reported aggregate differs from raw cases")
    test_texts = {case["text"] for case in public["test"]}
    composition_known = all(body in test_texts for case in public["composition"]
                            for body in case["text"].split("\n[LEFT]\n", 1)[1].split("\n[RIGHT]\n"))
    return dict(schema="hepta.group.independent-symbolic-review.v1", passed=True,
                protocol_sha256=_digest(protocol), observation_rows=len(rows), summaries=summaries,
                independent_symbolic_label_replay=True, complete_cohort_arm_membership=True,
                frozen_core_hash_consistent=True, actual_nonzero_cost_rows_checked=True,
                future_natural_task_gain_established=False, multimodal_efficacy_established=False,
                real_future_efficacy_established=False, natural_task_efficacy_established=False,
                model_execution_independently_attested=False,
                composition_uses_known_component_evidence=composition_known,
                verifier_is_programmatic_correctness_oracle=True,
                cost_scope="recorded timing/count consistency; not independent hardware measurement")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = review(args.root)
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()

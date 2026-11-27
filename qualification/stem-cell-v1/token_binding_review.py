"""Independent semantic audit of the generated ownership/storage binding task.

The exact public grammar is solved only here, outside model execution. Synthetic
paired-world success does not establish natural MultiRC or general reasoning.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

from token_review import _binary, _sha, require, score


_OWNERSHIP = re.compile(r"The ([A-Za-z]+) belongs to ([A-Za-z]+)\.")
_STORAGE = re.compile(r"([A-Za-z]+) stores all their possessions in the ([A-Za-z]+) box\.")
_QUESTION = re.compile(r"Where is the ([A-Za-z]+) stored\?")
_CANDIDATE = re.compile(r"The ([A-Za-z]+) box\.")
_PARAGRAPH = re.compile(r"(binding-v4/(train|tune|final)/-?\d+/\d+)/world-([01])")


def _truth(case):
    require(case["segmentation"] == "synthetic-ownership-storage-v1", "registered synthetic grammar required")
    paragraph = _PARAGRAPH.fullmatch(case["paragraph_id"])
    require(paragraph is not None, "registered paired-world identity required")
    identity = json.loads(case["case_id"])
    require(isinstance(identity, list) and len(identity) == 4 and identity[1] == case["paragraph_id"]
            and identity[2] == "0" and identity[3] in ("0", "1")
            and identity[0] == ("validation" if paragraph[2] == "final" else "train"),
            "case identity differs from registered synthetic source")
    facts = case["facts"]
    require(isinstance(facts, list) and len(facts) == 4 and all(type(f) is str for f in facts), "four complete public facts required")
    _sha(case["source_hash"])
    require(hashlib.sha256("\n".join(facts).encode()).hexdigest() == case["source_hash"], "synthetic evidence source changed")
    owners, storage = {}, {}
    for fact in facts:
        ownership, stored = _OWNERSHIP.fullmatch(fact), _STORAGE.fullmatch(fact)
        require(ownership is not None or stored is not None, "fact outside exact controlled grammar")
        if ownership:
            require(ownership[1] not in owners, "duplicate ownership fact")
            owners[ownership[1]] = ownership[2]
        else:
            require(stored[1] not in storage, "duplicate storage fact")
            storage[stored[1]] = stored[2]
    require(len(owners) == len(storage) == 2 and len(set(owners.values())) == 2
            and set(owners.values()) == set(storage) and len(set(storage.values())) == 2,
            "two distinct objects, people and boxes required")
    question, candidate = _QUESTION.fullmatch(case["question"]), _CANDIDATE.fullmatch(case["candidate"])
    require(question is not None and question[1] in owners and candidate is not None
            and candidate[1] in storage.values(), "complete controlled question/candidate required")
    target = int(storage[owners[question[1]]] == candidate[1])
    require(_binary(case["label"]) == target, "synthetic target contradicts independently solved public facts")
    return dict(target=target, question_key=tuple(identity[:3]), prefix=paragraph[1],
                world=paragraph[3], boxes=frozenset(storage.values()), words=Counter(" ".join(facts).split()))


def review_binding(cases_json, observations_json, report_json):
    cases = json.loads(Path(cases_json).read_text())
    rows = json.loads(Path(observations_json).read_text())
    report = json.loads(Path(report_json).read_text())
    require(isinstance(cases, list) and cases and isinstance(rows, list) and rows, "complete raw controlled cases/predictions required")
    official, public, pair_cases, worlds = {}, {}, defaultdict(dict), defaultdict(list)
    for case in cases:
        key = case["case_id"]
        require(key not in official, "duplicate controlled candidate")
        truth = _truth(case)
        official[key], public[key] = truth, case
        worlds[truth["question_key"]].append(case)
        pair_key = (truth["prefix"], case["question"], case["candidate"])
        require(truth["world"] not in pair_cases[pair_key], "duplicate candidate in paired world")
        pair_cases[pair_key][truth["world"]] = key
    for question, members in worlds.items():
        require(len(members) == 2 and {official[c["case_id"]]["target"] for c in members} == {0, 1}
                and {c["candidate"] for c in members} == {"The " + box + " box." for box in official[members[0]["case_id"]]["boxes"]}
                and len({c["source_hash"] for c in members}) == 1,
                "each world requires complete distinct box candidates on the same facts")
    for pair in pair_cases.values():
        require(set(pair) == {"0", "1"}, "both evidence worlds required")
        a, b = pair["0"], pair["1"]
        require(official[a]["target"] != official[b]["target"] and official[a]["words"] == official[b]["words"]
                and public[a]["facts"] != public[b]["facts"], "opposite-label equal-word-count worlds required")
    panels, model_ids = defaultdict(list), defaultdict(set)
    for row in rows:
        require(row["case_id"] in official, "unregistered controlled candidate")
        require(row["valid"] is True, "invalid controlled execution")
        _binary(row["prediction"])
        p = row["p_positive"]
        require(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1, "finite controlled probability required")
        if "raw_argmax" in row:
            require(_binary(row["raw_argmax"]) == int(p > .5), "raw probability threshold changed")
        if "target" in row:
            require(row["target"] == official[row["case_id"]]["target"], "controlled observation target changed")
        for field in ("model_sha256", "feature_sha256", "protocol_sha256"):
            _sha(row[field])
        require(row["protocol_sha256"] == report["protocol_sha256"], "controlled protocol changed")
        panels[(row["cohort"], row["arm"])].append(row)
        model_ids[row["arm"]].add(row["model_sha256"])
    require(all(len(values) == 1 for values in model_ids.values()), "controlled model changed between panels")
    arms, cohorts = {arm for _, arm in panels}, {cohort for cohort, _ in panels}
    require(set(panels) == {(cohort, arm) for cohort in cohorts for arm in arms}, "missing controlled cohort/arm panel")
    summaries = {}
    for (cohort, arm), panel in panels.items():
        require(len(panel) == len(official) and {r["case_id"] for r in panel} == set(official), "incomplete controlled candidate panel")
        summary = score(panel, official)
        predictions = {r["case_id"]: r["prediction"] for r in panel}
        summary.update(paired_candidates=len(pair_cases),
            evidence_switch_rate=sum(predictions[pair["0"]] != predictions[pair["1"]] for pair in pair_cases.values()) / len(pair_cases),
            both_worlds_correct=sum(all(predictions[key] == official[key]["target"] for key in pair.values()) for pair in pair_cases.values()) / len(pair_cases))
        name = cohort + "." + arm
        declared = report["summaries"][name]
        for field in ("questions", "f1_a", "exact_match", "accuracy", "paired_candidates", "evidence_switch_rate", "both_worlds_correct"):
            require(field in declared and type(declared[field]) in (int, float) and
                    math.isclose(declared[field], summary[field], rel_tol=0, abs_tol=1e-12),
                    "controlled metric differs from independently solved labels: " + name + "." + field)
        require(declared.get("n", declared.get("candidates")) == len(official), "controlled candidate count changed")
        summaries[name] = summary
    require(set(summaries) == set(report["summaries"]), "report includes unreviewed controlled panel")
    return dict(schema="hepta.token-binding.independent-review.v1", passed=True,
        controlled_cases=len(cases), controlled_pairs=len(pair_cases), observation_rows=len(rows),
        semantic_targets_independently_rederived=True, equal_word_count_worlds=True,
        complete_worlds_and_candidates=True, summaries=summaries,
        natural_multirc_generalization=False, model_execution_independently_attested=False,
        threshold_selection_independently_audited=False, physical_costs_audited_here=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    result = review_binding(args.folder / "controlled-cases.json", args.folder / "observations.json", args.folder / "report.json")
    (args.folder / "independent-binding-review.json").write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(passed=True, controlled_pairs=result["controlled_pairs"])))


if __name__ == "__main__":
    main()

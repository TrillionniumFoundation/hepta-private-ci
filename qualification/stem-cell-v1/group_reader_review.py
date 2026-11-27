"""Independent standard-library MultiRC metrics, provenance and cost review.

Targets are reread from pinned official JSONL bytes, without training/data module
imports. Hash agreement does not attest model execution or authenticate timing.
The controller's binary-correctness surrogate is not the nonadditive F1 objective.
"""
import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    _require(type(value) is str and len(value) == 64
             and all(c in "0123456789abcdef" for c in value), "SHA256 identity required")


def _binary(value):
    _require(type(value) is int and value in (0, 1), "typed binary label/prediction required")
    return value


def _question_key(row):
    try:
        identity = json.loads(row["case_id"])
        if isinstance(identity, list) and len(identity) == 4:
            return tuple(identity[:3])
    except (ValueError, TypeError):
        pass
    return row["source_hash"], str(row.get("paragraph_id", "")), str(row["question_id"])


def _metrics(rows, predictions):
    counts = Counter()
    questions = defaultdict(list)
    for row, prediction in zip(rows, predictions):
        target = _binary(row["target"])
        prediction = _binary(prediction)
        counts[(prediction, target)] += 1
        questions[_question_key(row)].append(prediction == target)
    tp, fp, fn, tn = (counts[k] for k in ((1, 1), (1, 0), (0, 1), (0, 0)))
    denominator = 2 * tp + fp + fn
    return dict(n=len(rows), questions=len(questions),
                f1_a=2 * tp / denominator if denominator else 0.,
                exact_match=sum(all(v) for v in questions.values()) / len(questions),
                accuracy=(tp + tn) / len(rows),
                confusion=dict(tp=tp, fp=fp, fn=fn, tn=tn))


def score_multirc(rows, *, majority_prediction=0):
    """Global positive-class F1a and complete-question exact match, in [0,1].

    Caller must supply every candidate. This metric cannot infer missing options;
    ``review`` cross-checks full question membership against official source data.
    Majority prediction must be frozen from training, never estimated on rows.
    """
    _require(isinstance(rows, (list, tuple)) and rows, "nonempty answer rows required")
    _binary(majority_prediction)
    ids = [r["case_id"] for r in rows]
    _require(len(ids) == len(set(ids)), "duplicate answer identity")
    result = _metrics(rows, [r["prediction"] for r in rows])
    result["baselines"] = {name: _metrics(rows, [label] * len(rows)) for name, label in
                           (("all_positive", 1), ("all_negative", 0),
                            ("training_majority", majority_prediction))}
    return result


def _official_sources(source_dir, file_hashes):
    cases, questions = {}, defaultdict(set)
    _require(isinstance(file_hashes, dict) and file_hashes, "pinned dataset file hashes required")
    for name, expected in file_hashes.items():
        _sha(expected)
        relative = Path(name)
        _require(not relative.is_absolute() and ".." not in relative.parts, "dataset path escapes source directory")
        path = source_dir / relative
        data = path.read_bytes()
        _require(hashlib.sha256(data).hexdigest() == expected, "official dataset bytes changed")
        if path.name not in ("train.jsonl", "val.jsonl", "validation.jsonl"):
            continue
        split = "train" if path.name == "train.jsonl" else "validation"
        for line in data.decode("utf-8").splitlines():
            record = json.loads(line)
            paragraph_id = str(record["idx"])
            passage = record["passage"]
            source = hashlib.sha256(passage["text"].encode("utf-8")).hexdigest()
            for question in passage["questions"]:
                question_id = str(question["idx"])
                for answer in question["answers"]:
                    answer_id = str(answer["idx"])
                    case_id = json.dumps([split, paragraph_id, question_id, answer_id], separators=(",", ":"))
                    _require(case_id not in cases, "duplicate official answer identity")
                    cases[case_id] = dict(source_hash=source, paragraph_id=paragraph_id,
                                          question_id=question_id, answer_id=answer_id,
                                          target=_binary(answer["label"]))
                    questions[(split, paragraph_id, question_id)].add(case_id)
    _require(cases, "no labeled official train/validation examples found")
    return cases, questions


def review(folder, *, source_dir, code_dir=None):
    """Reject leakage, partial questions, changed labels, invalid runs or cost caps.

    Every expected cohort/arm must contain exactly the frozen final case IDs.
    Null formula work remains null if any request lacks complete work coverage.
    CPU/wall totals are recorded consumption, not declared budget equivalence.
    """
    folder, source_dir = Path(folder), Path(source_dir)
    code_dir = Path(code_dir) if code_dir else Path(__file__).resolve().parent
    protocol = json.loads((folder / "protocol.json").read_text())
    report = json.loads((folder / "report.json").read_text())
    rows = json.loads((folder / "observations.json").read_text())
    _require(isinstance(rows, list) and rows, "complete raw observations required")
    protocol_sha = _digest(protocol)
    _require(report.get("protocol_sha256") == protocol_sha, "report protocol changed")
    _require(isinstance(protocol.get("selected_hyperparameters"), dict)
             and protocol["selected_hyperparameters"], "frozen selected hyperparameters required")
    source_hashes = protocol.get("source_sha256")
    _require(isinstance(source_hashes, dict) and source_hashes, "implementation hashes required")
    for name, expected in source_hashes.items():
        _sha(expected)
        relative = Path(name)
        _require(not relative.is_absolute() and ".." not in relative.parts, "code path escapes source directory")
        _require(hashlib.sha256((code_dir / relative).read_bytes()).hexdigest() == expected,
                 "recorded implementation source changed")
    partitions = protocol["partitions"]
    owners = {}
    for partition, sources in partitions.items():
        _require(isinstance(sources, list) and len(sources) == len(set(sources)), "duplicate partition source")
        for source in sources:
            _sha(source)
            _require(source not in owners, "paragraph source leaked across partitions")
            owners[source] = partition
    official, official_questions = _official_sources(source_dir, protocol["dataset_files_sha256"])
    final_ids = protocol["final_case_ids"]
    _require(isinstance(final_ids, list) and final_ids and len(final_ids) == len(set(final_ids)),
             "unique final case membership required")
    final_ids = set(final_ids)
    _require(final_ids <= set(official), "final case absent from official labeled source")
    selected_questions = defaultdict(set)
    final_partition = protocol.get("final_partition", "final")
    for case_id in final_ids:
        case = official[case_id]
        _require(owners.get(case["source_hash"]) == final_partition,
                 "final paragraph not exclusively held out")
        selected_questions[tuple(json.loads(case_id)[:3])].add(case_id)
    _require(all(ids == official_questions[key] for key, ids in selected_questions.items()),
             "final question omits official answer candidates")
    registered = protocol["final_question_candidate_ids"]
    _require(isinstance(registered, dict) and len(registered) == len(selected_questions),
             "complete final question registration required")
    registered_sets = []
    for candidates in registered.values():
        _require(isinstance(candidates, list) and candidates and len(candidates) == len(set(candidates)),
                 "unique full question candidate list required")
        registered_sets.append(frozenset(candidates))
    _require(set(registered_sets) == {frozenset(v) for v in selected_questions.values()},
             "question registration differs from official full candidate sets")
    majority = _binary(protocol["training_majority_prediction"])
    arms, cohorts = protocol["expected_arms"], protocol["expected_cohorts"]
    _require(arms and cohorts and len(arms) == len(set(arms)) and len(cohorts) == len(set(cohorts)),
             "unique expected arms and cohorts required")
    transforms = protocol.get("arm_input_transforms", {arm: "identity" for arm in arms})
    _require(set(transforms) == set(arms) and all(value in ("identity", "delete_evidence")
              for value in transforms.values()), "complete registered arm input transforms required")
    public_features = protocol.get("public_feature_sha256")
    if "arm_input_transforms" in protocol:
        _require(isinstance(public_features, dict) and set(public_features) == set(cohorts),
                 "frozen canonical public feature identities required")
    if public_features is not None:
        for cohort, identities in public_features.items():
            _require(cohort in cohorts and isinstance(identities, dict) and set(identities) == final_ids,
                     "complete canonical feature membership required")
            for identity in identities.values():
                _sha(identity)
    panels, models, features = defaultdict(list), defaultdict(set), defaultdict(set)
    invalid_statuses = {"callback_failed", "resource_budget_stop", "failed", "timed_out", "unknown"}
    for row in rows:
        _require(row["arm"] in arms and row["cohort"] in cohorts, "unexpected arm/cohort")
        case_id = row["case_id"]
        _require(case_id in final_ids, "unexpected final answer identity")
        for key in ("source_hash", "paragraph_id", "question_id", "answer_id", "target"):
            _require(row[key] == official[case_id][key], "observation changed official identity or target")
        _binary(row["prediction"])
        _require(row["valid"] is True and type(row["status"]) is str
                 and row["status"] not in invalid_statuses and "support_violated" not in row["status"],
                 "invalid/fallback request cannot count as successful reviewed execution")
        _require(row["protocol_sha256"] == protocol_sha, "observation protocol changed")
        for key in ("model_sha256", "feature_sha256"):
            _sha(row[key])
        for key in ("steps", "cpu_ns", "wall_ns"):
            _require(type(row[key]) is int and row[key] > 0, "actual positive request work/time required")
        child_cpu = row.get("native_child_cpu_ns")
        if child_cpu is not None:
            _require(type(child_cpu) is int and child_cpu >= 0, "nonnegative native child CPU required")
        if "native_subprocess_wall_ns" in row:
            native_wall = row["native_subprocess_wall_ns"]
            _require(type(native_wall) is int and 0 <= native_wall <= row["wall_ns"],
                     "native wall must be a subset of online wall, never an extra charge")
        if "total_online_cpu_ns" in row:
            expected_cpu = row["cpu_ns"] + child_cpu if child_cpu is not None else None
            _require(row["total_online_cpu_ns"] == expected_cpu,
                     "online CPU must include measured child CPU or remain null")
        work = row["formula_flops"]
        _require(work is None or type(work) is int and work >= 0, "formula work must be nonnegative or null")
        panels[(row["cohort"], row["arm"])].append(row)
        models[row["arm"]].add(row["model_sha256"])
        effective_cohort = "deleted" if transforms[row["arm"]] == "delete_evidence" else row["cohort"]
        if public_features is not None:
            _require(effective_cohort in public_features
                     and row["feature_sha256"] == public_features[effective_cohort][case_id],
                     "observation feature differs from its registered effective input")
        features[(effective_cohort, case_id)].add(row["feature_sha256"])
    expected = {(cohort, arm) for cohort in cohorts for arm in arms}
    _require(set(panels) == expected, "missing cohort/arm panel")
    _require(all(len(v) == 1 for v in models.values()), "selected model changed during final evaluation")
    _require(all(len(v) == 1 for v in features.values()), "shared feature identity changed across arms")
    if "arm_model_sha256" in protocol:
        _require({a: next(iter(v)) for a, v in models.items()} == protocol["arm_model_sha256"],
                 "final model differs from frozen selection")
    summaries = {}
    for (cohort, arm), panel in panels.items():
        _require(len(panel) == len(final_ids) and {r["case_id"] for r in panel} == final_ids,
                 "missing/duplicated candidate in a final panel")
        summary = score_multirc(panel, majority_prediction=majority)
        summary.update({key: sum(r[key] for r in panel) for key in ("steps", "cpu_ns", "wall_ns")})
        summary["formula_flops"] = (sum(r["formula_flops"] for r in panel)
                                    if all(r["formula_flops"] is not None for r in panel) else None)
        for key in ("native_child_cpu_ns", "native_subprocess_wall_ns", "total_online_cpu_ns"):
            summary[key] = sum(r[key] for r in panel) if all(r.get(key) is not None for r in panel) else None
        name = cohort + "." + arm
        declared = report["summaries"][name]
        for key in ("n", "questions", "f1_a", "exact_match", "accuracy", "steps", "cpu_ns", "wall_ns", "formula_flops"):
            actual = summary[key]
            value = declared[key]
            _require(value == actual if actual is None or type(actual) is int
                     else type(value) in (int, float) and math.isclose(value, actual, rel_tol=0., abs_tol=1e-12),
                     "reported metrics/costs disagree with raw consumption: " + name + "." + key)
        for key in ("native_child_cpu_ns", "native_subprocess_wall_ns", "total_online_cpu_ns"):
            if key in declared:
                _require(declared[key] == summary[key], "reported native cost differs from actual consumption")
        summaries[name] = summary
    _require(set(report["summaries"]) == set(summaries), "report includes unreviewed panels")
    return dict(schema="hepta.reader.independent-review.v1", passed=True,
                protocol_sha256=protocol_sha, observation_rows=len(rows), summaries=summaries,
                official_label_replay=True, paragraph_source_held_out=True,
                complete_question_candidates=True, actual_cost_sums_checked=True,
                model_execution_independently_attested=False,
                feature_values_independently_recomputed=False,
                preregistration_time_independently_verified=False,
                cpu_scope="cpu_ns_is_parent_process; total_online_cpu_ns_requires_measured_child_CPU",
                goal="binary_correctness_surrogate_not_benchmark_F1_optimization",
                timing_scope="reported_online_consumption_not_equal_caps_or_full_lifecycle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--code-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = review(args.folder, source_dir=args.source_dir, code_dir=args.code_dir)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(json.dumps(dict(passed=False, error=str(exc))))
        return 2
    output = args.output or args.folder / "independent-review.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(passed=True, observation_rows=result["observation_rows"], output=str(output))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

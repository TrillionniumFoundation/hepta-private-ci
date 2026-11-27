"""Independent official-label, held-out, threshold and physical-batch review.

This standard-library audit does not authenticate model execution or timing.
Natural evidence deletion preserves official labels and measures sensitivity;
it does not manufacture counterfactual labels or establish causal reasoning.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    require(type(value) is str and len(value) == 64 and
            all(c in "0123456789abcdef" for c in value), "SHA256 identity required")


def _binary(value):
    require(type(value) is int and value in (0, 1), "typed binary prediction required")
    return value


def _relative(root, name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts, "relative source path required")
    return root / path


def _official(source_dir, file_hashes):
    require(isinstance(file_hashes, dict) and file_hashes, "pinned official dataset files required")
    cases, questions = {}, defaultdict(set)
    for name, expected in file_hashes.items():
        _sha(expected)
        path = _relative(source_dir, name)
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected, "official dataset bytes changed")
        if path.name not in ("train.jsonl", "val.jsonl", "validation.jsonl"):
            continue
        split = "train" if path.name == "train.jsonl" else "validation"
        for line in data.decode().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            source = hashlib.sha256(record["passage"]["text"].encode()).hexdigest()
            for question in record["passage"]["questions"]:
                for answer in question["answers"]:
                    identity = [split, str(record["idx"]), str(question["idx"]), str(answer["idx"])]
                    case_id = json.dumps(identity, separators=(",", ":"))
                    require(case_id not in cases, "duplicate official answer identity")
                    cases[case_id] = dict(source_hash=source, target=_binary(answer["label"]),
                                          question_key=tuple(identity[:3]), split=split)
                    questions[tuple(identity[:3])].add(case_id)
    require(cases, "no labeled official examples found")
    return cases, questions


def score(rows, official, *, prediction_field="prediction"):
    """Compute positive-class F1a and complete-question EM independently."""
    require(rows, "nonempty predictions required")
    require(len({r["case_id"] for r in rows}) == len(rows), "duplicate candidate in panel")
    counts, questions = Counter(), defaultdict(list)
    for row in rows:
        ref = official[row["case_id"]]
        target, predicted = ref["target"], _binary(row[prediction_field])
        counts[(predicted, target)] += 1
        questions[ref["question_key"]].append(predicted == target)
    tp, fp, fn, tn = (counts[key] for key in ((1, 1), (1, 0), (0, 1), (0, 0)))
    denominator = 2 * tp + fp + fn
    return dict(n=len(rows), questions=len(questions), f1_a=2 * tp / denominator if denominator else 0.,
                exact_match=sum(all(v) for v in questions.values()) / len(questions),
                accuracy=(tp + tn) / len(rows), confusion=dict(tp=tp, fp=fp, fn=fn, tn=tn))


def _membership(protocol, official, questions, previous_design):
    partitions, owners = protocol["partitions"], {}
    train_sources = {ref["source_hash"] for ref in official.values() if ref["split"] == "train"}
    validation_sources = {ref["source_hash"] for ref in official.values() if ref["split"] == "validation"}
    for name, sources in partitions.items():
        require(isinstance(sources, list) and len(sources) == len(set(sources)), "unique partition sources required")
        for source in sources:
            _sha(source)
            require(source in (validation_sources if name in ("final", "regression") else train_sources),
                    "partition source is not from its registered official split")
            require(source not in owners, "paragraph sources leaked across partitions")
            owners[source] = name
    ids = protocol["final_case_ids"]
    require(isinstance(ids, list) and ids and len(ids) == len(set(ids)), "unique held-out candidate membership required")
    require(set(ids) <= set(official), "held-out candidate absent from official data")
    final_partition = protocol.get("final_partition", protocol.get("evaluation_partition", "final"))
    selected_questions, selected_sources = defaultdict(set), set()
    for case_id in ids:
        ref = official[case_id]
        require(ref["split"] == "validation", "official validation partition required")
        require(owners.get(ref["source_hash"]) == final_partition, "held-out paragraph belongs to another partition")
        selected_questions[ref["question_key"]].add(case_id)
        selected_sources.add(ref["source_hash"])
    require(selected_sources == set(partitions[final_partition]), "held-out source membership incomplete")
    require(all(members == questions[key] for key, members in selected_questions.items()),
            "held-out question omits official answer candidates")
    # Require all questions in each selected paragraph, not just complete chosen questions.
    require(set(ids) == {key for key, ref in official.items() if ref["source_hash"] in selected_sources},
            "held-out paragraph omits official questions")
    registered = protocol["final_question_candidate_ids"]
    require(isinstance(registered, dict) and len(registered) == len(selected_questions), "complete question registration required")
    require(all(isinstance(v, list) and v and len(v) == len(set(v)) for v in registered.values()),
            "unique registered candidate lists required")
    require({frozenset(v) for v in registered.values()} == {frozenset(v) for v in selected_questions.values()},
            "question registration differs from full official membership")
    previous_sources = protocol["previous_final_source_hashes"]
    previous_ids = protocol["previous_final_case_ids"]
    require(isinstance(previous_sources, list) and len(previous_sources) == len(set(previous_sources)), "prior source identities required")
    require(isinstance(previous_ids, list) and len(previous_ids) == len(set(previous_ids)), "prior candidate identities required")
    require(set(previous_ids) <= set(official), "prior candidates absent from official data")
    require({official[key]["source_hash"] for key in previous_ids} == set(previous_sources), "prior source/candidate binding changed")
    if final_partition == "regression":
        require(set(ids) == set(previous_ids) and selected_sources == set(previous_sources), "regression differs from prior evaluation")
    else:
        require(not selected_sources & set(previous_sources) and not set(ids) & set(previous_ids),
                "previously evaluated paragraph reused in fresh held-out set")
    if previous_design is not None:
        raw = Path(previous_design).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == protocol["previous_design_sha256"], "prior design bytes changed")
        prior = json.loads(raw)
        require(set(prior["partitions"]["final"]) == set(previous_sources) and
                set(prior["final_case_ids"]) == set(previous_ids), "prior evaluation registration changed")
    return set(ids), final_partition


def _feature_identity(protocol, cohort, arm, case_id):
    transforms = protocol.get("arm_input_transforms", {})
    transform = transforms.get(arm, "identity")
    require(transform in ("identity", "delete_evidence"), "unknown arm input transform")
    effective = "deleted" if transform == "delete_evidence" else cohort
    registered = protocol["public_feature_sha256"][effective]
    return registered[arm][case_id] if arm in registered else registered[case_id]


def _same(actual, declared, name):
    if isinstance(actual, dict):
        require(isinstance(declared, dict), "reported summary object required: " + name)
        require(set(actual) - {"confusion"} <= set(declared), "reported nested summary omits audited metric: " + name)
        for key, value in actual.items():
            if key in declared:
                _same(value, declared[key], name + "." + key)
        return
    require(declared == actual if actual is None or type(actual) in (int, str, bool) else
            type(declared) in (int, float) and math.isclose(declared, actual, rel_tol=0., abs_tol=1e-12),
            "reported metric/cost disagrees with raw observations: " + name)


def review(folder, *, source_dir, code_dir=None, previous_design=None):
    folder, source_dir = Path(folder), Path(source_dir)
    code_dir = Path(code_dir) if code_dir is not None else Path(__file__).resolve().parent
    protocol = json.loads((folder / "protocol.json").read_text())
    report = json.loads((folder / "report.json").read_text())
    rows = json.loads((folder / "observations.json").read_text())
    batches = json.loads((folder / "inference-batches.json").read_text())
    require(isinstance(rows, list) and rows and isinstance(batches, list) and batches, "raw observations and physical batches required")
    protocol_sha = digest(protocol)
    require(report["protocol_sha256"] == protocol_sha, "report protocol changed")
    sources = protocol["source_sha256"]
    require(isinstance(sources, dict) and sources, "frozen implementation hashes required")
    for name, expected in sources.items():
        _sha(expected)
        require(hashlib.sha256(_relative(code_dir, name).read_bytes()).hexdigest() == expected, "implementation source changed")
    official, questions = _official(source_dir, protocol["dataset_files_sha256"])
    selection_review = None
    if (folder.parent / "tuning.json").exists():
        from token_selection_review import review_selection
        selection_review = review_selection(folder.parent, source_dir=source_dir)
        require(selection_review["arm_thresholds"] == protocol["arm_thresholds"] and
                selection_review["arm_model_sha256"] == protocol["arm_model_sha256"],
                "final protocol differs from independently replayed selection")
    ids, final_partition = _membership(protocol, official, questions, previous_design)
    arms, cohorts = protocol["expected_arms"], protocol["expected_cohorts"]
    require(arms and cohorts and len(arms) == len(set(arms)) and len(cohorts) == len(set(cohorts)), "unique expected arms/cohorts required")
    require(set(protocol["arm_model_sha256"]) == set(arms) and set(protocol["arm_thresholds"]) == set(arms)
            and set(protocol["arm_depths"]) == set(arms), "complete frozen model/threshold/depth bindings required")
    batch_map, references, panels, physical_panels = {}, defaultdict(list), defaultdict(list), defaultdict(list)
    for batch in batches:
        key = batch["batch_id"]
        require(type(key) is str and key and key not in batch_map, "unique physical inference batch identity required")
        require(batch["arm"] in arms and batch["cohort"] in cohorts, "unexpected physical batch panel")
        members = batch["case_ids"]
        require(isinstance(members, list) and members and len(members) == len(set(members)) and set(members) <= ids,
                "unique held-out physical batch members required")
        for name in ("cpu_ns", "wall_ns", "steps"):
            require(type(batch[name]) is int and batch[name] > 0, "actual positive physical batch cost/depth required")
        require(batch["steps"] == protocol["arm_depths"][batch["arm"]], "batch depth differs from frozen arm")
        work = batch.get("formula_flops")
        require(work is None or type(work) is int and work >= 0, "formula work must remain actual or null")
        batch_map[key] = batch
        physical_panels[(batch["cohort"], batch["arm"])].append(batch)
    for row in rows:
        arm, cohort, case_id = row["arm"], row["cohort"], row["case_id"]
        require(arm in arms and cohort in cohorts and case_id in ids, "unexpected final observation")
        require(row["valid"] is True, "invalid execution cannot count as successful review")
        require(row["protocol_sha256"] == protocol_sha, "observation protocol changed")
        p = row["p_positive"]
        require(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1, "finite probability in [0,1] required")
        threshold = protocol["arm_thresholds"][arm]
        require(type(threshold) in (int, float) and math.isfinite(threshold) and 0 < threshold < 1, "frozen probability threshold required")
        require(_binary(row["prediction"]) == int(p >= threshold), "prediction differs from frozen threshold")
        require(_binary(row["raw_argmax"]) == int(p > .5), "raw argmax differs from probability or tie rule")
        if "target" in row:
            require(row["target"] == official[case_id]["target"], "observation changed official target")
        if "source_hash" in row:
            require(row["source_hash"] == official[case_id]["source_hash"], "observation changed source binding")
        for name in ("model_sha256", "feature_sha256"):
            _sha(row[name])
        require(row["model_sha256"] == protocol["arm_model_sha256"][arm], "final model differs from frozen selection")
        require(row["feature_sha256"] == _feature_identity(protocol, cohort, arm, case_id), "feature differs from registered effective input")
        key = row["batch_id"]
        require(key in batch_map, "observation lacks physical inference receipt")
        batch = batch_map[key]
        require(batch["arm"] == arm and batch["cohort"] == cohort, "physical batch panel changed")
        references[key].append(case_id)
        panels[(cohort, arm)].append(row)
    require(set(references) == set(batch_map), "unreferenced physical inference batch")
    require(all(references[key] == batch["case_ids"] for key, batch in batch_map.items()), "physical batch order/membership differs from observations")
    expected = {(cohort, arm) for cohort in cohorts for arm in arms}
    require(set(panels) == expected and set(physical_panels) == expected, "missing final panel")
    summaries = {}
    for (cohort, arm), panel in panels.items():
        require(len(panel) == len(ids) and {r["case_id"] for r in panel} == ids, "missing/duplicated held-out candidate")
        summary = score(panel, official)
        summary["raw_argmax_metrics"] = score(panel, official, prediction_field="raw_argmax")
        physical = physical_panels[(cohort, arm)]
        summary.update(physical_batches=len(physical), cpu_ns=sum(b["cpu_ns"] for b in physical),
                       wall_ns=sum(b["wall_ns"] for b in physical),
                       proposal_steps=sum(len(b["case_ids"]) * b["steps"] for b in physical))
        name = cohort + "." + arm
        declared = report["summaries"][name]
        for key in ("n", "questions", "f1_a", "exact_match", "accuracy", "raw_argmax_metrics",
                    "physical_batches", "cpu_ns", "wall_ns", "proposal_steps"):
            require(key in declared, "reported summary omits audited metric: " + name + "." + key)
            _same(summary[key], declared[key], name + "." + key)
        summary["formula_flops"] = sum(b["formula_flops"] for b in physical) if all(b.get("formula_flops") is not None for b in physical) else None
        if "formula_flops" in declared:
            _same(summary["formula_flops"], declared["formula_flops"], name + ".formula_flops")
        summaries[name] = summary
    require(set(report["summaries"]) == set(summaries), "report includes unreviewed panels")
    interventions = {}
    if "full" in cohorts and "deleted" in cohorts:
        for arm in arms:
            full = {r["case_id"]: r for r in panels[("full", arm)]}
            deleted = {r["case_id"]: r for r in panels[("deleted", arm)]}
            shifts = [full[key]["p_positive"] - deleted[key]["p_positive"] for key in sorted(ids)]
            interventions[arm] = dict(candidate_pairs=len(ids), changed_predictions=sum(full[key]["prediction"] != deleted[key]["prediction"] for key in ids),
                mean_probability_shift=sum(shifts) / len(shifts), mean_absolute_probability_shift=sum(abs(v) for v in shifts) / len(shifts),
                full_minus_deleted_f1_a=summaries["full." + arm]["f1_a"] - summaries["deleted." + arm]["f1_a"],
                full_minus_deleted_exact_match=summaries["full." + arm]["exact_match"] - summaries["deleted." + arm]["exact_match"],
                label_policy="same_official_labels_sensitivity_only")
    baseline_rows = [dict(case_id=key, prediction=1) for key in sorted(ids)]
    return dict(schema="hepta.token-reader.independent-review.v1", passed=True, protocol_sha256=protocol_sha,
        observation_rows=len(rows), physical_inference_batches=len(batches), summaries=summaries,
        all_positive=score(baseline_rows, official), evidence_interventions=interventions,
        official_label_replay=True, complete_paragraph_candidates=True, final_partition=final_partition,
        prior_design_bytes_independently_checked=previous_design is not None,
        train_internal_selection_review=selection_review,
        physical_cost_counted_once=True, strict_equal_compute=False,
        model_execution_independently_attested=False, timing_independently_authenticated=False,
        natural_deletion_is_counterfactual_label_supervision=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--code-dir", type=Path)
    parser.add_argument("--previous-design", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = review(args.folder, source_dir=args.source_dir, code_dir=args.code_dir, previous_design=args.previous_design)
    output = args.output or args.folder / "independent-review.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(passed=True, observation_rows=result["observation_rows"], physical_batches=result["physical_inference_batches"])))


if __name__ == "__main__":
    main()

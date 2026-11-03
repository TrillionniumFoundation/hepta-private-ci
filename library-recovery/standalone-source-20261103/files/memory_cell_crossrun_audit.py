"""Read-only SHA-pinned cross-host reproducibility of two completed Qwen studies.

Neither a new model inference nor an independent source review. Research outcomes
are not independent because both source archives reuse the same authored tasks.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-cell.two-completed-run-crosshost.v1"
ORIGINAL_SHA = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
MODEL_REVISION = "82f42baa094a9600e39ccd80d34058aeeb3abbc1"
MODEL_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
PINS = {
    "earlier": {
        "run_id": 38224780900,
        "source_commit": "6304b451268c73f3d1a605985226b102df841bbf",
        "reader_zip": "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8",
        "replay_zip": "2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071",
        "reader_files": 43,
        "replay_files": 8,
    },
    "later": {
        "run_id": 38389920977,
        "source_commit": "3b03ea7dee4b270bdf328251f7a404571c9d1013",
        "reader_zip": "de7087dbd3ee367475ef279d01dbeeeea46ee991b11399324289300df10c40bf",
        "replay_zip": "442c7171cb2c522988e6e6c52b12201d1b59104702229dc256ca91b7bf6559c1",
        "reader_files": 43,
        "replay_files": 8,
    },
}
CAL = ("k1", "k2", "k3", "k4", "k6")
EVAL = (
    "selected_k", "hybrid_k4", "hybrid_k6", "hybrid_k4_reversed",
    "single_hop", "entity_time", "organized", "program_support", "empty",
)
SCORER_ONLY = {"parsed_identifier", "strict_task_success", "required_sources_covered", "procedure_verification"}
RAW_FIELDS = ("question_id", "arm", "answer", "selected", "candidate_digest", "status", "kind")
RECEIPT_FIELDS = (
    "reader_identity", "reader_profile", "token_limit", "input_ids_digest",
    "generated_ids_digest", "input_tokens", "generated_tokens", "delivered_evidence",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def verified_zip(path, expected_sha, expected_files):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("bounded regular ZIP required")
    if sha(path.read_bytes()) != expected_sha:
        raise ValueError("outer ZIP digest differs from external pin")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) != expected_files + 1 or sum(i.file_size for i in entries) > 64 * 1024 * 1024:
            raise ValueError("incorrect source file population")
        files = {}
        for item in entries:
            pos = PurePosixPath(item.filename)
            if (pos.is_absolute() or ".." in pos.parts or "\\" in item.filename
                    or item.is_dir() or stat.S_ISLNK(item.external_attr >> 16)
                    or str(pos) in files):
                raise ValueError("unsafe or duplicate archived file")
            files[str(pos)] = archive.read(item)
    if "SHA256SUMS" not in files:
        raise ValueError("missing SHA256SUMS")
    declared = {}
    for line in files["SHA256SUMS"].decode("ascii").splitlines():
        hit = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if hit is None:
            raise ValueError("malformed archived file digest")
        hash_value, name = hit.groups()
        if name in declared:
            raise ValueError("duplicate manifest entry")
        declared[name] = hash_value
    if set(declared) != set(files) - {"SHA256SUMS"}:
        raise ValueError("unlisted or missing archived file")
    for name, hashed in declared.items():
        if sha(files[name]) != hashed:
            raise ValueError("tampered inner archived file: " + name)
    return files


def full_census(archive, phase, arms):
    rawfile = archive[f"{phase}/raw-answers.jsonl"]
    if not rawfile.endswith(b"\n"):
        raise ValueError("incomplete original answer journal")
    raw = [strict_json(line) for line in rawfile.splitlines()]
    scored = strict_json(archive[f"{phase}/scored-answers.json"])
    ids = {r["question_id"] for r in raw}
    if (len(ids) != 8 or len(raw) != 8 * len(arms)
            or len(scored) != len(raw)
            or Counter((r["question_id"], r["arm"]) for r in raw)
               != Counter((qid, arm) for qid in ids for arm in arms)):
        raise ValueError("incomplete or duplicate task/arm population")
    for a, b in zip(raw, scored, strict=True):
        if a.get("status") != "succeeded":
            raise ValueError("uncompleted model call cannot be promoted")
        if {k: v for k, v in b.items() if k not in SCORER_ONLY} != a:
            raise ValueError("scorer rewrote original answer or evidence")
        if type(b.get("strict_task_success")) is not bool:
            raise ValueError("missing strict task result")
        rec = b["receipt"]
        if (rec["reader_identity"] != MODEL_ID or rec["token_limit"] != 2048
                or rec.get("trainable_parameters") != 0
                or rec.get("answer_postprocessed") is not False
                or type(rec["input_tokens"]) is not int):
            raise ValueError("different model, policy or reader budget")
    report = strict_json(archive[f"{phase}/report.json"])
    if report["raw_answers_sha256"] != sha(rawfile) or report["production_accepted"] is not False:
        raise ValueError("published report detached from original journal")
    stats = {}
    for arm in arms:
        observed = [r for r in scored if r["arm"] == arm]
        stats[arm] = dict(
            strict_success=sum(r["strict_task_success"] for r in observed),
            input_tokens=sum(r["receipt"]["input_tokens"] for r in observed),
            generated_tokens=sum(r["receipt"]["generated_tokens"] for r in observed),
            inference_seconds=sum(r["receipt"]["seconds"] for r in observed),
        )
        original = (report["arms"] if phase == "calibration" else report["success_by_arm"])[arm]
        for key in ("strict_success", "input_tokens", "inference_seconds"):
            if abs(original[key] - stats[arm][key]) > 1e-6:
                raise ValueError("reported score or cost contradicts raw records")
        if original["output_tokens"] != stats[arm]["generated_tokens"]:
            raise ValueError("reported generation budget contradicts original tokens")
    return { (r["question_id"], r["arm"]): r for r in scored}, stats, report


def comparable_pairs(first, second):
    if set(first) != set(second):
        raise ValueError("different calibration/evaluation populations")
    for key in first:
        a, b = first[key], second[key]
        for field in RAW_FIELDS:
            if a.get(field) != b.get(field):
                raise ValueError("not a byte-identical output/selection replication: " + str((key, field)))
        for field in RECEIPT_FIELDS:
            if a["receipt"].get(field) != b["receipt"].get(field):
                raise ValueError("changed prompt/model/decoded tokens: " + str((key, field)))
        if a["strict_task_success"] != b["strict_task_success"]:
            raise ValueError("task outcome drift")
    return len(first)


def audit(original_zip, earlier_reader, earlier_replay, later_reader, later_replay):
    originals = verified_zip(original_zip, ORIGINAL_SHA, 35)
    if sha(originals["plan/plan.json"]) != PLAN_SHA:
        raise ValueError("original preregistered test-plan pin mismatch")
    analyzed = {}
    for cohort, reader, replay in (
        ("earlier", earlier_reader, earlier_replay),
        ("later", later_reader, later_replay),
    ):
        pin = PINS[cohort]
        rr = verified_zip(reader, pin["reader_zip"], pin["reader_files"])
        audited = verified_zip(replay, pin["replay_zip"], pin["replay_files"])
        commit = rr["tested-commit.txt"].decode().strip()
        if commit != pin["source_commit"]:
            raise ValueError("different generating commit")
        stage = strict_json(rr["stage.json"])
        inventory = strict_json(rr["inventory.json"])
        if (stage["revision"] != MODEL_REVISION or stage["tier"] != "qwen-3b"
                or inventory["inventory_digest"] != MODEL_ID):
            raise ValueError("different licensed research reader")
        response = strict_json(audited["receipt.json"])
        if (response["generating_commit"] != commit or response["model_identity"] != MODEL_ID
                or response["calibration"]["attempts"] != 40
                or response["evaluation"]["attempts"] != 72
                or response["production_accepted"] is not False
                or response["independent_semantic_judge"] is not False):
            raise ValueError("missing complete independent read-only replay")
        cal, cal_stats, cal_report = full_census(rr, "calibration", CAL)
        ev, ev_stats, ev_report = full_census(rr, "evaluation", EVAL)
        choice = min((1, 2, 3, 4, 6), key=lambda k: (-cal_stats[f"k{k}"]["strict_success"], cal_stats[f"k{k}"]["input_tokens"], k))
        policy = strict_json(rr["calibration/frozen-policy.json"])
        if (policy["selected_k"] != choice or cal_report["frozen_k"] != choice
                or ev_report["selected_k"] != choice
                or response["calibration"]["strict_success"] != {arm: cal_stats[arm]["strict_success"] for arm in CAL}
                or response["evaluation"]["strict_success"] != {arm: ev_stats[arm]["strict_success"] for arm in EVAL}
                or response["paired_contrasts"] != ev_report["paired_contrasts"]
                or response["formal_citation_chain"] != ev_report["formal_citation_chain"]):
            raise ValueError("published policy/effects differ from authenticated originals")
        audited_citation = ev_report["formal_citation_chain"]["by_arm"]
        if any(audited_citation[arm]["strict_task_success"] != ev_stats[arm]["strict_success"] for arm in EVAL):
            raise ValueError("citation summary detached from model answers")
        host = strict_json(rr["host-qualification.json"])
        runtime = strict_json(rr["evaluation/runtime-preflight.json"])
        analyzed[cohort] = dict(
            commit=commit,
            run_id=pin["run_id"],
            model=MODEL_ID,
            host=host["cpu_models"],
            logical_cpu_records=host["logical_cpu_records"],
            torch_intra_op=runtime["torch"]["intra_op_threads"],
            torch_inter_op=runtime["torch"]["inter_op_threads"],
            selected_k=choice,
            calibration=cal,
            evaluation=ev,
            cal_stats=cal_stats,
            ev_stats=ev_stats,
            citation_by_arm=audited_citation,
            calibration_stable=cal_report["calibration_sensitivity"]["stable_to_one_calibration_case_removal"],
            replay_source_commit=response["generating_commit"],
        )
    earlier, later = analyzed["earlier"], analyzed["later"]
    if (earlier["selected_k"] != later["selected_k"]
            or earlier["citation_by_arm"] != later["citation_by_arm"]
            or earlier["calibration_stable"] != later["calibration_stable"]):
        raise ValueError("different frozen policy, citation outcome, or calibration stability")
    cal_matches = comparable_pairs(earlier["calibration"], later["calibration"])
    test_matches = comparable_pairs(earlier["evaluation"], later["evaluation"])
    all_arms = {}
    for arm in EVAL:
        old = earlier["ev_stats"][arm]
        new = later["ev_stats"][arm]
        if old["strict_success"] != new["strict_success"] or old["input_tokens"] != new["input_tokens"]:
            raise ValueError("nonreproducible answer or prompt cost")
        all_arms[arm] = dict(
            correct=old["strict_success"],
            complete_declared_citations=earlier["citation_by_arm"][arm]["correct_with_full_program_declared_citations"],
            prompt_tokens=old["input_tokens"],
            old_reader_seconds=round(old["inference_seconds"], 3),
            new_reader_seconds=round(new["inference_seconds"], 3),
            new_over_old_runtime_ratio=round(new["inference_seconds"] / old["inference_seconds"], 3),
        )
    return dict(
        schema=SCHEMA,
        artifacts={name: {k: v for k,v in pin.items() if k not in ("reader_files","replay_files")} for name,pin in PINS.items()},
        original_sha256=ORIGINAL_SHA,
        original_plan_sha256=PLAN_SHA,
        reader_id=MODEL_ID,
        matched_calibration_original_answers=cal_matches,
        matched_evaluation_original_answers=test_matches,
        all_original_answers_match=cal_matches == 40 and test_matches == 72,
        both_complete_independent_replays=True,
        selected_k=earlier["selected_k"],
        calibration_sensitive_to_one_case=not earlier["calibration_stable"],
        host_comparison={name: {k: v for k, v in row.items() if k in ("host","logical_cpu_records","torch_intra_op","torch_inter_op")} for name,row in analyzed.items()},
        per_arm=all_arms,
        full_path_vs_single_hop_task_gain=all_arms["entity_time"]["correct"] - all_arms["single_hop"]["correct"],
        full_organizer_vs_full_path_task_gain=all_arms["organized"]["correct"] - all_arms["entity_time"]["correct"],
        full_organizer_vs_full_path_complete_citation_gain=all_arms["organized"]["complete_declared_citations"]-all_arms["entity_time"]["complete_declared_citations"],
        full_organizer_prompt_tokens_saved=all_arms["entity_time"]["prompt_tokens"] - all_arms["organized"]["prompt_tokens"],
        inference_seconds_cross_host_incomparable=True,
        independent_task_families=0,
        independent_human_semantic_judgments=0,
        independent_future_windows=0,
        trainable_memory_optimizer_steps=0,
        full_lifecycle_cost=None,
        statistical_superiority_established=False,
        qualified_memory_accuracy_improvement=False,
        parametric_training_qualified=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original_zip", "earlier_reader", "earlier_replay", "later_reader", "later_replay"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.original_zip, args.earlier_reader, args.earlier_replay, args.later_reader, args.later_replay)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    print(json.dumps({k: result[k] for k in ("matched_calibration_original_answers", "matched_evaluation_original_answers", "full_organizer_vs_full_path_task_gain", "production_accepted")}, sort_keys=True))


if __name__ == "__main__":
    main()

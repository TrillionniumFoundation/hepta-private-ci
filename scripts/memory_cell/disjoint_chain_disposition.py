"""Read-only source-pinned disposition of the completed authored Qwen 40+72 trial.

This is not a semantic judge, new inference, training, or production admission.
The independent replay has already re-executed the bounded program evaluator;
this second audit verifies original answers and distinguishes evidence delivery
from citation *emission*, without repairing any model output.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

PROFILE = "hepta.memory-cell.disjoint-chain-disposition.v1"
SOURCE = "bc76ac57ba972bf105c71ddd997cd215cec5df2e"
PLAN = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfd827187c31ad1897"
MODEL = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
RELEASE_ZIP = "b6ccc6606bf9935d052fb78884560487d2030772572199d8a8fa38e516fcc8be"
AUDIT_ZIP = "373f51d12c29b7fbba39a050db6909eb6b9855e616228e4b4f4539e0749fee5c"
ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)
CAL_ARMS = ("k1", "k2", "k3", "k4", "k6")
KINDS = ("new_fact", "correction", "composition", "procedure")
SCORER_FIELDS = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)
SHA = re.compile(r"[0-9a-f]{64}\Z")


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload):
    def unique(pairs):
        row = {}
        for key, value in pairs:
            if key in row:
                raise ValueError("duplicate JSON key")
            row[key] = value
        return row

    def bad(value):
        raise ValueError("nonfinite JSON: " + value)

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON float")
        return number

    return json.loads(
        payload, object_pairs_hook=unique, parse_constant=bad, parse_float=finite
    )


def checked_zip(path, expected, *, count, expanded_limit=16 * 1024 * 1024):
    """Externally pinned ZIP, complete SHA256SUMS, no symlinks or path escapes."""
    path = Path(path)
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError("externally pinned sha256 required")
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 8 * 1024 * 1024
    ):
        raise ValueError("regular bounded original ZIP required")
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError("external original ZIP hash changed")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if (
            len(entries) != count + 1
            or sum(x.file_size for x in entries) > expanded_limit
        ):
            raise ValueError("incomplete original archive census")
        contents = {}
        for entry in entries:
            pos = PurePosixPath(entry.filename)
            if (
                pos.is_absolute()
                or ".." in pos.parts
                or "\\" in entry.filename
                or entry.is_dir()
                or stat.S_ISLNK(entry.external_attr >> 16)
                or str(pos) != entry.filename
                or entry.filename in contents
            ):
                raise ValueError("unsafe original ZIP entry")
            contents[entry.filename] = z.read(entry)
    manifest = contents.get("SHA256SUMS")
    if manifest is None:
        raise ValueError("no full original SHA256SUMS")
    pins = {}
    for line in manifest.decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([^\n]+)", line)
        if match is None or match.group(2) in pins:
            raise ValueError("invalid duplicate SHA256SUMS")
        pins[match.group(2)] = match.group(1)
    if set(pins) != set(contents) - {"SHA256SUMS"}:
        raise ValueError("incomplete inner manifest")
    if any(digest(contents[k]) != value for k, value in pins.items()):
        raise ValueError("original ZIP member changed")
    return contents


def rows(files, name, size):
    raw = files[name]
    if not raw.endswith(b"\n"):
        raise ValueError("incomplete answer journal")
    result = [strict_json(line) for line in raw.splitlines()]
    if len(result) != size:
        raise ValueError("original answer census differs")
    return result


def classify(row, case):
    """Missing required citations may be delivered-but-uncited or not delivered."""
    selected = row["selected"]
    delivered = row["receipt"]["delivered_evidence"]
    if [item["original_id"] for item in delivered] != selected:
        raise ValueError("delivered evidence differs from frozen selection")
    cited = case["cited_source_ids"]
    missing = case["missing_program_declared_support"]
    if (
        len(set(selected)) != len(selected)
        or len(set(cited)) != len(cited)
        or len(set(missing)) != len(missing)
        or not set(cited).issubset(selected)
        or set(missing) & set(cited)
    ):
        raise ValueError("inconsistent citation source identities")
    if case["question_id"] != row["question_id"] or case["arm"] != row["arm"]:
        raise ValueError("citation query identity drift")
    if (
        case["generation_status"] != row["status"]
        or case["strict_task_success"] != row["strict_task_success"]
    ):
        raise ValueError("citation success diverges from original answer")
    return {
        "delivered_but_uncited": sorted(set(missing) & set(selected)),
        "not_delivered": sorted(set(missing) - set(selected)),
    }


def reconcile(release, audit):
    """Fail-closed, model-free comparison of exact original and replay receipts."""
    read = lambda name: strict_json(release[name])
    reread = lambda name: strict_json(audit[name])
    cal, policy = (
        read("calibration/report.json"),
        read("calibration/frozen-policy.json"),
    )
    report = read("evaluation/report.json")
    replay, replay_shards = (
        reread("rag-original-reader-audit.json"),
        reread("rag-original-shard-replay.json"),
    )
    cal_raw = rows(release, "calibration/raw-answers.jsonl", 40)
    eval_raw = rows(release, "evaluation/raw-answers.jsonl", 72)
    scored = read("evaluation/scored-answers.json")
    if (
        not isinstance(scored, list)
        or len(scored) != 72
        or cal["source_commit"]
        != policy["source_commit"]
        != report["source_commit"]
        != SOURCE
        or replay["generating_commit"] != replay_shards["source_commit"] != SOURCE
        or replay["original_plan_sha256"] != policy["original_test_plan_sha256"] != PLAN
        or replay["model_identity"]
        != cal["reader_identity"]
        != policy["reader_identity"]
        != MODEL
        or report["total_attempts"]
        != replay["evaluation"]["attempts"]
        != replay_shards["evaluation_rows"]
        != 72
        or cal["planned_attempts"]
        != replay["calibration"]["attempts"]
        != replay_shards["calibration_rows"]
        != 40
        or policy["selected_k"] != cal["frozen_k"] != report["selected_k"]
        or policy["selected_k"] not in (1, 2, 3, 4, 6)
        or policy["frozen_before_evaluation"] is not True
        or policy["candidate_accepted"] is not False
        or replay_shards["shard_census"] != 32
        or replay_shards["source_byte_replay"] is not True
        or replay["verified_artifact_files"] != 272
        or digest(release["calibration/raw-answers.jsonl"]) != cal["raw_answers_sha256"]
        or digest(release["evaluation/raw-answers.jsonl"])
        != report["raw_answers_sha256"]
        or replay["evaluation"]["original_raw_sha256"] != report["raw_answers_sha256"]
        or replay["calibration"]["original_raw_sha256"] != cal["raw_answers_sha256"]
    ):
        raise ValueError("source/policy/answers/replay identity mismatch")
    for obj in (cal, policy, report, replay, replay_shards):
        if obj.get("production_accepted") is not False:
            raise ValueError("forged production acceptance")
    if (
        report["independent_source_family_count"] != 0
        or report["statistical_superiority"] is not False
        or report["total_lifecycle_cost"] is not None
        or report["citation_entailment_accuracy"] is not None
        or replay["independent_semantic_judge"] is not False
        or replay["independent_source_families"] != 0
    ):
        raise ValueError("forged independence or complete lifecycle")
    if {(r["question_id"], r["arm"]) for r in cal_raw} != {
        (qid, arm) for qid in {r["question_id"] for r in cal_raw} for arm in CAL_ARMS
    } or len({r["question_id"] for r in cal_raw}) != 8:
        raise ValueError("incomplete calibration arms")
    found = {}
    kinds = Counter()
    for original, judged in zip(eval_raw, scored, strict=True):
        if {k: v for k, v in judged.items() if k not in SCORER_FIELDS} != original:
            raise ValueError("scorer rewrote an original answer")
        key = (judged["question_id"], judged["arm"])
        if key in found or judged["arm"] not in ARMS or judged["kind"] not in KINDS:
            raise ValueError("duplicate or unknown answer identity")
        if (
            judged["status"] != "succeeded"
            or type(judged["strict_task_success"]) is not bool
        ):
            raise ValueError("unscored actual reader execution")
        receipt = judged["receipt"]
        if (
            receipt["reader_identity"] != MODEL
            or receipt["trainable_parameters"] != 0
            or receipt["answer_postprocessed"] is not False
            or receipt["semantic_citation_precision"] is not None
            or receipt["independent_semantic_review"] is not False
            or type(receipt["input_tokens"]) is not int
            or not 0 <= receipt["input_tokens"] <= 2048
            or type(receipt["generated_tokens"]) is not int
            or not 0 <= receipt["generated_tokens"] <= 64
            or not isinstance(receipt["seconds"], (float, int))
            or not math.isfinite(receipt["seconds"])
            or receipt["seconds"] < 0
        ):
            raise ValueError("reader weight/budget/model execution drift")
        if judged["kind"] == "procedure" and judged["strict_task_success"]:
            p = judged.get("procedure_verification")
            if (
                p is None
                or p["exit_code"] != 0
                or p["request"]["operation"] != "execute"
            ):
                raise ValueError("program success without executed worker")
            effect = strict_json(p["stdout"])
            if (
                effect["succeeded"] is not True
                or effect["actual_output"] != p["request"]["recipe"]["target"]
            ):
                raise ValueError("program answer not execution-verified")
        found[key] = judged
        kinds[judged["question_id"]] = judged["kind"]
    if (
        len(kinds) != 8
        or Counter(kinds.values()) != Counter({k: 2 for k in KINDS})
        or set(found) != {(qid, arm) for qid in kinds for arm in ARMS}
    ):
        raise ValueError("test case/arm denominators differ from fixed plan")
    citation = report["formal_citation_chain"]
    indexed = {(c["question_id"], c["arm"]): c for c in citation["cases"]}
    if (
        len(citation["cases"]) != 72
        or len(indexed) != 72
        or set(indexed) != set(found)
        or citation["independent_semantic_adjudication"] is not False
    ):
        raise ValueError("citation case census or review authority changed")
    grouped = {arm: [] for arm in ARMS}
    worklist = []
    for (qid, arm), row in found.items():
        c = indexed[qid, arm]
        result = classify(row, c)
        if row["strict_task_success"] and (
            result["delivered_but_uncited"] or result["not_delivered"]
        ):
            worklist.append(
                dict(
                    question_id=qid,
                    arm=arm,
                    kind=row["kind"],
                    answer_sha256=digest(row["answer"].encode()),
                    selected_source_ids=list(row["selected"]),
                    cited_source_ids=list(c["cited_source_ids"]),
                    **result,
                )
            )
        grouped[arm].append((row, c, result))
    summary = {}
    for arm, group in grouped.items():
        success = sum(r["strict_task_success"] for r, _, _ in group)
        supported = sum(r["required_sources_covered"] for r, _, _ in group)
        full_cite = sum(
            r["strict_task_success"]
            and c["program_declared_support_cited"]
            and c["publicly_declared_event_path_connected"]
            and c["answer_has_citation_marker"]
            and not c["missing_program_declared_support"]
            for r, c, _ in group
        )
        summary[arm] = dict(
            planned=len(group),
            strict_task_success=success,
            required_source_coverage=supported,
            correct_with_complete_formal_citations=full_cite,
            prompt_tokens=sum(r["receipt"]["input_tokens"] for r, _, _ in group),
            generated_tokens=sum(r["receipt"]["generated_tokens"] for r, _, _ in group),
            measured_inference_seconds=sum(
                r["receipt"]["seconds"] for r, _, _ in group
            ),
            successful_without_full_required_citations=success - full_cite,
            missing_from_selected_count=sum(
                bool(v["not_delivered"]) for _, _, v in group
            ),
            delivered_but_uncited_count=sum(
                bool(v["delivered_but_uncited"]) for _, _, v in group
            ),
        )
        archived = report["success_by_arm"][arm]
        independent = replay["evaluation"]["strict_success"][arm]
        cited = citation["by_arm"][arm]
        if (
            len(group) != 8
            or archived["strict_success"] != success
            or archived["strict_success"] != independent
            or archived["input_tokens"] != summary[arm]["prompt_tokens"]
            or cited["correct_with_full_program_declared_citations"] != full_cite
        ):
            raise ValueError("published arm totals conflict with original rows")
    # No learning arms exist in this actual nine-arm trial, hence no learning claim.
    if {"learned_policy", "knowledge", "parametric_only"} & set(grouped):
        raise ValueError("unexpected parametric memory arm")
    # Recheck exact published paired contrasts without trusting their point estimate.
    checks = {
        "organized_minus_hybrid4": ("organized", "hybrid_k4"),
        "organized_minus_selected": ("organized", "selected_k"),
        "organized_minus_entity_time": ("organized", "entity_time"),
    }
    pairs = {}
    for name, (a, b) in checks.items():
        wins = sum(
            found[qid, a]["strict_task_success"]
            and not found[qid, b]["strict_task_success"]
            for qid in kinds
        )
        losses = sum(
            found[qid, b]["strict_task_success"]
            and not found[qid, a]["strict_task_success"]
            for qid in kinds
        )
        prior = report["paired_contrasts"][name]
        if (wins, losses, 8 - wins - losses) != (
            prior["wins"],
            prior["losses"],
            prior["ties"],
        ):
            raise ValueError("changed registered paired comparison")
        pairs[name] = dict(wins=wins, losses=losses, ties=8 - wins - losses)
    sizes = report["source_and_index_costs"]
    if not isinstance(sizes, dict) or len(sizes) != 16:
        raise ValueError("original and index retained cost census missing")
    if (
        sum(v["source_bytes"] for v in sizes.values())
        != report["retained_original_source_bytes"]
    ):
        raise ValueError("original source storage disappeared")
    return dict(
        schema=PROFILE,
        original_model_commit=SOURCE,
        original_evaluation_plan_sha256=PLAN,
        reader_identity=MODEL,
        frozen_selected_k=policy["selected_k"],
        calibration_actual_generations=40,
        evaluation_actual_generations=72,
        independent_archive_members_verified=replay["verified_artifact_files"],
        distinct_evaluation_tasks=8,
        independent_source_families=0,
        arms=summary,
        paired=pairs,
        citation_gap_worklist=sorted(
            worklist, key=lambda x: (x["question_id"], x["arm"])
        ),
        source_bytes_retained=report["retained_original_source_bytes"],
        index_bytes_retained=sum(v["index_bytes"] for v in sizes.values()),
        production_maintenance_revocation_recovery_cost_usd=None,
        total_lifecycle_cost_usd=None,
        reference_reader_with_human_sufficient_evidence_observed=False,
        human_semantic_citation_adjudication=False,
        parametric_memory_gain_observed=False,
        statistical_superiority=False,
        eligible_for_new_blinded_experiment=True,
        allow_parametric_promotion=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = reconcile(
        checked_zip(args.release, RELEASE_ZIP, count=272),
        checked_zip(args.replay, AUDIT_ZIP, count=4),
    )
    content = json.dumps(output, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as f:
            f.write(content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()

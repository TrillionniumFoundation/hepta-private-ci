"""Reconcile actual Qwen event and LoCoMo research receipts without mixing metrics.

The fixed historical ZIP pins are not model outputs or semantic authority.
No model is loaded, no source text or target answers are published, and the
result cannot accept a learned memory or a production candidate.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-cell.cross-population-evidence.v1"
PINS = {
    "event_model": "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8",
    "event_replay": "2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071",
    "locomo_public": "51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37",
    "locomo_retrieval": "3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097",
    "locomo_targets": "d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978",
    "locomo_model": "7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48",
    "locomo_score": "5c36103c506367de2ba42ea242bc81b53ad9734f1417132ce2945d0473ed391e",
}
EVENT_SOURCE = "6304b451268c73f3d1a605985226b102df841bbf"
LOCOMO_SOURCE = "96b5ec37b82f87d445740403e07e3705e9850955"
EVENT_ARMS = (
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
EVENT_COUNTS = {
    "selected_k": 5,
    "hybrid_k4": 3,
    "hybrid_k6": 2,
    "hybrid_k4_reversed": 3,
    "single_hop": 4,
    "entity_time": 8,
    "organized": 8,
    "program_support": 8,
    "empty": 0,
}
EVENT_CITED = {
    "selected_k": 3,
    "hybrid_k4": 1,
    "hybrid_k6": 0,
    "hybrid_k4_reversed": 1,
    "single_hop": 4,
    "entity_time": 4,
    "organized": 4,
    "program_support": 4,
    "empty": 0,
}
READER_INVENTORY = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
MAX_ZIP = 16 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite JSON number")

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON float")
        return number

    return json.loads(
        data, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite
    )


def pinned_zip(path, external_sha):
    """Reject replaced archives, duplicate members, path escapes and bogus manifests."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < MAX_ZIP:
        raise ValueError("regular bounded ZIP required")
    raw = path.read_bytes()
    if sha(raw) != external_sha:
        raise ValueError("original ZIP differs from externally pinned bytes")
    try:
        archive = zipfile.ZipFile(path)
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if not 1 <= len(names) <= 200 or len(names) != len(set(names)):
            raise ValueError("incomplete or repeated artifact members")
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise ValueError("unbounded artifact expansion")
        for member in infos:
            part = PurePosixPath(member.filename)
            if (
                part.is_absolute()
                or ".." in part.parts
                or "\\" in member.filename
                or member.is_dir()
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise ValueError("unsafe artifact member")
        if "SHA256SUMS" in names:
            listed = {}
            for line in archive.read("SHA256SUMS").decode("utf-8").splitlines():
                match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([^\n]+)", line)
                if not match:
                    raise ValueError("invalid artifact manifest")
                declared, name = match.groups()
                if name in listed or name not in names:
                    raise ValueError("orphan or repeated hash entry")
                listed[name] = declared
                if sha(archive.read(name)) != declared:
                    raise ValueError("modified inner artifact bytes")
            if set(listed) != set(names) - {"SHA256SUMS"}:
                raise ValueError("incomplete artifact file census")
        return archive
    except Exception:
        archive.close()
        raise


def json_at(archive, path):
    return strict_json(archive.read(path))


def journal(archive, path, n, arms):
    lines = archive.read(path).splitlines()
    if len(lines) != n:
        raise ValueError("incomplete original model execution census")
    rows = [strict_json(line) for line in lines]
    pairs = [(r["question_id"], r["arm"]) for r in rows]
    if len(set(pairs)) != n:
        raise ValueError("duplicated original model execution")
    ids = {q for q, _ in pairs}
    if len(ids) * len(arms) != n or set(pairs) != {
        (qid, arm) for qid in ids for arm in arms
    }:
        raise ValueError("incomplete paired arms")
    if any(r["status"] != "succeeded" for r in rows):
        raise ValueError("failed or missing original model call")
    return rows


def event_summary(model, replay):
    cal = journal(
        model, "calibration/raw-answers.jsonl", 40, ("k1", "k2", "k3", "k4", "k6")
    )
    ev = journal(model, "evaluation/raw-answers.jsonl", 72, EVENT_ARMS)
    cal_scored = json_at(model, "calibration/scored-answers.json")
    ev_scored = json_at(model, "evaluation/scored-answers.json")
    for raw, scored in ((cal, cal_scored), (ev, ev_scored)):
        if len(raw) != len(scored):
            raise ValueError("score rewrote the planned denominator")
        for a, b in zip(raw, scored):
            for key, value in a.items():
                if b.get(key) != value:
                    raise ValueError("score modified the original model answer")
            if type(b.get("strict_task_success")) is not bool:
                raise ValueError("no strict scoring of original output")
    policy = json_at(model, "calibration/frozen-policy.json")
    report = json_at(model, "evaluation/report.json")
    cal_report = json_at(model, "calibration/report.json")
    check = json_at(replay, "receipt.json")
    if (
        policy["source_commit"] != EVENT_SOURCE
        or policy["selected_k"] != 1
        or report["source_commit"] != EVENT_SOURCE
        or report["total_attempts"] != 72
        or report["test_task_count"] != 8
        or cal_report["planned_attempts"] != 40
        or not (
            check["calibration"]["all_model_calls_succeeded"]
            and check["evaluation"]["all_model_calls_succeeded"]
        )
        or check["generating_commit"] != EVENT_SOURCE
        or check["model_identity"] != READER_INVENTORY
        or check["production_accepted"] is not False
        or report["production_accepted"] is not False
    ):
        raise ValueError("event source, frozen policy or replay lineage drift")
    if check["calibration"]["original_raw_sha256"] != sha(
        model.read("calibration/raw-answers.jsonl")
    ) or check["evaluation"]["original_raw_sha256"] != sha(
        model.read("evaluation/raw-answers.jsonl")
    ):
        raise ValueError("unmatched independent raw-answer replay")
    counts = {}
    for arm in EVENT_ARMS:
        rows = [r for r in ev_scored if r["arm"] == arm]
        n_correct = sum(r["strict_task_success"] for r in rows)
        cited = report["formal_citation_chain"]["by_arm"][arm]
        chain = cited["correct_with_public_event_chain_connected"]
        stats = report["success_by_arm"][arm]
        if (
            len(rows) != 8
            or n_correct != EVENT_COUNTS[arm]
            or stats["strict_success"] != n_correct
            or stats["succeeded"] != 8
            or stats["failed"] != 0
            or chain != EVENT_CITED[arm]
            or cited["strict_task_success"] != n_correct
            or check["evaluation"]["strict_success"][arm] != n_correct
        ):
            raise ValueError("changed reported event accuracy or citation chain")
        counts[arm] = {
            "strict_correct": n_correct,
            "correct_with_full_public_citation_path": chain,
            "input_tokens": stats["input_tokens"],
        }
    if (
        cal_report["calibration_sensitivity"]["stable_to_one_calibration_case_removal"]
        is not False
        or policy["candidate_accepted"] is not False
        or report["independent_source_family_count"] != 0
    ):
        raise ValueError("unqualified calibration was reclassified")
    return {
        "source_commit": EVENT_SOURCE,
        "model_identity": check["model_identity"],
        "original_model_calls": 112,
        "calibration_calls": len(cal),
        "evaluation_calls": len(ev),
        "selected_k": policy["selected_k"],
        "calibration_stable_under_leave_one_out": False,
        "arms": counts,
        "completed_independent_execution_replay": True,
        "independent_semantic_review": False,
        "authenticated_future_source_families": 0,
    }


def locomo_summary(public, retrieval, targets, model, scoring):
    ready = json_at(model, "run/READY.json")
    scored = json_at(scoring, "result/report.json")
    source = json_at(public, "population.json")
    frozen = json_at(retrieval, "receipt.json")
    original_targets = json_at(targets, "targets.json")
    rows = journal(model, "run/raw-answers.jsonl", 32, ("lexical_k4", "lexical_k8"))
    if (
        ready["generating_commit"] != LOCOMO_SOURCE
        or scored["generating_commit"] != LOCOMO_SOURCE
        or ready["model_identity"] != READER_INVENTORY
        or scored["reference_model_inventory_identity"] != READER_INVENTORY
        or ready["actual_model_calls"] != 32
        or ready["succeeded"] != 32
        or ready["labels_seen_during_generation"] is not False
        or ready["weight_updates"] != 0
        or ready["original_answers_rewritten"] is not False
        or ready["production_accepted"] is not False
        or scored["production_accepted"] is not False
        or scored["original_raw_answers_sha256"]
        != sha(model.read("run/raw-answers.jsonl"))
        or ready["raw_journal_sha256"] != scored["original_raw_answers_sha256"]
        or ready["original_source_sha256"] != PINS["locomo_public"]
        or ready["original_six_decisions_sha256"] != PINS["locomo_retrieval"]
        or len(original_targets) != 16
        or source["published_benchmarks_are_future_observations"] is not False
        or frozen["labels_opened"] is not False
        or scored["paired"]["family_proxies"] != 2
        or scored["paired"]["planned"] != 16
    ):
        raise ValueError("LoCoMo original evidence, labels or model lineage drift")
    result = {}
    for arm in ("lexical_k4", "lexical_k8"):
        members = [r for r in rows if r["arm"] == arm]
        stats = scored["arms"][arm]
        tokens = sum(r["receipt"]["input_tokens"] for r in members)
        generated = sum(r["receipt"]["generated_tokens"] for r in members)
        if (
            len(members) != 16
            or stats["planned"] != 16
            or stats["succeeded"] != 16
            or stats["failed"] != 0
            or stats["actual_input_tokens"] != tokens
            or stats["actual_generated_tokens"] != generated
            or not math.isfinite(stats["diagnostic_f1"])
            or not 0 <= stats["diagnostic_f1"] <= 1
        ):
            raise ValueError("LoCoMo measured cost or score denominator drift")
        result[arm] = {
            "mean_diagnostic_token_f1": round(stats["diagnostic_f1"], 12),
            "prompt_tokens": tokens,
            "successful_model_calls": 16,
            "metric": "diagnostic normalized token-F1; NOT strict exact match",
        }
    if (
        result["lexical_k8"]["mean_diagnostic_token_f1"]
        >= result["lexical_k4"]["mean_diagnostic_token_f1"]
    ):
        raise ValueError("the pinned observed top-k disposition differs")
    return {
        "source_commit": LOCOMO_SOURCE,
        "model_identity": READER_INVENTORY,
        "original_model_calls": 32,
        "source_family_proxies": 2,
        "published_development_questions": 16,
        "arms": result,
        "independent_human_sufficiency_reviews": 0,
        "published_benchmark_not_future_observation": True,
    }


def reconcile(inputs):
    if set(inputs) != set(PINS):
        raise ValueError("exact seven pinned research archives required")
    archives = {name: pinned_zip(inputs[name], pin) for name, pin in PINS.items()}
    try:
        e = event_summary(archives["event_model"], archives["event_replay"])
        l = locomo_summary(
            archives["locomo_public"],
            archives["locomo_retrieval"],
            archives["locomo_targets"],
            archives["locomo_model"],
            archives["locomo_score"],
        )
    finally:
        for archive in archives.values():
            archive.close()
    if e["model_identity"] != l["model_identity"]:
        raise ValueError("different model inventory across research populations")
    return {
        "schema": SCHEMA,
        "source_zip_sha256": dict(PINS),
        "reader_identity": e["model_identity"],
        "observed_completed_model_calls": e["original_model_calls"]
        + l["original_model_calls"],
        "controlled_authored_event": e,
        "published_locomo": l,
        "pooled_accuracy": None,
        "reason_no_pooled_accuracy": (
            "incompatible strict-ID and diagnostic token-F1 metrics; "
            "authored tasks and only two published family proxies"
        ),
        "qualification": {
            "frozen_reader_evidence_transfer_proven": False,
            "calibrated_k_stable": False,
            "independent_future_source_families": 0,
            "human_certified_sufficient_contexts": 0,
            "semantic_citation_precision": None,
            "parametric_memory_training_qualified": False,
            "production_accepted": False,
        },
        "registered_next_experiment": (
            "Same frozen reader + publisher-support-only evidence on the "
            "LoCoMo 16, then blinded independent sufficient-span decisions "
            "and new disjoint source families; preserve top-4 and top-8 "
            "lexical baselines, refusals, citations, and all costs"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in PINS:
        parser.add_argument(key, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile({key: getattr(args, key) for key in PINS})
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            result,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "calls": result["observed_completed_model_calls"],
                "parametric_training_qualified": False,
            }
        )
    )


if __name__ == "__main__":
    main()

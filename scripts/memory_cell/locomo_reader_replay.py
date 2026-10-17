"""Independent-source replay of a 32-call frozen Smol135 LoCoMo diagnosis.

Reads original target labels only AFTER the sealed journal digest and complete
source/task census are verified. No weights, model inferences, independent human
semantics, prospective family claims, or production admission.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

SOURCE_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
PROFILE = "hepta.offline-original-smol135-fp32.v1"
EXPECTED_IDENTITY = "75f5cbf51c65ca5ef81117d3df4366b425703817985257b31282a7e7b0b0891e"
ARMS = ("empty", "bm25_top3", "annotated_witness", "witness_lesion")
WORD = re.compile(r"[a-z0-9]+")
CITE = re.compile(r"\[E([1-9][0-9]*)\]")


def need(ok, why):
    if not ok:
        raise ValueError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def freeze_digest(value):
    return sha(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    )


def independent_metrics(target, result):
    expected = WORD.findall(str(target).lower())
    response = WORD.findall(result.lower())
    hits = sum((Counter(expected) & Counter(response)).values())
    f1 = 2.0 * hits / (len(expected) + len(response)) if expected and response else 0.0
    return expected == response, f1


def review(dataset, run_dir, report, expected_raw_sha, expected_report_sha):
    dataset, run_dir, report = Path(dataset), Path(run_dir), Path(report)
    for path, expected in (
        (dataset, SOURCE_SHA),
        (run_dir / "raw-answers.jsonl", expected_raw_sha),
        (report, expected_report_sha),
    ):
        need(
            path.is_file() and not path.is_symlink(), "regular pinned original required"
        )
        need(sha(path.read_bytes()) == expected, "original artifact SHA mismatch")
    plan = json.loads((run_dir / "preregistered.json").read_text())
    sealed = (run_dir / "sealed-inputs.json").read_bytes()
    need(
        sha(sealed) == plan["sealed_inputs_sha256"],
        "sealed question/source bytes changed",
    )
    requests = json.loads(sealed)["requests"]
    need(
        len(requests) == 32
        and len(plan["fixed_cases"]) == 8
        and tuple(plan["arms"]) == ARMS,
        "predeclared 8x4 matched source census required",
    )
    raw = (run_dir / "raw-answers.jsonl").read_bytes()
    need(raw.endswith(b"\n"), "incomplete fsynced answer journal")
    attempts = [json.loads(line) for line in raw.splitlines()]
    need(
        len(attempts) == 32
        and [(a["qid"], a["arm"]) for a in attempts]
        == [(q["qid"], q["arm"]) for q in requests],
        "full planned model answer census not sealed",
    )
    original = json.loads(dataset.read_text())
    by_root = {sha(root["sample_id"].encode()): root for root in original}
    aggregated = {arm: Counter() for arm in ARMS}
    for i, (ask, row) in enumerate(zip(requests, attempts, strict=True)):
        need(
            row["status"] == "succeeded"
            and row["reader_profile"] == PROFILE
            and row["model_identity"] == EXPECTED_IDENTITY,
            "reader call status/profile tampering",
        )
        need(
            row["root_sha256"] == ask["root_sha256"]
            and row["delivered_ids_digest"] == freeze_digest(ask["source_ids"]),
            "original source ID changed after inference",
        )
        need(
            type(row.get("input_tokens")) is int
            and 0 < row["input_tokens"] <= 1200
            and type(row.get("output_tokens")) is int
            and 0 <= row["output_tokens"] <= 24
            and type(row.get("actual_reader_wall_seconds")) in (int, float)
            and math.isfinite(row["actual_reader_wall_seconds"])
            and 0 <= row["actual_reader_wall_seconds"] < 100000,
            "model inference cost malformed",
        )
        need(
            isinstance(row.get("answer"), str) and len(row["answer"]) < 5000,
            "raw original model answer missing",
        )
        original_root = by_root.get(ask["root_sha256"])
        need(original_root is not None, "unknown original source family")
        case = next((c for c in plan["fixed_cases"] if c["qid"] == row["qid"]), None)
        need(
            case is not None and case["root_sha256"] == ask["root_sha256"],
            "original pre-answer question identity altered",
        )
        q = original_root["qa"][case["original_question_index"]]
        need(
            freeze_digest(
                (
                    original_root["sample_id"],
                    case["original_question_index"],
                    q["question"],
                )
            )
            == row["qid"]
            and ask["question"] == q["question"],
            "changed original question after register",
        )
        actual_sources = {
            t["dia_id"]: t
            for k, session in original_root["conversation"].items()
            if re.fullmatch(r"session_[0-9]+", k) and isinstance(session, list)
            for t in session
            if isinstance(t, dict) and "dia_id" in t
        }
        need(
            len(ask["sources"]) == len(ask["source_ids"]),
            "source evidence size changed",
        )
        for entry, original_id in zip(ask["sources"], ask["source_ids"], strict=True):
            need(
                entry["id"] == original_id
                and original_id in actual_sources
                and entry["text"] == actual_sources[original_id]["text"]
                and entry["speaker"] == actual_sources[original_id]["speaker"],
                "original delivered dialogue bytes or speaker changed",
            )
        publisher_id = q["evidence"][0]
        if row["arm"] == "empty":
            need(not ask["sources"], "empty arm received evidence")
        elif row["arm"] == "annotated_witness":
            need(ask["source_ids"][0] == publisher_id, "publisher witness replaced")
        elif row["arm"] == "witness_lesion":
            need(publisher_id not in ask["source_ids"], "deleted premise retained")
        valid, f1 = independent_metrics(q["answer"], row["answer"])
        citations = {int(x) for x in CITE.findall(row["answer"])}
        counts = aggregated[row["arm"]]
        counts["planned"] += 1
        counts["model_succeeded"] += 1
        counts["strict_correct"] += valid
        counts["token_f1_sum"] += f1
        counts["input_tokens"] += row["input_tokens"]
        counts["output_tokens"] += row["output_tokens"]
        counts["model_wall_seconds"] += row["actual_reader_wall_seconds"]
        counts["structurally_valid_citation"] += bool(
            citations and all(1 <= n <= len(ask["sources"]) for n in citations)
        )
    prior = json.loads(report.read_text())
    need(
        prior["original_raw_journal_sha256"] == expected_raw_sha
        and prior["real_neural_model_attempts"] == 32
        and prior["successful_neural_model_attempts"] == 32
        and prior["production_accepted"] is False,
        "falsified original model-call disposition",
    )
    for arm in ARMS:
        known = prior["by_arm"][arm]
        again = aggregated[arm]
        for field in (
            "planned",
            "model_succeeded",
            "strict_correct",
            "input_tokens",
            "output_tokens",
            "structurally_valid_citation",
        ):
            need(
                known[field] == again[field],
                "original metric tampered: " + arm + "/" + field,
            )
        for field in ("token_f1_sum", "model_wall_seconds"):
            need(
                math.isclose(known[field], again[field], rel_tol=0, abs_tol=1e-7),
                "original float metric tampered: " + arm + "/" + field,
            )
    return dict(
        schema="hepta.memory.locomo-eight-root-original-independent-replay.v1",
        raw_journal_sha256=expected_raw_sha,
        original_report_sha256=expected_report_sha,
        source_sha256=SOURCE_SHA,
        model_calls_source_replayed=32,
        original_dialogue_bytes_rechecked=32,
        original_answer_scores_independently_recomputed=32,
        new_model_forward_calls=0,
        original_model_forwards_independently_attested=False,
        prospective_future_source_families=0,
        independent_sufficiency_judgments=0,
        parameter_memory_gain_qualified=False,
        real_repository_program_tasks=0,
        semantic_citation_precision=None,
        complete_lifecycle_cost=None,
        production_accepted=False,
        decision="DENY_ALL",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("original_report", type=Path)
    parser.add_argument("--raw-sha256", required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(
        args.dataset,
        args.run_dir,
        args.original_report,
        args.raw_sha256,
        args.report_sha256,
    )
    need(not args.output.exists(), "do not overwrite read-only audit")
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))

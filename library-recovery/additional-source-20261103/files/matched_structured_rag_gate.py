"""SHA-pinned actual-artifact same-reader Hybrid vs organization gate.

Read-only historical controlled data. Does not run a model or admit a
production/learned MemoryCell. Author-created events are not external truth.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ORIGINAL_ARTIFACT_ID = 12038816070
ORIGINAL_ARTIFACT_SHA = "861e84719f26f48d1d1156bb39273ce706ae83cde47bafcd7f400c037edd871d"
ORIGINAL_COMMIT = "45a7f7e14625f27d8397f8e18f9ff7b908443753"
ORIGINAL_JOURNAL_SHA = "8a3c2c186be79cd5e65077017906c731ce1a6f30da937ef9a6894f5c61058cf2"
ORIGINAL_SOURCE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
READER = "hepta.memory.local-causal-reader.v1"
ARMS = ("empty", "hybrid", "entity_time", "organized", "program_support", "without_prerequisite")
FILES = ("execution/preregistered.json", "execution/report.json", "execution/replay.json",
         "execution/scored-answers.json", "execution/raw-answers.jsonl")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def payload(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size < 128000,
            "safe bounded archived artifact required")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == ORIGINAL_ARTIFACT_SHA,
            "original immutable GitHub artifact SHA mismatch")
    with zipfile.ZipFile(path) as bundle:
        members = bundle.infolist()
        require(len({m.filename for m in members}) == len(members), "duplicate ZIP paths")
        require(sum(m.file_size for m in members) < 256000, "unsafe inflated ZIP size")
        require(all(name in bundle.namelist() for name in FILES), "missing audited inputs")
        plan, report, replay, scored = [json.loads(bundle.read(name)) for name in FILES[:-1]]
        raw = bundle.read(FILES[-1])
    return plan, report, replay, scored, raw


def audit(plan, report, replay, scored, raw):
    require(plan.get("schema") == "hepta.memory.local-causal-trial.v1", "original trial missing")
    require(plan.get("generating_commit") == ORIGINAL_COMMIT, "source commit changed")
    require(plan.get("original_zip_sha256") == ORIGINAL_SOURCE_SHA, "original source archive changed")
    require(plan.get("input_profile") == READER and tuple(plan.get("arms", [])) == ARMS,
            "reader or six-arm source selection changed")
    require(plan.get("reader_is_structured_program_not_llm") is True and
            plan.get("no_source_scope_candidate_oracle") is True and
            plan.get("prior_public_test_exposure") is True and
            plan.get("no_label_before_answer_journal") is True and
            plan.get("production_accepted") is False, "misrepresented original protocol")
    questions = plan.get("frozen_question_ids")
    require(isinstance(questions, list) and len(questions) == 8 and
            len(set(questions)) == 8, "eight frozen question census changed")
    require(report.get("schema") == "hepta.memory.local-causal-trial-result.v1" and
            report.get("generating_commit") == ORIGINAL_COMMIT and
            report.get("actual_reader_type") == "bounded_symbolic_source_local" and
            report.get("original_source_archive_sha256") == ORIGINAL_SOURCE_SHA,
            "original report identity changed")
    require(report.get("all_planned") == 48 and report.get("original_program_verifications") == 12 and
            report.get("model_calls") == 0 and report.get("training_steps") == 0 and
            report.get("effective_source_family_count") == 0 and
            report.get("independent_future_windows") == 0 and
            report.get("production_accepted") is False and
            report.get("total_lifecycle_cost") is None and
            report.get("maintained_revoked_restored_costs") is None,
            "unmeasured lifetime or model work claimed")
    require(hashlib.sha256(raw).hexdigest() == ORIGINAL_JOURNAL_SHA == report.get("raw_journal_sha256"),
            "exact original raw answers were modified")
    require(replay.get("schema") == "hepta.memory.local-causal-independent-process-replay.v1" and
            replay.get("generating_commit") == ORIGINAL_COMMIT and
            replay.get("original_journal_sha256") == ORIGINAL_JOURNAL_SHA and
            replay.get("independently_recomputed_original_answers") == 48 and
            replay.get("independently_reexecuted_authored_program_cases") == 12 and
            replay.get("new_model_calls") == 0 and replay.get("production_accepted") is False,
            "independent-process original replay missing")
    originals = [json.loads(line) for line in raw.splitlines()]
    require(len(originals) == len(scored) == 48, "raw/scored paired census incomplete")
    observed = {}
    for original, row in zip(originals, scored):
        require(isinstance(original, dict) and isinstance(row, dict), "invalid output row")
        for key in ("question_id", "task_kind", "arm", "selected", "candidate_digest",
                    "query_digest", "source_view_sha", "reader_profile", "status", "output"):
            require(original.get(key) == row.get(key), "postscore answer tampering: " + key)
        q, arm = row["question_id"], row["arm"]
        require(q in questions and arm in ARMS and (q, arm) not in observed,
                "unknown or duplicate paired task")
        require(row["reader_profile"] == READER and row["status"] == "succeeded", "reader changed")
        require(type(row.get("strict_task_success")) is bool and
                type(row.get("complete_declared_chain_cited")) is bool,
                "unverified task or citation result")
        outcome = row["output"]
        require(outcome.get("status") in ("answered", "abstained"), "reader response status changed")
        require(isinstance(outcome.get("trace"), list) and isinstance(outcome.get("citations"), list),
                "source trace missing")
        if outcome["status"] == "abstained":
            require(not row["strict_task_success"] and not row["complete_declared_chain_cited"]
                    and not outcome["trace"] and not outcome["citations"], "unsupported abstention success")
        if row["complete_declared_chain_cited"]:
            require(row["strict_task_success"] and outcome["trace"], "fabricated citation success")
        require(isinstance(row["selected"], list) and
                len(set(row["selected"])) == len(row["selected"]), "duplicate evidence")
        for entry in outcome["trace"]:
            require(entry.get("original_id") in row["selected"] and
                    entry.get("label") in [f"E{i}" for i in range(1, len(row["selected"]) + 1)],
                    "citation not bound to delivered evidence")
        observed[q, arm] = row
    require(len(observed) == 48, "paired observations incomplete")
    for q in questions:
        family = [observed[q, arm] for arm in ARMS]
        for key in ("reader_profile", "task_kind", "query_digest", "candidate_digest", "source_view_sha"):
            require(len({x[key] for x in family}) == 1, "non-matched paired reader/questions")
    by_arm = {}
    for arm in ARMS:
        rows = [observed[q, arm] for q in questions]
        measured = dict(tasks=8, strict_success=sum(r["strict_task_success"] for r in rows),
                        cited_complete=sum(r["complete_declared_chain_cited"] for r in rows),
                        abstained=sum(r["output"]["status"] == "abstained" for r in rows),
                        selected_source_ids=sum(len(r["selected"]) for r in rows))
        root = report["result_by_arm"][arm]
        attested = replay["outcomes"][arm]
        require(root["strict_task_success"] == attested["success"] == measured["strict_success"] and
                root["complete_declared_chain_cited"] == attested["cited_complete"] == measured["cited_complete"] and
                root["abstained"] == attested["abstained"] == measured["abstained"],
                "result or replay score mismatch")
        by_arm[arm] = measured
    require(by_arm["empty"]["abstained"] == 8 and
            by_arm["without_prerequisite"]["abstained"] == 8,
            "missing-evidence refusal failed")
    contrasts = {}
    for arm in ("entity_time", "organized"):
        wins = sum(observed[q, arm]["strict_task_success"] and not observed[q, "hybrid"]["strict_task_success"] for q in questions)
        losses = sum(observed[q, "hybrid"]["strict_task_success"] and not observed[q, arm]["strict_task_success"] for q in questions)
        citation_wins = sum(observed[q, arm]["complete_declared_chain_cited"] and not observed[q, "hybrid"]["complete_declared_chain_cited"] for q in questions)
        citation_losses = sum(observed[q, "hybrid"]["complete_declared_chain_cited"] and not observed[q, arm]["complete_declared_chain_cited"] for q in questions)
        contrasts[arm] = dict(paired_tasks=8, task_wins=wins, task_losses=losses,
                              citation_wins=citation_wins, citation_losses=citation_losses,
                              net_task_success_delta=(wins - losses) / 8,
                              selected_source_id_reduction=by_arm["hybrid"]["selected_source_ids"] - by_arm[arm]["selected_source_ids"])
    return dict(schema="hepta.memory.original-same-reader-ci-audit.v1",
                frozen_source_commit=ORIGINAL_COMMIT, original_artifact_id=ORIGINAL_ARTIFACT_ID,
                original_artifact_sha256=ORIGINAL_ARTIFACT_SHA, reader=READER,
                observed_tasks=48, original_program_checks_replayed=12,
                verified_separate_process_replay=True,
                by_arm=by_arm, contrasts=contrasts,
                new_model_calls=0, new_source_families=0, external_human_review=False,
                task_memory_gain_qualified=False, parameter_memory_gain_qualified=False,
                complete_cost=None, production_accepted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    report = audit(*payload(args.source))
    if args.destination.exists():
        raise ValueError("refuse to overwrite evidence result")
    args.destination.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

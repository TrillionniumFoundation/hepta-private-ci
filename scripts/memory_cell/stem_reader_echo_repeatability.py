"""Two SHA256-pinned strict-run Reader output pathologies, without new inference.

This is a read-only post-generation diagnostic. Frozen Reader payload/prompt,
source evidence, trained policy results and citation adjudication are untouched.
Exactly 32 UNIQUE questions, not 96 checkpoint replays, are its denominator.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

from stem_audit_archive import PinnedArchive, require

RUNS = (
    ("675970bb610c70bb0ec30a2dee05c025440510e6",
     "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb",
     "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8"),
    ("d0f69d7b94f65730fa1e093dee6989916f01898e",
     "87e3b17a0601c17712b9512fc01eadc123060391",
     "07b0f15ec150cc9817db6bfc9b4bae1e2c06a5296ca2ba3c4c7895da18b99e2f"),
)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank", "prototype", "linear", "gated",
    "lineage_lora_gated", "independent_lora_gated",
)
JSON_PREFIX = '{"question":'
MARKER = re.compile(r"\[E[0-9]+\]")


def _bound_census(plan, raw, empty, report):
    questions = plan["questions"]
    require(
        set(questions) == {"train", *PHASES}
        and len(questions["train"]) == 48
        and all(len(questions[p]) == 8 for p in PHASES)
        and len({q for qs in questions.values() for q in qs}) == 80
        and tuple(plan["arms"]) == ARMS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1"
        and plan["generator_config"]["max_new_tokens"] == 96
        and report["census"]["complete"] is True
        and report["logical_policy_attempts"] == 576
        and report["production_accepted"] is False
        and report["semantic_citation_precision"] is None,
        "noncanonical or previously promoted original research trial",
    )
    registered = {
        (stage, phase, q, arm)
        for stage in STAGES for phase in PHASES
        for q in questions[phase] for arm in ARMS
    }
    got = {}
    for row in raw:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        require(
            key in registered and key not in got
            and row["status"] == "succeeded",
            "missing, duplicate or failed original policy attempt",
        )
        got[key] = row
    require(len(got) == len(registered) == 576, "not all 576 original policies")
    empty_by_q = {}
    for row in empty:
        key = row["phase"], row["question_id"]
        require(
            key[0] in PHASES and key[1] in questions[key[0]]
            and key not in empty_by_q and row["status"] == "succeeded",
            "missing, duplicate or failed no-evidence control",
        )
        empty_by_q[key] = row
    require(len(empty_by_q) == 32, "not all 32 no-evidence Reader controls")
    frozen = {
        (phase, q): got[(48, phase, q, "frozen_rerank")]
        for phase in PHASES for q in questions[phase]
    }
    return frozen, empty_by_q


def _inspect(row, *, expected_empty):
    receipt = row["receipt"]
    query = receipt["observable_query"]
    evidence = receipt["delivered_evidence"]
    canonical = hashlib.sha256(
        json.dumps(
            (receipt["generator_identity"], receipt["generator_profile"], query, evidence),
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    require(
        receipt["canonical_request_digest"] == canonical
        and receipt["reached_token_ceiling"] == (receipt["generated_tokens"] == 96)
        and query["identity"] == row["question_id"]
        and isinstance(evidence, list) and len(evidence) <= 1
        and (not expected_empty or evidence == [])
        and isinstance(row["answer"], str) and row["answer"].strip()
        and receipt["generator_identity"] and receipt["generator_profile"]
        and type(receipt["reached_token_ceiling"]) is bool
        and type(receipt["generated_tokens"]) is int
        and 1 <= receipt["generated_tokens"] <= 96,
        "detached or incomplete Reader/prompt original receipt",
    )
    prompt = json.dumps(
        dict(
            question=query["content"], question_time=query["observed_at"],
            evidence=[dict(label=s["label"], observed_at=s["observed_at"],
                           text=s["excerpt"]) for s in evidence],
        ),
        ensure_ascii=False,
    )
    answer = row["answer"]
    return dict(
        question_id=row["question_id"],
        phase=row["phase"],
        answer_sha256=hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        canonical_request_digest=receipt["canonical_request_digest"],
        generator_identity=receipt["generator_identity"],
        generator_profile=receipt["generator_profile"],
        input_token_sha256=receipt["input_ids_digest"],
        generated_token_sha256=receipt["generated_ids_digest"],
        delivered_evidence_sha256=hashlib.sha256(
            json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        generated_json_question_prefix=answer.lstrip().startswith(JSON_PREFIX),
        exact_original_user_json_prefix=(
            answer.lstrip().startswith(JSON_PREFIX) and prompt.startswith(answer.strip())
        ),
        reached_output_token_ceiling=receipt["reached_token_ceiling"],
        emitted_structural_citation_marker_count=len(MARKER.findall(answer)),
        no_gold_text_or_answers_exported=True,
    )


def compare_reader_outputs(a, b):
    """Two immutable Reader executions, same 32 identities, not 64 independent Qs."""
    for field in (
        "questions", "arms", "curriculum_attempted_examples",
        "dataset_sha256", "reader_inventory", "generator_config",
        "generator_template_digest", "source_visibility_policy",
        "retriever_inventory", "ranker_inventory", "window_budget",
        "primary_policy",
    ):
        require(a["plan"][field] == b["plan"][field],
                "cohort or fixed Reader/source model changed: " + field)
    left = _bound_census(a["plan"], a["raw"], a["empty"], a["report"])
    right = _bound_census(b["plan"], b["raw"], b["empty"], b["report"])
    panels, summaries = {}, {}
    for label, frozen_index in (("original_evidence", 0), ("zero_evidence", 1)):
        before = {k: _inspect(v, expected_empty=(frozen_index == 1))
                  for k, v in left[frozen_index].items()}
        after = {k: _inspect(v, expected_empty=(frozen_index == 1))
                 for k, v in right[frozen_index].items()}
        require(set(before) == set(after) and len(before) == 32,
                "Reader comparison lost original question identity")
        per_phase = {}
        output = []
        for key in sorted(before):
            old, new = before[key], after[key]
            require(old == new, "original frozen Reader bytes or prompt changed across runs")
            output.append({k: v for k, v in old.items()
                           if k in (
                               "phase", "question_id", "answer_sha256",
                               "generated_json_question_prefix",
                               "exact_original_user_json_prefix",
                               "reached_output_token_ceiling",
                               "emitted_structural_citation_marker_count",
                           )})
        for phase in PHASES:
            group = [x for x in output if x["phase"] == phase]
            require(len(group) == 8, "not eight preregistered phase questions")
            per_phase[phase] = dict(
                unique_questions=len(group),
                generated_json_question_prefix=sum(x["generated_json_question_prefix"] for x in group),
                exact_user_prompt_prefix=sum(x["exact_original_user_json_prefix"] for x in group),
                reached_output_token_ceiling=sum(x["reached_output_token_ceiling"] for x in group),
                emitted_structural_citation_markers=sum(
                    x["emitted_structural_citation_marker_count"] for x in group
                ),
            )
        summaries[label] = dict(
            **{k: sum(rec[k] for rec in per_phase.values())
               for k in (
                   "unique_questions", "generated_json_question_prefix",
                   "exact_user_prompt_prefix", "reached_output_token_ceiling",
                   "emitted_structural_citation_markers",
               )},
            per_phase=per_phase,
            byte_identical_across_two_completed_strict_runs=True,
        )
        panels[label] = output
    return dict(
        schema="hepta.stem-reader-echo-two-strict-runs.v1",
        original_run_sha256=[x[2] for x in RUNS],
        independent_question_ids=32,
        two_run_repeats_are_not_independent_examples=True,
        max_generation_tokens=96,
        controls=summaries,
        per_question_diagnostics=panels,
        exact_prompt_and_raw_model_output_compared=True,
        no_new_model_calls=True,
        no_private_source_or_answer_text_exported=True,
        input_echo_is_only_structural_diagnostic=True,
        independent_reader_sufficiency_verified=False,
        semantic_citation_precision=None,
        citation_quality_qualification=False,
        scale_out_permitted=False,
        production_accepted=False,
    )


def audit_two_pinned_artifacts(earlier, later):
    archives = []
    try:
        for path, (source, tree, sha) in zip((earlier, later), RUNS, strict=True):
            a = PinnedArchive(Path(path), sha)
            archives.append(a)
            require(a.read("tested-commit.txt").decode().strip() == source
                    and a.read("tested-tree.txt").decode().strip() == tree,
                    "archive source commit/tree pin mismatch")
        inp = [dict(
            plan=a.json("comparison/preregistered.json"),
            raw=a.jsonl("comparison/policy-predictions.jsonl"),
            empty=a.jsonl("comparison/reader-no-evidence.jsonl"),
            report=a.json("comparison/report.json"),
        ) for a in archives]
        result = compare_reader_outputs(*inp)
        result["archives"] = [dict(
            original_source=run[0], original_tree=run[1],
            zip_sha256=run[2], internal_file_sha256_checks=a.manifest_entries,
        ) for run, a in zip(RUNS, archives, strict=True)]
        return result
    finally:
        for a in archives:
            a.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--earlier", type=Path, required=True)
    parser.add_argument("--later", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_two_pinned_artifacts(args.earlier, args.later)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report["controls"], sort_keys=True))

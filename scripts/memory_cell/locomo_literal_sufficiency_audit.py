"""After-seal literal coverage check on the real published LoCoMo source cohort.

An answer string occurring verbatim is NOT a human judgment that the evidence
is sufficient or causally entails the answer. Conversely nonoccurrence cannot
show the source is insufficient: an answer may require synthesis/paraphrase.
The labels are opened only in this separate model-free, post-inference process.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from locomo_format_trial import SOURCE_PIN, DATA_SHA, sha, source_file

OLD_RAW_SHA = "1e36a1dcfefabf8d8912b81e215a9e7383bc4eb08a63e2dc592a0b46ce65aab3"
NEW_RAW_SHA = "1d8fc82f4843b8805709e1d60d878f0e9154099dcb0e33a773fae972e1a0b710"
ARMS = ("empty", "bm25_top3", "annotated_witness", "witness_lesion")
WORD = re.compile(r"[a-z0-9]+")


def normalized(value):
    return tuple(WORD.findall(str(value).lower()))


def literal_span(target, text):
    """Literal token substring, not semantic entailment or target selection."""
    left, right = normalized(target), normalized(text)
    return bool(
        left
        and any(
            tuple(right[i : i + len(left)]) == left
            for i in range(len(right) - len(left) + 1)
        )
    )


def census(corpus, plan, sealed):
    if len(plan.get("fixed_cases", [])) != 8 or not isinstance(corpus, list):
        raise ValueError("eight sealed original test cases required")
    root_map = {sha(item["sample_id"].encode()): item for item in corpus}
    if len(root_map) != len(corpus):
        raise ValueError("ambiguous source conversation roots")
    request_map = {}
    for request in sealed["requests"]:
        key = request["qid"], request["arm"]
        if key in request_map or request["arm"] not in ARMS:
            raise ValueError("duplicate/unknown registered evidence arm")
        request_map[key] = request
    expected = {(c["qid"], arm) for c in plan["fixed_cases"] for arm in ARMS}
    if set(request_map) != expected:
        raise ValueError("original sealed question/arm set changed")
    counts = Counter()
    for case in plan["fixed_cases"]:
        root = root_map[case["root_sha256"]]
        question = root["qa"][case["original_question_index"]]
        target = str(question["answer"])
        if not target.strip():
            raise ValueError("empty original publisher annotation")
        all_turns = [
            turn["text"]
            for key, session in root["conversation"].items()
            if re.fullmatch(r"session_[0-9]+", key)
            for turn in session
            if isinstance(turn, dict) and isinstance(turn.get("text"), str)
        ]
        counts["whole_conversation_literal"] += literal_span(
            target, " ".join(all_turns)
        )
        for arm in ARMS:
            request = request_map[case["qid"], arm]
            if (
                request["root_sha256"] != case["root_sha256"]
                or request["question"] != question["question"]
            ):
                raise ValueError("original question/lineage drift")
            delivery = request["sources"]
            counts[arm] += literal_span(target, " ".join(x["text"] for x in delivery))
            if arm == "annotated_witness":
                counts["single_annotated_witness_literal"] += literal_span(
                    target, delivery[0]["text"]
                )
    return dict(counts)


def analyze(dataset, earlier, later):
    earlier, later = Path(earlier), Path(later)
    old_raw = (earlier / "raw-answers.jsonl").read_bytes()
    new_raw = (later / "raw-answers.jsonl").read_bytes()
    original_sealed = (earlier / "sealed-inputs.json").read_bytes()
    old_plan = json.loads((earlier / "preregistered.json").read_bytes())
    latest_plan = json.loads((later / "preregistered.json").read_bytes())
    if (
        sha(old_raw) != OLD_RAW_SHA
        or sha(new_raw) != NEW_RAW_SHA
        or sha(original_sealed) != SOURCE_PIN
        or latest_plan.get("sealed_prompt_sha256")
        != sha((later / "sealed-prompts.json").read_bytes())
    ):
        raise ValueError("source/original model journal pin drift")
    source = source_file(dataset, DATA_SHA)
    totals = census(source, old_plan, json.loads(original_sealed))
    return dict(
        schema="hepta.memory.locomo-exposed-literal-coverage-audit.v1",
        evaluated_old_public_conversation_roots=8,
        matched_label_source_target_only_after_seal=True,
        original_32_model_calls_recomputed=0,
        latest_48_model_calls_recomputed=0,
        reference_only_publisher_answers=True,
        literal_target_in_one_annotated_witness=totals[
            "single_annotated_witness_literal"
        ],
        literal_target_in_full_root=totals["whole_conversation_literal"],
        literal_target_by_original_evidence_arm={a: totals[a] for a in ARMS},
        missing_literal_does_not_imply_insufficient_evidence=True,
        present_literal_does_not_certify_sufficiency=True,
        independent_human_review=None,
        original_reader_generation_success=0,
        independent_future_families=0,
        model_training_steps=0,
        complete_lifecycle_cost=None,
        production_accepted=False,
        decision="DENY_ALL",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_published_locomo", type=Path)
    parser.add_argument("prior_sealed_run", type=Path)
    parser.add_argument("latest_sealed_run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    value = analyze(
        args.original_published_locomo, args.prior_sealed_run, args.latest_sealed_run
    )
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("refuse to overwrite source review")
    with args.output.open("x") as writer:
        json.dump(value, writer, indent=2, sort_keys=True, allow_nan=False)
        writer.write("\n")
    print(json.dumps(value, sort_keys=True))

"""Read-only paired audit of two completed original source-only Qwen writers.

No new model execution, training, source-review authority or production adoption.
The original historical validator separately audits each answer and internal ZIP.
"""

import argparse
import json
import math
from pathlib import Path

from source_write_retrospective import ARMS, checked_archive, diagnose, strict_json

SOURCE = (
    "source/experience_memory.py",
    "source/experience_write_trial.py",
    "source/experience_policy.py",
    "source/source_write_effects.py",
    "environment.txt",
    "inventory.json",
    "publisher.json",
    "policy-scopes.json",
)


def compare(full, sparse, *, full_commit, sparse_commit):
    baseline = diagnose(full, full_commit)
    optimized = diagnose(sparse, sparse_commit)
    ready = [
        strict_json(record["snapshot/READY.json"].decode()) for record in (full, sparse)
    ]
    training = [record["training"] for record in ready]
    if [t["loss_backend"] for t in training] != ["full", "supervised_positions"]:
        raise ValueError("not the two declared loss backends")
    for file in SOURCE:
        if full[file] != sparse[file]:
            raise ValueError("source, executable writer or model drift: " + file)
    for field in (
        "source_sha",
        "source_documents_digest",
        "base_identity",
        "reader_profile",
        "scopes",
        "roots",
        "retained_original_source_bytes",
    ):
        if ready[0][field] != ready[1][field]:
            raise ValueError("different source or reader: " + field)
    for field in (
        "revision",
        "examples",
        "source_supervision",
        "training_digest",
        "write_schedule",
        "steps",
        "input_tokens",
        "supervised_tokens",
        "trainable_parameters",
        "base_unchanged",
    ):
        if training[0][field] != training[1][field]:
            raise ValueError("training exposure drift: " + field)
    full_tokens = training[0]["input_tokens"]
    sparse_tokens = training[1]["supervised_tokens"]
    if not (
        type(full_tokens) is int
        and type(sparse_tokens) is int
        and 0 < sparse_tokens < full_tokens
        and training[0]["actual_projection_positions"] == full_tokens
        and training[1]["actual_projection_positions"] == sparse_tokens
        and all(t["full_projection_positions"] == full_tokens for t in training)
        and baseline["actual_optimizer_updates"]
        == optimized["actual_optimizer_updates"]
        and baseline["actual_optimizer_updates"] > 0
    ):
        raise ValueError("source update/projection accounting drift")

    rows = [
        [
            strict_json(line.decode())
            for line in record["tasks/raw-answers.jsonl"].splitlines()
        ]
        for record in (full, sparse)
    ]
    lookup = [
        {(row["question_id"], row["arm"]): row for row in values} for values in rows
    ]
    if (
        len(lookup[0]) != len(rows[0])
        or len(lookup[1]) != len(rows[1])
        or set(lookup[0]) != set(lookup[1])
        or len(lookup[0]) != len(ARMS) * baseline["original_task_count"]
        or optimized["original_task_count"] != baseline["original_task_count"]
    ):
        raise ValueError("task/arm census was changed")
    changed = 0
    for key, first in lookup[0].items():
        second = lookup[1][key]
        if first["status"] != "succeeded" or second["status"] != "succeeded":
            raise ValueError("original pair contains an incomplete execution")
        if any(first[k] != second[k] for k in ("kind", "candidate_digest", "selected")):
            raise ValueError("candidate or task changed")
        for field in (
            "input_ids_digest",
            "delivered_evidence",
            "derived_evidence",
            "reader_identity",
            "reader_profile",
            "knowledge_module_enabled",
        ):
            if first["receipt"][field] != second["receipt"][field]:
                raise ValueError("actual model prompt/adapter drift: " + field)
        changed += first["answer"] != second["answer"]
    for field in (
        "strict_task_successes",
        "paired_effects",
        "unsupported_empty_context_citation_answers",
    ):
        if baseline[field] != optimized[field]:
            raise ValueError("quality/citation outcome changed: " + field)
    duration = [entry["write_seconds"] for entry in ready]
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in duration
    ):
        raise ValueError("unknown write time cannot be a speedup")
    step_diff = max(
        abs(x - y)
        for x, y in zip(training[0]["losses"], training[1]["losses"], strict=True)
    )
    return dict(
        schema="hepta.source-only.projection-pair.v1",
        generating_commits=dict(full=full_commit, selected=sparse_commit),
        original_questions=baseline["original_task_count"],
        original_answers_each=baseline["original_generation_calls"],
        changed_answers=changed,
        full_training_projection_positions=full_tokens,
        selected_training_projection_positions=sparse_tokens,
        input_training_tokens=full_tokens,
        supervised_training_tokens=sparse_tokens,
        actual_optimizer_updates=baseline["actual_optimizer_updates"],
        source_examples=training[0]["examples"],
        maximum_step_loss_difference=step_diff,
        full_write_seconds=duration[0],
        selected_write_seconds=duration[1],
        observed_write_time_reduction_fraction=(duration[0] - duration[1])
        / duration[0],
        task_successes=optimized["strict_task_successes"],
        task_outcomes_unchanged=True,
        parametric_only_unsupported_citation_answers=optimized[
            "unsupported_empty_context_citation_answers"
        ]["parameter_only"],
        rejected_parameter_candidate=optimized["research_parameter_candidate_rejected"],
        rejection_reasons=optimized["reason_codes"],
        speed_is_not_quality=True,
        source_groups_are_previous_authored_controls=True,
        new_independent_observations=0,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def run(
    full_path, sparse_path, output, *, full_sha, sparse_sha, full_commit, sparse_commit
):
    output = Path(output)
    if output.exists():
        raise ValueError("do not overwrite the original paired receipt")
    report = compare(
        checked_archive(Path(full_path), full_sha),
        checked_archive(Path(sparse_path), sparse_sha),
        full_commit=full_commit,
        sparse_commit=sparse_commit,
    )
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("full", type=Path)
    parser.add_argument("sparse", type=Path)
    parser.add_argument("output", type=Path)
    for name in ("full-sha", "sparse-sha", "full-commit", "sparse-commit"):
        parser.add_argument("--" + name, required=True)
    a = parser.parse_args()
    print(
        json.dumps(
            run(
                a.full,
                a.sparse,
                a.output,
                full_sha=a.full_sha,
                sparse_sha=a.sparse_sha,
                full_commit=a.full_commit,
                sparse_commit=a.sparse_commit,
            ),
            allow_nan=False,
        )
    )

"""Matched frozen-reader citation-instruction experiment on existing event cases.

No learning, no new retrieval, no post-hoc citation insertion. The precomputed
program_support arm is annotation-privileged and remains diagnostic only.
Original answers are synchronized before task labels or worker recipes are read.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import time

from bundle_reader import PromptBudgetError, SYSTEM
from bundle_trial import write
from event_experience import call_worker
from event_memory_trial import LIMIT, read, strict_identifier
from event_reader_experiment import preflight
from event_reader_view import EventPresentationReader, event_prompt
from evidence_bundle import EvidenceBundle, EvidenceSpan
from native import Question, digest
from native_citation import capture_native

PROFILE = "hepta.controlled-event.citation-instruction-v1"
CONDITIONS = ("hybrid", "organized", "program_support", "without_prerequisite")
STYLES = ("original", "premise_chain")
MARKERS = re.compile(r"\[E([1-9][0-9]*)\]")
PREMISE_APPENDIX = (
    " When a final fact depends on multiple distinct premises, cite each "
    "actually used premise's supplied evidence label. Do not cite an "
    "irrelevant source merely because it was delivered. Do not guess a missing "
    "premise or cite an undelivered label. Reply with only the requested "
    "identifier followed by its supporting [E1] [E2] labels, without extra "
    "explanation. If a necessary premise is unavailable, refuse."
)


def premise_prompt(tokenizer, query, receipt, *, token_limit):
    """Re-render only the system instruction, not the question or evidence."""
    if type(token_limit) is not int or token_limit not in (1024, 2048, 4096):
        raise ValueError("registered token ceiling required")
    sources = receipt["delivered_evidence"]
    derived = receipt["derived_evidence"]
    body = dict(
        question=query.content,
        question_time=query.observed_at,
        evidence=[
            dict(label=s["label"], observed_at=s["observed_at"], text=s["excerpt"])
            for s in sources
        ],
        controlled_schema_expansions=derived,
    )
    ids = tokenizer.apply_chat_template(
        [
            dict(role="system", content=SYSTEM + PREMISE_APPENDIX),
            dict(role="user", content=json.dumps(body, ensure_ascii=False)),
        ],
        tokenize=True,
        add_generation_prompt=True,
    )
    if not ids or len(ids) > token_limit:
        raise PromptBudgetError(len(ids), token_limit)
    return ids


class PairedCitationReader(EventPresentationReader):
    """One frozen model instance; prompt style is a registered, sequential arm."""

    def __init__(self, directory, *, expected_inventory):
        super().__init__(directory, expected_inventory=expected_inventory)
        self.original_profile = self.profile
        self.style = "original"

    def use_style(self, style):
        if style not in STYLES:
            raise ValueError("unregistered citation prompt style")
        self.style = style
        self.profile = (
            self.original_profile
            if style == "original"
            else digest((self.original_profile, PROFILE, PREMISE_APPENDIX))
        )

    def compile_input(
        self, query, bundle, originals, *, frontier, revoked, token_limit
    ):
        ids, receipt = event_prompt(
            self.tokenizer,
            query,
            bundle,
            originals,
            frontier=frontier,
            revoked=revoked,
            token_limit=token_limit,
        )
        if self.style == "original":
            return ids, receipt
        if self.style != "premise_chain":
            raise ValueError("unregistered prompt style")
        changed = premise_prompt(
            self.tokenizer, query, receipt, token_limit=token_limit
        )
        if digest(changed) == digest(ids):
            raise ValueError(
                "citation intervention failed to change actual model input"
            )
        return changed, receipt | dict(
            input_ids_digest=digest(changed),
            input_tokens=len(changed),
            citation_prompt_profile=PROFILE,
            source_body_unchanged=True,
            prompt_intervention_not_parameter_learning=True,
        )


def score_one(row, truth):
    """Post-journal only; necessary sources are privileged authored labels."""
    if row["kind"] != truth["kind"]:
        raise ValueError("task kind changed after generation")
    if row["status"] != "succeeded":
        return row | dict(
            strict_task_success=False,
            required_delivered=None,
            complete_citation_chain=None,
            postrun_failure_retained=True,
        )
    receipt = row["receipt"]
    supplied = receipt["delivered_evidence"]
    label_map = {s["label"]: s["original_id"] for s in supplied}
    if len(label_map) != len(supplied):
        raise ValueError("duplicate delivered label")
    if {s["original_id"] for s in supplied} != set(row["selected"]):
        raise ValueError("actual delivery changed selected original sources")
    answer = row["answer"]
    cited_markers = ["E" + m for m in MARKERS.findall(answer)]
    bound = {label_map[m] for m in cited_markers if m in label_map}
    required = set(truth["support"])
    if not 1 <= len(required) <= 4 or len(required) != len(truth["support"]):
        raise ValueError("invalid original authored requirement census")
    identifier = strict_identifier(answer)
    correct = identifier == truth["expected"]
    result = row | dict(
        parsed_identifier=identifier,
        strict_task_success=correct,
        required_delivered=required <= set(row["selected"]),
        required_source_count=len(required),
        required_delivered_but_uncited=sorted(
            (required & set(row["selected"])) - bound
        ),
        required_undelivered=sorted(required - set(row["selected"])),
        unbound_label_occurrences=[m for m in cited_markers if m not in label_map],
        cited_not_program_declared=sorted(bound - required),
        complete_citation_chain=required <= bound,
        formal_requirements_are_not_human_verified=True,
    )
    if truth["kind"] == "procedure":
        observed = call_worker(
            dict(
                operation="execute",
                recipe=truth["procedure"],
                supplied=identifier or "invalid_response",
            )
        )
        result["procedure_verification"] = observed
        result["strict_task_success"] = observed["exit_code"] == 0
    result["strict_success_and_complete_chain"] = bool(
        result["strict_task_success"] and result["complete_citation_chain"]
    )
    return result


def summarize(scored, cases):
    expected = {
        (qid, condition, style)
        for qid in cases
        for condition in CONDITIONS
        for style in STYLES
    }
    keys = [(r["question_id"], r["condition"], r["style"]) for r in scored]
    if (
        len(scored) != len(expected)
        or len(set(keys)) != len(keys)
        or set(keys) != expected
    ):
        raise ValueError("incomplete, duplicated or renamed pair census")
    by_key = dict(zip(keys, scored, strict=True))
    summary = {}
    for condition in CONDITIONS:
        baseline_success = changed_success = changed_citations = completed = missing = (
            wins
        ) = losses = 0
        original_chains = intervention_chains = 0
        for qid in cases:
            a, b = (by_key[(qid, condition, style)] for style in STYLES)
            if (
                a["selected"] != b["selected"]
                or a["candidate_digest"] != b["candidate_digest"]
            ):
                raise ValueError("comparison selected different evidence")
            if a["status"] != "succeeded" or b["status"] != "succeeded":
                missing += 1
                continue
            ra, rb = a["receipt"], b["receipt"]
            for field in ("reader_identity", "delivered_evidence", "derived_evidence"):
                if ra[field] != rb[field]:
                    raise ValueError("same-model citation contrast drifted evidence")
            if ra["input_ids_digest"] == rb["input_ids_digest"]:
                raise ValueError("missing prompt intervention")
            completed += 1
            baseline_success += a["strict_task_success"]
            changed_success += b["strict_task_success"]
            original_chains += a["strict_success_and_complete_chain"]
            intervention_chains += b["strict_success_and_complete_chain"]
            changed_citations += a["answer"] != b["answer"]
            wins += b["strict_task_success"] and not a["strict_task_success"]
            losses += a["strict_task_success"] and not b["strict_task_success"]
        n = len(cases)
        summary[condition] = dict(
            planned_pairs=n,
            completed_pairs=completed,
            missing_pairs=missing,
            original_strict_correct=baseline_success,
            premise_prompt_strict_correct=changed_success,
            original_strict_and_complete_formal_chain=original_chains,
            premise_prompt_strict_and_complete_formal_chain=intervention_chains,
            changed_raw_answers=changed_citations,
            task_wins=wins,
            task_losses=losses,
            all_planned_task_effect_bounds=[
                (wins - losses - missing) / n,
                (wins - losses + missing) / n,
            ],
        )
    return dict(
        schema="hepta.memory-cell.frozen-citation-prompt-paired-v1",
        real_model_calls=len(scored),
        question_count=len(cases),
        same_frozen_reader=True,
        identical_selected_evidence_within_pairs=True,
        generation_budget_unchanged=True,
        instructions_changed_not_training=True,
        authored_program_requirements_are_privileged=True,
        by_condition=summary,
        independent_semantic_citation_precision=None,
        independent_source_families=0,
        statistically_significant_advantage=False,
        production_accepted=False,
    )


def run(plan_dir, inputs, model_dir, output, *, plan_sha, stage_sha):
    from reader_reference import MODELS

    generating_source = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", generating_source):
        raise ValueError("exact source commit required")
    # Input wrapper verifies source and label byte hashes without parsing gold values.
    plan, originals = preflight(plan_dir, inputs, plan_sha)
    if len(plan["cases"]) != 8:
        raise ValueError("exact eight original questions required")
    stage = read(model_dir / "stage.json", stage_sha)
    if (stage["repository"], stage["revision"]) != MODELS[stage["tier"]]:
        raise ValueError("reader model revision differs from registered original")
    inventory = read(model_dir / "inventory.json", stage["inventory_sha256"])
    output.mkdir()
    write(
        output / "execution.json",
        dict(
            generating_source=generating_source,
            exact_plan_sha256=plan_sha,
            exact_reader_inventory=inventory["inventory_digest"],
            original_prompt_profile=SYSTEM,
            changed_prompt_appendix=PREMISE_APPENDIX,
            conditions=CONDITIONS,
            styles=STYLES,
            source_annotations_never_placed_in_prompt=True,
            publisher_support_arms_are_privileged=True,
            training_steps=0,
            production_accepted=False,
        ),
    )
    reader = PairedCitationReader(
        model_dir / "reader", expected_inventory=inventory["inventory_digest"]
    )
    raw_rows = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in plan["cases"]:
            query = Question(**case["query"])
            for condition in CONDITIONS:
                selected = list(case["controls"][condition]["selected"])
                spans = tuple(
                    EvidenceSpan(
                        d.identity,
                        d.root,
                        d.scope,
                        d.session,
                        d.observed_at,
                        0,
                        len(d.content.encode()),
                        d.content,
                        digest(d.content),
                    )
                    for d in (originals[key] for key in selected)
                )
                bundle = EvidenceBundle(
                    digest(asdict(query)), case["frontier"], spans, condition
                )
                for style in STYLES:
                    reader.use_style(style)
                    row = dict(
                        question_id=query.identity,
                        kind=case["kind"],
                        condition=condition,
                        style=style,
                        selected=selected,
                        candidate_digest=case["candidate_digest"],
                    )
                    try:
                        answer, receipt = reader.answer(
                            query,
                            bundle,
                            originals,
                            frontier=case["frontier"],
                            revoked=set(),
                            token_limit=LIMIT,
                        )
                        citation_request = capture_native(
                            query,
                            answer,
                            dict(
                                input_ids_sha256=receipt["input_ids_digest"],
                                delivered_evidence=receipt["delivered_evidence"],
                            ),
                            experiment_digest=digest(
                                (plan_sha, PROFILE, condition, style)
                            ),
                            family_digest=digest(query.family),
                        )
                        row.update(
                            status="succeeded",
                            answer=answer,
                            receipt=receipt,
                            citation_audit=citation_request,
                        )
                    except Exception as error:
                        row.update(
                            status="failed",
                            error_type=type(error).__name__,
                            error=str(error)[:1024],
                        )
                    journal.write(
                        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                    )
                    journal.flush()
                    os.fsync(journal.fileno())
                    raw_rows.append(row)
    reader.verify_frozen()
    # From this point onward the original targets may be parsed for postrun scoring.
    label_rows = read(inputs / "labels.json", plan["labels_sha"])
    labels = {item["id"]: item for item in label_rows}
    cases = {case["query"]["identity"]: case for case in plan["cases"]}
    if len(labels) != len(label_rows) or set(cases) - set(labels):
        raise ValueError("original task annotation census changed")
    scored = [score_one(row, labels[row["question_id"]]) for row in raw_rows]
    write(output / "scored-answers.json", scored)
    report = summarize(scored, cases)
    report["generating_source"] = generating_source
    report["source_plan_sha256"] = plan_sha
    report["reader_inventory_digest"] = inventory["inventory_digest"]
    report["raw_answer_bytes_preserved"] = True
    report["new_pretrained_training"] = False
    write(output / "report.json", report)
    if any(row["status"] == "failed" for row in scored):
        raise ValueError(
            "complete source-citation experiment contains failed model calls"
        )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "inputs", "model", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--plan-sha", required=True)
    parser.add_argument("--stage-sha", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.plan,
                args.inputs,
                args.model,
                args.output,
                plan_sha=args.plan_sha,
                stage_sha=args.stage_sha,
            ),
            ensure_ascii=False,
            allow_nan=False,
        )
    )

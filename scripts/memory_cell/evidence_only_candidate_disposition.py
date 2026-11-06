"""Post-hoc evidence-local candidate filtering on SEALED real model scores.

No model inference and no prospective preregistration. Candidate extraction
from a single delivered value is NOT reader ability. Missing prerequisites
can leave a terminal value visible despite insufficient causal support.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from offline_event_reader_trial import ARMS, inputs, write
from reader_candidate_capacity import CHOICE


def delivered_choices(selected, originals):
    visible = set()
    for identity in selected:
        doc = originals[identity]
        data = json.loads(doc["content"])
        if (
            data["id"] != doc["identity"]
            or data["schema"] != "hepta.controlled-event.v1"
        ):
            raise ValueError("unbound original event")
        value = data["value"]
        if isinstance(value, str) and CHOICE.fullmatch(value):
            visible.add(value)
    return visible


def restrict_scored(row, selected, originals):
    """Filter already-computed scores; never rescore or add hypotheses."""
    visible = delivered_choices(selected, originals)
    hypotheses = [s for s in row["candidates"] if s["value"] in visible]
    if len({s["value"] for s in hypotheses}) != len(hypotheses):
        raise ValueError("duplicate scored candidate")
    best = (
        max(hypotheses, key=lambda s: s["mean_log_likelihood"])["value"]
        if hypotheses
        else None
    )
    return dict(
        chosen=best,
        evidence_only_candidates=[s["value"] for s in hypotheses],
        candidate_count=len(hypotheses),
        abstained=best is None,
        singleton=len(hypotheses) == 1,
    )


def analyze(archive, raw_scores, result, output):
    plan, originals, _ = inputs(archive)
    raw = Path(raw_scores).read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    original_result = json.loads(Path(result).read_text())
    if (
        len(rows) != 48
        or original_result["raw_scores_sha256"] != hashlib.sha256(raw).hexdigest()
        or original_result["actual_inferences"] != 48
    ):
        raise ValueError("original journal does not match sealed actual results")
    restricted = []
    index = 0
    for case in plan["cases"]:
        for arm in ARMS:
            row = rows[index]
            index += 1
            if row["arm"] != arm or row["question_id"] != case["query"]["identity"]:
                raise ValueError("original paired score order changed")
            view = restrict_scored(row, case["controls"][arm]["selected"], originals)
            restricted.append(dict(question_id=row["question_id"], arm=arm, **view))
    # This is retrospective diagnosis. No new candidate inference occurs.
    with zipfile.ZipFile(archive) as package:
        raw_labels = package.read("observations/labels.json")
    if hashlib.sha256(raw_labels).hexdigest() != plan["labels_sha"]:
        raise ValueError("pinned labels changed")
    labels = {r["id"]: r for r in json.loads(raw_labels)}
    metrics = {}
    for arm in ARMS:
        subset = [r for r in restricted if r["arm"] == arm]
        metrics[arm] = dict(
            n=len(subset),
            abstained=sum(r["abstained"] for r in subset),
            singleton=sum(r["singleton"] for r in subset),
            multiple_options=sum(r["candidate_count"] >= 2 for r in subset),
            strictly_correct=sum(
                r["chosen"] == labels[r["question_id"]]["expected"] for r in subset
            ),
            nontrivial_choice_correct=sum(
                r["candidate_count"] >= 2
                and r["chosen"] == labels[r["question_id"]]["expected"]
                for r in subset
            ),
            visible_gold=sum(
                labels[r["question_id"]]["expected"] in r["evidence_only_candidates"]
                for r in subset
            ),
        )
    report = dict(
        schema="hepta.memory.evidence-only-posthoc-disposition.v1",
        original_score_journal_sha256=original_result["raw_scores_sha256"],
        model_calls=0,
        training_steps=0,
        query_time_candidate_generation=False,
        posthoc=True,
        prior_exposed_development_cases=True,
        human_sufficiency_review=False,
        independent_source_family_success=False,
        production_accepted=False,
        conditions=metrics,
        records=restricted,
    )
    write(Path(output), report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("archive", "raw", "result", "output"):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            analyze(args.archive, args.raw, args.result, args.output)["conditions"]
        )
    )

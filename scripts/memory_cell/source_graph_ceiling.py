"""Typed event-graph solvability ceiling over original, delivered evidence.

No model inference, human sufficiency certificate, parameter learning, or production authorization.
"""

import hashlib
import json
import zipfile
from pathlib import Path

ARCHIVE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)


def resolve(spec, selection, originals):
    """Conservative closed-world lookup: reject gaps, conflicts, and scope escapes."""
    if not selection or len(selection) != len(set(selection)):
        return None
    visible = {}
    for identity in selection:
        source = originals[identity]
        if source["scope"] != spec["id"]:
            raise ValueError("source scope leak")
        row = json.loads(source["content"])
        if row["id"] != identity or row["schema"] != "hepta.controlled-event.v1":
            raise ValueError("original source identity changed")
        if row["revision"] <= spec["revision"]:
            visible[identity] = row
    heads = set(visible)
    for row in visible.values():
        for prior in row["supersedes"]:
            if prior in visible:
                old = visible[prior]
                if (old["entity"], old["attribute"]) != (
                    row["entity"],
                    row["attribute"],
                ) or old["revision"] >= row["revision"]:
                    raise ValueError("invalid correction edge")
                heads.discard(prior)
    entities = {spec["entity"]}
    for attribute in spec["path"]:
        next_entities = set()
        for entity in entities:
            values = {
                visible[k]["value"]
                for k in heads
                if (visible[k]["entity"], visible[k]["attribute"])
                == (entity, attribute)
            }
            if len(values) != 1:
                return None
            next_entities.update(values)
        if len(next_entities) != 1:
            return None
        entities = next_entities
    return next(iter(entities)) if len(entities) == 1 else None


def diagnose(archive):
    archive = Path(archive)
    if (
        archive.is_symlink()
        or hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA
    ):
        raise ValueError("original archive pin mismatch")
    with zipfile.ZipFile(archive) as z:
        plan = json.loads(z.read("plan/plan.json"))
        source_bytes = z.read("plan/source-view.json")
        if hashlib.sha256(source_bytes).hexdigest() != plan["source_view_sha"]:
            raise ValueError("frozen source view changed")
        originals = {d["identity"]: d for d in json.loads(source_bytes)}
        question_bytes = z.read("observations/questions.json")
        if (
            hashlib.sha256(question_bytes).hexdigest()
            != plan["extraction"]["files"]["questions.json"]
        ):
            raise ValueError("public question source changed")
        questions = {r["id"]: r for r in json.loads(question_bytes)}
        labels_bytes = z.read("observations/labels.json")
        if hashlib.sha256(labels_bytes).hexdigest() != plan["labels_sha"]:
            raise ValueError("target label pin changed")
        if tuple(plan["arms"]) != ARMS or len(plan["cases"]) != 8:
            raise ValueError("registered census changed")
        # Solve using ONLY public question fields and originally selected sources.
        # Targets are parsed only after all candidate-independent solves finish.
        rows = []
        for case in plan["cases"]:
            qid = case["query"]["identity"]
            for arm in ARMS:
                selection = case["controls"][arm]["selected"]
                rows.append(
                    dict(
                        question_id=qid,
                        task=case["kind"],
                        arm=arm,
                        predicted=resolve(questions[qid], selection, originals),
                        selected=list(selection),
                    )
                )
        labels = {r["id"]: r for r in json.loads(labels_bytes)}
        for row in rows:
            label = labels[row["question_id"]]
            row["strict_success"] = (
                row["predicted"] is not None and row["predicted"] == label["expected"]
            )
            row["program_declared_support_covered"] = set(label["support"]).issubset(
                row["selected"]
            )
        return dict(
            schema="hepta.memory.typed-source-ceiling.v1",
            source_archive_sha256=ARCHIVE_SHA,
            model_calls=0,
            new_retrieval_calls=0,
            training_calls=0,
            controlled_schema_only=True,
            previously_exposed_development_set=True,
            human_semantic_sufficiency_certified=False,
            general_reader_ability_established=False,
            memory_gain_established=False,
            production_accepted=False,
            arms={
                arm: dict(
                    planned=8,
                    strict_success=sum(
                        r["strict_success"] for r in rows if r["arm"] == arm
                    ),
                    support_covered=sum(
                        r["program_declared_support_covered"]
                        for r in rows
                        if r["arm"] == arm
                    ),
                )
                for arm in ARMS
            },
            observations=rows,
        )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path)
    p.add_argument("report", type=Path)
    args = p.parse_args()
    args.report.write_text(json.dumps(diagnose(args.archive), indent=2) + "\n")

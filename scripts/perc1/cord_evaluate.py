"""Post-freeze scoring for CORD; labels are never supplied to confirmation actors."""

import json
from pathlib import Path

from . import cord_task
from .schema import require, sha


def read(path):
    return json.loads(Path(path).read_bytes())


def label(item):
    raw = Path(item["annotation_path"]).read_bytes()
    require(sha(raw) == item["annotation_sha256"], "annotation changed")
    value = json.loads(raw)
    target = value.get("gt_parse", {}).get("total", {}).get("total_price")
    if type(target) is not str or not any(character.isdigit() for character in target):
        return None
    return cord_task.normalize_amount(target)


def evaluate(args):
    from .cord_active import ARMS, QUALITY_RUBRIC

    root, index = args.output.resolve(), read(args.index)
    done = read(root / "ACTOR_DONE.json")
    plan = read(root / "PLAN.json")
    for filename, key in (
        ("PLAN.json", "plan_file_sha256"),
        ("PAIRS.json", "pairs_file_sha256"),
        ("TRAINING_ATTEMPTS.json", "training_attempts_file_sha256"),
    ):
        require(
            sha((root / filename).read_bytes()) == done[key],
            "frozen training/plan evidence changed",
        )
    require(plan["arms"] == list(ARMS), "actor roster protocol changed")
    require(
        all(
            sha(Path(__file__).with_name(name).read_bytes()) == digest
            for name, digest in plan["source_pins"].items()
        ),
        "execution source changed before evaluation",
    )
    require(
        sha(args.index.read_bytes()) == plan["input_index_sha256"],
        "frozen input index changed",
    )
    head, recipe = read(root / "HEAD.json"), read(root / "PROFILE.json")
    require(
        sha(head) == done["head_sha256"]
        and sha(recipe) == done["profile_sha256"]
        and sha((root / "HEAD.json").read_bytes()) == done["head_file_sha256"]
        and sha((root / "PROFILE.json").read_bytes()) == done["profile_file_sha256"],
        "frozen model/profile changed",
    )
    expected = {
        (s["id"], arm)
        for s in index["sources"]
        if s["split"] == "confirmation"
        for arm in ARMS
    }
    require(
        len(done["results"]) == len(expected)
        and {(r["task_id"], r["arm"]) for r in done["results"]} == expected,
        "incomplete actor roster",
    )
    for entry in done["results"]:
        raw = (
            root / "results" / (entry["task_id"] + "-" + entry["arm"] + ".json")
        ).read_bytes()
        record = json.loads(raw)
        require(
            sha(raw) == entry["sha256"]
            and record["task_id"] == entry["task_id"]
            and record["arm"] == entry["arm"]
            and record["status"] == entry["status"]
            and record["seed"] == plan["seed"],
            "actor record changed before label access",
        )
    rows = []
    for item in index["sources"]:
        if item["split"] != "confirmation":
            continue
        target = label(item)
        for arm in ARMS:
            raw = (root / "results" / (item["id"] + "-" + arm + ".json")).read_bytes()
            record = json.loads(raw)
            pin = next(
                r["sha256"]
                for r in done["results"]
                if (r["task_id"], r["arm"]) == (item["id"], arm)
            )
            require(sha(raw) == pin, "actor result changed")
            quality = (
                float(record["answer"] == target)
                if target is not None and record["status"] == "COMPLETED"
                else None
            )
            rows.append(
                dict(
                    task_id=item["id"],
                    arm=arm,
                    quality=quality,
                    actor_sha256=pin,
                    status=record["status"],
                    inclusive_wall_ns=record.get("cost", {}).get("inclusive_wall_ns"),
                    trained_head_decision_retained=(
                        record.get("active_head_sha256") == done["head_sha256"]
                        and record.get("active_decision_sha256") is not None
                    ),
                    visual_choice_changed=(
                        record.get("selected_without_visual_diagnostic", {}).get(
                            "candidate_id"
                        )
                        != record.get("selected")
                    )
                    if arm == "learned"
                    and record.get("selected_without_visual_diagnostic")
                    else None,
                )
            )
    summary = {}
    for arm in ARMS:
        group = [row for row in rows if row["arm"] == arm]
        summary[arm] = dict(
            tasks=len(group),
            correct=sum(row["quality"] == 1 for row in group),
            unknown_quality=sum(row["quality"] is None for row in group),
            completed=sum(row["status"] == "COMPLETED" for row in group),
            total_inclusive_wall_ns=sum(row["inclusive_wall_ns"] or 0 for row in group)
            if all(row["inclusive_wall_ns"] is not None for row in group)
            else None,
        )
    report = dict(
        schema="perc1.cord-pilot-report.v1",
        scientific_status="HOLD",
        adoption="NoUpdate",
        source_independence_verified=False,
        new_independent_confirmation_sources=0,
        tasks_evaluated=len({row["task_id"] for row in rows}),
        quality_rubric=QUALITY_RUBRIC,
        training_source_groups={
            split: dict(
                attempted=sum(
                    a["split"] == split for a in read(root / "TRAINING_ATTEMPTS.json")
                ),
                fitted=len(
                    {
                        p["source_group"]
                        for p in read(root / "PAIRS.json")
                        if p["split"] == split
                    }
                ),
            )
            for split in ("train", "dev")
        },
        train_pairs=head["training_receipt"]["train_count"],
        dev_pairs=head["training_receipt"]["dev_count"],
        optimizer_updates=head["training_receipt"]["steps"],
        trained_attention_head_executed=any(
            row["trained_head_decision_retained"] for row in rows
        ),
        trained_head_decisions_retained=sum(
            row["trained_head_decision_retained"] for row in rows
        ),
        visual_choice_changes=sum(row["visual_choice_changed"] is True for row in rows),
        visual_input_intervention="zero_visual arm executes counterfactual actions; actual encoder cost retained, testing signal contribution rather than encoder cost removal",
        selection_intervention="fixed_selection arm keeps neural encoder and OCR decoder, replacing learned choice with lower band",
        native_daemon_integrated=False,
        summary=summary,
        rows=rows,
        measured_net_benefit=None,
        direct_roi_ocr="not run: target is private; oracle upper bound remains missing",
        decoding_learned=False,
        decoding_ablation="not run",
        dynamic_environment="not exercised",
        cost_limits="energy/billing/historical capture unknown; child CPU measured only for successful terminated children; failed invocation stage costs incomplete; shared preprocessing separate; every arm cold-reads terminal artifacts and learned additionally cold-reads head decision; no full-cost superiority claim",
    )
    cord_task.write(root / "REPORT.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))

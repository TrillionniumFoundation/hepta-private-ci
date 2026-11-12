"""Real OCR branch pairs; failed observations remain attempted evidence, never labels."""

from dataclasses import asdict
from pathlib import Path

from . import acquisition, cord_task
from .cord_evaluate import label
from .mlp_head import train_head
from .schema import Cost, require, sha
from .source_feature_profile import feature_extractor_sha256, observed_prefix


def profile(receipt):
    result = receipt["result"]["producer"]
    return dict(
        schema="perc1.source-feature-profile.v1",
        observation="first",
        aggregation="flatten",
        representation="dense",
        token_count=len(result["observation"]["latents"]),
        token_dimension=result["encoder"]["dimension"],
        task_goal_width=5,
        encoder_digest=sha(result["encoder"]),
        latent_model_digest=sha(result["model"]),
        projection_sha256=result["model"]["projection_sha256"],
    )


def cost(receipt):
    """Training target proxy: measured enclosing dispatch, never nested-time sum."""
    read_ns = receipt["result"]["source_evidence"]["measurements"]["read_wall_ns"]
    total = max(1, (receipt["measurements"]["wall_ns"] + 999) // 1000)
    acquisition_us = max(1, (read_ns + 999) // 1000)
    require(total >= acquisition_us, "capture read exceeds dispatch envelope")
    return asdict(Cost(acquisition=acquisition_us, inference=total - acquisition_us))


def evidence(receipt):
    return dict(
        source_id=receipt["result"]["source_evidence"]["source_id"],
        receipt_sha256=receipt["receipt_sha256"],
        capture_sha256=receipt["result"]["source_evidence"]["capture_sha256"],
    )


def train(index, public, projection, root, seed):
    rows, attempts, recipe = [], [], None
    labels = {
        item["id"]: item for item in index["sources"] if item["split"] != "confirmation"
    }
    solver = sha(Path(cord_task.__file__).read_bytes())
    for task in public:
        if task["split"] == "confirmation":
            continue
        value = cord_task.config(task, root / (task["id"] + "-train"))
        cord_task.write(root / (task["id"] + "-config.json"), value)
        owner, producer = cord_task.adapter(value, projection)
        cord_task.write(
            root / (task["id"] + "-attempt-started.json"),
            dict(task_id=task["id"], split=task["split"], status="STARTED"),
        )
        with owner:
            initial = cord_task.acquire(owner, producer, task, "initial", neural=True)
            valid_initial = initial["status"] == "executed"
            if valid_initial:
                current = profile(initial)
                recipe = current if recipe is None else recipe
                require(
                    recipe == current,
                    "feature profile differs across training observations",
                )
                prefix = observed_prefix(
                    owner, task["task_sha256"], ["initial"], recipe
                )
                before = cord_task.answer(owner, [initial])
                offerings = cord_task.candidates(
                    task, prefix, cord_task.text(owner, initial)
                )
            else:
                offerings = [{"id": name} for name in cord_task.BANDS]
            # All controlled branch effects finish before this task's evaluator is opened.
            branches = [
                (
                    offering,
                    cord_task.acquire(
                        owner, producer, task, offering["id"], neural=True
                    ),
                )
                for offering in offerings
            ]
            target = label(labels[task["id"]])
            attempts.append(
                dict(
                    task_id=task["id"],
                    split=task["split"],
                    target_available=target is not None,
                    initial_receipt_sha256=initial["receipt_sha256"],
                    branch_receipts=[r["receipt_sha256"] for _, r in branches],
                    initial_status=initial["status"],
                    observations=[
                        dict(
                            operation_id=r["operation_id"],
                            status=r["status"],
                            error=r["error"],
                            receipt_sha256=r["receipt_sha256"],
                            measurements=r["measurements"],
                        )
                        for r in [initial] + [r for _, r in branches]
                    ],
                    fitted_candidates=[
                        offering["id"]
                        for offering, r in branches
                        if valid_initial
                        and target is not None
                        and r["status"] == "executed"
                    ],
                    failure_policy="one attempt per view; retain failures and their costs; no retry; incomplete observations excluded from fit, reported as censoring",
                )
            )
            cord_task.write(
                root / (task["id"] + "-attempt-completed.json"), attempts[-1]
            )
            if target is None or not valid_initial:
                continue  # Incomplete TRAIN/DEV prefixes stay in attempts; confirmation never pruned.
            for offering, extra in branches:
                if extra["status"] != "executed":
                    continue
                initial_cost, extra_cost = cost(initial), cost(extra)
                common = dict(
                    prefix_sha256=sha(prefix), solver_sha256=solver, inference_seed=seed
                )
                pair = dict(
                    schema="perc1.acquisition-pair.v1",
                    source_group=task["id"],
                    split=task["split"],
                    candidate_id=offering["id"],
                    features=offering["features"],
                    without=dict(
                        common,
                        evidence=[evidence(initial)],
                        score=float(before == target),
                        cost=initial_cost,
                    ),
                    with_=None,
                )
                del pair["with_"]
                pair["with"] = dict(
                    common,
                    evidence=[evidence(initial), evidence(extra)],
                    score=float(cord_task.answer(owner, [initial, extra]) == target),
                    cost={
                        key: initial_cost[key] + extra_cost[key] for key in initial_cost
                    },
                )
                acquisition.paired_label(pair)
                rows.append(pair)
    cord_task.write(root / "TRAINING_ATTEMPTS.json", attempts)
    cord_task.write(root / "PAIRS.json", rows)
    registry = {
        split: [t["id"] for t in public if t["split"] == split]
        for split in ("train", "dev", "confirmation")
    }
    selected = {
        split: [row for row in rows if row["split"] == split]
        for split in ("train", "dev")
    }
    require(
        len(selected["train"]) >= 24 and len(selected["dev"]) >= 6,
        "insufficient labeled training pairs",
    )
    # One preregistered seed/fit; no DEV-based architecture or threshold search.
    head = train_head(
        selected["train"],
        selected["dev"],
        registry,
        feature_extractor_sha256=feature_extractor_sha256(recipe),
        seed=seed,
        steps=200,
        hidden=8,
        cost_value=0.5 / 1_000_000,
        threshold=0.0,
    )
    cord_task.write(root / "HEAD.json", head)
    cord_task.write(root / "PROFILE.json", recipe)
    return head, recipe, attempts

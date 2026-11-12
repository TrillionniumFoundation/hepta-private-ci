"""Bounded real-image attention pilot; HOLD regardless of observed outcome.

TRAIN/DEV paired values come from executed OCR continuations. Confirmation actors
receive image-only tasks; the evaluation subcommand opens labels afterwards.
The only learned component is acquisition. The content decoder remains OCR/rules.
"""

import argparse
import copy
import json
import random
import resource
import time
from pathlib import Path

from . import acquisition, cord_task
from .cord_evaluate import evaluate, read
from .cord_training import train
from .active_capture import observe, read_decision
from .schema import require, sha
from .source_capture import configured_capture
from .source_feature_profile import observed_prefix

SEED = 1101
ARMS = (
    "learned",
    "full_ocr",
    "public_feature_rule",
    "fixed_region",
    "random_region",
    "zero_visual",
    "fixed_selection",
)
QUALITY_RUBRIC = "exact ASCII digit-string match after removing punctuation and leading zeros; not a currency-aware monetary equivalence test"


def tasks(index, root, weights, projection):
    directory = root / "tasks"
    directory.mkdir()
    public = []
    for item in index["sources"]:
        source = {k: item[k] for k in ("id", "split", "image_path", "image_sha256")}
        source["source_uri"] = (
            "https://huggingface.co/datasets/naver-clova-ix/cord-v2/tree/"
            + index["revision"]
            + "#"
            + item["id"]
        )
        public.append(
            cord_task.prepare(source, directory / item["id"], weights, projection)
        )
    cord_task.write(root / "PUBLIC_TASKS.json", public)
    return public


def execute(task, arm, head, recipe, projection, root):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    value = cord_task.config(task, root / (task["id"] + "-" + arm))
    cord_task.write(root / (task["id"] + "-" + arm + "-config.json"), value)
    owner, producer = cord_task.adapter(value, projection)
    receipts, selected, counterfactual = [], None, None
    original, recovery_ns, ablation = None, 0, None
    with owner:
        if arm == "full_ocr":
            receipts.append(
                cord_task.acquire(owner, producer, task, "full", neural=False)
            )
            selected = "full"
        else:
            neural = arm in ("learned", "zero_visual", "fixed_selection")
            initial = cord_task.acquire(owner, producer, task, "initial", neural=neural)
            receipts.append(initial)
            if arm in ("learned", "zero_visual"):
                prefix = observed_prefix(
                    owner, task["task_sha256"], ["initial"], recipe
                )
                offers = cord_task.candidates(
                    task, prefix, cord_task.text(owner, initial)
                )
                # Causal diagnostic only: these zero-latent scores do not dispatch effects.
                counter = copy.deepcopy(offers)
                for entry in counter:
                    entry["features"]["acquired_latent"] = [0.0] * len(
                        prefix["latent_summary"]
                    )
                counterfactual = acquisition.choose(
                    head,
                    [
                        {k: entry[k] for k in ("id", "upper_cost", "features")}
                        for entry in counter
                    ],
                )
                if arm == "zero_visual":
                    selected = counterfactual["candidate_id"]
                    ablation = dict(
                        schema="perc1.cord-visual-intervention.v1",
                        intervention="zero 64 acquired visual inputs after real encoding; all public features and trained head held fixed",
                        original_prefix_sha256=sha(prefix),
                        head_sha256=sha(head),
                        modified_candidates=counter,
                        selection=counterfactual,
                    )
                    cord_task.write(
                        root / (task["id"] + "-zero-visual-decision.json"), ablation
                    )
                    if selected is not None:
                        receipts.append(
                            cord_task.acquire(
                                owner, producer, task, selected, neural=True
                            )
                        )
                else:
                    original = observe(
                        producer,
                        "choose",
                        head,
                        offers,
                        lambda admitted: configured_capture(
                            task["sources"][admitted["source_id"]], admitted
                        ),
                        expected_head_sha256=sha(head),
                        task_sha256=task["task_sha256"],
                        observed_operations=["initial"],
                        feature_profile=recipe,
                    )
                    require(
                        original["outcome"] in ("executed", "stopped"),
                        "active outcome incomplete",
                    )
                    selected = original["decision"]["selection"]["candidate_id"]
                    if original["owner_receipt"] is not None:
                        receipts.append(original["owner_receipt"])
            else:
                if arm == "random_region":
                    selected = random.Random(sha([SEED, task["id"]])).choice(
                        list(cord_task.BANDS)
                    )
                elif (
                    arm == "public_feature_rule"
                    and cord_task.answer(owner, receipts) is not None
                ):
                    selected = None
                else:
                    selected = "lower"
                if selected:
                    receipts.append(
                        cord_task.acquire(
                            owner, producer, task, selected, neural=neural
                        )
                    )
        answer = cord_task.answer(owner, receipts)
        counts = dict(
            encoder_calls=0 if producer.worker is None else producer.worker.calls,
            ocr_calls=len(receipts),
            reservations=owner.status()["reserved_units"],
        )
        # Reopening performs journal and artifact verification; no new acquisition.
        bindings = owner.binding
    begin = time.perf_counter_ns()
    from .owner import Owner

    with Owner(value["state_dir"], bindings, value["budget_units"]) as cold:
        if arm == "learned":
            require(
                read_decision(cold, "choose") == original["decision"],
                "cold decision differs",
            )
        require(
            cord_task.answer(cold, [cold.receipt(r["operation_id"]) for r in receipts])
            == answer,
            "cold terminal read differs",
        )
    recovery_ns = time.perf_counter_ns() - begin
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(
        schema="perc1.cord-actor-result.v1",
        task_id=task["id"],
        source_group=task["id"],
        arm=arm,
        seed=SEED,
        status="COMPLETED",
        answer=answer,
        selected=selected,
        observed_source_ids=[
            r["result"]["source_evidence"]["source_id"] for r in receipts
        ],
        receipt_sha256s=[r["receipt_sha256"] for r in receipts],
        counts=counts,
        selected_without_visual_diagnostic=counterfactual,
        selection=original["decision"]["selection"] if original else None,
        active_decision_sha256=original["decision_sha256"] if original else None,
        active_head_sha256=original["decision"]["head_sha256"] if original else None,
        ablation=ablation,
        cost=dict(
            inclusive_wall_ns=time.perf_counter_ns() - started,
            process_cpu_ns=time.process_time_ns() - cpu,
            terminated_child_cpu_ns=round(
                1e9
                * (
                    children_after.ru_utime
                    + children_after.ru_stime
                    - children.ru_utime
                    - children.ru_stime
                )
            ),
            recovery_nested_wall_ns=recovery_ns,
            energy_joules=None,
            provider_billing=None,
            historical_capture_cost=None,
            shared_preparation_wall_ns=task["preparation_wall_ns"],
            nested_observation_measurements=[
                dict(
                    owner=r["measurements"],
                    source=r["result"]["source_evidence"]["measurements"],
                    producer=r["result"].get("producer", {}).get("measurements"),
                )
                for r in receipts
            ],
            scope="inclusive task invocation including local cold terminal read in every arm; learned also verifies retained head decision; nested observations are explanatory, never added to inclusive wall time; preparation separate",
        ),
        actual_native_daemon=False,
        scientific_qualified=False,
        adoption="NoUpdate",
    )


def run(args):
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    names = (
        "cord_active cord_evaluate cord_training cord_task active_capture source_feature_profile source_entry source_capture "
        "capture_entry owner producer projection raster native schema mlp_head acquisition entry browser_capture"
    ).split()
    paths = [Path(__file__).with_name(name + ".py") for name in names]
    pins = {p.name: sha(p.read_bytes()) for p in paths}
    prior = None
    if args.prior_failed_run is not None:
        previous = args.prior_failed_run.resolve()
        previous_plan = read(previous / "PLAN.json")
        require(
            previous_plan["input_index_sha256"] == sha(args.index.read_bytes()),
            "prior attempt used a different source panel",
        )
        require(
            read(previous / "FAILURE.json")["status"] == "INCOMPLETE"
            and not (previous / "ACTOR_DONE.json").exists()
            and not list((previous / "results").glob("*.json")),
            "prior confirmation exposure requires a new protocol",
        )
        prior = dict(
            name=previous.name,
            plan_sha256=sha((previous / "PLAN.json").read_bytes()),
            failure_sha256=sha((previous / "FAILURE.json").read_bytes()),
            completed_training_attempts=len(
                list(previous.glob("*-attempt-completed.json"))
            ),
            confirmation_actor_results=0,
            previous_costs="retained in prior execution envelope; not erased or included as new confirmation",
        )
    plan = dict(
        schema="perc1.cord-pilot-plan.v1",
        input_index_sha256=sha(args.index.read_bytes()),
        source_pins=pins,
        prior_failed_attempt=prior,
        seed=SEED,
        head_steps=200,
        hidden=8,
        arms=list(ARMS),
        target=cord_task.TASK,
        target_rectangle_public=False,
        quality_rubric=QUALITY_RUBRIC,
        selection_intervention="zero_visual dispatches the zero-latent choice through ordinary owner after real encoding; fixed_selection keeps encoding and decoder but fixes lower band; learned also retains offline zero-latent scores",
        missing_train_target="retain all four view attempts and costs per source; no retries; omit unlabeled or incomplete fit pairs with explicit censoring, minimum24/6 pairs; no confirmation pruning",
        complete_cost_required=True,
        source_independence_verified=False,
        scientific_status="HOLD",
    )
    cord_task.write(root / "PLAN.json", plan)
    index = read(args.index)
    require(index["success"] is True, "source acquisition incomplete")
    public = tasks(index, root, args.weights.resolve(), args.projection.resolve())
    projection = read(args.projection)
    head, recipe, attempts = train(index, public, projection, root, SEED)
    result_dir = root / "results"
    result_dir.mkdir()
    statuses = []
    for task in public:
        if task["split"] != "confirmation":
            continue
        for arm in ARMS:
            started, cpu = time.perf_counter_ns(), time.process_time_ns()
            try:
                result = execute(task, arm, head, recipe, projection, result_dir)
            except Exception as error:
                result = dict(
                    schema="perc1.cord-actor-result.v1",
                    task_id=task["id"],
                    arm=arm,
                    seed=SEED,
                    status="UNKNOWN",
                    error_type=type(error).__name__,
                    error=str(error),
                    answer=None,
                    cost=dict(
                        inclusive_wall_ns=time.perf_counter_ns() - started,
                        process_cpu_ns=time.process_time_ns() - cpu,
                        energy_joules=None,
                        provider_billing=None,
                        partial_observation_stage_costs="incomplete on failed invocation; retained owner originals remain available",
                    ),
                    retained_owner_directory=task["id"] + "-" + arm,
                    scientific_qualified=False,
                    adoption="NoUpdate",
                )
            result_path = result_dir / (task["id"] + "-" + arm + ".json")
            cord_task.write(result_path, result)
            statuses.append(
                dict(
                    task_id=task["id"],
                    arm=arm,
                    status=result["status"],
                    sha256=sha(result_path.read_bytes()),
                )
            )
            print(json.dumps(statuses[-1]), flush=True)
    require(
        pins == {p.name: sha(p.read_bytes()) for p in paths},
        "source changed during pilot",
    )
    cord_task.write(
        root / "ACTOR_DONE.json",
        dict(
            results=statuses,
            all_results_retained=True,
            source_unchanged=True,
            head_sha256=sha(head),
            profile_sha256=sha(recipe),
            head_file_sha256=sha((root / "HEAD.json").read_bytes()),
            profile_file_sha256=sha((root / "PROFILE.json").read_bytes()),
            plan_file_sha256=sha((root / "PLAN.json").read_bytes()),
            pairs_file_sha256=sha((root / "PAIRS.json").read_bytes()),
            training_attempts_file_sha256=sha(
                (root / "TRAINING_ATTEMPTS.json").read_bytes()
            ),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "evaluate"))
    for name in ("index", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("weights", "projection"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--prior-failed-run", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        existed = args.output.exists()
        try:
            run(args)
        except Exception as error:
            if not existed and args.output.is_dir():
                cord_task.write(
                    args.output / "FAILURE.json",
                    dict(
                        status="INCOMPLETE",
                        error_type=type(error).__name__,
                        message=str(error),
                        scientific_status="HOLD",
                        adoption="NoUpdate",
                    ),
                )
            raise
    else:
        evaluate(args)


if __name__ == "__main__":
    main()

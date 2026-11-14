"""Precommitted source writes and fresh-process parameter-only recall experiment.

Development cohorts may choose a recipe. Confirmation uses a different fixed
cohort and cannot accept command-line recipe overrides. Neither is production
qualification, storage compression evidence, or an independent natural memory task.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import torch

from native import digest
from parametric_cohort import (
    cohort,
    questions,
    score,
    TRAIN_TEMPLATES,
    TEST_TEMPLATE,
    SELECT_TEMPLATE,
    VALUES,
)
from parametric_model import SourceMemoryCell, adapter_digest
from prepare_parametric import prepare

CONFIRMATION_STEPS = 512
CONFIRMATION_LR = 0.001
MODEL_SEED = 2718


def write_json(path, value):
    data = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def read_worker(
    model, snapshot, sha, scope, roots, query, output, label, *, control="adapter"
):
    request = dict(
        model=str(Path(model).resolve()),
        snapshot=str(Path(snapshot).resolve()),
        manifest_sha256=sha,
        scope=scope,
        allowed_roots=sorted(roots),
        questions=query,
        rank=8,
        seed=MODEL_SEED,
        control=control,
    )
    write_json(output / f"{label}.request.json", request)
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name("parametric_worker.py"))],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=180,
        cwd=output / "reader-cwd",
        check=False,
    )
    (output / f"{label}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"isolated reader failed ({label}): {result.stderr[-2000:]}")
    journal = json.loads(result.stdout)
    journal["fresh_process_wall_seconds"] = time.perf_counter() - started
    write_json(output / f"{label}.journal.json", journal)
    return journal


def identity():
    root = Path(__file__).resolve().parent
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob("*.py"))
    }
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return dict(
        git_head=head,
        files_sha256=files,
        source_manifest_sha256=digest(files),
        python=platform.python_version(),
        torch=torch.__version__,
        platform=platform.platform(),
    )


def run_trial(model, output, phase, *, steps=None, learning_rate=None):
    if phase not in ("development", "confirmation"):
        raise ValueError("registered phase required")
    if phase == "confirmation" and (steps is not None or learning_rate is not None):
        raise ValueError("confirmation recipe cannot be tuned by CLI")
    steps = steps if steps is not None else CONFIRMATION_STEPS
    learning_rate = learning_rate if learning_rate is not None else CONFIRMATION_LR
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "reader-cwd").mkdir()
    torch.set_num_threads(2)
    acquisition = prepare(model)
    protocol = dict(
        schema="hepta.parametric-memory.protocol.v1",
        phase=phase,
        seed=413 if phase == "development" else 95873,
        scope=f"parametric-{phase}",
        source_count=16,
        steps=steps,
        learning_rate=learning_rate,
        rank=8,
        model_seed=MODEL_SEED,
        train_templates=list(TRAIN_TEMPLATES),
        test_template=TEST_TEMPLATE,
        global_values=list(VALUES),
        value_choice_before_source_sampling=True,
        evolution_steps_per_slot=128,
        lifecycle_steps_per_write=512,
        selection_template=SELECT_TEMPLATE,
        primary_metric="raw_unconstrained_greedy_exact_match",
        minimum_holdout_accuracy=0.75,
        minimum_over_base=0.5,
        minimum_over_shuffled=0.5,
        minimum_selected_network_accuracy=0.75,
        selected_network_must_preserve_nochange_score=True,
        production_accepted=False,
    )
    write_json(output / "protocol.json", protocol)
    initial_identity = identity()
    write_json(output / "source-identity.json", initial_identity)
    facts = cohort(protocol["seed"], protocol["scope"])
    write_json(output / "source-facts.json", facts)
    cell = SourceMemoryCell(model, rank=8, seed=MODEL_SEED)
    if any(
        len(cell.reader.tokenizer.encode(v, add_special_tokens=False)) != 1
        for v in VALUES
    ):
        raise ValueError("registered low-entropy values must be one decoder token")
    cell.reset(protocol["scope"])
    print(json.dumps(dict(stage="write-start", phase=phase, steps=steps)), flush=True)
    receipt = cell.fit_sources(facts, steps, learning_rate, list(TRAIN_TEMPLATES))
    write_json(output / "write.json", receipt)
    snapshot = output / "written-cell"
    sha = cell.save(snapshot)
    write_json(output / "save.json", cell.last_save_receipt)
    print(
        json.dumps(
            dict(
                stage="write-complete",
                seconds=receipt["seconds"],
                first_loss=receipt["losses"][0],
                last_loss=receipt["losses"][-1],
            )
        ),
        flush=True,
    )
    evolution = None
    if phase == "confirmation":
        from parametric_evolution import run_evolution

        print(json.dumps(dict(stage="evolution-start")), flush=True)
        evolution = run_evolution(
            cell,
            parent_dir=snapshot,
            parent_sha=sha,
            facts=facts,
            output=output / "evolution",
            steps=protocol["evolution_steps_per_slot"],
            learning_rate=learning_rate,
            templates=list(TRAIN_TEMPLATES),
            selection_template=SELECT_TEMPLATE,
        )
        cell.load(
            snapshot,
            expected_manifest_sha256=sha,
            scope=protocol["scope"],
            allowed_roots={f["source_digest"] for f in facts},
            revoked=set(),
        )
        print(
            json.dumps(
                dict(stage="evolution-complete", chosen=evolution["chosen_arm"])
            ),
            flush=True,
        )
    query = questions(facts, TEST_TEMPLATE)
    before = adapter_digest(cell.reader.model)
    in_memory = cell.generate(query)
    write_json(output / "in-memory-generation.json", in_memory)
    training_rows = cell.generate(questions(facts, TRAIN_TEMPLATES[0]))
    write_json(output / "training-template-generation.json", training_rows)
    journals = {}
    for control in ("adapter", "base", "shuffled"):
        journals[control] = read_worker(
            model,
            snapshot,
            sha,
            protocol["scope"],
            cell.reader.roots,
            query,
            output,
            control,
            control=control,
        )
    # Complete raw generation journals precede scoring. Gold never crosses worker input.
    metrics = {
        name: score(journal["rows"], facts) for name, journal in journals.items()
    }
    from parametric_metrics import binding_specificity, exact_kv_baseline

    binding = binding_specificity(cell, facts, query)
    kv = exact_kv_baseline(facts, query)
    metrics["sqlite_key_value"] = score(kv["rows"], facts)
    write_json(output / "binding-specificity.json", binding)
    write_json(output / "key-value-baseline.json", kv)
    reload_equal = [
        (r["text"], r["token_ids"], r["prompt_sha256"]) for r in in_memory
    ] == [
        (r["text"], r["token_ids"], r["prompt_sha256"])
        for r in journals["adapter"]["rows"]
    ]
    prompts_equal = (
        len({tuple(r["prompt_sha256"] for r in j["rows"]) for j in journals.values()})
        == 1
    )
    accuracy = metrics["adapter"]["exact_match"]
    gate = dict(
        all_facts_updated=all(n > 0 for n in receipt["fact_visits"]),
        frozen_base_unchanged=receipt["base_unchanged"],
        exact_fresh_process_reload=reload_equal,
        matched_control_prompts=prompts_equal,
        inference_did_not_write=before == adapter_digest(cell.reader.model),
        holdout_threshold=accuracy >= protocol["minimum_holdout_accuracy"],
        causal_over_base=accuracy - metrics["base"]["exact_match"]
        >= protocol["minimum_over_base"],
        causal_over_shuffled=accuracy - metrics["shuffled"]["exact_match"]
        >= protocol["minimum_over_shuffled"],
    )
    network, lifecycle = None, None
    if evolution is not None:
        from parametric_network_trial import read_network
        from parametric_lifecycle_trial import run_lifecycle

        network = read_network(
            cell,
            model=model,
            evolution=evolution,
            facts=facts,
            output=output / "network",
            read_worker=read_worker,
            write_json=write_json,
        )
        selected_accuracy = network["metrics"][network["chosen_arm"]]["exact_match"]
        gate["selected_network_holdout"] = (
            selected_accuracy >= protocol["minimum_selected_network_accuracy"]
        )
        gate["selected_network_preserves_parent"] = (
            selected_accuracy >= network["metrics"]["nochange"]["exact_match"]
        )
        print(json.dumps(dict(stage="lifecycle-start")), flush=True)
        lifecycle = run_lifecycle(
            cell,
            model=model,
            parent_dir=snapshot,
            parent_sha=sha,
            facts=facts,
            output=output / "lifecycle",
            steps=protocol["lifecycle_steps_per_write"],
            learning_rate=learning_rate,
            templates=list(TRAIN_TEMPLATES),
            derived_cells=[
                v
                for arm in ("continue", "split")
                for v in evolution["arms"][arm]["cells"]
            ],
            read_worker=read_worker,
            write_json=write_json,
        )
        gate["correction_recalled"] = (
            lifecycle["correction"]["revised"]["exact_match"] == 1
        )
        gate["correction_retained"] = (
            lifecycle["correction"]["retained"]["exact_match"] >= 0.75
        )
        gate["clean_replay_recall"] = (
            lifecycle["clean_replay_recall"]["exact_match"] >= 0.75
        )
        gate["revoked_descendants_never_executed"] = (
            lifecycle["forward_calls_on_revoked"] == 0
        )
        gate["clean_base_delete_recovery"] = lifecycle["clean_base_replay_verified"]
        gate["matched_split_budget_and_parent_unchanged"] = (
            evolution["matched_parameter_bytes_and_optimizer_steps"]
            and evolution["parent_unchanged"]
        )
        print(json.dumps(dict(stage="lifecycle-complete")), flush=True)
    final_identity = identity()
    write_json(output / "source-identity-after.json", final_identity)
    gate["source_files_unchanged"] = (
        initial_identity["source_manifest_sha256"]
        == final_identity["source_manifest_sha256"]
    )
    result = dict(
        schema="hepta.parametric-memory.trial.v1",
        phase=phase,
        protocol_sha256=digest(protocol),
        checkpoint_manifest_sha256=sha,
        metrics=metrics,
        training_template=score(training_rows, facts),
        gates=gate,
        evolution=evolution,
        network=network,
        lifecycle=lifecycle,
        binding_specificity=binding,
        exact_kv_baseline=kv,
        mechanism_gate_passed=all(gate.values()),
        production_accepted=False,
        compression_advantage_proven=False,
        general_memory_proven=False,
        memory_recall_not_unseen_fact_generalization=True,
        isolation="fresh interpreter, closed JSON input; not an OS sandbox",
        costs=dict(
            shared_base_disk_bytes=acquisition["total_bytes"],
            loaded_base_tensor_bytes=sum(
                p.numel() * p.element_size()
                for n, p in cell.reader.model.named_parameters()
                if "lora_" not in n
            ),
            private_parameter_bytes=receipt["parameter_bytes"],
            checkpoint_bytes=sum(
                p.stat().st_size for p in snapshot.iterdir() if p.is_file()
            ),
            original_source_json_bytes=(output / "source-facts.json").stat().st_size,
            optimizer_tensor_bytes=receipt["optimizer_tensor_bytes"],
            source_entropy_upper_bound_bits=len(facts) * 3,
            sqlite_key_value_bytes=kv["sqlite_bytes"],
        ),
    )
    write_json(output / "result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--phase", choices=("development", "confirmation"), required=True
    )
    parser.add_argument("--steps", type=int)
    parser.add_argument("--learning-rate", type=float)
    args = parser.parse_args()
    result = run_trial(
        args.model,
        args.output,
        args.phase,
        steps=args.steps,
        learning_rate=args.learning_rate,
    )
    if args.phase == "confirmation" and not result["mechanism_gate_passed"]:
        raise SystemExit(1)

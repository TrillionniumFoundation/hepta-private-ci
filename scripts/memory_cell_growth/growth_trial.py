"""Fixed sequential color-to-shape arrival probe; no general-memory acceptance."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import torch

from growth_protocol import (
    LR,
    MODEL_SEED,
    PARENT_SHA,
    SHAPES,
    SINGLE_STEPS,
    parent_inputs,
    protocol,
    shape_arrivals,
    source_identity,
)
from growth_reads import read_arms
from growth_runtime import train_candidates
from parametric_cohort import (
    TRAIN_TEMPLATES,
    SELECT_TEMPLATE,
    TEST_TEMPLATE,
    questions,
    score,
)
from parametric_metrics import exact_kv_baseline
from parametric_model import SourceMemoryCell
from parametric_trial import read_worker, write_json
from prepare_parametric import prepare


def peak_rss():
    result = {
        "parent_process_peak_rss_bytes": None,
        "child_process_peak_rss_bytes": None,
        "peak_rss_basis": f"unsupported platform {sys.platform}; measurement unavailable",
    }
    if sys.platform not in ("linux", "darwin"):
        return result
    try:
        import resource
    except ImportError:
        result["peak_rss_basis"] = (
            "resource module unavailable; measurement unavailable"
        )
        return result
    multiplier = 1024 if sys.platform == "linux" else 1
    unit = "KiB converted to bytes" if sys.platform == "linux" else "native bytes"
    result.update(
        {
            "parent_process_peak_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            * multiplier,
            "child_process_peak_rss_bytes": resource.getrusage(
                resource.RUSAGE_CHILDREN
            ).ru_maxrss
            * multiplier,
            "peak_rss_basis": f"{sys.platform} getrusage, {unit}; child maximum is not simultaneous total",
        }
    )
    return result


def retained_old_items(output, readout, chosen, old, incoming):
    final_rows = {}
    for arm in {"nochange", chosen}:
        rows = [None] * (len(old) + len(incoming))
        for call in readout["routed_calls"]:
            if call["arm"] != arm:
                continue
            journal = json.loads(
                (output / "final" / f"{arm}-{call['slot']}.journal.json").read_text()
            )
            for index, row in zip(call["query_indices"], journal["rows"], strict=True):
                rows[index] = row
        final_rows[arm] = rows
    return all(
        parent_row["text"] != fact["value"] or selected_row["text"] == fact["value"]
        for parent_row, selected_row, fact in zip(
            final_rows["nochange"][: len(old)],
            final_rows[chosen][: len(old)],
            old,
            strict=True,
        )
    )


def measure_costs(
    cell,
    output,
    parent_manifest,
    provenance,
    candidates,
    acquisition,
    baseline,
    readout,
    registered,
):
    historical = parent_manifest["training"]
    chosen = candidates["selection"]["chosen_arm"]
    upstream = {
        key: value
        for key, value in provenance["historical_writes"].items()
        if key != "clean_replay"
    }
    return {
        "incremental_experiment_training_steps": sum(
            row["optimizer_steps"] for row in candidates["costs"].values()
        ),
        "parent_historical_optimizer_steps": historical["steps"],
        "parent_historical_input_tokens": historical["input_tokens"],
        "parent_historical_training_seconds": historical["seconds"],
        "upstream_original_and_correction_writes": upstream,
        "prior_evolution_research_not_in_upstream_write_subtotal": True,
        "inherited_parent_is_common_cost": True,
        "candidate_training_input_tokens": sum(
            row["input_tokens"] for row in candidates["work"].values()
        ),
        "candidate_training_seconds": sum(
            row["training_seconds"] for row in candidates["work"].values()
        ),
        "candidate_checkpoint_bytes": sum(
            row["retained_checkpoint_bytes"]
            for arm, row in candidates["costs"].items()
            if arm != "nochange"
        ),
        "selected_retained_cost": candidates["costs"][chosen],
        "source_selection_input_tokens": candidates["source_selection_input_tokens"],
        "source_selection_generated_tokens": candidates[
            "source_selection_generated_tokens"
        ],
        "source_selection_seconds": candidates["source_selection_seconds"],
        "final_reader_work": readout["work"],
        "source_ledger_bytes": (output / "source-facts.json").stat().st_size,
        "shared_base_disk_bytes": acquisition["total_bytes"],
        "loaded_base_tensor_bytes": sum(
            t.numel() * t.element_size()
            for name, t in cell.reader.model.named_parameters()
            if "lora_" not in name
        ),
        "sqlite_bytes": baseline["sqlite_bytes"],
        "sqlite_write_seconds": baseline["write_seconds"],
        "sqlite_read_seconds": baseline["read_seconds"],
        "router_metadata_bytes": len(
            json.dumps(registered["typed_namespace_router"]).encode()
        ),
        "owner_database_bytes": readout["owner_database_bytes"],
        **peak_rss(),
        "actual_input_tokens_equal": candidates["work"]["single"]["input_tokens"]
        == candidates["work"]["split"]["input_tokens"],
        "same_private_parameter_budget": False,
        "source_ledger_retained": True,
    }


def run(model, parent_dir, source_facts, output):
    output, parent_dir = Path(output).resolve(), Path(parent_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    registered = protocol()
    write_json(output / "protocol.json", registered)
    before = source_identity()
    write_json(output / "source-identity.json", before)
    old, parent_manifest, provenance, frontier = parent_inputs(parent_dir, source_facts)
    write_json(output / "parent-provenance.json", provenance)
    write_json(output / "source-frontier.json", asdict(frontier))
    incoming = shape_arrivals(old)
    facts = old + incoming
    write_json(output / "source-facts.json", facts)
    acquisition = prepare(model)
    write_json(output / "model-acquisition.json", acquisition)
    torch.set_num_threads(2)
    cell = SourceMemoryCell(model, rank=8, seed=MODEL_SEED)
    cell.load(
        parent_dir,
        expected_manifest_sha256=PARENT_SHA,
        scope=frontier.scope,
        allowed_roots={row["source_digest"] for row in old},
        revoked=set(frontier.revoked),
    )
    lengths = {
        value: len(cell.reader.tokenizer.encode(value, add_special_tokens=False))
        for value in SHAPES
    }
    if any(not 1 <= length < 16 for length in lengths.values()):
        raise ValueError("predeclared shape value exceeds closed generation budget")
    write_json(
        output / "vocabulary-token-bounds.json",
        {"token_lengths": lengths, "vocabulary_changed": False},
    )
    parent = {
        "directory": str(parent_dir),
        "manifest_sha256": PARENT_SHA,
        "roots": sorted(row["source_digest"] for row in old),
    }
    print(
        json.dumps(
            {"stage": "candidate-training-start", "optimizer_steps": 2 * SINGLE_STEPS}
        ),
        flush=True,
    )
    candidates = train_candidates(
        cell,
        old=old,
        incoming=incoming,
        parent=parent,
        frontier=frontier,
        output=output / "candidates",
        single_steps=SINGLE_STEPS,
        learning_rate=LR,
        templates=list(TRAIN_TEMPLATES),
        selection_template=SELECT_TEMPLATE,
        final_template=TEST_TEMPLATE,
        write_json=write_json,
    )
    print(
        json.dumps(
            {
                "stage": "source-selection-complete",
                "chosen": candidates["selection"]["chosen_arm"],
            }
        ),
        flush=True,
    )
    selection_path = output / "candidates/precommitted-selection.json"
    selection_sha = hashlib.sha256(selection_path.read_bytes()).hexdigest()
    readout = read_arms(
        model=model,
        report=candidates,
        old=old,
        incoming=incoming,
        frontier=frontier,
        output=output / "final",
        final_template=TEST_TEMPLATE,
        read_worker=read_worker,
        write_json=write_json,
    )
    selection_unchanged = (
        hashlib.sha256(selection_path.read_bytes()).hexdigest() == selection_sha
    )
    baseline = exact_kv_baseline(facts, questions(facts, TEST_TEMPLATE))
    write_json(output / "sqlite-baseline.json", baseline)
    chosen = candidates["selection"]["chosen_arm"]
    selected = readout["metrics"][chosen]
    preserved = retained_old_items(output, readout, chosen, old, incoming)
    after = source_identity()
    write_json(output / "source-identity-after.json", after)
    gates = {
        "selected_old_recall": selected["old"]["exact_match"] >= 0.75,
        "selected_new_recall": selected["new"]["exact_match"] >= 0.75,
        "selected_preserves_parent_correct_old": preserved,
        "parent_unchanged": candidates["parent_unchanged"],
        "matched_training_steps": candidates["matched_optimizer_steps"],
        "revoked_ancestry_disjoint": candidates["revoked_ancestry_disjoint"],
        "final_owner_admission": all(
            call["owner_admitted_before_and_after"] for call in readout["routed_calls"]
        ),
        "selection_preceded_final_reads": readout["chosen_before_final_read"] == chosen,
        "selection_bytes_unchanged": selection_unchanged,
        "source_identity_unchanged": before == after,
        "sqlite_exact_recall": score(baseline["rows"], facts)["exact_match"] == 1,
    }
    costs = measure_costs(
        cell,
        output,
        parent_manifest,
        provenance,
        candidates,
        acquisition,
        baseline,
        readout,
        registered,
    )
    result = {
        "schema": "hepta.parametric-memory.arrival-result.v1",
        "gates": gates,
        "bounded_arrival_gate_passed": all(gates.values()),
        "selection": candidates["selection"],
        "metrics": readout["metrics"],
        "costs": costs,
        "training_loss_by_relation": candidates["training_loss_by_relation"],
        "fresh_worker_processes": readout["fresh_worker_processes"],
        "parent_manifest_sha256": PARENT_SHA,
        "source_manifest_sha256": before["source_manifest_sha256"],
        "source_frontier": asdict(frontier),
        "new_relation_acquisition_not_new_architectural_cell_type": True,
        "learned_routing_proven": False,
        "compression_advantage_proven": False,
        "general_memory_proven": False,
        "production_accepted": False,
    }
    write_json(output / "result.json", result)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--source-facts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.model, args.parent, args.source_facts, args.output)
    raise SystemExit(0 if result["bounded_arrival_gate_passed"] else 1)

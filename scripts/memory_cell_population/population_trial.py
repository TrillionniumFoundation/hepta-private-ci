"""Run one immutable heterogeneous population trial without recipe overrides."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import time
import traceback

import torch

from growth_trial import peak_rss
from native import digest
from parametric_trial import write_json
from population_aggregate import assess_trial
from population_baselines import measure_exact
from population_codec_trial import evaluate_codecs
from population_fixtures import dataset
from population_protocol import SEEDS, protocol, source_identity
from population_reads import read_final
from population_selection import prepare_selection
from population_training import train_population
from prepare_parametric import prepare


def _artifact_inventory(directory):
    return {
        str(p.relative_to(directory)): {
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def measure_costs(
    model, output, acquisition, training, selection, final, codec, baseline
):
    with (Path(model) / "model.safetensors").open("rb") as stream:
        length = struct.unpack("<Q", stream.read(8))[0]
        if not 0 < length <= 1024 * 1024:
            raise ValueError("bounded base tensor inventory required")
        layout = json.loads(stream.read(length))
    scalars = sum(
        math.prod(v["shape"]) for k, v in layout.items() if k != "__metadata__"
    )
    packed = sum(
        v["costs"]["packed_artifact_bytes"] for v in codec["variants"].values()
    )
    materialized = sum(
        v["costs"]["materialized_checkpoint_bytes"] for v in codec["variants"].values()
    )
    owners = final["owner_database_bytes"] + codec["owner_database_bytes"]
    ledger = baseline["measurements"]["complete_records.json"]["bytes"]
    router = selection["router_receipt"]["artifact_bytes"]
    snapshots = training["costs"]["all_retained_snapshot_bytes"]
    active = selection["choice"]["selected_cost"]
    capabilities = final["capability_metadata_bytes"]
    selected_hot = (
        active["retained_checkpoint_bytes"]
        + active["router_artifact_bytes"]
        + ledger
        + final["owner_database_bytes"]
        + capabilities
    )
    return {
        "training": training["costs"],
        "source_selection": selection["source_work"],
        "final_reads": final["work"],
        "codec_work": {bits: v["costs"] for bits, v in codec["variants"].items()},
        "shared_base_disk_bytes": acquisition["total_bytes"],
        "base_tensor_bytes_loaded_float32": scalars * 4,
        "source_ledger_bytes": ledger,
        "router_artifact_bytes": router,
        "capability_metadata_bytes": capabilities,
        "owner_database_bytes": owners,
        "all_training_checkpoint_bytes": snapshots,
        "all_codec_packed_bytes": packed,
        "all_codec_materialized_bytes": materialized,
        "selected_hot_artifacts_excluding_shared_base_bytes": selected_hot,
        "selected_hot_artifacts_including_shared_base_bytes": selected_hot
        + acquisition["total_bytes"],
        "retained_data_and_model_lower_bound_bytes": acquisition["total_bytes"]
        + snapshots
        + packed
        + materialized
        + ledger
        + router
        + owners
        + capabilities,
        "data_only_exact_best_bytes": baseline[
            "smallest_complete_exact_representation"
        ]["bytes"],
        "runtime_libraries_and_code_not_in_lower_bound": True,
        "full_system_costs_and_comparable_baseline_accounted": False,
        "complete_system_storage_bytes": None,
        "actual_experiment_directory_bytes_before_result": sum(
            p.stat().st_size for p in output.rglob("*") if p.is_file()
        ),
        "all_diagnostic_expert_reads_are_charged": True,
        "shared_base_must_be_counted_once_when_combining_seeds": True,
        "frontier_is_local_pinned_research_view": True,
        **peak_rss(),
    }


def run(model, output, seed):
    if type(seed) is not int or seed not in SEEDS:
        raise ValueError("registered seed required")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    registered, before = protocol(), source_identity()
    write_json(output / "protocol.json", registered)
    write_json(output / "source-identity.json", before)
    data = dataset(seed)
    write_json(output / "dataset.json", data)
    # Download is deliberately not an option here. Admission hashes the exact
    # previously acquired publisher bytes before any model or optimizer work.
    acquisition = prepare(Path(model))
    write_json(output / "model-acquisition.json", acquisition)
    baseline = measure_exact(data, output / "exact-baselines", write_json)
    torch.set_num_threads(2)
    training = train_population(
        model, data, output / "training", seed=seed, write_json=write_json
    )
    selection = prepare_selection(
        model, data, training, output / "selection", write_json
    )
    print(
        json.dumps(
            {
                "seed": seed,
                "stage": "selection-frozen",
                "choice": selection["choice"]["chosen_arm"],
                "selection_sha256": selection["selection_sha256"],
            }
        ),
        flush=True,
    )
    final = read_final(model, data, training, selection, output / "final", write_json)
    print(json.dumps({"seed": seed, "stage": "fixed-codecs"}), flush=True)
    codec = evaluate_codecs(
        model, data, training, final["metrics"]["single"], output / "codec", write_json
    )
    costs = measure_costs(
        model, output, acquisition, training, selection, final, codec, baseline
    )
    after = source_identity()
    write_json(output / "source-identity-after.json", after)
    result = {
        "schema": "hepta.memory-population.trial-result.v1",
        "seed": seed,
        "protocol_sha256": digest(registered),
        "source_identity": before,
        "training": training,
        "selection": selection,
        "final": final,
        "codec": codec,
        "baseline": baseline,
        "costs": costs,
        **assess_trial(training, selection, final, codec, baseline, costs),
    }
    result["engineering_gates"]["source_identity_unchanged"] = before == after
    result["engineering_gates"]["selection_bytes_unchanged_after_codecs"] = (
        hashlib.sha256(Path(selection["selection_path"]).read_bytes()).hexdigest()
        == selection["selection_sha256"]
    )
    result["total_wall_seconds"] = time.perf_counter() - started
    write_json(output / "raw-evidence-inventory.json", _artifact_inventory(output))
    write_json(output / "result.json", result)
    print(
        json.dumps(
            {
                "seed": seed,
                "stage": "complete",
                "summary": result["summary"],
                "engineering_gates": result["engineering_gates"],
                "research_gates": result["research_gates"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, choices=SEEDS, required=True)
    args = parser.parse_args()
    output_was_absent = not args.output.exists()
    try:
        result = run(args.model, args.output, args.seed)
    except Exception as error:
        failure = {
            "schema": "hepta.memory-population.execution-failure.v1",
            "seed": args.seed,
            "error_type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
            "production_accepted": False,
        }
        if (
            output_was_absent
            and args.output.is_dir()
            and not (args.output / "execution-failure.json").exists()
        ):
            write_json(args.output / "execution-failure.json", failure)
        raise
    # Negative hypotheses never interrupt the remaining seed/codec experiments.
    raise SystemExit(0 if all(result["engineering_gates"].values()) else 1)

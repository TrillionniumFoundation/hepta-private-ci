"""Replay registered cached horizon policies after a successful train/dev run.

This executable never fits a model. Both successful outer termination and a
complete exact grid are required before opening any fit outcome or checkpoint.
All output is create-only, and old confirmation material is never accessed.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from time import perf_counter, process_time

import numpy as np

from .cached_preparation import PANELS, evaluate_cached_development
from .crossed_design import canonical, decompose, design_cells, transform_inputs, validate_config
from .crossed_training import _source
from .crossed_training_fit import _write, model_digest
from .models import Model, matched_hidden_dim
from .preparation import PreparationTariff
from .simulator import ACTION_DIM, INPUT_DIM, generate_dataset


class Incomplete(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f"ordinary file required: {path}")
    require(path.stat().st_size <= 16 * 1024 * 1024, "oversized replay input")
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    digest(path)

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        Path(path).read_text(),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )


def source_hashes():
    files = _source()
    for name in ("cached_preparation.py", "cached_replay.py"):
        files[name] = Path(__file__).with_name(name).read_bytes()
    return {name: sha256(value).hexdigest() for name, value in files.items()}


def gate(args):
    """Validate terminal state and all registration bindings before fit reads."""
    campaign = args.campaign.resolve()
    if not args.execution_receipt.is_file() or not (campaign / "RESULT.json").is_file():
        raise Incomplete("successful outer receipt and terminal RESULT are required")
    receipt = read(args.execution_receipt)
    if receipt.get("status") != "EXITED" or type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0:
        raise Incomplete("outer process has not exited successfully")
    result = read(campaign / "RESULT.json")
    if result.get("status") != "COMPLETE":
        raise Incomplete("campaign is not COMPLETE; fit outcomes remain unopened")
    cfg, training, frozen = read(args.registered_config), read(args.training_freeze), read(args.replay_freeze)
    attempt, started = read(campaign / "attempt.json"), read(campaign.parent / "EXECUTION_STARTED.json")
    validate_config(cfg)
    config_hash = sha256(canonical(cfg).encode()).hexdigest()
    require(read(campaign / "config.json") == cfg, "executed configuration changed")
    for item in (training, frozen, attempt, started, receipt):
        require(item["config_sha256"] == config_hash, "configuration identity mismatch")
    require(frozen["schema"] == "pred1-cached-replay-freeze-v1", "unsupported replay registration")
    require(frozen["training_freeze_sha256"] == digest(args.training_freeze), "training freeze mismatch")
    require(frozen["panels"] == {k: list(v) for k, v in PANELS.items()}, "registered horizon panels changed")
    require(frozen["new_fits"] == 0 and frozen["outcomes_read_before_registration"] is False, "replay scope changed")
    for item in (training, frozen, attempt, result):
        require(
            item["confirmation_data_read"] is False and item["confirmation_samples_generated"] == 0,
            "confirmation boundary changed",
        )
    require(result["qualification"] == training["original_qualification"] == "HOLD_UNCHANGED", "qualification changed")
    require(training["base_commit"] == cfg["base_commit"] == attempt["base_commit"], "base commit mismatch")
    for key in ("registration_commit", "execution_source_commit"):
        require(receipt[key] == started[key] == frozen["training_" + key], "training publication identity mismatch")
    require(receipt["argv"] == started["argv"], "launch argv changed")
    argv = receipt["argv"]
    require(Path(argv[argv.index("--output") + 1]).resolve() == campaign, "receipt belongs to another campaign")
    require(digest(argv[argv.index("--config") + 1]) == config_hash, "launch configuration bytes changed")
    require(receipt["result_present"] is True, "outer process did not observe RESULT")
    require(set(receipt["logs"]) == {"stdout.log", "stderr.log"}, "outer logs missing")
    for name, metadata in receipt["logs"].items():
        path = campaign.parent / name
        require(digest(path) == metadata["sha256"] and path.stat().st_size == metadata["bytes"], "outer log mismatch")
    parse = datetime.fromisoformat
    require(
        parse(training["frozen_at_utc"])
        <= parse(started["started_at_utc"])
        <= parse(attempt["started_at"])
        <= parse(receipt["finished_at_utc"]),
        "invalid training chronology",
    )
    require(parse(frozen["frozen_at_utc"]) <= datetime.now(timezone.utc), "replay registration is in the future")
    sources = source_hashes()
    require(frozen["source_files"] == sources, "replay source changed after registration")
    original = {
        name: value for name, value in sources.items() if name not in ("cached_preparation.py", "cached_replay.py")
    }
    require(training["source_files"] == original, "training source manifest changed")
    for item in (attempt, started, receipt):
        require(item["source_sha256"] == original, "execution source identity mismatch")
    for name, value in original.items():
        require(digest(campaign / "source" / name) == value, "saved training source mismatch")
    require(attempt["environment"]["numpy"] == np.__version__, "replay requires the training NumPy version")
    cells = design_cells(cfg)
    ids = {
        f"{v}-d{d}-i{i}-o{o}": dict(variant=v, data_seed=d, init_seed=i, order_seed=o)
        for d, i, o in cells
        for v in cfg["variants"]
    }
    require(
        len(ids) == training["fit_count"] == frozen["fit_count"] == 189
        and len(cells) == training["factor_cells"] == frozen["factor_cells"] == 27,
        "registered grid changed",
    )
    require(
        result["completed_fits"] == result["expected_fits"] == len(ids)
        and result["failed_fits"] == result["unstarted_fits"] == 0
        and not result["failures"]
        and result["source_unchanged"] is True,
        "campaign is incomplete or source changed",
    )
    require(
        {p.name for p in (campaign / "fits").iterdir()}
        == {name + suffix for name in ids for suffix in (".json", ".started.json", ".npz")},
        "fit files do not match exact grid",
    )
    require(cfg["expanded_budget"] == 16 and cfg["expanded_deadline"] == 20, "expanded resource contract changed")
    return cfg, frozen, result, ids


def replay_checkpoint(campaign, name, identity, config, dev, hidden):
    """Validate one saved fit and replay; all old-cheap episode fields must agree."""
    wall, cpu = perf_counter(), process_time()
    directory = Path(campaign) / "fits"
    original = read(directory / (name + ".json"))
    require(
        read(directory / (name + ".started.json")) == identity and {k: original[k] for k in identity} == identity,
        "fit identity mismatch",
    )
    calls = math.ceil(config["train_episodes"] / config["batch_size"]) * config["epochs"]
    require(
        original["status"] == "COMPLETE"
        and original["epochs_consumed"] == config["epochs"]
        and original["fit_step_calls_consumed"] == calls
        and original["training_examples_consumed"] == config["epochs"] * config["train_episodes"],
        "fit optimization budget mismatch",
    )
    checkpoint = directory / (name + ".npz")
    require(
        original["checkpoint"] == checkpoint.name and original["checkpoint_sha256"] == digest(checkpoint),
        "checkpoint byte identity mismatch",
    )
    model = Model.load(checkpoint)
    variant, seed = identity["variant"], identity["init_seed"]
    kind = variant if variant in ("single_step", "gru", "diag_ssm", "dual_timescale") else "gru"
    expected = Model(kind, INPUT_DIM, ACTION_DIM, 32, hidden[kind], seed)
    require(
        model.config == expected.config
        and original["hidden_dim"] == hidden[kind]
        and model.parameter_count == original["parameters"],
        "checkpoint model configuration mismatch",
    )
    require(
        model_digest(expected) == original["initial_parameter_sha256"]
        and model_digest(model) == original["selected_parameter_sha256"]
        and model_digest(model, optimizer=True) == original["selected_optimizer_state_sha256"],
        "checkpoint numerical identity mismatch",
    )
    require(
        model.steps == original["selected_checkpoint_steps"]
        and 0 <= model.steps <= original["optimizer_steps_consumed"] <= calls,
        "checkpoint optimizer steps mismatch",
    )
    validation = {"wall_seconds": perf_counter() - wall, "process_cpu_seconds": process_time() - cpu}
    x, query, reset = transform_inputs(dev.x, dev.query, variant)
    visible = replace(dev, x=x, query=query)
    expanded = replace(
        visible,
        remaining_budget=np.full(len(x), config["expanded_budget"]),
        deadline=np.full(len(x), config["expanded_deadline"]),
    )
    panels, tariff = {}, PreparationTariff(**config["cost_profile"])
    require(
        set(original["resource_panels"]) == {"original_resources", "expanded_resources"},
        "missing original resource panel",
    )
    for label, dataset in (("original_resources", visible), ("expanded_resources", expanded)):
        panels[label] = evaluate_cached_development(
            model, dataset, tariff=tariff, reset=reset, mask_candidate_action=variant == "gru_no_action"
        )
        current = panels[label]["arms"]["matched_cached_fixed1"]
        old = original["resource_panels"][label]["arms"]["fixed_1_cheap"]
        require(all(current[key] == old[key] for key in current), "formal old-cheap episode/aggregate parity failed")
        meters = panels[label]["policy_meters"]
        bridge = panels[label]["old_cheap_bridge"]
        # Legacy chooser's score count equals the already-verified Fixed1 choices;
        # its old meter calls this a reservation, so retain both explicit labels.
        bridge["planning_candidate_rows"] = meters["matched_cached_fixed1"]["planning_candidate_rows"]
        bridge["planning_count_scope"] = (
            "same legal scores as matched Fixed1, parity verified; boolean-mask traversal unpriced"
        )
        for meter in meters.values():
            require(
                meter["planning_candidate_rows"]
                == meter["reserved_planning_candidate_rows"]
                == meter["prediction_rows"],
                "planning/head tariff count mismatch",
            )
        old_meter = original["resource_panels"][label]["meter"]["fixed_1_cheap"]
        for key in (
            "prediction_calls",
            "prediction_rows",
            "state_update_calls",
            "state_update_rows",
            "history_encodings",
            "planning_candidate_rows",
        ):
            require(meters["matched_cached_fixed1"][key] == old_meter[key], "formal old-cheap operation count mismatch")
        panels[label]["formal_oldcheap_parity"] = True
    return {
        **identity,
        "status": "COMPLETE",
        "original_fit_sha256": digest(directory / (name + ".json")),
        "checkpoint_sha256": original["checkpoint_sha256"],
        "selected_parameter_sha256": original["selected_parameter_sha256"],
        "selected_optimizer_state_sha256": original["selected_optimizer_state_sha256"],
        "dataset_sha256": dev.fingerprint(),
        "resource_panels": panels,
        "checkpoint_validation": validation,
        "meter": {
            "wall_seconds": perf_counter() - wall,
            "process_cpu_seconds": process_time() - cpu,
            "physical_cost_complete": False,
        },
    }


def summarize(config, records):
    dims = tuple(len(config[k]) for k in ("data_seeds", "init_seeds", "order_seeds"))
    cells = design_cells(config)
    lookup = {(r["variant"], r["data_seed"], r["init_seed"], r["order_seed"]): r for r in records}
    require(len(lookup) == len(records) == len(cells) * len(config["variants"]), "incomplete or repeated replay grid")
    metrics = ("expected_net_utility", "realized_net_utility", "complete_environment_cost", "stop_rate")
    result = {}
    for variant in config["variants"]:
        group = [lookup[(variant, *cell)] for cell in cells]
        result[variant] = {}
        for resource in ("original_resources", "expanded_resources"):
            arrays = {
                arm: {
                    metric: np.array([r["resource_panels"][resource]["arms"][arm][metric] for r in group]).reshape(dims)
                    for metric in metrics
                }
                for arm in PANELS
            }
            result[variant][resource] = {
                "means": {
                    arm: {metric: float(a.mean()) for metric, a in values.items()} for arm, values in arrays.items()
                },
                "paired_factor_cell_differences": {
                    arm + "_minus_matched_cached_fixed1": {
                        metric: decompose(a - arrays["matched_cached_fixed1"][metric]) for metric, a in values.items()
                    }
                    for arm, values in arrays.items()
                    if arm != "matched_cached_fixed1"
                },
            }
    return result


def run(args):
    wall, cpu = perf_counter(), process_time()
    config, frozen, result, ids = gate(args)
    gate_meter = {"wall_seconds": perf_counter() - wall, "process_cpu_seconds": process_time() - cpu}
    output = args.output.resolve()
    require(not output.is_relative_to(args.campaign.resolve()), "replay output must be outside the original campaign")
    output.mkdir(parents=True, exist_ok=False)
    (output / "fits").mkdir()
    _write(output / "REPLAY_FREEZE.json", frozen)
    _write(output / "config.json", config)
    _write(
        output / "attempt.json",
        {
            "status": "RUNNING",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "original_result_sha256": digest(args.campaign / "RESULT.json"),
            "outer_receipt_sha256": digest(args.execution_receipt),
            "new_fits": 0,
            "config_sha256": frozen["config_sha256"],
            "source_sha256": frozen["source_files"],
            "replay_freeze_sha256": digest(args.replay_freeze),
        },
    )
    records, datasets, failure, current = [], {}, None, None
    hidden_search = None
    try:
        for seed in config["data_seeds"]:
            start_wall, start_cpu = perf_counter(), process_time()
            dev = generate_dataset(config["dev_episodes"], seed, "dev", config["history_length"])
            require(
                dev.fingerprint() == result["datasets"][str(seed)]["dev_sha256"],
                "regenerated development fingerprint mismatch",
            )
            require(
                read(args.campaign / f"dataset-{seed}.json") == result["datasets"][str(seed)],
                "original dataset record mismatch",
            )
            datasets[seed] = dev
            _write(
                output / f"dataset-{seed}.json",
                {
                    "dev_sha256": dev.fingerprint(),
                    "episodes": len(dev.x),
                    "generation_wall_seconds": perf_counter() - start_wall,
                    "generation_process_cpu_seconds": process_time() - start_cpu,
                },
            )
        start_wall, start_cpu = perf_counter(), process_time()
        hidden = {
            kind: matched_hidden_dim(kind, INPUT_DIM, ACTION_DIM, 32, config["target_parameters"])
            for kind in ("single_step", "gru", "diag_ssm", "dual_timescale")
        }
        hidden_search = {"wall_seconds": perf_counter() - start_wall, "process_cpu_seconds": process_time() - start_cpu}
        for name, identity in ids.items():
            current = name
            record = replay_checkpoint(args.campaign, name, identity, config, datasets[identity["data_seed"]], hidden)
            _write(output / "fits" / (name + ".json"), record)
            for panel in record["resource_panels"].values():
                for arm in panel["arms"].values():
                    arm.pop("per_episode")  # Evidence is saved; aggregate memory stays bounded.
            records.append(record)
            print(json.dumps({**identity, "status": "REPLAYED"}), flush=True)
        require(source_hashes() == frozen["source_files"], "replay source changed during execution")
        summary = summarize(config, records)
    except Exception as error:
        failure = {
            "fit": current,
            "type": type(error).__name__,
            "message": str(error),
            "partial_operation_counts": "unknown for the failing phase; host time remains in run totals",
        }
        summary = None
    unchanged = source_hashes() == frozen["source_files"]
    if not unchanged and failure is None:
        failure, summary = {"type": "SourceChanged", "message": "replay source changed"}, None
    operation_keys = (
        "prediction_calls",
        "prediction_rows",
        "state_update_calls",
        "state_update_rows",
        "history_encodings",
        "planning_candidate_rows",
    )
    operations = {}
    for resource in ("original_resources", "expanded_resources"):
        operations[resource] = {
            arm: {
                key: sum(r["resource_panels"][resource]["policy_meters"][arm][key] for r in records)
                for key in operation_keys
            }
            for arm in PANELS
        }
        bridges = [r["resource_panels"][resource]["old_cheap_bridge"] for r in records]
        operations[resource]["additional_oldcheap_bridge"] = {
            key: sum(b[key] if key == "planning_candidate_rows" else b["meter"][key] for b in bridges)
            for key in operation_keys
        }
    report = {
        "schema": "pred1-cached-replay-result-v1",
        "status": "INCOMPLETE" if failure else "COMPLETE",
        "qualification": "HOLD_UNCHANGED",
        "replayed_checkpoints": len(records),
        "expected_checkpoints": len(ids),
        "new_fits": 0,
        "failure": failure,
        "source_unchanged": unchanged,
        "completed_checkpoint_operation_totals": operations,
        "summary": summary,
        "source_files": frozen["source_files"],
        "config_sha256": frozen["config_sha256"],
        "training_registration_commit": frozen["training_registration_commit"],
        "training_execution_source_commit": frozen["training_execution_source_commit"],
        "replay_freeze_sha256": digest(args.replay_freeze),
        "confirmation_data_read": False,
        "confirmation_samples_generated": 0,
        "validation_meter": {"gate": gate_meter, "matched_hidden_search": hidden_search},
        "meter": {
            "wall_seconds": perf_counter() - wall,
            "process_cpu_seconds": process_time() - cpu,
            "physical_cost_complete": False,
            "energy_joules": None,
            "financial_cost": None,
        },
        "scope": [
            "All policies reuse the registered checkpoints and development data; this is not new training or independent confirmation.",
            "Each policy pays its own prefix encoding and requested legal heads; conservative whole-panel reservation is not optimal subset selection.",
            "The separately metered old-cheap bridge is additional host work, not another policy arm or a second simulated policy charge.",
            "Tariffs cover declared state/head rows and candidate score comparisons; model validation, admission, boolean-mask traversal, transport and training are unpriced.",
            "Wall/CPU spans are nested: run totals include validation, all policies, bridge, dataset and per-fit writes; exclude imports/startup and final RESULT serialization. Do not add nested spans.",
            "Retained-state bytes are not peak memory; simulated decision delay does not advance latent state; physical costs remain incomplete.",
            "Shared factor levels and original/expanded resource panels are dependent; descriptive differences have no promotion test or new p-value.",
            "Registration timestamp and hash bindings do not independently attest prior human outcome access or owner authenticity.",
        ],
    }
    _write(output / "RESULT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("campaign", "execution-receipt", "training-freeze", "registered-config", "replay-freeze", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    try:
        report = run(parser.parse_args())
        print(
            canonical(
                {
                    key: report[key]
                    for key in ("status", "replayed_checkpoints", "expected_checkpoints", "qualification")
                }
            )
        )
        return 0 if report["status"] == "COMPLETE" else 2
    except (Incomplete, ValueError, KeyError, OSError) as error:
        print(canonical({"status": "INCOMPLETE" if isinstance(error, Incomplete) else "FAIL", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

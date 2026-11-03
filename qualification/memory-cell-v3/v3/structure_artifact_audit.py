"""Audit structural migrations, independent read metrics and strict flow gates."""

import json
import math

import numpy as np

from .native_structure_audit_core import _packed, _prefix, require, same, sha
from .structure_audit_models import _bank, _metrics, _model_check, _owner_binding


def _structural_episode(reader, directory, episode, budget, previous):
    schema_raw = reader.raw(_prefix(directory, "shared-schema.json"))
    schema = json.loads(schema_raw)
    shape = tuple(schema["shape"])
    require(
        len(shape) == 2 and all(type(value) is int and value > 0 for value in shape),
        "invalid source matrix shape",
    )
    raw = reader.raw(_prefix(directory, "shared-replay.i32"))
    require(len(raw) == 4 * math.prod(shape), "shared replay shape/byte mismatch")
    matrix = np.frombuffer(raw, dtype="<i4").reshape(shape)
    same(sha(raw), schema["matrix_sha256"], "source schema binding")
    same(sha(raw), episode["matrix_sha256"], "episode source binding")
    same(list(shape), episode["shape"], "episode source shape")
    domains = np.asarray(schema["domains"], dtype=np.int64)
    require(domains.shape == (shape[0],), "retention domain shape differs")
    selection_name = _prefix(directory, "selection-addresses.bits")
    selection = _packed(reader, selection_name, math.prod(shape)).reshape(shape)
    availability_name = _prefix(directory, "availability.bits")
    mask = (
        _packed(reader, availability_name, math.prod(shape)).reshape(shape)
        if (reader.root / availability_name).exists()
        else np.ones(shape, dtype=bool)
    )
    require(not (selection & ~mask).any(), "selection includes withdrawn coordinates")
    same(
        sha(reader.raw(selection_name)),
        episode["adaptive"]["selection_sha256"],
        "selection address binding",
    )
    shared = {
        "source_replay_bytes": len(raw),
        "schema_bytes": len(schema_raw),
        "selection_address_bytes": len(reader.raw(selection_name)),
        "availability_bytes": 0 if mask.all() else len(reader.raw(availability_name)),
        "fixed_owner_binding_bytes_per_arm": 80,
        "same_serving_state_cap_per_arm": budget + 80,
    }
    shared["charged_bytes_per_arm"] = sum(
        shared[key]
        for key in (
            "source_replay_bytes",
            "schema_bytes",
            "selection_address_bytes",
            "availability_bytes",
            "fixed_owner_binding_bytes_per_arm",
        )
    )
    for key, value in shared.items():
        same(value, episode["shared_state"][key], f"common state bytes {key}")
    models = {}
    adaptive_dir = _prefix(directory, "adaptive")
    digest = _owner_binding(reader, adaptive_dir, sha(raw), episode["index"] + 1)
    adaptive = _bank(reader, adaptive_dir, digest)
    models["adaptive"] = _model_check(
        reader,
        adaptive_dir,
        adaptive,
        episode["adaptive"],
        matrix,
        mask,
        selection,
        domains,
        budget,
        0,
    )
    migration = episode["adaptive"]["route_migration"]
    same(migration["selected_artifact_sha256"], digest, "migration selected artifact")
    same(
        migration["parent_artifact_sha256"],
        None if previous is None else previous.digest,
        "migration parent artifact",
    )
    prior_routes = (
        np.zeros(shape[0], dtype=np.uint8) if previous is None else previous.routes
    )
    same(
        int(np.count_nonzero(prior_routes != adaptive.routes)),
        migration["changed_row_routes"],
        "migration changed routes",
    )
    same(
        int(np.count_nonzero(mask & ~selection)),
        migration["queries"],
        "migration query count",
    )
    require(
        migration["hidden_coordinate_read_parity_after_reload"] is True,
        "migration parity summary differs",
    )
    require(
        len(adaptive.blocks) == episode["adaptive"]["cells"],
        "adaptive cell count differs",
    )
    same(
        [block.rank for block in adaptive.blocks],
        episode["adaptive"]["ranks"],
        "adaptive rank allocation",
    )
    single_digest = episode["adaptive"]["work"]["records"][0]["fit"]["artifact_sha256"]
    single = _bank(reader, adaptive_dir, single_digest)
    single_selection = _metrics(single, matrix, selection, domains)
    same(
        single_selection,
        episode["adaptive"]["single_selection"],
        "initial single-cell selection",
    )
    for k in (1, 2, 4):
        arm, arm_dir = f"fixed_{k}", _prefix(directory, f"fixed-{k}")
        report = episode[arm]
        natural_report = report["efficient_before_work_padding"]
        natural_digest = _owner_binding(reader, arm_dir, sha(raw), episode["index"] + 1)
        natural = _bank(reader, arm_dir, natural_digest)
        require(len(natural.blocks) == k, "fixed natural cell count differs")
        records = natural_report["work"]["records"]
        candidates = [
            item["allocation"]["deployed_sha256"]
            for item in records
            if "allocation" in item
        ]
        if k == 1:
            candidates = [records[0]["fit"]["artifact_sha256"]]
        require(candidates, "fixed controller has no fitted in-budget candidate")
        best_natural = min(
            candidates,
            key=lambda candidate: _metrics(
                _bank(reader, arm_dir, candidate), matrix, selection, domains
            )["mse"],
        )
        same(natural_digest, best_natural, "efficient fixed choice uses selection only")
        models[f"efficient_{arm}"] = _model_check(
            reader,
            arm_dir,
            natural,
            natural_report,
            matrix,
            mask,
            selection,
            domains,
            budget,
            0,
        )
        matched = natural
        current_mse = models[f"efficient_{arm}"]["selection"]["mse"]
        repetitions = [
            item
            for item in report["work"]["records"]
            if item.get("label") == "matched_work_repeat"
        ]
        same(
            len(repetitions),
            report["matched_work_repeat_fits"],
            "fixed work-padding fit count",
        )
        same(
            report["work"]["records"][: len(records)],
            records,
            "padding starts after unchanged natural ledger",
        )
        for item in repetitions:
            candidate = _bank(reader, arm_dir, item["fit"]["artifact_sha256"])
            candidate_mse = _metrics(candidate, matrix, selection, domains)["mse"]
            if candidate_mse < current_mse:
                matched, current_mse = candidate, candidate_mse
        models[arm] = _model_check(
            reader,
            arm_dir,
            matched,
            report,
            matrix,
            mask,
            selection,
            domains,
            budget,
            1,
        )
        require(
            models[arm]["work"]["total_work_proxy"]
            >= models["adaptive"]["work"]["total_work_proxy"],
            "matched-work fixed controller received less work",
        )
        require(
            models[f"efficient_{arm}"]["work"]["total_work_proxy"]
            <= models[arm]["work"]["total_work_proxy"],
            "natural fixed cost includes padding",
        )
    return {
        "models": models,
        "shared": shared,
        "single_selection": single_selection,
        "single_fit": episode["adaptive"]["work"]["records"][0]["fit"],
        "migration": migration,
    }, adaptive


def _aggregate_models(episodes, name):
    models = [episode["models"][name] for episode in episodes]
    return {
        "hidden_mse": float(np.mean([model["hidden"]["mse"] for model in models])),
        "selection_mse": float(
            np.mean([model["selection"]["mse"] for model in models])
        ),
        "hidden_mae": float(np.mean([model["hidden"]["mae"] for model in models])),
        "hidden_exact": float(np.mean([model["hidden"]["exact"] for model in models])),
        "work_proxy": sum(model["work"]["total_work_proxy"] for model in models),
        "retained_artifact_bytes": sum(
            model["work"]["retained_artifact_bytes"] for model in models
        ),
        "retained_audit_metadata_bytes": sum(
            model["work"]["retained_audit_metadata_bytes"] for model in models
        ),
        "common_replay_and_owner_bytes": sum(
            episode["shared"]["charged_bytes_per_arm"] for episode in episodes
        ),
        "fit_seconds": sum(model["work"]["fit_wall_seconds"] for model in models),
        "owner_wall_seconds": sum(model["owner_wall_seconds"] for model in models),
        "mean_deployed_bytes": float(
            np.mean([model["deployed_bytes"] for model in models])
        ),
        "query_factor_multiplications": sum(
            model["hidden"]["read_factor_multiplications"] for model in models
        ),
    }


def audit_structure_stage(reader, prefix="structure"):
    data = reader.json(_prefix(prefix, "structure.json"))
    protocol, compact = data["protocol"], []
    minimum_gain = protocol["minimum_gain"]
    for flow in data["results"]:
        directory = _prefix(prefix, f"seed-{flow['seed']}/{flow['name']}")
        budget, previous, audited = (
            protocol.get("budget_bytes", flow["budget_bytes"]),
            None,
            [],
        )
        same(flow["budget_bytes"], budget, "flow budget")
        for index, episode in enumerate(flow["episodes"]):
            same(episode["index"], index, "episode sequence")
            result, previous = _structural_episode(
                reader,
                _prefix(directory, f"episode-{index}"),
                episode,
                budget,
                previous,
            )
            audited.append(result)
        names = (
            "adaptive",
            "fixed_1",
            "fixed_2",
            "fixed_4",
            "efficient_fixed_1",
            "efficient_fixed_2",
            "efficient_fixed_4",
        )
        totals = {name: _aggregate_models(audited, name) for name in names}
        efficient = min(
            ("efficient_fixed_1", "efficient_fixed_2", "efficient_fixed_4"),
            key=lambda name: totals[name]["selection_mse"],
        )
        matched = min(
            ("fixed_1", "fixed_2", "fixed_4"),
            key=lambda name: totals[name]["selection_mse"],
        )
        same(
            efficient,
            flow["best_fixed_by_whole_flow_selection"],
            "flow efficient fixed choice",
        )
        same(
            matched,
            flow["best_matched_work_fixed_by_whole_flow_selection"],
            "flow matched fixed choice",
        )
        error_scale = max(totals["fixed_1"]["hidden_mse"], 1.0)
        work_scale = max(
            sum(episode["single_fit"]["svd_work_proxy"] for episode in audited), 1
        )
        byte_scale = max(
            sum(episode["single_fit"]["artifact_bytes"] for episode in audited), 1
        )
        same(error_scale, flow["pricing"]["error_normalizer"], "price error normalizer")
        same(
            work_scale,
            flow["pricing"]["single_fit_work_normalizer"],
            "price natural single-fit work normalizer",
        )
        same(
            byte_scale,
            flow["pricing"]["single_artifact_bytes_normalizer"],
            "price single artifact normalizer",
        )
        for key in ("training_price", "retention_price"):
            same(flow["pricing"][key], protocol[key], f"frozen {key}")
        for values in totals.values():
            values["retained_state_bytes"] = (
                values["retained_artifact_bytes"]
                + values["retained_audit_metadata_bytes"]
                + values["common_replay_and_owner_bytes"]
            )
            values["priced_loss"] = (
                values["hidden_mse"] / error_scale
                + protocol["training_price"] * values["work_proxy"] / work_scale
                + protocol["retention_price"]
                * values["retained_state_bytes"]
                / byte_scale
            )
            values["horizon_work_proxy"] = {
                str(horizon): values["work_proxy"]
                + horizon * values["query_factor_multiplications"]
                for horizon in (1, 10, 100)
            }
        same(
            totals,
            flow["totals"],
            "independent structure totals and natural/matched costs",
        )
        adaptive = totals["adaptive"]
        fixed = totals[efficient]
        gain = (fixed["hidden_mse"] - adaptive["hidden_mse"]) / max(
            fixed["hidden_mse"], 1.0
        )
        matched_gain = (totals[matched]["hidden_mse"] - adaptive["hidden_mse"]) / max(
            totals[matched]["hidden_mse"], 1.0
        )
        retention = all(
            all(
                error
                <= episode["single_selection"]["domain_mse"][domain]
                * (1 + protocol["retention_relative"])
                + protocol["retention_absolute_mse"]
                for domain, error in episode["models"]["adaptive"]["selection"][
                    "domain_mse"
                ].items()
            )
            for episode in audited
        )
        gate = bool(
            gain >= minimum_gain
            and matched_gain >= minimum_gain
            and adaptive["priced_loss"] < fixed["priced_loss"]
            and adaptive["priced_loss"] < totals[matched]["priced_loss"]
            and retention
        )
        same(
            gain,
            flow["relative_hidden_mse_gain_vs_best_fixed"],
            "strict flow normalized MSE gain",
        )
        same(
            adaptive["hidden_mse"] - fixed["hidden_mse"],
            flow["hidden_mse_regret_vs_best_fixed"],
            "strict flow MSE regret",
        )
        same(
            adaptive["priced_loss"] - fixed["priced_loss"],
            flow["priced_loss_regret_vs_best_fixed"],
            "strict flow natural-cost regret",
        )
        same(
            retention,
            flow["selection_retention_floor_pass"],
            "strict flow retention floors",
        )
        same(gate, flow["strict_new_flow_gate"], "strict flow conjunction")
        compact.append(
            {
                "seed": flow["seed"],
                "flow": flow["name"],
                "strict_gate": gate,
                "best_efficient_fixed": efficient,
                "best_matched_fixed": matched,
                "normalized_gain_vs_efficient": gain,
                "normalized_gain_vs_matched": matched_gain,
                "priced_regret_vs_efficient": adaptive["priced_loss"]
                - fixed["priced_loss"],
                "priced_regret_vs_matched": adaptive["priced_loss"]
                - totals[matched]["priced_loss"],
                "retention_floors": retention,
                "totals": totals,
                "migrations": [episode["migration"] for episode in audited],
            }
        )
    expected_pairs = [
        (seed, name)
        for seed in data["seeds"]
        for name in protocol.get(
            "flows", ["heterogeneous", "convergent", "stable_lowrank", "random"]
        )
    ]
    same(
        [(row["seed"], row["flow"]) for row in compact],
        expected_pairs,
        "structure seed/flow coverage",
    )
    convergent = all(
        row["strict_gate"] for row in compact if row["flow"] == "convergent"
    )
    all_cases = all(row["strict_gate"] for row in compact)
    same(convergent, data["convergent_specific_gate"], "convergent-specific aggregate")
    same(
        all_cases, data["all_cases_strict_gate_diagnostic"], "all-flow strict aggregate"
    )
    same(
        data["negative_controls"],
        [
            flow
            for flow in data["results"]
            if flow["name"] in ("stable_lowrank", "random")
        ],
        "negative controls retain complete original results",
    )
    return {
        "verified": True,
        "development": data["development"],
        "all_flows_strict_gate": all_cases,
        "convergent_specific_gate": convergent,
        "normalized_gain_denominator_floor_mse": 1.0,
        "flows": compact,
        "cost_audit_limitations": [
            "SVD/reconstruction work and retained bytes are recomputed from saved artifacts and logs.",
            "Aggregate diagnostic counters are checked in sums; clustering is not rerun and diagnostic operations were not individually traced.",
            "Historical elapsed times and floating-point prequantization SVD errors cannot be independently remeasured by a read-only audit.",
        ],
    }

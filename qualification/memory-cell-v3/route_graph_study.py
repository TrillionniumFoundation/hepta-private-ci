"""Train one semantic/layout policy, then reuse it for independent numeric domains.

The bounded operation catalog and calendar handles are supplied. The router is
trained from whole utterances and layouts from actual terminal execution rewards.
The parameter-only arm never repairs its predictions with a source value table.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

import numpy as np

from v3.learned_graph import LearnedGraph, collect_feedback
from v3.codec_reader import write_codec_memories
from v3.numeric_graph import (
    EXACT_PLANS,
    INTENTS,
    SPECS,
    exact_reader,
    make_query,
    numeric_executor,
    numeric_grade,
    target_for,
    write_memory,
)
from v3.route_language import graph_training_rows, language_digest, language_rows
from v3.route_metrics import evaluate_arm
from v3.routing_study import policies_digest, routing_evaluation, train_routing
from v3.semantic_router import canonical, digest


ROOT = Path(__file__).resolve().parent


def write_json(path, value):
    path.write_bytes(canonical(value) + b"\n")


def write_jsonl(path, values):
    with path.open("xb") as stream:
        for value in values:
            stream.write(canonical(value) + b"\n")


def bound_executor(source, read_values, artifact_binding):
    """Study snapshot guard; the production owner may supply its own callback."""
    frontier = digest(
        canonical({"domain": source["domain"], "raw_source": source["raw_source"]})
    )
    bindings = {
        spec.name: artifact_binding
        if spec.cell_type == "semantic"
        else digest(canonical(asdict(spec)))
        for spec in SPECS
    }

    def admit(generation, operation, artifact, source_frontier):
        if (
            generation != 1
            or artifact != bindings[operation]
            or source_frontier != frontier
        ):
            raise ValueError("stale or mismatched numeric study snapshot")

    return numeric_executor(
        source["domain"],
        read_values,
        admission_check=admit,
        artifact_bindings=bindings,
        source_frontier_digest=frontier,
    )


def train_layout(source, executor, path, *, seed, source_commit, support_digest):
    training_rows = graph_training_rows(source, seed)
    examples = []
    for row in training_rows:
        initial, query = make_query(row)
        examples.append(
            (
                row["id"],
                row["intent"],
                initial,
                query,
                target_for(source, row["intent"], tuple(row["address"])),
            )
        )
    # A one-physical-unit smooth reward scale is fixed in advance. Exactness,
    # provenance and physical MAE remain independently reported outcomes.
    feedback = collect_feedback(
        executor,
        examples,
        partition="train",
        score_function=lambda actual, target: numeric_grade(
            actual, target, reward_scale=source["scale"]
        ),
    )
    graph = LearnedGraph(SPECS, INTENTS, ("address",), seed=seed)
    receipt = graph.fit(feedback)
    manifest = graph.save(
        path / "model", source_commit=source_commit, support_digest=support_digest
    )
    loaded, _ = LearnedGraph.load(
        path / "model", expected_manifest_digest=manifest["manifest_sha256"]
    )
    if not np.array_equal(graph.weights, loaded.weights):
        raise AssertionError("graph save/load changed learned edge parameters")
    write_jsonl(path / "candidate-feedback.jsonl", feedback)
    receipt.update(
        {
            "manifest": manifest,
            "feedback_bytes": (path / "candidate-feedback.jsonl").stat().st_size,
            "feedback_sha256": digest((path / "candidate-feedback.jsonl").read_bytes()),
            "reward": "correct ordered source coordinates * 1/(1+absolute_error/one_physical_unit)",
            "reward_scale_scaled": source["scale"],
            "save_load_parity": True,
            "learned_paths": {
                intent: list(loaded.select(intent, "address")) for intent in INTENTS
            },
            "candidate_paths_per_query": len(executor.candidates("address")),
        }
    )
    write_json(path / "training-receipt.json", receipt)
    return loaded, receipt


def run_route_graph_study(
    encoder,
    sources,
    output,
    *,
    seed,
    source_commit,
    support_digest,
    development=False,
    rank=4,
):
    started = time.perf_counter()
    path = Path(output)
    path.mkdir(parents=True, exist_ok=False)
    write_json(path / "strong-planner.json", EXACT_PLANS)
    allowed = {"co2", "temperature", "sunspots", "unemployment"}
    if set(sources) - allowed or not {"co2", "temperature", "sunspots"} <= set(sources):
        raise ValueError("the declared numeric sources are required")
    if development:
        sources = {
            name: source for name, source in sources.items() if name != "unemployment"
        }
    elif set(sources) != allowed:
        raise ValueError("formal evaluation requires the untouched unemployment source")
    if rank != 4:
        raise ValueError(
            "this protocol fixes rank=4; capacity sweeps are a separate study"
        )
    partition = "development" if development else "held"
    training_source = sources["co2"]
    # Writes are allowed on each new domain. Only NOAA supplies policy examples.
    readers, memory_receipts, parameter_executors, exact_executors = {}, {}, {}, {}
    codec_executors, strong_codec_executors, codec_receipts = {}, {}, {}
    for name, source in sources.items():
        reader, receipt = write_memory(
            source, path / "memories" / name, rank=rank, seed=seed
        )
        readers[name], memory_receipts[name] = reader, receipt
        parameter_executors[name] = bound_executor(
            source, reader.read, reader.artifact_sha256
        )
        exact_executors[name] = bound_executor(
            source, exact_reader(source), digest(canonical(source["values"]))
        )
        codec_reader, strong_reader, codec_receipt = write_codec_memories(
            source, reader, path / "codecs" / name
        )
        codec_receipts[name] = codec_receipt
        codec_executors[name] = bound_executor(
            source, codec_reader.read, codec_reader.archive_sha256
        )
        strong_codec_executors[name] = bound_executor(
            source, strong_reader.read, strong_reader.archive_sha256
        )
    routers, description_features, router_study = train_routing(
        encoder,
        training_source,
        path / "routing-policies",
        seed=seed,
        source_commit=source_commit,
        support_digest=support_digest,
    )
    primary_mode = router_study["selected_primary_mode"]
    graph, graph_fit = train_layout(
        training_source,
        parameter_executors["co2"],
        path / "parameter-layout",
        seed=seed,
        source_commit=source_commit,
        support_digest=support_digest,
    )
    exact_graph, exact_graph_fit = train_layout(
        training_source,
        exact_executors["co2"],
        path / "exact-layout-diagnostic",
        seed=seed,
        source_commit=source_commit,
        support_digest=support_digest,
    )
    frozen_before = digest(
        policies_digest(routers).encode()
        + graph.weights.tobytes()
        + exact_graph.weights.tobytes()
    )
    summaries = {}
    evaluation_paths = []
    for name, source in sources.items():
        domain_path = path / "evaluation" / name
        domain_path.mkdir(parents=True, exist_ok=False)
        rows = language_rows(
            source, seed, partition, repetitions=3 if development else 4
        )
        routes, route_records, routing = routing_evaluation(
            encoder, routers, primary_mode, rows, description_features
        )
        write_jsonl(domain_path / "routing.jsonl", route_records)
        # One learned layout is held fixed across all memory and structure arms.
        # A separately trained exact-source layout is only a diagnostic.
        arms = (
            (
                "parameter_learned_semantic",
                parameter_executors[name],
                graph,
                "semantic",
                {},
            ),
            (
                "parameter_raw_semantic",
                parameter_executors[name],
                graph,
                "raw_semantic",
                {},
            ),
            (
                "parameter_slot_semantic",
                parameter_executors[name],
                graph,
                "slot_semantic",
                {},
            ),
            (
                "parameter_learned_oracle_route",
                parameter_executors[name],
                graph,
                "oracle",
                {},
            ),
            (
                "parameter_exact_planner_semantic",
                parameter_executors[name],
                graph,
                "semantic",
                {"planner": True},
            ),
            (
                "parameter_exact_planner_oracle",
                parameter_executors[name],
                graph,
                "oracle",
                {"planner": True},
            ),
            (
                "parameter_single_hop",
                parameter_executors[name],
                graph,
                "semantic",
                {"maximum_hops": 1},
            ),
            (
                "parameter_removed_cross_edges",
                parameter_executors[name],
                graph,
                "semantic",
                {"mode": "no_cross_cell_edges"},
            ),
            (
                "parameter_permuted_ports",
                parameter_executors[name],
                graph,
                "semantic",
                {"shuffled": True},
            ),
            (
                "parameter_zero_shot_route",
                parameter_executors[name],
                graph,
                "zero_shot_description",
                {},
            ),
            (
                "parameter_literal_route",
                parameter_executors[name],
                graph,
                "literal",
                {},
            ),
            (
                "exact_values_learned_semantic",
                exact_executors[name],
                graph,
                "semantic",
                {},
            ),
            (
                "exact_values_learned_oracle_route",
                exact_executors[name],
                graph,
                "oracle",
                {},
            ),
            (
                "exact_values_exact_planner_semantic",
                exact_executors[name],
                graph,
                "semantic",
                {"planner": True},
            ),
            (
                "exact_values_exact_planner_oracle",
                exact_executors[name],
                graph,
                "oracle",
                {"planner": True},
            ),
            (
                "exact_values_exact_trained_layout",
                exact_executors[name],
                exact_graph,
                "semantic",
                {},
            ),
            (
                "lossless_codec_learned_semantic",
                codec_executors[name],
                graph,
                "semantic",
                {},
            ),
            (
                "lossless_codec_raw_semantic",
                codec_executors[name],
                graph,
                "raw_semantic",
                {},
            ),
            (
                "lossless_codec_slot_semantic",
                codec_executors[name],
                graph,
                "slot_semantic",
                {},
            ),
            (
                "lossless_codec_raw_without_risk_abstention",
                codec_executors[name],
                graph,
                "raw_without_risk_abstention",
                {},
            ),
            ("lossless_codec_oracle_route", codec_executors[name], graph, "oracle", {}),
            (
                "lossless_codec_removed_cross_edges",
                codec_executors[name],
                graph,
                "semantic",
                {"mode": "no_cross_cell_edges"},
            ),
            (
                "lossless_codec_permuted_ports",
                codec_executors[name],
                graph,
                "semantic",
                {"shuffled": True},
            ),
            (
                "strong_exact_codec_planner_semantic",
                strong_codec_executors[name],
                graph,
                "semantic",
                {"planner": True},
            ),
            (
                "strong_exact_codec_planner_oracle",
                strong_codec_executors[name],
                graph,
                "oracle",
                {"planner": True},
            ),
        )
        arm_summaries = {}
        for arm, executor, selected_graph, route_name, options in arms:
            records, summary = evaluate_arm(
                rows,
                source,
                executor,
                selected_graph,
                routes[route_name],
                arm=arm,
                seed=seed,
                **options,
            )
            write_jsonl(domain_path / f"{arm}.jsonl", records)
            arm_summaries[arm] = summary
        summaries[name] = {
            "policy_training_domain": "co2",
            "memory_write_training": memory_receipts[name],
            "codec_memory_writes": codec_receipts[name],
            "query_partition": partition,
            "routing": routing,
            "arms": arm_summaries,
            "new_domain_policy_updates": 0,
            "domain_development_outcomes_previously_observed": name != "unemployment",
            "same_entity_distinct_supported_predicates": list(INTENTS),
        }
        summaries[name]["controlled_gaps"] = {
            "parameter_exact_routing_gap": arm_summaries[
                "parameter_learned_oracle_route"
            ]["exact_answer_rate"]
            - arm_summaries["parameter_learned_semantic"]["exact_answer_rate"],
            "lossless_exact_routing_gap": arm_summaries["lossless_codec_oracle_route"][
                "exact_answer_rate"
            ]
            - arm_summaries["lossless_codec_learned_semantic"]["exact_answer_rate"],
            "lossless_cross_edge_gain": arm_summaries[
                "lossless_codec_learned_semantic"
            ]["exact_answer_rate"]
            - arm_summaries["lossless_codec_removed_cross_edges"]["exact_answer_rate"],
            "lossless_same_port_permutation_gain": arm_summaries[
                "lossless_codec_learned_semantic"
            ]["exact_answer_rate"]
            - arm_summaries["lossless_codec_permuted_ports"]["exact_answer_rate"],
            "learned_minus_strong_exact_planner": arm_summaries[
                "lossless_codec_learned_semantic"
            ]["exact_answer_rate"]
            - arm_summaries["strong_exact_codec_planner_semantic"]["exact_answer_rate"],
        }
        write_json(domain_path / "summary.json", summaries[name])
        evaluation_paths.append(str(domain_path.relative_to(path)))
    frozen_after = digest(
        policies_digest(routers).encode()
        + graph.weights.tobytes()
        + exact_graph.weights.tobytes()
    )
    if frozen_before != frozen_after:
        raise AssertionError("evaluation modified the frozen policy")
    router_bytes = sum(
        p.stat().st_size for p in (path / "routing-policies" / primary_mode).iterdir()
    )
    layout_bytes = sum(
        p.stat().st_size for p in (path / "parameter-layout" / "model").iterdir()
    )
    factor_bytes = sum(r["deployed_bytes"] for r in memory_receipts.values())
    codec_bytes = sum(
        r["factor_residual"]["deployed_bytes"] for r in codec_receipts.values()
    )
    strong_codec_bytes = sum(
        r["strong_exact"]["deployed_bytes"] for r in codec_receipts.values()
    )
    planner_bytes = (path / "strong-planner.json").stat().st_size
    summary = {
        "schema": "memory-cell-v3.numeric-route-graph-study.v1",
        "seed": seed,
        "development": development,
        "evaluation_partition": partition,
        "policy_training_domain": "co2",
        "transfer_domains": [name for name in sources if name != "co2"],
        "untouched_domain_until_formal": "unemployment",
        "untouched_domain_evaluated": not development,
        "source_commit": source_commit,
        "support_digest": support_digest,
        "language_fixture_digest": language_digest(),
        "encoder": encoder.manifest(),
        "encoder_base_bytes": encoder.base_bytes,
        "encoder_load_seconds": encoder.load_seconds,
        "router_selection_study": router_study,
        "primary_router_mode": primary_mode,
        "router_save_load_parity": True,
        "parameter_layout_training": graph_fit,
        "exact_value_layout_diagnostic_training": exact_graph_fit,
        "frozen_policy_digest_before_evaluation": frozen_before,
        "frozen_policy_digest_after_evaluation": frozen_after,
        "policy_unchanged": True,
        "all_candidate_costs_included": True,
        "domains": summaries,
        "primary_deployment_cost": {
            "frozen_encoder_bytes": encoder.base_bytes,
            "selected_router_bytes": router_bytes,
            "learned_layout_bytes": layout_bytes,
            "parameter_memories_with_address_metadata_bytes": factor_bytes,
            "lossless_codec_memories_with_address_metadata_bytes": codec_bytes,
            "strong_exact_codec_memories_with_address_metadata_bytes": strong_codec_bytes,
            "strong_exact_planner_metadata_bytes": planner_bytes,
            "parameter_total_with_shared_encoder": encoder.base_bytes
            + router_bytes
            + layout_bytes
            + factor_bytes,
            "lossless_total_with_shared_encoder": encoder.base_bytes
            + router_bytes
            + layout_bytes
            + codec_bytes,
            "strong_exact_planner_total_with_shared_encoder": encoder.base_bytes
            + router_bytes
            + planner_bytes
            + strong_codec_bytes,
            "budget_scope": "serialized model and address/control metadata; common runtime/interpreter/program code excluded",
            "codec_resident_exact_cache_bytes": sum(
                r["factor_residual"]["resident_decoded_cache_bytes"]
                for r in codec_receipts.values()
            ),
            "encoder_is_charged_once": True,
            "diagnostic_models_are_separately_saved": True,
        },
        "all_study_seconds": time.perf_counter() - started,
        "evaluation_artifact_paths": evaluation_paths,
        "limits": {
            "entity_and_date_handles": "explicit value-free inputs, not learned extraction",
            "capability_catalog": "supplied typed ports, calendar navigation and arithmetic; edge preferences are learned",
            "owner_check": "per-operation local study snapshot validation; production owner journal tested separately",
            "memory": "lossy integer low-rank parameters; no residual correction in parameter arms",
            "transfer": "unemployment is unobserved until formal; other domains have disclosed development outcomes; no new-domain policy training",
            "language": "predeclared English template folds; broader or multilingual language remains untested",
            "source_records": "all canonical source values are written; held queries test reads of written facts, not forecasts",
        },
    }
    write_json(path / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--sources", type=Path, default=ROOT / "sources" / "numeric")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=8011)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--support-digest", required=True)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT.parent / "memory-cell-v2"))
    from v2.encoder import MiniLMEncoder

    encoder = MiniLMEncoder(args.base)
    names = (
        ("co2", "temperature", "sunspots")
        if args.development
        else ("co2", "temperature", "sunspots", "unemployment")
    )
    sources = {
        name: json.loads(
            (
                args.sources / f"{name}.json"
                if name != "unemployment"
                else args.sources.parent / "held-economy" / "unemployment.json"
            ).read_bytes()
        )
        for name in names
    }
    summary = run_route_graph_study(
        encoder,
        sources,
        args.output,
        seed=args.seed,
        source_commit=args.source_commit,
        support_digest=args.support_digest,
        development=args.development,
    )
    print(
        json.dumps(
            {
                name: value["routing"]["routes"]["semantic"]
                for name, value in summary["domains"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

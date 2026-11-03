"""Fit one language/layout policy, then freeze it across old and new memory types."""

from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from bootstrap import PACKAGE

from route_graph_study import train_layout
from v3.codec_reader import write_codec_memories
from v3.numeric_graph import EXACT_PLANS, write_memory
from v4.joint_data import (
    materialize,
    month_view,
    retail_descriptor,
    science_sources,
    scientific_descriptor,
    serving_requests,
    truth_table,
)
from v4.joint_graph import evaluate, executor_for
from v4.language_train import make_rows
from v4.routing_study import train_routing
from v4.semantic_calibration import route_metrics
from v4.semantic_common import REJECT, canonical, digest
from v4.semantic_model import RouteDecision
from v4.typed_memory_events import EventMemory
from v4.typed_memory_codecs import decode_event_archive


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def write_jsonl(path, values):
    with Path(path).open("xb") as stream:
        for value in values:
            stream.write(canonical(value) + b"\n")


def state_digest(directory):
    return digest(
        canonical(
            {
                str(path.relative_to(directory)): digest(path.read_bytes())
                for path in sorted(Path(directory).rglob("*"))
                if path.is_file()
            }
        )
    )


def router_digest(directory):
    root = Path(directory)
    return digest(
        (root / "PRIMARY.json").read_bytes() + state_digest(root / "selected").encode()
    )


def fresh_routes(root, router_root, receipt, rows, *, base):
    deployed = root / "deployed-router"
    deployed.mkdir()
    shutil.copyfile(router_root / "PRIMARY.json", deployed / "PRIMARY.json")
    shutil.copytree(router_root / "selected", deployed / "selected")
    requests = root / "unlabeled-serving-requests.json"
    output = root / "fresh-router-output.json"
    write_json(requests, serving_requests(rows))
    started = time.perf_counter()
    process = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "router_reader.py"),
            "--base",
            str(base),
            "--router",
            str(deployed),
            "--primary-sha256",
            receipt["primary_sha256"],
            "--requests",
            str(requests),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    read_receipt = {
        "returncode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "wall_seconds": time.perf_counter() - started,
        "actual_fresh_process": True,
    }
    write_json(root / "fresh-router-process.json", read_receipt)
    if process.returncode != 0:
        raise RuntimeError("fresh routing process failed; process receipt retained")
    result = json.loads(output.read_bytes())
    if (
        result["requests_sha256"] != digest(requests.read_bytes())
        or result["primary_sha256"] != receipt["primary_sha256"]
    ):
        raise ValueError("fresh routing output request/model binding differs")
    return (
        [RouteDecision(**value) for value in result["decisions"]],
        result,
        read_receipt,
    )


def prepare_science(sources, root, seed, *, primary_rank, diagnostic_rank):
    domains, receipts = {}, {}
    for domain, source in sources.items():
        descriptor = scientific_descriptor(source)
        primary, fitted = write_memory(
            source, root / domain / "primary", rank=primary_rank, seed=seed
        )
        diagnostic, low_fitted = write_memory(
            source, root / domain / "rank-control", rank=diagnostic_rank, seed=seed
        )
        residual, strong, codecs = write_codec_memories(
            source, primary, root / domain / "codecs"
        )
        frontier = digest(canonical({"domain": domain, "source": source["raw_source"]}))
        executors = {
            name: executor_for(
                descriptor,
                reader.read,
                artifact_digest=binding,
                frontier_digest=frontier,
            )
            for name, reader, binding in (
                ("parameter", primary, primary.artifact_sha256),
                ("rank_control", diagnostic, diagnostic.artifact_sha256),
                ("residual", residual, residual.archive_sha256),
                ("strong", strong, strong.archive_sha256),
            )
        }
        domains[domain] = {
            "descriptor": descriptor,
            "truth": truth_table(source),
            "executors": executors,
        }
        receipts[domain] = {
            "primary": fitted,
            "rank_control": low_fitted,
            "codecs": codecs,
            "larger_primary_is_not_same_budget_as_v3_rank4": True,
        }
        write_json(root / domain / "write-receipts.json", receipts[domain])
    return domains, receipts


def prepare_events(source, seed_root, root):
    summary = json.loads((seed_root / "seed-summary.json").read_bytes())
    write = summary["event_arms"]["full_rank"]["write"]
    memory_path = seed_root / "full_rank" / "memory"
    common = {
        "expected_metadata_sha256": write["metadata_sha256"],
        "expected_exact_sha256": write["exact_metadata_sha256"],
    }
    parameter = EventMemory.load(memory_path, mode="parameter", **common)
    residual = EventMemory.load(memory_path, mode="residual_exact", **common)
    selected = summary["best_traditional_control"]
    archive = (seed_root / "exact-controls" / f"{selected}.archive").read_bytes()
    if digest(archive) != summary["exact_controls"][selected]["sha256"]:
        raise ValueError("strong event baseline archive binding differs")
    records = decode_event_archive(archive)
    conventional = {record["record_id"]: record for record in records}

    def exact_read(record_id, field):
        if record_id not in conventional:
            return None
        return {
            "kind": "integer",
            "value": conventional[record_id][field],
            "support": [f"{record_id}:{field}"],
        }

    root.mkdir()
    domains, views = {}, {}
    for field in ("quantity", "unit_price_pence"):
        view = month_view(parameter.metadata, field)
        raw = canonical(view) + b"\n"
        (root / f"{view['domain']}.json").write_bytes(raw)
        descriptor = retail_descriptor(view)
        executors = {
            name: executor_for(
                descriptor,
                read,
                artifact_digest=binding,
                frontier_digest=digest(raw),
                event_view=view,
            )
            for name, read, binding in (
                ("parameter", parameter.read, write["metadata_sha256"]),
                ("residual", residual.read, write["exact_metadata_sha256"]),
                ("strong", exact_read, digest(archive)),
            )
        }
        domains[view["domain"]] = {
            "descriptor": descriptor,
            "truth": truth_table(source, view),
            "executors": executors,
        }
        views[view["domain"]] = {
            "bytes": len(raw),
            "sha256": digest(raw),
            "record_count": len(view["record_by_month"]),
            "source_paths_in_parameter_reader": 0,
            "view_has_answer_values": False,
        }
    receipt = {
        "reused_transfer_seed_memory": str(memory_path),
        "repeated_event_training": 0,
        "parameter_deployment_bytes": write["parameter_deployment_bytes"],
        "residual_deployment_bytes": write["exact_deployment_bytes"],
        "strong_deployment_bytes": len(archive),
        "strong_decoded_canonical_record_bytes": len(canonical(records)),
        "residual_decoded_array_bytes": write["decoded_exact_runtime_array_bytes"],
        "views": views,
        "time_address_is_supplied_metadata": True,
        "source_population_statistics_claimed": False,
    }
    write_json(root / "event-view-receipt.json", receipt)
    return domains, receipt


def run_seed(
    encoder,
    base,
    sources,
    event_source,
    transfer_root,
    output,
    protocol,
    source_commit,
    seed,
    *,
    development,
):
    started = time.perf_counter()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    settings = protocol["joint"]
    router, routing = train_routing(
        encoder,
        make_rows("train", seed),
        make_rows("selection", seed),
        root / "router",
        seed=seed,
        source_commit=source_commit,
        config=protocol["routing"],
    )
    domains, numeric_receipts = prepare_science(
        sources,
        root / "numeric-memories",
        seed,
        primary_rank=settings["primary_rank"],
        diagnostic_rank=settings["diagnostic_rank"],
    )
    events, event_receipt = prepare_events(
        event_source, transfer_root / f"seed-{seed}", root / "event-views"
    )
    domains.update(events)
    support_digest = digest(canonical(protocol))
    graph, graph_receipt = train_layout(
        sources["co2"],
        domains["co2"]["executors"]["parameter"],
        root / "layout",
        seed=seed,
        source_commit=source_commit,
        support_digest=support_digest,
    )
    frozen_before = {
        "router": router_digest(root / "router"),
        "layout": digest(graph.weights.tobytes()),
        "numeric": state_digest(root / "numeric-memories"),
        "event": state_digest(transfer_root / f"seed-{seed}" / "full_rank" / "memory"),
    }
    rows_by_domain = {
        name: materialize(
            data["descriptor"],
            seed,
            development=development,
            protocol_frozen=protocol["frozen_before_formal_execution"],
        )
        for name, data in domains.items()
    }
    rows = [row for domain_rows in rows_by_domain.values() for row in domain_rows]
    write_jsonl(root / "grader-queries.jsonl", rows)
    fresh, fresh_receipt, process = fresh_routes(
        root, root / "router", routing, rows, base=base
    )
    inprocess = router.decisions(serving_requests(rows))
    if [asdict(value) for value in fresh] != [asdict(value) for value in inprocess]:
        raise AssertionError("fresh and parent selected-router decisions differ")
    reload_receipt = dict(router.last_inference_receipt)
    if router_digest(root / "deployed-router") != frozen_before["router"]:
        raise AssertionError(
            "copied deployment router differs from selected training artifact"
        )
    result, offset = {}, 0
    for name, data in domains.items():
        domain_rows = rows_by_domain[name]
        decisions = fresh[offset : offset + len(domain_rows)]
        offset += len(domain_rows)
        routes = [decision.route for decision in decisions]
        oracle = [
            None if row["intent"] == REJECT else row["intent"] for row in domain_rows
        ]
        domain_root = root / "evaluation" / name
        domain_root.mkdir(parents=True)
        write_jsonl(
            domain_root / "routing.jsonl",
            [
                {
                    "query_id": row["id"],
                    "template_id": row["template_id"],
                    **asdict(decision),
                }
                for row, decision in zip(domain_rows, decisions, strict=True)
            ],
        )
        summaries = {}
        for memory in ("parameter", "residual", "strong", "rank_control"):
            if memory not in data["executors"]:
                continue
            variants = (
                ("actual", "oracle", "planner", "removed", "permuted")
                if memory in {"parameter", "residual"}
                else ("planner", "oracle")
                if memory == "strong"
                else ("actual", "oracle")
            )
            for variant in variants:
                arm = f"{memory}_{variant}"
                records, measured = evaluate(
                    domain_rows,
                    data["truth"],
                    data["descriptor"],
                    data["executors"][memory],
                    graph,
                    oracle if variant == "oracle" else routes,
                    arm=arm,
                    seed=seed,
                    planner=variant == "planner" or memory == "strong",
                    removed=variant == "removed",
                    shuffled=variant == "permuted",
                )
                write_jsonl(domain_root / f"{arm}.jsonl", records)
                summaries[arm] = measured
        metrics = route_metrics(domain_rows, decisions)
        gates = {
            "semantic": metrics["known_correct_accepted_rate"]
            >= settings["minimum_correct_coverage"]
            and metrics["unsupported_false_accept_rate"]
            <= settings["maximum_ood_false_accept"]
        }
        for memory in ("parameter", "residual"):
            actual = summaries[f"{memory}_actual"]["composed_exact_answer_rate"]
            removed = summaries[f"{memory}_removed"]["composed_exact_answer_rate"]
            permuted = summaries[f"{memory}_permuted"]["composed_exact_answer_rate"]
            gates[f"{memory}_composition"] = (
                actual - removed >= settings["edge_gain_minimum"]
                and actual - permuted >= settings["edge_gain_minimum"]
            )
        result[name] = {
            "descriptor": {
                key: value
                for key, value in data["descriptor"].items()
                if key != "coordinates"
            },
            "routing": metrics,
            "arms": summaries,
            "gates": gates,
            "oracle_gap_parameter": summaries["parameter_oracle"]["exact_answer_rate"]
            - summaries["parameter_actual"]["exact_answer_rate"],
            "oracle_gap_residual": summaries["residual_oracle"]["exact_answer_rate"]
            - summaries["residual_actual"]["exact_answer_rate"],
        }
        write_json(domain_root / "summary.json", result[name])
    frozen_after = {
        "router": router_digest(root / "deployed-router"),
        "layout": digest(graph.weights.tobytes()),
        "numeric": state_digest(root / "numeric-memories"),
        "event": state_digest(transfer_root / f"seed-{seed}" / "full_rank" / "memory"),
    }
    if frozen_before != frozen_after:
        raise AssertionError("formal query execution modified deployed parameters")
    layout_bytes = sum(
        path.stat().st_size
        for path in (root / "layout" / "model").iterdir()
        if path.is_file()
    )
    router_bytes = (
        routing["selected_artifact"]["bytes"]
        + (root / "router" / "PRIMARY.json").stat().st_size
    )
    address_bytes = sum(info["bytes"] for info in event_receipt["views"].values())
    memory_parameter = (
        sum(
            receipt["primary"]["deployed_bytes"]
            for receipt in numeric_receipts.values()
        )
        + event_receipt["parameter_deployment_bytes"]
    )
    memory_residual = (
        sum(
            receipt["codecs"]["factor_residual"]["deployed_bytes"]
            for receipt in numeric_receipts.values()
        )
        + event_receipt["residual_deployment_bytes"]
    )
    memory_strong = (
        sum(
            receipt["codecs"]["strong_exact"]["deployed_bytes"]
            for receipt in numeric_receipts.values()
        )
        + event_receipt["strong_deployment_bytes"]
    )
    planner_bytes = len(canonical(EXACT_PLANS) + b"\n")
    common = encoder.base_bytes + router_bytes + address_bytes
    summary = {
        "schema": "memory-cell-v4.joint-seed.v1",
        "seed": seed,
        "source_commit": source_commit,
        "development_only": development,
        "routing_training": routing,
        "layout_training": graph_receipt,
        "numeric_memories": numeric_receipts,
        "event_memory_views": event_receipt,
        "domains": result,
        "fresh_process": process,
        "fresh_read": {
            key: value for key, value in fresh_receipt.items() if key != "decisions"
        },
        "parent_reload_verification_work": reload_receipt,
        "frozen_before": frozen_before,
        "frozen_after": frozen_after,
        "domain_policy_updates": 0,
        "fresh_parent_route_parity": True,
        "independent_language_templates": len(next(iter(rows_by_domain.values()))),
        "same_templates_reused_across_domains_and_seeds": True,
        "serialized_deployment": {
            "shared_encoder": encoder.base_bytes,
            "selected_router_and_pointer": router_bytes,
            "learned_layout": layout_bytes,
            "event_month_address_views": address_bytes,
            "parameter_memories": memory_parameter,
            "residual_memories": memory_residual,
            "strong_exact_memories": memory_strong,
            "strong_planner": planner_bytes,
            "parameter_system": common + layout_bytes + memory_parameter,
            "residual_system": common + layout_bytes + memory_residual,
            "strong_planner_system": common + planner_bytes + memory_strong,
            "runtime_and_executable_code_not_in_serialized_state": True,
        },
        "wall_seconds": time.perf_counter() - started,
    }
    write_json(root / "strong-planner.json", EXACT_PLANS)
    write_json(root / "summary.json", summary)
    return summary


def run_joint(
    protocol,
    output,
    source_commit,
    seeds,
    *,
    encoder,
    base,
    transfer_root,
    development=False,
):
    if not development and (
        not protocol["frozen_before_formal_execution"]
        or list(seeds) != [401, 409, 419, 421, 431]
    ):
        raise ValueError("formal joint study requires the frozen five-seed protocol")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    source_path = (
        PACKAGE
        / "sources"
        / "retail"
        / ("retail-development.json" if development else "retail-held.json")
    )
    event_source = json.loads(source_path.read_bytes())
    sources = science_sources()
    results = [
        run_seed(
            encoder,
            base,
            sources,
            event_source,
            Path(transfer_root),
            root / f"seed-{seed}",
            protocol,
            source_commit,
            seed,
            development=development,
        )
        for seed in seeds
    ]
    summary = {
        "schema": "memory-cell-v4.joint-study.v1",
        "seeds": list(seeds),
        "source_commit": source_commit,
        "development_only": development,
        "results": results,
        "source_retail_sha256": digest(source_path.read_bytes()),
        "held_language_evaluated": not development,
        "policy_transfer_scope": "One numeric intent/layout policy across four previously seen science domains and two views over actual new event reads; identity slots and primitive ports are supplied.",
    }
    write_json(root / "summary.json", summary)
    return summary

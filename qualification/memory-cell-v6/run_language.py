"""Execute the frozen six-arm language experiment once, preserving raw evidence.

The evaluator receives gold for recording and the explicitly named oracle arm.
Ordinary readers receive only bounded requests and frozen router operations.
The paired exact reader has no parameter object files in its deployments.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import shutil
import time

import numpy as np

from prepare_run import dump, identity, inventory, load, verify_files, verify_run
from v6.contracts import MemoryRequest, canonical, digest
from v6.encoder import MiniLMEncoder, normalize_request
from v6.network import MetaNetwork, NodeProcess
from v6.router import Router
from v6.study_data import expected


def read_held(directory, freeze, plan):
    directory = Path(directory)
    if identity(directory / "SEAL.json")["sha256"] != freeze["held_seal_sha256"]:
        raise ValueError("held seal differs from pre-exposure freeze")
    seal = load(directory / "SEAL.json")
    verify_files(directory, seal["files"])
    if identity(directory / "queries.json")["sha256"] != freeze["held_queries_sha256"]:
        raise ValueError("held queries differ from pre-exposure freeze")
    queries = load(directory / "queries.json")
    if len(queries) != plan["templates"] or len({row["id"] for row in queries}) != len(
        queries
    ):
        raise ValueError("held inventory differs from the execution plan")
    if (
        sum(row["operation"] is None for row in queries)
        != plan["unsupported_templates"]
    ):
        raise ValueError("held class balance differs from execution plan")
    return queries


def requests_for(queries, case, truth, plan, arm):
    entities, requests = sorted(truth["entities"]), []
    times, budget = plan["time_contract"], plan["execution_budget"]
    for index, query in enumerate(queries):
        entity = entities[(index + case["seed"]) % len(entities)]
        text = query["text"].format(entity=entity, at=times["at"], since=times["since"])
        requests.append(
            MemoryRequest(
                f"{case['seed']}.{case['domain']}.{arm}.{index}",
                truth["scope"],
                entity,
                text,
                times["at"],
                times["since"],
                budget["max_read_hops"],
                budget["max_cells"],
            )
        )
    return requests


def child_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def sampled_resident(nodes):
    result = {}
    for node in nodes:
        try:
            pages = int(Path(f"/proc/{node.process.pid}/statm").read_text().split()[1])
            result[str(node.process.pid)] = pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            result[str(node.process.pid)] = None
    return result


@contextmanager
def deploy(case_folder, work, pinned, timeout):
    nodes, networks, cost = [], {}, {"deployments": []}
    started, cpu, children = time.perf_counter(), time.process_time(), child_cpu()
    try:
        for reader in ("parameter", "exact"):
            selected = []
            for index in range(3):
                folder = work / f"{reader}-{index}"
                folder.mkdir(parents=True)
                shutil.copy2(case_folder / "source.sqlite", folder / "source.sqlite")
                shutil.copytree(
                    case_folder / "artifacts",
                    folder / "artifacts",
                    ignore=shutil.ignore_patterns("objects")
                    if reader == "exact"
                    else None,
                )
                files = inventory(folder)
                node = NodeProcess(
                    folder / "source.sqlite",
                    folder / "artifacts",
                    reader,
                    log_path=folder / "node.log",
                )
                node.client.timeout = timeout
                nodes.append(node)
                selected.append(node)
                if node.ready["snapshot_digest"] != pinned:
                    raise ValueError("deployment admitted a different snapshot")
                cost["deployments"].append(
                    {
                        "reader_kind": reader,
                        "node_index": index,
                        "pid": node.process.pid,
                        "source_inode": (folder / "source.sqlite").stat().st_ino,
                        "path": str(folder),
                        "files": files,
                        "required_snapshot_bytes": sum(
                            row["bytes"] for row in files.values()
                        ),
                        "has_parameter_objects": (
                            folder / "artifacts" / "objects"
                        ).exists(),
                    }
                )
            networks[reader] = MetaNetwork(*(node.client for node in selected))
        cost["startup_wall_seconds"] = time.perf_counter() - started
        cost["startup_parent_cpu_seconds"] = time.process_time() - cpu
        cost["resident_after_startup_bytes"] = sampled_resident(nodes)
        yield networks, nodes, cost
    finally:
        cost["resident_before_stop_bytes"] = sampled_resident(nodes)
        for node in nodes:
            node.stop()
        cost["child_cpu_seconds"] = child_cpu() - children
        cost["deployment_lifetime_wall_seconds"] = time.perf_counter() - started


def make_record(
    query,
    request,
    case,
    truth,
    operation,
    result,
    router_digest,
    model_digest,
    read_seconds,
    route_seconds,
):
    expected_value, expected_sources = expected(
        truth["entities"][request.entity], query["operation"]
    )
    actual_value, actual_sources = result["value"], list(result["source_ids"])
    expected_digest = None if expected_value is None else digest(expected_value)
    actual_digest = None if actual_value is None else digest(actual_value)
    accepted = result["status"] == "ok"
    source_ids = {
        item for row in truth["entities"].values() for item in row["sources"].values()
    }
    transport = result["transport"]
    version_valid = (
        accepted
        and result["snapshot_digest"] == case["snapshot_digest"]
        and result["generation"] == 1
        and bool(actual_sources)
        and set(actual_sources) <= source_ids
        and transport["validation_attempts"] == transport["node_count"]
    )
    return {
        "template_id": query["id"],
        "seed": case["seed"],
        "domain": case["domain"],
        "language": query["language"],
        "query_family": query["family"],
        "gold_operation": query["operation"],
        "actual_operation": operation,
        "router_accepted": operation is not None,
        "accepted": accepted,
        "expected_value": expected_value,
        "actual_value": actual_value,
        "expected_value_digest": expected_digest,
        "actual_value_digest": actual_digest,
        "expected_sources": expected_sources,
        "actual_sources": actual_sources,
        "value_correct": expected_digest is not None
        and expected_digest == actual_digest,
        "source_correct": bool(expected_sources) and expected_sources == actual_sources,
        "source_versions_valid": version_valid,
        "snapshot_digest": result["snapshot_digest"],
        "router_digest": router_digest,
        "model_digest": model_digest,
        "generation": result["generation"],
        "latency_seconds": read_seconds,
        "rpc_bytes": transport["rpc_bytes"],
        "hops": result["hops"],
        "status": result["status"],
        "prediction_kind": result["prediction_kind"],
        "reason": result["reason"],
        "request": request.as_dict(),
        "request_sha256": digest(request.as_dict()),
        "actual_cell_digests": list(result["cell_digests"]),
        "transport": transport,
        "routing_batch_amortized_seconds": route_seconds,
        "read_plus_amortized_routing_seconds": read_seconds + route_seconds,
    }


def evaluate(run, freeze_path, freeze_digest, held):
    run = Path(run).resolve()
    started, cpu, children = time.perf_counter(), time.process_time(), child_cpu()
    freeze, prepared, plan = verify_run(run, freeze_path, freeze_digest)
    output = run / "evaluation"
    output.mkdir(exist_ok=False)
    dump(
        output / "STARTED.json",
        {
            "freeze_sha256": freeze_digest,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "source_commit": freeze["source_commit"],
            "resume_supported": False,
        },
    )
    # No code above this line has opened the held directory.
    queries = read_held(held, freeze, plan)
    encoders, features, feature_prices, encoder_costs = {}, {}, {}, {}
    for item in prepared["encoders"]:
        begin, process = time.perf_counter(), time.process_time()
        encoder = MiniLMEncoder(item["path"])
        if encoder.digest != item["digest"]:
            raise ValueError("encoder identity changed after freeze")
        (
            encoders[encoder.digest],
            features[encoder.digest],
            feature_prices[encoder.digest],
        ) = encoder, {}, {}
        encoder_costs[encoder.digest] = {
            "base_bytes": encoder.base_bytes,
            "load_wall_seconds": time.perf_counter() - begin,
            "load_cpu_seconds": time.process_time() - process,
            "encoding_wall_seconds": 0.0,
            "encoding_cpu_seconds": 0.0,
            "unique_texts_encoded": 0,
        }
    routers, router_costs = {}, {}
    for seed, item in prepared["routers"].items():
        begin, process = time.perf_counter(), time.process_time()
        routers[int(seed)] = Router.load(
            run / item["path"],
            encoders.get(item["encoder_digest"]),
            item["manifest_sha256"],
        )
        router_costs[seed] = {
            "load_wall_seconds": time.perf_counter() - begin,
            "load_cpu_seconds": time.process_time() - process,
            "artifact_bytes": sum(value["bytes"] for value in item["files"].values()),
        }
    case_costs, records = [], 0
    with (output / "records.jsonl").open("xb") as raw:
        for case_index, case in enumerate(prepared["cases"]):
            case_folder = run / case["path"]
            truth = load(case_folder / "truth.json")
            admitted = prepared["routers"][str(case["seed"])]
            router = routers[case["seed"]]
            begin, process = time.perf_counter(), time.process_time()
            requests = requests_for(queries, case, truth, plan, "routing")
            texts = [
                normalize_request(row.text, row.entity, row.at, row.since)
                for row in requests
            ]
            normalization = {
                "wall_seconds": time.perf_counter() - begin,
                "cpu_seconds": time.process_time() - process,
            }
            dense, assigned_encoding = None, 0.0
            if admitted["encoder_digest"] is not None:
                key = admitted["encoder_digest"]
                missing = list(
                    dict.fromkeys(text for text in texts if text not in features[key])
                )
                if missing:
                    begin, process = time.perf_counter(), time.process_time()
                    encoded = encoders[key].encode(missing)
                    elapsed, consumed = (
                        time.perf_counter() - begin,
                        time.process_time() - process,
                    )
                    for text, vector in zip(missing, encoded):
                        features[key][text], feature_prices[key][text] = (
                            vector,
                            elapsed / len(missing),
                        )
                    encoder_costs[key]["encoding_wall_seconds"] += elapsed
                    encoder_costs[key]["encoding_cpu_seconds"] += consumed
                    encoder_costs[key]["unique_texts_encoded"] += len(missing)
                dense = np.vstack([features[key][text] for text in texts])
                assigned_encoding = sum(feature_prices[key][text] for text in texts)
            begin, process = time.perf_counter(), time.process_time()
            decisions = router.decisions(texts, router.scores(texts, dense=dense))
            routing = {
                "wall_seconds": time.perf_counter() - begin,
                "cpu_seconds": time.process_time() - process,
            }
            per_query_routing = (
                normalization["wall_seconds"]
                + routing["wall_seconds"]
                + assigned_encoding
            ) / len(queries)
            work = output / "deployments" / f"seed-{case['seed']}" / case["domain"]
            bundle = load(
                case_folder
                / "artifacts"
                / "snapshots"
                / (case["snapshot_digest"] + ".json")
            )
            model_digest = digest(bundle["cells"])
            arm_costs = {}
            order = (
                plan["full_arms"][case_index % len(plan["full_arms"]) :]
                + plan["full_arms"][: case_index % len(plan["full_arms"])]
            )
            with deploy(
                case_folder,
                work,
                case["snapshot_digest"],
                plan["execution_budget"]["rpc_timeout_seconds"],
            ) as (networks, nodes, deployment):
                for arm in order:
                    requests = requests_for(queries, case, truth, plan, arm)
                    costs = {
                        "rows": 0,
                        "read_wall_seconds": 0.0,
                        "rpc_bytes": 0,
                        "rpc_attempts": 0,
                        "read_attempts": 0,
                        "validation_attempts": 0,
                    }
                    for query, request, decision in zip(queries, requests, decisions):
                        operation = (
                            query["operation"]
                            if arm == "parameter_oracle"
                            else decision["operation"]
                        )
                        disabled = (
                            ("semantic",)
                            if arm == "parameter_no_semantic"
                            else ("procedure",)
                            if arm == "parameter_no_procedure"
                            else ()
                        )
                        before = time.perf_counter()
                        result = networks[
                            "exact" if arm == "exact_same_router" else "parameter"
                        ].read(
                            request,
                            operation,
                            disabled=disabled,
                            permute=arm == "parameter_shuffled",
                        )
                        elapsed = time.perf_counter() - before
                        record = make_record(
                            query,
                            request,
                            case,
                            truth,
                            operation,
                            result,
                            admitted["manifest_sha256"],
                            model_digest,
                            elapsed,
                            0.0 if arm == "parameter_oracle" else per_query_routing,
                        )
                        record.update(
                            arm=arm,
                            router_decision=decision,
                            normalized_text_sha256=digest(texts[costs["rows"]]),
                            reader_kind="exact"
                            if arm == "exact_same_router"
                            else "parameter",
                        )
                        raw.write(canonical(record) + b"\n")
                        records += 1
                        costs["rows"] += 1
                        costs["read_wall_seconds"] += elapsed
                        for name in (
                            "rpc_bytes",
                            "rpc_attempts",
                            "read_attempts",
                            "validation_attempts",
                        ):
                            costs[name] += result["transport"][name]
                    arm_costs[arm] = costs
                    raw.flush()
                    os.fsync(raw.fileno())
            case_costs.append(
                {
                    "seed": case["seed"],
                    "domain": case["domain"],
                    "arm_order": order,
                    "normalization": normalization,
                    "routing": routing,
                    "per_query_assigned_routing_wall_seconds": per_query_routing,
                    "deployment": deployment,
                    "arms": arm_costs,
                }
            )
            dump(output / "CASE_COSTS.json", case_costs)
            print(
                json.dumps(
                    {"completed": [case["seed"], case["domain"]], "records": records}
                ),
                flush=True,
            )
    if records != plan["expected_records"]:
        raise ValueError("formal record count differs from frozen execution plan")
    for key, cached in features.items():
        path = output / ("encoder-cache-" + key + ".npz")
        vectors = np.vstack(list(cached.values())) if cached else np.zeros((0, 384))
        np.savez_compressed(
            path,
            text_digests=np.array([digest(text) for text in cached]),
            vectors=vectors,
        )
        encoder_costs[key].update(
            cache_artifact=identity(path),
            numeric_array_bytes=vectors.nbytes,
            normalized_text_utf8_bytes=sum(len(text.encode()) for text in cached),
        )
    ledger = {
        "schema": "hepta.memory.v6.language-cost-ledger.v1",
        "freeze_sha256": freeze_digest,
        "records": identity(output / "records.jsonl"),
        "record_count": records,
        "cases": case_costs,
        "encoders": encoder_costs,
        "routers": router_costs,
        "preparation": identity(run / "PREPARED.json"),
        "formal_router_training": identity(run / "ROUTER_TRAINING.json"),
        "wall_seconds": time.perf_counter() - started,
        "parent_cpu_seconds": time.process_time() - cpu,
        "child_cpu_seconds": child_cpu() - children,
        "parent_peak_resident_kib_linux": resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss,
        "cost_interpretation": [
            "Actual experiment caches embeddings and shares each case's route decisions across arms.",
            "Every non-oracle arm is assigned the same batch-amortized routing burden for system comparisons.",
            "Recorded latency_seconds measures network read plus final validation, not uncached end-to-end language latency.",
            "Replica inventories are experiment allocations; exact deployments exclude parameter objects.",
            "Node RSS is sampled, not a continuous peak; RPC bytes exclude HTTP/TCP overhead.",
            "Development, learning, replay and structure-search ledgers remain separate mandatory cost components.",
        ],
        "audit_authorship": "Held author and record auditor also implemented transport and this runner; no third-party audit claim.",
    }
    dump(output / "COSTS.json", ledger)
    dump(
        output / "COMPLETE.json",
        {
            "freeze_sha256": freeze_digest,
            "records": ledger["records"],
            "costs": identity(output / "COSTS.json"),
            "rows": records,
        },
    )
    return {
        "records": records,
        "output": str(output),
        "records_sha256": ledger["records"]["sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--held", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(evaluate(args.run, args.freeze, args.freeze_sha256, args.held)),
        flush=True,
    )


if __name__ == "__main__":
    main()

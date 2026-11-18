"""Read unique original E4 graph receipts; partial evidence never becomes full cost."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--protocol-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.protocol.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.protocol_sha:
        raise ValueError("frozen protocol differs")
    protocol = json.loads(raw)
    root = args.run_root.resolve()
    circuit = root / "circuit"
    issues, inventory = [], {}

    def read(path, optional=False):
        if not path.is_file() or path.is_symlink():
            if not optional:
                issues.append("missing: " + str(path))
            return None
        raw = path.read_bytes()
        value = json.loads(raw)
        inventory[str(path.relative_to(root))] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_digest": digest(value),
        }
        return value

    def rebase(original):
        relative = Path(original).relative_to(Path(protocol["output_root"]))
        target = root / relative
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("receipt reference escapes this run")
        return target.resolve()

    def same(value, expected, label):
        if value != expected:
            issues.append(label)

    job, complete = read(circuit / "RESULT.json"), read(root / "COMPLETE.json")
    pool = read(circuit / "POOL.json")
    worker_intent = read(root / "WORKER_INTENT.json")
    if worker_intent is not None:
        for key, expected in (
            ("protocol_sha256", args.protocol_sha),
            ("comparison_digest", protocol["original_comparison_digest"]),
            ("source_inventory_sha256", protocol["original_B_source_inventory_sha256"]),
        ):
            same(worker_intent.get(key), expected, "worker " + key + " differs")
    if complete is not None:
        same(complete.get("status"), "COMPLETE", "worker completion status differs")
        same(
            complete.get("protocol_sha256"),
            args.protocol_sha,
            "worker completion protocol differs",
        )
    if pool is not None:
        same(
            pool["pool_identity"],
            digest(pool["inventory"]),
            "pool inventory identity differs",
        )
        actual_cells = pool["inventory"]["cells"]
        same(set(actual_cells), set(protocol["models"]), "pool Cell inventory differs")
        for cell, expected in protocol["models"].items():
            same(
                actual_cells.get(cell, {}).get("model_digest"),
                expected["manifest_digest"],
                "pool frozen model differs: " + cell,
            )
    pool_binding = None
    repair = protocol.get("adapter_precision_repair")
    if repair is not None:
        pool_binding = read(circuit / "POOL_BINDING.json")
        expected_source = protocol["source_sha256"]["shared_pool_v4.py"]
        if pool_binding is not None:
            for key, expected in (
                ("class_module", repair["expected_pool_class_module"]),
                ("class_name", "SharedAdapterPool"),
                ("source_sha256", expected_source),
                ("protocol_digest", args.protocol_sha),
            ):
                same(
                    pool_binding.get(key), expected, "pool binding " + key + " differs"
                )
        if pool is not None:
            same(
                pool["inventory"]["source_sha256"],
                expected_source,
                "actual pool source differs",
            )
        if worker_intent is not None:
            same(
                worker_intent.get("actual_pool_source_sha256"),
                expected_source,
                "worker pool source differs",
            )
            same(
                worker_intent.get("actual_pool_class_module"),
                repair["expected_pool_class_module"],
                "worker pool module differs",
            )
    search = read(circuit / "search/SEARCH.json")
    static = read(circuit / "STATIC_SELECTION.json")
    studies, plans = {}, {}
    for kind in ("original", "additional"):
        for panel in ("old_A", "old_B"):
            name = kind + "/" + panel
            studies[name] = read(circuit / name / "STUDY.json")
            plans[name] = read(circuit / name / "PLAN.json")
    if job and complete:
        same(complete["result_digest"], digest(job), "worker result binding differs")
        same(job["protocol_digest"], args.protocol_sha, "job protocol differs")
        same(
            job["comparison_digest"],
            protocol["original_comparison_digest"],
            "comparison differs",
        )
        for value, key in (
            (pool, "pool_digest"),
            (search, "search_digest"),
            (static, "static_selection_digest"),
        ):
            if value is not None:
                same(digest(value), job[key], key + " differs")
        for name, value in studies.items():
            if value is not None:
                kind, panel = name.split("/")
                same(
                    digest(value),
                    job["panel_study_digests"][panel][kind],
                    name + " binding differs",
                )
    expected_results = {}
    for row in search["observations"] if search else []:
        path = str(rebase(row["result_path"]))
        if path in expected_results:
            issues.append("duplicate result reference: " + path)
        expected_results[path] = row["result_digest"]
    for name, study in studies.items():
        if study is None:
            continue
        if plans[name] is not None:
            same(study["plan_digest"], digest(plans[name]), name + " plan differs")
        for category in ("arms", "interventions"):
            for rows in study.get(category, {}).values():
                for row in rows:
                    path = str(rebase(row["result_path"]))
                    if path in expected_results:
                        issues.append("duplicate result reference: " + path)
                    expected_results[path] = row["result_digest"]
    allowed_records = {
        row["record_digest"]: row["task_id"]
        for rows in protocol["panels"].values()
        for row in rows
    }
    costs = (
        "model_calls",
        "verifier_calls",
        "business_executions",
        "format_rejections",
        "input_tokens",
        "output_tokens",
    )
    groups, graph_paths, all_rows = defaultdict(list), set(), []
    call_paths, call_intents = set(), set()
    observed_cost_integrity = True
    for path in sorted(circuit.rglob("RESULT.json")):
        value = read(path)
        if value is None:
            continue
        if value.get("schema") != "hepta.online-message-circuit.result.v4":
            continue
        graph_paths.add(str(path))
        same(
            digest(value),
            expected_results.get(str(path)),
            "unbound graph: " + str(path),
        )
        if value["record_digest"] not in allowed_records:
            issues.append("unknown task record: " + str(path))
        same(
            value["task_id"],
            allowed_records.get(value["record_digest"]),
            "frozen task identity differs: " + str(path),
        )
        same(value.get("status"), "COMPLETE", "graph status differs: " + str(path))
        contract = read(path.parent / "CONTRACT.json")
        same(
            digest(contract),
            value["contract_digest"],
            "graph contract differs: " + str(path),
        )
        if contract is not None:
            same(contract["budget"], protocol["budget"], "contract budget differs")
            same(
                contract["output_selection"],
                protocol["output_selection"],
                "contract output selection differs",
            )
            same(
                contract["graph"]["graph_id"],
                value["graph_id"],
                "graph identity differs",
            )
            same(
                [node["slot"] for node in value["nodes"]],
                list(range(len(contract["graph"]["path"]))),
                "graph slots differ",
            )
            same(
                [node["cell_id"] for node in value["nodes"]],
                contract["graph"]["path"],
                "graph Cell path differs",
            )
            for cell, expected in protocol["models"].items():
                same(
                    contract["cells"].get(cell, {}).get("model_digest"),
                    expected["manifest_digest"],
                    "contract frozen model differs: " + cell,
                )
        if any(
            type(node["slot"]) is not int
            or node["status"] not in ("COMPLETE", "REMOVED")
            for node in value["nodes"]
        ):
            issues.append("invalid graph node slot or status")
        nodes = [node for node in value["nodes"] if node["status"] == "COMPLETE"]
        outputs = []
        for node in nodes:
            items = {}
            expected_call = (path.parent / ("node-" + str(node["slot"]))).resolve()
            call = rebase(node["output_path"]).parent
            if call != expected_call or call in call_paths:
                issues.append("duplicate or misplaced call reference: " + str(call))
                observed_cost_integrity = False
            call_paths.add(call)
            for key in ("request", "output", "verification"):
                item_path = rebase(node[key + "_path"])
                if item_path != expected_call / (key.upper() + ".json"):
                    issues.append("call artifact slot differs: " + str(item_path))
                    observed_cost_integrity = False
                item = read(item_path)
                items[key] = item
                same(
                    digest(item),
                    node[key + "_digest"],
                    key + " bytes differ: " + str(path),
                )
                if key != "request":
                    same(item, node[key], key + " embedded copy differs: " + str(path))
            outputs.append(items["output"])
            if items["output"] is not None:
                for key, minimum, cap in (
                    ("input_tokens", 1, "max_input_tokens_per_call"),
                    ("output_tokens", 0, "max_output_tokens_per_call"),
                ):
                    count = items["output"][key]
                    if (
                        type(count) is not int
                        or not minimum <= count <= protocol["budget"][cap]
                    ):
                        issues.append("call token budget differs: " + str(call))
            same(
                read(expected_call / "STEP.json"),
                node,
                "graph STEP differs: " + str(expected_call),
            )
            same(
                read(call / "POOL_RESULT.json"),
                items["output"],
                "pool output differs: " + str(call),
            )
            same(
                read(call / "POOL_REQUEST.json"),
                items["request"],
                "pool request differs: " + str(call),
            )
            intent, raw_output = (
                read(call / "POOL_INTENT.json"),
                read(call / "POOL_RAW_OUTPUT.json"),
            )
            if intent and items["output"] and pool:
                if digest(intent) in call_intents:
                    issues.append("reused pool intent: " + str(call))
                    observed_cost_integrity = False
                call_intents.add(digest(intent))
                same(
                    intent["request_digest"],
                    node["request_digest"],
                    "pool request binding differs",
                )
                same(
                    intent["pool_identity"],
                    pool["pool_identity"],
                    "pool identity differs",
                )
                same(
                    intent["pool_identity"],
                    items["output"]["pool_identity"],
                    "call pool differs",
                )
                same(intent["cell_id"], node["cell_id"], "active Cell intent differs")
                same(
                    intent["model_digest"],
                    items["output"]["loaded_model_digest"],
                    "loaded model differs",
                )
                same(
                    items["output"]["loaded_model_digest"],
                    protocol["models"].get(node["cell_id"], {}).get("manifest_digest"),
                    "call frozen model differs",
                )
            if raw_output and items["output"]:
                for key, item in raw_output.items():
                    same(
                        item,
                        items["output"].get(key),
                        "raw provider field differs: " + key,
                    )
        observed = {
            "model_calls": len(nodes),
            "verifier_calls": len(nodes),
            "business_executions": sum(
                node["business"]["verifier_executed"] for node in nodes
            ),
            "format_rejections": sum(
                node["business"]["format_admitted"] is False for node in nodes
            ),
            "input_tokens": sum(
                item["input_tokens"] for item in outputs if item is not None
            ),
            "output_tokens": sum(
                item["output_tokens"] for item in outputs if item is not None
            ),
        }
        reported_cost = {key: value["cost"][key] for key in costs}
        if observed != reported_cost:
            observed_cost_integrity = False
        same(
            observed,
            reported_cost,
            "graph counts differ: " + str(path),
        )
        first = nodes[0]["business"]["business_success"] if nodes else None
        last = nodes[-1]["business"]["business_success"] if nodes else None
        selected = next(
            (node for node in nodes if node["business"]["business_success"] is True),
            nodes[-1] if nodes else None,
        )
        selected_success = (
            selected["business"]["business_success"] if selected else False
        )
        for key, expected in (
            ("output_selection", protocol["output_selection"]),
            ("success", selected_success),
            ("first_success", first if nodes else False),
            ("final_slot", selected["slot"] if selected else None),
            ("last_executed_slot", nodes[-1]["slot"] if nodes else None),
            (
                "final_answer_sha256",
                hashlib.sha256(selected["output"]["answer"].encode()).hexdigest()
                if selected
                else None,
            ),
        ):
            same(value.get(key), expected, "graph " + key + " differs: " + str(path))
        paired = len(nodes) == 2 and type(first) is bool and type(last) is bool
        parts = path.relative_to(circuit).parts
        group = (
            "search/" + parts[2]
            if parts[0] == "search"
            else "/".join((parts[0], parts[1], parts[3]))
        )
        row = {
            "task_id": value["task_id"],
            "result_path": path.relative_to(root).as_posix(),
            "result_digest": digest(value),
            "selected_success": selected_success,
            "first_success": first,
            "last_success": last,
            "two_steps": len(nodes) == 2,
            "recovery_0_to_1": first is False and last is True if paired else None,
            "regression_1_to_0": first is True and last is False if paired else None,
            "intervention": value["intervention"],
            "cost": value["cost"],
        }
        groups[group].append(row)
        all_rows.append(row)
    same(
        graph_paths,
        set(expected_results),
        "graph inventory differs from completed summaries",
    )
    totals = {key: sum(row["cost"][key] for row in all_rows) for key in costs}
    coverage = {}
    for name in (
        "POOL_INTENT.json",
        "POOL_REQUEST.json",
        "POOL_RAW_OUTPUT.json",
        "POOL_RESULT.json",
        "REQUEST.json",
        "OUTPUT.json",
        "VERIFICATION.json",
        "STEP.json",
    ):
        paths = list(circuit.rglob(name))
        coverage[name] = len(paths)
        actual_calls = {path.parent.resolve() for path in paths}
        same(actual_calls, call_paths, "call artifact coverage differs: " + name)
        same(len(paths), len(actual_calls), "call artifact aliases differ: " + name)
    additional_routes = [
        row
        for name, plan in plans.items()
        if name.startswith("additional/") and plan
        for row in plan["selections"]
    ]
    route_costs = [row["route_validation_cost"] for row in additional_routes]
    noops = {
        row["task_id"]: row["identity_replacement_noop"] for row in additional_routes
    }
    summaries = {}
    for group, rows in groups.items():
        panel = "old_A" if group.startswith("search/") else group.split("/")[1]
        task_ids = [row["task_id"] for row in rows]
        same(len(task_ids), len(set(task_ids)), "duplicate group task: " + group)
        same(
            set(task_ids),
            {row["task_id"] for row in protocol["panels"][panel]},
            "group task coverage differs: " + group,
        )
        summaries[group] = {
            "tasks": len(rows),
            **{
                key: sum(row[key] is True for row in rows)
                for key in (
                    "selected_success",
                    "first_success",
                    "last_success",
                    "two_steps",
                    "recovery_0_to_1",
                    "regression_1_to_0",
                )
            },
            "unknown_selected_success": sum(
                row["selected_success"] is None for row in rows
            ),
            "missing_first_or_last": sum(
                row["first_success"] is None or row["last_success"] is None
                for row in rows
            ),
            "effective_interventions": sum(
                row["intervention"]["effective_on_graph"] is True for row in rows
            )
            if "/cell-" in group or "/edge-" in group
            else None,
            "ineffective_interventions": sum(
                row["intervention"]["effective_on_graph"] is False for row in rows
            )
            if "/cell-" in group or "/edge-" in group
            else None,
            "identity_replacement_noops": sum(
                noops.get(row["task_id"]) is True for row in rows
            )
            if group.endswith("/replace_non_F")
            else None,
            "identity_replacement_noop_unknown": sum(
                noops.get(row["task_id"]) is None for row in rows
            )
            if group.endswith("/replace_non_F")
            else None,
            "cost": {key: sum(row["cost"][key] for row in rows) for key in costs},
        }
    paired_controls = {}
    for panel in ("old_A", "old_B"):
        learned = {
            row["task_id"]: row
            for row in groups.get("original/" + panel + "/learned_sparse", [])
        }
        for source, arm in (
            ("original", "single"),
            ("original", "fixed"),
            ("additional", "single_T"),
            ("additional", "single_C"),
            ("additional", "task_random"),
            ("additional", "best_static"),
            ("additional", "replace_non_F"),
        ):
            name = source + "/" + panel + "/" + arm
            paired_controls[name] = [
                {
                    "task_id": row["task_id"],
                    "learned_minus_control_selected_success": int(
                        learned[row["task_id"]]["selected_success"]
                    )
                    - int(row["selected_success"])
                    if type(learned[row["task_id"]]["selected_success"]) is bool
                    and type(row["selected_success"]) is bool
                    else None,
                }
                for row in groups.get(name, [])
                if row["task_id"] in learned
            ]
    failures = [
        {"path": str(path.relative_to(root)), "receipt": read(path)}
        for path in sorted(root.rglob("*FAILED.json"))
    ]
    full = bool(
        job
        and complete
        and job.get("status") == "COMPLETE"
        and not issues
        and not failures
    )
    if full:
        same(
            len(graph_paths),
            protocol["planned_counts_only"]["graph_results"],
            "graph count differs from plan",
        )
        same(
            totals["model_calls"],
            protocol["planned_counts_only"]["total_model_calls"],
            "call count differs from plan",
        )
        same(
            totals["verifier_calls"],
            totals["model_calls"],
            "verifier opportunities differ",
        )
        for count in coverage.values():
            same(count, totals["model_calls"], "shared-pool call coverage differs")
        full = not issues
    result = {
        "schema": "hepta.extended-e4-readout.v2",
        "status": "COMPLETE" if full else "INCOMPLETE",
        "protocol_sha256": args.protocol_sha,
        "actual_pool_binding": pool_binding,
        "pre_execution_cost_history": protocol.get("prior_cost_history"),
        "pre_execution_history_scope": "Protocol-bound earlier failure and diagnostic costs; separate from this run graph totals",
        "issues": issues,
        "failures": failures,
        "planned_counts_only": protocol["planned_counts_only"],
        "completed_graph_records": len(graph_paths),
        "pool_call_receipt_coverage": coverage,
        "observed_completed_graph_cost_integrity": observed_cost_integrity,
        "observed_completed_graph_cost_lower_bound": totals
        if observed_cost_integrity
        else {key: None for key in costs},
        "complete_call_and_token_totals": totals
        if full
        else {key: None for key in costs},
        "summaries": summaries,
        "rows": dict(groups),
        "paired_controls": paired_controls,
        "static_selection": static,
        "nested_cost_scopes_do_not_add": {
            "pool_initialization": pool["initialization_cost"] if pool else None,
            "search_total_wall_seconds": search.get("total_wall_seconds")
            if search
            else None,
            "router_fit_wall_seconds": search.get("router_fit_wall_seconds")
            if search
            else None,
            "extra_route_validation_wall_seconds": sum(
                row["wall_seconds"] for row in route_costs
            )
            if all(
                plans[name] is not None
                for name in ("additional/old_A", "additional/old_B")
            )
            else None,
            "observed_graph_wall_seconds_sum": sum(
                row["cost"]["wall_seconds"] for row in all_rows
            ),
            "observed_provider_seconds_sum": sum(
                row["cost"]["provider_seconds_sum"] for row in all_rows
            ),
            "observed_verifier_wall_seconds_sum": sum(
                row["cost"]["verifier_wall_seconds_sum"] for row in all_rows
            ),
            "worker_after_admission_wall_seconds": complete.get("worker_wall_seconds")
            if complete
            else None,
        },
        "actual_cost_matching_claim": False,
        "full_system_cost_known": False,
        "monetary_cost": None,
        "energy_joules": None,
        "gpu_active_seconds": None,
        "independent_sample_increment": 0,
        "scientific_qualification": False,
        "original_file_inventory": inventory,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(
            result,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "issues",
                    "completed_graph_records",
                    "complete_call_and_token_totals",
                )
            }
        )
    )


if __name__ == "__main__":
    main()

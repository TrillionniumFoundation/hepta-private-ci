"""Frozen, four-domain evaluation of actual routing and reused numeric graphs."""

import os
from pathlib import Path
import subprocess
import sys
import time

from .contracts import canonical, file_identity, normalized_request, sha256, write_json
from .graph_assets import Assets, DOMAINS
from .graph_runtime import GraphRuntime
from .joint_cases import GATES, PROJECT, SEEDS, load_held, make_cases, verify_freeze
from .joint_grading import grade_domain
from .joint_io import read_document, write_document
from .joint_selection import selected_identity as selected_identity
from .joint_selection import verify_selected_models


def fresh_process(folder, request, label):
    folder = Path(folder)
    request_file, output_file = (
        folder / (label + "-request.json"),
        folder / (label + "-output.json"),
    )
    write_json(request_file, request)
    command = [
        sys.executable,
        str(PROJECT / "graph_reader.py"),
        "--request",
        str(request_file),
        "--output",
        str(output_file),
    ]
    environment = {
        **os.environ,
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    started = time.perf_counter()
    process = subprocess.run(
        command, cwd=PROJECT, env=environment, capture_output=True, text=True
    )
    receipt = {
        "schema": "hepta.memory.v5.fresh-process.v1",
        "command": command,
        "exit_code": process.returncode,
        "wall_seconds": time.perf_counter() - started,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "request": file_identity(request_file),
        "request_file": request_file.name,
        "output_file": output_file.name if output_file.is_file() else None,
        "output_envelope": file_identity(output_file)
        if output_file.is_file()
        else None,
        "operating_system_filesystem_isolation_claimed": False,
    }
    write_json(folder / (label + "-process.json"), receipt)
    if process.returncode:
        raise RuntimeError(
            f"actual {label} reader failed; receipt retained at {folder}"
        )
    output = read_document(output_file)
    if (
        output["request_sha256"] != sha256(canonical(request))
        or output["smoke_only"] != request["smoke_only"]
    ):
        raise ValueError("fresh process output does not bind exact request")
    for index, (query, actual) in enumerate(
        zip(request["requests"], output["rows"], strict=True)
    ):
        if actual["index"] != index or actual["request_sha256"] != sha256(
            canonical(query)
        ):
            raise ValueError("fresh process output query order differs")
    return output, receipt


def oracle_control(assets_directory, requests, graders, domain, seed):
    parameter = GraphRuntime(assets_directory, domain, seed, mode="parameter")
    strong = GraphRuntime(assets_directory, domain, seed, mode="strong")
    rows = []
    for index, (request, grader) in enumerate(zip(requests, graders, strict=True)):
        intent = grader["gold_intent"]
        rows.append(
            {
                "index": index,
                "oracle_intent_supplied_by_grader": intent,
                "parameter_oracle": parameter.execute(
                    request, intent, "parameter_connected"
                ),
                "strong_oracle": strong.execute(request, intent, "strong_planner"),
            }
        )
    return {
        "schema": "hepta.memory.v5.oracle-control.v1",
        "not_actual_semantic_routing": True,
        "rows": rows,
        "parameter_state": parameter.receipt(),
        "strong_state": strong.receipt(),
    }


def evaluate_domain(
    templates,
    assets_directory,
    router,
    seed,
    domain,
    folder,
    freeze_path,
    freeze_identity,
):
    folder.mkdir(parents=True, exist_ok=False)
    requests, graders, source = make_cases(templates, assets_directory, domain, seed)
    write_document(folder / "grader.json", {"source": source, "rows": graders})
    common = {
        "schema": "hepta.memory.v5.graph-read-request.v1",
        "domain": domain,
        "seed": seed,
        "requests": requests,
        "router_directory": router["directory"],
        "router_manifest_sha256": router["files"]["manifest.json"]["sha256"],
        "assets_directory": str(Path(assets_directory).resolve()),
        "assets_binding_sha256": file_identity(Path(assets_directory) / "ASSETS.json")[
            "sha256"
        ],
        "freeze_file": str(Path(freeze_path).resolve()),
        "freeze_sha256": freeze_identity["sha256"],
        "smoke_only": False,
    }
    parameter, p_receipt = fresh_process(
        folder, {**common, "mode": "parameter"}, "parameter"
    )
    strong, s_receipt = fresh_process(folder, {**common, "mode": "strong"}, "strong")
    oracle = oracle_control(assets_directory, requests, graders, domain, seed)
    write_document(folder / "oracle-control.json", oracle)
    scores = grade_domain(graders, parameter["rows"], strong["rows"], oracle["rows"])
    if (
        scores["routing"]["known_queries"] != 144
        or scores["routing"]["ood_queries"] != 72
        or scores["arms"]["parameter_connected"]["composed_queries"] != 120
    ):
        raise ValueError("formal metric denominators differ")
    write_document(folder / "row-grades.json", scores.pop("rows"))
    normalized = [normalized_request(request) for request in requests]
    result = {
        "schema": "hepta.memory.v5.domain-evaluation.v1",
        "seed": seed,
        "domain": domain,
        "independent_language_templates": len(templates),
        "slot_instantiations_are_not_new_templates": True,
        "source": source,
        **scores,
        "parameter_process": p_receipt,
        "strong_process": s_receipt,
        "actual_parameter_state": parameter["state"],
        "strong_state": strong["state"],
        "pure_deployment_files": parameter["serving_file_identities"],
        "strong_deployment_files": strong["serving_file_identities"],
        "parameter_python_read_opens": parameter["observed_python_read_opens"],
        "strong_python_read_opens": strong["observed_python_read_opens"],
        "normalized_requests_sha256": sha256(canonical(normalized)),
        "route_decisions_sha256": sha256(
            canonical([row["decision"] for row in parameter["rows"]])
        ),
        "oracle_controls_supply_gold_intents": True,
        "new_numeric_or_graph_training": False,
        "historical_v4_run_reproduced": False,
        "operating_system_filesystem_isolation_claimed": False,
    }
    write_json(folder / "summary.json", result)
    return result


def merged_files(results, key):
    merged = {}
    for row in results:
        for path, identity in row[key].items():
            if path in merged and merged[path] != identity:
                raise ValueError("shared deployment state changed between domains")
            merged[path] = identity
    return merged


def access_held(held_path, frozen, output):
    write_json(
        Path(output) / "held-access-attempt.json",
        {
            "schema": "hepta.memory.v5.held-access-attempt.v1",
            "held_access_attempted": True,
            "requested_path": str(Path(held_path).absolute()),
            "expected_seal_sha256": frozen["held_seal_sha256"],
            "written_before_loading_any_held_file": True,
            "held_parse_completed_at_this_record": False,
        },
    )
    return load_held(held_path, frozen)


def evaluate_joint(
    router_directories, assets_directory, held_path, output, freeze_file
):
    frozen, freeze_identity = verify_freeze(freeze_file)
    selected, selected_seal = verify_selected_models(
        router_directories, frozen, freeze_identity
    )
    assets = Assets(
        assets_directory, expected_binding_sha256=frozen["assets_binding_sha256"]
    )
    for domain in DOMAINS:
        assets.parameter(domain)
        assets.exact(domain)
    assets.layout()
    frozen_assets = assets.verify_consumed()
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(
        root / "evaluation-inputs.json",
        {
            "schema": "hepta.memory.v5.evaluation-inputs.v1",
            "freeze": freeze_identity,
            "source_commit": frozen["source_commit"],
            "selected_router_states": selected,
            "selected_models_seal": selected_seal,
            "assets_binding_sha256": assets.binding_sha256,
            "assets_used": frozen_assets,
            "held_text_not_opened_before_this_record": True,
        },
    )
    opened_held = False
    parsed_held = False
    try:
        opened_held = True
        templates, held_identity = access_held(held_path, frozen, root)
        parsed_held = True
        write_json(root / "held-identity.json", held_identity)
        results = []
        for seed in SEEDS:
            domains = [
                evaluate_domain(
                    templates,
                    assets_directory,
                    selected[seed],
                    seed,
                    domain,
                    root / f"seed-{seed}" / domain,
                    freeze_file,
                    freeze_identity,
                )
                for domain in DOMAINS
            ]
            if (
                len({row["normalized_requests_sha256"] for row in domains}) != 1
                or len({row["route_decisions_sha256"] for row in domains}) != 1
            ):
                raise ValueError(
                    "series/date normalization introduced domain-dependent route decisions"
                )
            pure_files = merged_files(domains, "pure_deployment_files")
            strong_files = merged_files(domains, "strong_deployment_files")
            result = {
                "seed": seed,
                "domains": domains,
                "all_preregistered_gates_pass": all(
                    row["all_preregistered_gates_pass"] for row in domains
                ),
                "identical_normalized_language_and_routes_across_domains": True,
                "pure_four_domain_deployment_bytes": sum(
                    info["bytes"] for info in pure_files.values()
                ),
                "strong_four_domain_deployment_bytes": sum(
                    info["bytes"] for info in strong_files.values()
                ),
                "pure_four_domain_deployment_files": pure_files,
                "strong_four_domain_deployment_files": strong_files,
            }
            write_json(root / f"seed-{seed}" / "summary.json", result)
            results.append(result)
        if (
            verify_selected_models(router_directories, frozen, freeze_identity)
            != (selected, selected_seal)
            or assets.verify_consumed() != frozen_assets
        ):
            raise ValueError("formal inference changed frozen model states")
        verify_freeze(freeze_file)
        flat = [row for result in results for row in result["domains"]]
        summary = {
            "schema": "hepta.memory.v5.joint-evaluation.v1",
            "source_commit": frozen["source_commit"],
            "freeze": freeze_identity,
            "selected_models_seal": selected_seal,
            "held": held_identity,
            "seeds": list(SEEDS),
            "domains": list(DOMAINS),
            "results": results,
            "gates": GATES,
            "semantic_cases_pass": sum(row["checks"]["semantic"] for row in flat),
            "parameter_oracle_cases_pass": sum(
                row["checks"]["parameter_oracle_exact"] for row in flat
            ),
            "composed_cases_pass": sum(
                row["checks"]["composed_actual_ablation_gain"] for row in flat
            ),
            "cases": len(flat),
            "all_preregistered_gates_pass": all(
                row["all_preregistered_gates_pass"] for row in flat
            ),
            "actual_route_requests": len(SEEDS) * len(DOMAINS) * len(templates),
            "additional_strong_control_route_requests": len(SEEDS)
            * len(DOMAINS)
            * len(templates),
            "independent_authored_language_templates": len(templates),
            "wall_seconds": time.perf_counter() - started,
            "source_and_weights_reused_from_partial_recovery": True,
            "retail_evaluated": False,
            "graph_and_numeric_training_steps_in_v5": 0,
            "all_blockers_closed_claimed": False,
        }
        write_document(root / "summary.json", summary)
        write_json(
            root / "execution-status.json",
            {
                "execution": "completed",
                "held_opened": True,
                "held_access_attempted": True,
                "held_parse_completed": True,
                "training_performed_by_evaluator": False,
            },
        )
        return summary
    except BaseException as error:
        write_json(
            root / "execution-status.json",
            {
                "execution": "failed",
                "held_opened": opened_held,
                "held_access_attempted": opened_held,
                "held_parse_completed": parsed_held,
                "held_opened_is_conservative_on_failure": True,
                "error_type": type(error).__name__,
                "error": str(error),
                "evidence_retained": True,
            },
        )
        raise

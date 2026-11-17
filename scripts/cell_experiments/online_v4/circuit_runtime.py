"""Execute fresh Cell calls and business tests, including causal message removal."""

import copy
import hashlib
import json
from pathlib import Path
import time

try:
    import resource
except ImportError:
    resource = None

from ..circuit_receipts_v3 import business_evidence
from .circuit_contract import (EDGES, OUTPUT_SELECTION, canonical, contract_record, digest,
                               measured_output, require, validate,
                               visible_request, write_new)
from .onpolicy_feedback import feedback


def _children_cpu():
    if resource is None:
        return None
    used = resource.getrusage(resource.RUSAGE_CHILDREN)
    return used.ru_utime + used.ru_stime


def _business(record, answer, verification):
    require(verification.get("record_id") == record["record_id"] and
            verification.get("input_sha256") == hashlib.sha256(
                record["task"]["input"].encode()).hexdigest() and
            verification.get("parameters_sha256") == digest(record["task"]["verifier"]["parameters"]),
            "business verification task identity differs")
    return business_evidence({"semantic_receipt": verification,
        "semantic_receipt_sha256": verification.get("receipt_sha256"),
        "raw_answer": answer, "success": verification.get("success")})


def run_graph(record, graph, cells, budget, generate, verify, output_dir, *,
              drop_edge=None, drop_cell=None, feedback_fn=None):
    """Pay for both live slots; retain earliest business success, else last output.

    generate(cell_id, whitelisted_request, call_dir) returns actual model output.
    verify(original_record, answer) is the existing fresh repository verifier.
    Only a source-pinned, reviewed stable feedback function may be substituted.
    """
    validate(cells, graph, budget)
    require(drop_edge is None or drop_edge in EDGES, "invalid edge intervention")
    require(drop_cell is None or drop_cell in cells, "invalid Cell intervention")
    require(feedback_fn is None or feedback_fn is feedback,
            "only the bound stable feedback implementation is supported")
    require(record["task"]["verifier"]["name"] == "repo_patch" and
            record["task"]["verifier"]["version"] == "1",
            "this profile requires the resettable repository-contract verifier")
    initial = visible_request(record)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    contract = contract_record(cells, graph, budget)
    write_new(directory / "CONTRACT.json", contract)
    start, cpu, children = time.perf_counter(), time.process_time(), _children_cpu()
    nodes, dispatched, verified = [], 0, 0
    feedback_fn = feedback if feedback_fn is None else feedback_fn
    try:
        for slot, cell_id in enumerate(graph.path):
            if cell_id == drop_cell:
                nodes.append({"slot": slot, "cell_id": cell_id, "status": "REMOVED",
                              "model_calls": 0, "verifier_calls": 0})
                continue
            request = copy.deepcopy(initial)
            incoming = {}
            previous = next((node for node in reversed(nodes)
                             if node["status"] == "COMPLETE"), None)
            if slot == 1 and previous is not None:
                if "answer" in graph.edges and drop_edge != "answer":
                    incoming["answer"] = previous["output"]["answer"]
                if "feedback" in graph.edges and drop_edge != "feedback":
                    incoming["feedback"] = json.loads(feedback_fn(previous["verification"]))
            if incoming:
                content = canonical({"schema": "hepta.circuit-message.v4", **incoming}).decode()
                require(len(content.encode()) <= budget.max_relay_bytes,
                        "message exceeds frozen relay bound; no truncation")
                request["task"]["messages"].append({"role": "tool", "content": content})
            call_dir = directory / ("node-" + str(slot))
            call_dir.mkdir(exist_ok=False)
            write_new(call_dir / "REQUEST.json", request)
            dispatched += 1
            tick = time.perf_counter()
            output = generate(cell_id, copy.deepcopy(request), call_dir)
            dispatch_seconds = time.perf_counter() - tick
            write_new(call_dir / "OUTPUT.json", output)
            measured = measured_output(output, cells[cell_id], budget)
            if "messages_sha256" in output:
                require(output["messages_sha256"] == digest(request["task"]["messages"]),
                        "provider consumed different messages")
            if "input_sha256" in output:
                require(output["input_sha256"] == hashlib.sha256(
                    request["task"]["input"].encode()).hexdigest(), "provider input differs")
            verified += 1
            tick = time.perf_counter()
            verification = verify(record, output["answer"])
            verifier_seconds = time.perf_counter() - tick
            write_new(call_dir / "VERIFICATION.json", verification)
            business = _business(record, output["answer"], verification)
            node = {"slot": slot, "cell_id": cell_id, "status": "COMPLETE",
                    "request_digest": digest(request), "output_digest": digest(output),
                    "verification_digest": digest(verification),
                    "request_path": str(call_dir / "REQUEST.json"),
                    "output_path": str(call_dir / "OUTPUT.json"),
                    "verification_path": str(call_dir / "VERIFICATION.json"),
                    "incoming_edges": sorted(incoming), "output": output,
                    "verification": verification, "business": business,
                    "cost": {**measured, "dispatch_wall_seconds": dispatch_seconds,
                             "verifier_wall_seconds": verifier_seconds}}
            write_new(call_dir / "STEP.json", node)
            nodes.append(node)
    except BaseException as error:
        failure = {"schema": "hepta.online-message-circuit.failure.v4",
                   "status": "FAILED", "contract_digest": digest(contract),
                   "record_digest": digest(record), "nodes": nodes,
                   "model_calls_dispatched": dispatched, "verifier_calls_dispatched": verified,
                   "error_type": type(error).__name__, "error": str(error),
                   "cost_complete": False, "automatic_retry": False,
                   "wall_seconds": time.perf_counter() - start}
        write_new(directory / "FAILED.json", failure)
        raise
    complete = [node for node in nodes if node["status"] == "COMPLETE"]
    final = next((node for node in complete if node["business"]["business_success"] is True),
                 complete[-1] if complete else None)
    parameter_counts = [node["cost"]["reported_active_parameters"] for node in complete]
    declared = [node["cost"]["declared_active_parameters"] for node in complete]
    child_after = _children_cpu()
    result = {"schema": "hepta.online-message-circuit.result.v4", "status": "COMPLETE",
              "record_id": record["record_id"], "task_id": record["task_id"],
              "record_digest": digest(record), "contract_digest": digest(contract),
              "graph_id": graph.graph_id, "nodes": nodes,
              "intervention": {"edge": drop_edge, "cell": drop_cell,
                  "effective_on_graph": (drop_edge in graph.edges if drop_edge is not None
                                         else drop_cell in graph.path if drop_cell is not None
                                         else False)},
              "final_slot": final["slot"] if final else None,
              "last_executed_slot": complete[-1]["slot"] if complete else None,
              "output_selection": OUTPUT_SELECTION,
              "success": final["business"]["business_success"] if final else False,
              "first_success": complete[0]["business"]["business_success"] if complete else False,
              "final_answer_sha256": hashlib.sha256(final["output"]["answer"].encode()).hexdigest()
                                     if final else None,
              "cost": {"model_calls": dispatched, "verifier_calls": verified,
                  "business_executions": sum(node["business"]["verifier_executed"] for node in complete),
                  "format_rejections": sum(node["business"]["format_admitted"] is False for node in complete),
                  "input_tokens": sum(node["cost"]["input_tokens"] for node in complete),
                  "output_tokens": sum(node["cost"]["output_tokens"] for node in complete),
                  "provider_seconds_sum": sum(node["cost"]["provider_seconds"] for node in complete),
                  "dispatch_wall_seconds_sum": sum(node["cost"]["dispatch_wall_seconds"] for node in complete),
                  "verifier_wall_seconds_sum": sum(node["cost"]["verifier_wall_seconds"] for node in complete),
                  "active_parameter_calls_reported": sum(parameter_counts)
                      if all(value is not None for value in parameter_counts) else None,
                  "active_parameter_calls_declared": sum(declared)
                      if all(value is not None for value in declared) else None,
                  "unused_model_call_opportunities": budget.model_calls - dispatched,
                  "wall_seconds": time.perf_counter() - start,
                  "parent_cpu_seconds": time.process_time() - cpu,
                  "process_children_cpu_seconds": child_after - children
                      if child_after is not None and children is not None else None,
                  "call_and_token_count_complete": True, "full_system_cost_known": False,
                  "scope": "wall includes callbacks and persistence; nested scope timings are not additive; child rusage includes any concurrent process children"},
              "matched_budget_cap_only": True, "matched_actual_cost_claim": False,
              "native_cell_or_HIA_execution": False, "scientific_qualification": False,
              "independent_sample_increment": 0}
    write_new(directory / "RESULT.json", result)
    return result

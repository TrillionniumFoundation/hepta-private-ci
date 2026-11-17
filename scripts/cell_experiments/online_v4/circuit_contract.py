"""Bounded, same-bundle two-Cell message graphs and experiment contracts."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re

EDGES = ("answer", "feedback")
OUTPUT_SELECTION = "earliest_business_success_else_last_surviving"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class CellSpec:
    cell_id: str
    model_digest: str
    base_model_digest: str
    bundle_digest: str
    protocol_digest: str
    active_parameters: int | None = None
    parameter_evidence_digest: str | None = None


@dataclass(frozen=True)
class Graph:
    graph_id: str
    path: tuple[str, str]
    edges: tuple[str, ...] = EDGES


@dataclass(frozen=True)
class Budget:
    model_calls: int = 2
    max_input_tokens_per_call: int = 4096
    max_output_tokens_per_call: int = 256
    max_relay_bytes: int = 8192


def validate(cells, graph, budget):
    require(isinstance(graph, Graph) and isinstance(budget, Budget), "typed graph/budget required")
    require(isinstance(cells, dict) and 1 <= len(cells) <= 16, "bounded Cell registry required")
    for key, cell in cells.items():
        require(isinstance(cell, CellSpec) and key == cell.cell_id, "Cell registry identity differs")
        require(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key), "invalid Cell ID")
        require(all(is_sha(getattr(cell, field)) for field in
                    ("model_digest", "base_model_digest", "bundle_digest", "protocol_digest")),
                "complete Cell version identities required")
        require(cell.active_parameters is None or
                type(cell.active_parameters) is int and cell.active_parameters > 0,
                "invalid active parameter count")
        require((cell.active_parameters is None and cell.parameter_evidence_digest is None) or
                cell.active_parameters is not None and is_sha(cell.parameter_evidence_digest),
                "parameter count needs bound source evidence")
    for field in ("base_model_digest", "bundle_digest", "protocol_digest"):
        require(len({getattr(cell, field) for cell in cells.values()}) == 1,
                "incompatible Cell " + field)
    require(isinstance(graph.graph_id, str) and
            re.fullmatch(r"[A-Za-z0-9_-]{1,96}", graph.graph_id), "invalid graph identifier")
    require(type(graph.path) is tuple and len(graph.path) == 2 and
            all(cell in cells for cell in graph.path), "two declared Cell slots required")
    require(type(graph.edges) is tuple and len(set(graph.edges)) == len(graph.edges) and
            all(edge in EDGES for edge in graph.edges), "invalid or duplicate message edge")
    require(budget.model_calls == 2 and type(budget.model_calls) is int,
            "this profile fixes two model-call opportunities")
    for key, high in (("max_input_tokens_per_call", 16384),
                      ("max_output_tokens_per_call", 1024), ("max_relay_bytes", 8192)):
        value = getattr(budget, key)
        require(type(value) is int and 1 <= value <= high, "invalid budget: " + key)


def visible_request(record):
    """Never pass targets, verifier parameters or trajectories to the provider."""
    task = record["task"]
    prompt = task["input"]
    require(isinstance(prompt, str) and 0 < len(prompt.encode()) <= 65536,
            "bounded original task input required")
    messages = task.get("messages", [{"role": "user", "content": prompt}])
    require(isinstance(messages, list) and 1 <= len(messages) <= 128,
            "bounded initial messages required")
    for message in messages:
        require(isinstance(message, dict) and set(message) == {"role", "content"} and
                message["role"] in ("user", "assistant", "tool") and
                isinstance(message["content"], str) and
                len(message["content"].encode()) <= 65536, "invalid initial message")
    require(messages[0] == {"role": "user", "content": prompt} and
            messages[-1]["role"] != "assistant", "original prompt/history differs")
    return {"record_id": record["record_id"], "task": {"input": prompt,
            "messages": [dict(message) for message in messages]}}


def measured_output(output, cell, budget):
    require(isinstance(output, dict) and output.get("loaded_model_digest") == cell.model_digest,
            "loaded model differs from frozen Cell")
    require(isinstance(output.get("answer"), str) and len(output["answer"].encode()) <= 65536,
            "bounded generated answer required")
    for key, high, low in (("input_tokens", budget.max_input_tokens_per_call, 1),
                           ("output_tokens", budget.max_output_tokens_per_call, 0)):
        require(type(output.get(key)) is int and low <= output[key] <= high,
                "actual token count violates budget: " + key)
    elapsed = output.get("wall_seconds", output.get("elapsed_seconds"))
    require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
            "measured provider elapsed time required")
    parameters = output.get("active_parameters")
    if parameters is not None:
        require(type(parameters) is int and parameters > 0 and
                parameters == cell.active_parameters and
                output.get("parameter_evidence_digest") == cell.parameter_evidence_digest,
                "reported active parameters differ from their binding")
    return {"input_tokens": output["input_tokens"], "output_tokens": output["output_tokens"],
            "provider_seconds": elapsed, "reported_active_parameters": parameters,
            "declared_active_parameters": cell.active_parameters}


def contract_record(cells, graph, budget):
    return {"schema": "hepta.online-message-circuit.contract.v4",
            "cells": {key: asdict(cell) for key, cell in sorted(cells.items())},
            "graph": asdict(graph), "budget": asdict(budget),
            "state": "stateless native-chat calls; original task is shared input",
            "edge_definition": {"answer": "first generated answer to second Cell",
                                "feedback": "first actual verification feedback to second Cell"},
            "cell_removal": "skip every occurrence; never replace the removed Cell",
            "output_selection": OUTPUT_SELECTION,
            "selection_evidence": "current paid business verifications only; no surviving output fails",
            "context_review_required": budget.max_relay_bytes > 1000,
            "no_full_system_cost_or_native_adoption_claim": True}

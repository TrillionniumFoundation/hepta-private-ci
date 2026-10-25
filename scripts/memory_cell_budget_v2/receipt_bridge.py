"""Pinned process/controller observations with explicit nonoverlapping coverage."""

from common import METERS, file_identity, observations, read_json
from scripts.memory_cell_cost_v2.receipt_reader import read_receipt


def collect(plan):
    if set(plan) != {"rows", "wall_owner"}:
        raise ValueError("explicit receipt coverage plan required")
    rows = []
    for entry in plan["rows"]:
        if set(entry) != {"kind", "path", "identity", "id", "related"}:
            raise ValueError("unregistered receipt input")
        if entry["kind"] == "warm-controller-v1":
            row = controller_receipt(
                entry["path"],
                entry["identity"],
                attempt_id=entry["id"],
                children=entry["related"],
            )
        else:
            row = process_receipt(
                entry["path"],
                entry["identity"],
                format_name=entry["kind"],
                attempt_id=entry["id"],
                covers=entry["related"],
            )
        rows.append(row)
    return merge(rows, wall_owner=plan["wall_owner"])


def process_receipt(path, expected, *, format_name, attempt_id, covers=()):
    """A wait4 process cost includes its waited descendants, not its caller."""
    source = read_json(path, expected)
    raw = read_receipt(path, format_name=format_name, attempt_id=attempt_id)
    if raw["receipt_sha256"] != expected["sha256"] or file_identity(path) != expected:
        raise ValueError("consumed process receipt changed")
    meters = dict.fromkeys(METERS)
    meters.update(cpu_ns=raw["cpu_ns"], wall_ns=raw["wall_ns"])
    return {
        "id": attempt_id,
        "identity": expected,
        "path": str(path),
        "scope": "waited_tree",
        "covers": list(covers),
        "meters": meters,
        "output_bytes": raw["output_bytes"],
        "process_failed": raw["failed"],
        "infrastructure_status": "timeout"
        if source.get("timeout") or source.get("timed_out")
        else (
            "failed"
            if raw["returncode"] is None
            or raw["returncode"] < 0
            or any(
                source.get(k)
                for k in ("error", "spawn_error", "cleanup_error", "reap_error")
            )
            else "completed"
        ),
    }


def controller_receipt(path, expected, *, attempt_id, children):
    raw = read_json(path, expected)
    if (
        raw.get("schema") != "hepta.memory.warm-controller-cost.v1"
        or raw.get("self_cpu_excludes_child_cpu") is not True
    ):
        raise ValueError("unregistered controller CPU semantics")
    meters = dict.fromkeys(METERS)
    meters.update(cpu_ns=raw["self_cpu_ns"], wall_ns=raw["whole_execute_wall_ns"])
    observations(meters)
    for key in ("charged_child_cpu_ns", "controller_plus_child_cpu_ns"):
        value = raw[key]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("invalid controller child cost")
    if raw["charged_child_cpu_ns"] is not None and (
        raw["controller_plus_child_cpu_ns"]
        != raw["self_cpu_ns"] + raw["charged_child_cpu_ns"]
    ):
        raise ValueError("controller sum differs from declared self/child split")
    return {
        "id": attempt_id,
        "identity": expected,
        "path": str(path),
        "scope": "self",
        "covers": [],
        "meters": meters,
        "output_bytes": None,
        "process_failed": bool(raw["error"]),
        "infrastructure_status": "failed" if raw["error"] else "completed",
        "children": list(children),
        "declared_child_cpu_ns": raw["charged_child_cpu_ns"],
    }


def merge(rows, *, wall_owner):
    """Coverage is a trusted controller declaration, not remote attestation.

    Each row is charged unless explicitly covered by one charged waited-tree
    row. Controller self CPU and its child costs are separate charged rows.
    End-to-end wall comes from one explicit owner, never the nested wall sum.
    """
    if not rows:
        raise ValueError("nonempty receipt set required")
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows) or len({r["identity"]["sha256"] for r in rows}) != len(
        rows
    ):
        raise ValueError("duplicate attempt or raw receipt")
    covered = {}
    for row in rows:
        observations(row["meters"])
        if row["scope"] not in ("self", "waited_tree"):
            raise ValueError("unregistered process coverage")
        if len(row["covers"]) != len(set(row["covers"])):
            raise ValueError("duplicate coverage")
        if row["scope"] == "self" and row["covers"]:
            raise ValueError("self CPU cannot cover a child")
        for child in row["covers"]:
            if child not in by_id or child == row["id"] or child in covered:
                raise ValueError("missing, cyclic or duplicate coverage")
            covered[child] = row["id"]
    if any(parent in covered for parent in covered.values()):
        raise ValueError("coverage must flatten to one charged ancestor")
    charged = [row for row in rows if row["id"] not in covered]
    if wall_owner not in {row["id"] for row in charged}:
        raise ValueError("wall owner must be a charged covering observation")
    for row in rows:
        if "children" not in row:
            continue
        children = row["children"]
        if len(children) != len(set(children)) or any(
            child not in by_id or child == row["id"] for child in children
        ):
            raise ValueError("controller child identity mismatch")
        numbers = [by_id[child]["meters"]["cpu_ns"] for child in children]
        total = sum(numbers) if all(n is not None for n in numbers) else None
        declared = row["declared_child_cpu_ns"]
        # Old float-second receipts can differ by one integer ns per child.
        if (total is None) != (declared is None) or (
            total is not None and abs(total - declared) > len(children)
        ):
            raise ValueError("controller child CPU does not match raw processes")
    measured, subtotals, unknown = {}, {}, {}
    for meter in METERS:
        values = [row["meters"][meter] for row in charged]
        known = [value for value in values if value is not None]
        subtotals[meter] = sum(known)
        unknown[meter] = len(values) - len(known)
        measured[meter] = sum(known) if not unknown[meter] else None
    measured["wall_ns"] = by_id[wall_owner]["meters"]["wall_ns"]
    lower_bounds = dict(subtotals)
    lower_bounds["wall_ns"] = measured["wall_ns"] or 0
    statuses = {row["infrastructure_status"] for row in rows}
    return {
        "schema": "hepta.memory-budget.observations.v2",
        "observation": measured,
        "known_subtotals": subtotals,
        "lower_bounds": lower_bounds,
        "unknown_charged_rows": unknown,
        "charged_ids": [row["id"] for row in charged],
        "attribution_to": covered,
        "wall_owner": wall_owner,
        "attempt_wall_sum_ns": subtotals["wall_ns"],
        "receipts": rows,
        "infrastructure_status": "timeout"
        if "timeout" in statuses
        else ("failed" if "failed" in statuses else "completed"),
        "whole_host_cpu_ns": None,
        "energy_joules": None,
        "billing_usd": None,
        "whole_system_cost_complete": False,
    }

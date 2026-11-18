"""Check source metadata without opening task/oracle payloads or authorizing a run."""

from collections import defaultdict
from datetime import datetime
import re


def audit_source_manifest(records):
    """Conservatively join declared dependencies; valid metadata is not source custody.

    Each row describes a task, its original event and all transformed parents.
    Hashes are commitments only: callers must separately verify retained bytes,
    independent provenance/custody, the experiment freeze and phase access.
    """
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("source manifest must be a list of at most 10000 rows")
    reasons, indexed, links = [], {}, defaultdict(set)

    def block(code, task_ids, detail):
        reasons.append({"code": code, "task_ids": sorted(task_ids), "detail": detail})

    def has_text(value):
        return (
            isinstance(value, str)
            and bool(value)
            and value == value.strip()
            and not any(ord(c) < 32 for c in value)
        )

    def digest(value, size=64):
        return isinstance(value, str) and re.fullmatch(
            r"[0-9a-f]{" + str(size) + r"}", value
        )

    def timestamp(value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else None
        except (ValueError, TypeError, AttributeError):
            return None

    if not records:
        block("EMPTY_SOURCE_MANIFEST", [], "No task sources supplied")
    for number, row in enumerate(records):
        if not isinstance(row, dict) or not has_text(row.get("task_id")):
            block("INVALID_TASK_ROW", [], f"Row {number} requires a task_id")
            continue
        task_id = row["task_id"]
        if task_id in indexed:
            block("DUPLICATE_TASK_ID", [task_id], "Task IDs must be unique")
            continue
        indexed[task_id] = row
        for field in ("origin_repository", "origin_id", "root_cause_group"):
            if not has_text(row.get(field)):
                block("MISSING_ORIGIN_IDENTITY", [task_id], field)
        if not digest(row.get("origin_commit"), 40):
            block("UNPINNED_ORIGIN", [task_id], "origin_commit requires a full Git SHA")
        for field in (
            "task_sha256",
            "oracle_sha256",
            "generator_sha256",
            "source_receipt_sha256",
        ):
            if not digest(row.get(field)):
                block("MISSING_COMMITMENT", [task_id], field)
        for field in ("parent_task_ids", "transformation_provenance"):
            value = row.get(field)
            if not isinstance(value, list) or any(not has_text(item) for item in value):
                block("INVALID_LINEAGE", [task_id], field)
        seed = row.get("generation_seed")
        if type(seed) is not int or seed < 0:
            block(
                "MISSING_GENERATION_SEED",
                [task_id],
                "A frozen nonnegative integer is required",
            )
        dates = [
            timestamp(row.get(key))
            for key in ("origin_time", "available_at", "admission_time")
        ]
        if any(date is None for date in dates) or dates != sorted(dates):
            block(
                "INVALID_SOURCE_CHRONOLOGY",
                [task_id],
                "Require original <= available <= admission, with timezones",
            )
        split = row.get("split")
        if not isinstance(split, str) or split not in {
            "A",
            "B",
            "C",
            "D_cold",
            "retention",
        }:
            block("SOURCE_NOT_ASSIGNED", [task_id], "Research split is not frozen")
        if row.get("origin_kind") != "real_source":
            block(
                "NOT_REAL_SOURCE",
                [task_id],
                "Fixtures, replays and synthesized sources cannot add independent N",
            )
        if (
            isinstance(split, str)
            and split in {"B", "C", "D_cold", "retention"}
            and row.get("exposure") != "sealed"
        ):
            block(
                "HELDOUT_ALREADY_EXPOSED_OR_UNKNOWN",
                [task_id],
                "Evaluation source must have independently reviewed sealed custody",
            )
        authority = row.get("authorization")
        if not isinstance(authority, dict):
            authority = {}
        permission = "training_allowed" if split == "A" else "evaluation_allowed"
        if (
            authority.get(permission) is not True
            or not has_text(authority.get("rights_basis"))
            or not digest(authority.get("receipt_sha256"))
        ):
            block("MISSING_SOURCE_AUTHORITY", [task_id], permission)
        links[("task", task_id)].add(task_id)
        if has_text(row.get("origin_repository")) and has_text(row.get("origin_id")):
            links[
                ("origin", row["origin_repository"].casefold(), row["origin_id"])
            ].add(task_id)
        if has_text(row.get("root_cause_group")):
            links[("root_cause", row["root_cause_group"])].add(task_id)
        if digest(row.get("task_sha256")):
            links[("task_bytes", row["task_sha256"])].add(task_id)
        if has_text(row.get("source_template_id")):
            links[("template", row["source_template_id"])].add(task_id)
        parents = row.get("parent_task_ids")
        if isinstance(parents, list):
            for parent in parents:
                if has_text(parent):
                    links[("task", parent)].add(task_id)

    adjacency = {task_id: set() for task_id in indexed}
    for members in links.values():
        first = min(members)
        for task_id in members:
            adjacency[first].add(task_id)
            adjacency[task_id].add(first)
    for task_id, row in indexed.items():
        parents = row.get("parent_task_ids")
        if isinstance(parents, list):
            for parent in parents:
                if has_text(parent) and (parent not in indexed or parent == task_id):
                    block("UNRESOLVED_PARENT", [task_id], parent)

    colors = {}
    for start in sorted(indexed):
        stack = [(start, False)]
        while stack:
            task_id, leaving = stack.pop()
            if leaving:
                colors[task_id] = 2
                continue
            if colors.get(task_id) == 1:
                block("LINEAGE_CYCLE", [task_id], "Parent graph must be acyclic")
                continue
            if colors.get(task_id) == 2:
                continue
            colors[task_id] = 1
            stack.append((task_id, True))
            parents = indexed[task_id].get("parent_task_ids")
            if isinstance(parents, list):
                stack.extend(
                    (p, False) for p in parents if has_text(p) and p in indexed
                )

    components, visited = [], set()
    for start in sorted(indexed):
        if start in visited:
            continue
        pending, members = [start], set()
        while pending:
            task_id = pending.pop()
            if task_id not in members:
                members.add(task_id)
                pending.extend(adjacency[task_id] - members)
        visited.update(members)
        splits = sorted({str(indexed[t].get("split")) for t in members})
        if len(splits) != 1:
            block("DEPENDENCY_CROSSES_SPLITS", members, ",".join(splits))
        components.append({"task_ids": sorted(members), "declared_splits": splits})
    blocked_ids = {task_id for reason in reasons for task_id in reason["task_ids"]}
    for component in components:
        component["metadata_eligible"] = not bool(
            set(component["task_ids"]) & blocked_ids
        )
    return {
        "schema": "hepta.research-source-audit.v1",
        "status": "BLOCKED" if reasons else "METADATA_VALID",
        "blocking_reasons": reasons,
        "components": components,
        "counts": {
            "metadata_rows": len(records),
            "distinct_task_ids": len(indexed),
            "declared_dependency_components": len(components),
            "metadata_eligible_components": sum(
                c["metadata_eligible"] for c in components
            ),
        },
        "authenticated_independent_source_groups": None,
        "research_execution_authorized": False,
        "execution": None,
        "result": None,
    }

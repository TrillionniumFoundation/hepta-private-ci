"""Bounded context serialization and internal read-receipt consistency.

This contract detects contradictory evidence, not dishonest execution, source
ownership, omitted record content or a rolled-back authority database.
"""

import hashlib
import math
import re

from .episodic_memory import (
    bounded_text,
    canonical_bytes,
    digest,
    integer,
    sha256,
    validate_record,
)


MODES = {"on", "off", "retrieval_off", "delivery_off", "association_off"}

STRATEGIES = {"exact_kv", "bm25", "uniform_replay", "icl"}

RECEIPT_FIELDS = {
    "schema",
    "session_id",
    "mode",
    "strategy",
    "source_ids",
    "query_sha256",
    "limit",
    "max_context_bytes",
    "replay_seed",
    "store_read",
    "retrieval_executed",
    "view_receipt",
    "eligible_count",
    "retrieved_ids",
    "selected_ids",
    "delivered_ids",
    "byte_dropped_ids",
    "context_bytes",
    "association_status",
    "association_id",
    "association_called",
    "association_authentication_established",
    "scientific_acceptance",
    "real_task_benefit_established",
    "context_sha256",
    "decision_cpu_seconds",
    "decision_wall_seconds",
    "provenance",
    "receipt_sha256",
}

VIEW_FIELDS = {
    "authority_id",
    "authority_generation",
    "frontier_sha256",
    "snapshot_sha256",
    "snapshot_rejections",
    "resident_record_count",
    "logical_serialized_bytes",
    "scientific_acceptance",
    "malicious_owner_rollback_protected",
}


def assemble_context(records, max_context_bytes):
    """Admit whole JSON records under a UTF-8 budget; never truncate a fact."""
    integer(max_context_bytes, "context byte bound", 0, 65536)
    lines, delivered, dropped = [], [], []
    used = 0
    for record in records:
        line = canonical_bytes(
            {
                k: record[k]
                for k in (
                    "record_id",
                    "namespace",
                    "source_id",
                    "key",
                    "version",
                    "text",
                    "provenance",
                )
            }
        ).decode()
        addition = len(line.encode()) + bool(lines)
        if used + addition > max_context_bytes:
            dropped.append(record["record_id"])
            continue
        lines.append(line)
        delivered.append(record)
        used += addition
    return "\n".join(lines), delivered, dropped


def hashlib_sha(text):
    # A content digest covers the actual delivered bytes, including the empty case.
    return hashlib.sha256(text.encode()).hexdigest()


def verify_read_receipt(result):
    """Check the v1 intervention/roster contract as well as content digests.

    A recomputed digest cannot make contradictory mode, source, provenance or
    selection claims consistent. This is still not authentication: the reader
    cannot prove retrieval/ranking, omitted-record byte costs, current authority
    or callback execution from a self-contained receipt. Legacy v1 receipts
    without source_dependency_rejections remain readable; that absence does not
    establish that the later source-dependency filter ran.
    """
    try:
        if not isinstance(result, dict) or set(result) != {
            "receipt",
            "records",
            "context",
        }:
            return False
        receipt = result["receipt"]
        if (
            not isinstance(receipt, dict)
            or not RECEIPT_FIELDS <= receipt.keys()
            or receipt.keys() - RECEIPT_FIELDS - {"source_dependency_rejections"}
            or receipt["schema"] != "hepta.mem6.read-receipt.v1"
        ):
            return False
        mode, strategy = receipt["mode"], receipt["strategy"]
        if (
            not isinstance(mode, str)
            or mode not in MODES
            or not isinstance(strategy, str)
            or strategy not in STRATEGIES
        ):
            return False
        bounded_text(receipt["session_id"], "session id")
        sources = receipt["source_ids"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
            return False
        for source in sources:
            bounded_text(source, "source id")
        if len(set(sources)) != len(sources) or sources != sorted(sources):
            return False
        limit = integer(receipt["limit"], "retrieval limit", 1, 128)
        budget = integer(receipt["max_context_bytes"], "context byte bound", 0, 65536)
        integer(receipt["replay_seed"], "replay seed", 0, 2**63 - 1)
        integer(receipt["context_bytes"], "context bytes", 0, budget)
        for field in ("query_sha256", "context_sha256", "receipt_sha256"):
            sha256(receipt[field])
        for field in ("decision_cpu_seconds", "decision_wall_seconds"):
            value = receipt[field]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return False
        if (
            receipt["scientific_acceptance"] != "HOLD"
            or receipt["real_task_benefit_established"] is not False
            or receipt["association_authentication_established"] is not False
        ):
            return False

        store_read = mode != "off"
        retrieved = mode not in {"off", "retrieval_off"}
        if (
            receipt["store_read"] is not store_read
            or receipt["retrieval_executed"] is not retrieved
        ):
            return False
        eligible = integer(receipt["eligible_count"], "eligible count", 0, 4096)
        rejected = integer(
            receipt.get("source_dependency_rejections", 0),
            "source dependency rejections",
            0,
            4096,
        )
        view = receipt["view_receipt"]
        if not store_read:
            if view is not None or eligible != 0 or rejected != 0:
                return False
        else:
            if not isinstance(view, dict) or set(view) != VIEW_FIELDS:
                return False
            if (
                not isinstance(view["authority_id"], str)
                or re.fullmatch(r"[0-9a-f]{32}", view["authority_id"]) is None
            ):
                return False
            integer(view["authority_generation"], "authority generation", 0, 2**63 - 1)
            resident = integer(view["resident_record_count"], "resident count", 0, 4096)
            integer(
                view["logical_serialized_bytes"], "authority bytes", 0, 16 * 1024**2
            )
            snapshot_rejections = integer(
                view["snapshot_rejections"], "snapshot rejections", 0, 4096
            )
            sha256(view["frontier_sha256"])
            if view["snapshot_sha256"] is not None:
                sha256(view["snapshot_sha256"])
            elif snapshot_rejections:
                return False
            if (
                eligible + rejected > resident
                or view["scientific_acceptance"] != "HOLD"
                or view["malicious_owner_rollback_protected"] is not False
            ):
                return False

        rosters = [
            receipt[field]
            for field in (
                "retrieved_ids",
                "selected_ids",
                "delivered_ids",
                "byte_dropped_ids",
            )
        ]
        for ids in rosters:
            if not isinstance(ids, list) or len(ids) > limit:
                return False
            for record_id in ids:
                sha256(record_id)
            if len(set(ids)) != len(ids):
                return False
        fetched, selected, delivered, dropped_ids = rosters
        if len(fetched) > eligible or set(selected) != set(fetched):
            return False
        if not retrieved and any(rosters):
            return False
        association_id = receipt["association_id"]
        if association_id is not None:
            sha256(association_id)
        expected_status = (
            "disabled"
            if mode == "association_off"
            else "unavailable"
            if association_id is None
            else "applied"
            if retrieved
            else "not_run"
        )
        called = expected_status == "applied"
        if (
            receipt["association_status"] != expected_status
            or receipt["association_called"] is not called
            or (not called and selected != fetched)
        ):
            return False
        if mode == "delivery_off":
            if delivered or dropped_ids:
                return False
        elif (
            set(delivered) & set(dropped_ids)
            or set(delivered) | set(dropped_ids) != set(selected)
            or delivered != [value for value in selected if value in set(delivered)]
            or dropped_ids != [value for value in selected if value in set(dropped_ids)]
        ):
            return False

        if (
            not isinstance(result["records"], list)
            or len(result["records"]) > limit
            or not isinstance(result["context"], str)
            or len(result["context"].encode()) > budget
        ):
            return False
        records = [validate_record(r) for r in result["records"]]
        if (
            any(record["source_id"] not in sources for record in records)
            or len({record["namespace"] for record in records}) > 1
            or any(
                view is None
                or not record["version"]
                <= record["write_sequence"]
                <= view["authority_generation"]
                for record in records
            )
            or receipt["provenance"]
            != [
                {"record_id": record["record_id"], **record["provenance"]}
                for record in records
            ]
        ):
            return False
        context, _, dropped = assemble_context(records, budget)
        return (
            receipt["receipt_sha256"]
            == digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
            and receipt["context_sha256"] == hashlib_sha(result["context"])
            and receipt["context_bytes"] == len(result["context"].encode())
            and delivered == [r["record_id"] for r in records]
            and context == result["context"]
            and not dropped
        )
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return False

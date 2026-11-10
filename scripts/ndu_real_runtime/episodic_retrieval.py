"""Deterministic retrieval baselines and separately observable MEM6 ablations.

Receipts belong to the evaluator, not the actor context. No neural association
head is supplied: a caller may supply a version-bound permutation callback.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
import random
import re
import time

from .episodic_memory import (
    EpisodicStore, bounded_text, canonical_bytes, digest, integer, sha256, validate_record,
)


MODES = {"on", "off", "retrieval_off", "delivery_off", "association_off"}
STRATEGIES = {"exact_kv", "bm25", "uniform_replay", "icl"}


def _tokens(value):
    return re.findall(r"\w+", value.casefold(), flags=re.UNICODE)


def exact_kv(records, key, limit):
    """Exact case-sensitive key matching within the caller's approved sources."""
    bounded_text(key, "exact key")
    return sorted((r for r in records if r["key"] == key),
                  key=lambda r: (r["source_id"], r["key"], r["record_id"]))[:limit]


def bm25(records, query, limit):
    """BM25(k1=1.2,b=0.75), Unicode word tokens, positive scores, stable ties."""
    terms = set(_tokens(query))
    if not terms or not records:
        return []
    documents = [Counter(_tokens(r["key"] + " " + r["text"])) for r in records]
    lengths = [sum(document.values()) for document in documents]
    average = sum(lengths) / len(lengths)
    if average == 0:
        return []
    frequencies = {term: sum(term in doc for doc in documents) for term in terms}
    scored = []
    for record, document, length in zip(records, documents, lengths):
        score = 0.0
        for term in sorted(terms):
            count = document[term]
            if count:
                idf = math.log1p((len(records) - frequencies[term] + 0.5) /
                                (frequencies[term] + 0.5))
                score += idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average))
        if score > 0:
            scored.append((score, record))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["record_id"]))
    return [record for _, record in scored[:limit]]


def assemble_context(records, max_context_bytes):
    """Admit whole JSON records under a UTF-8 budget; never truncate a fact."""
    integer(max_context_bytes, "context byte bound", 0, 65536)
    lines, delivered, dropped = [], [], []
    used = 0
    for record in records:
        line = canonical_bytes({k: record[k] for k in (
            "record_id", "namespace", "source_id", "key", "version", "text", "provenance"
        )}).decode()
        addition = len(line.encode()) + bool(lines)
        if used + addition > max_context_bytes:
            dropped.append(record["record_id"])
            continue
        lines.append(line)
        delivered.append(record)
        used += addition
    return "\n".join(lines), delivered, dropped


def read_memory(store, *, session_id, source_ids, query="", key=None, mode="on",
                strategy="bm25", limit=8, max_context_bytes=8192,
                snapshot_path=None, seed=0, association=None, association_id=None):
    """Return delivered records/context and an audit-only, hash-bound read receipt.

    off never opens a view; retrieval_off reads the store but skips retrieval;
    delivery_off performs retrieval/association but emits no actor content;
    association_off skips only the supplied association callback. A missing
    callback is explicitly unavailable, and is not a neural-head ablation.
    """
    wall, cpu = time.perf_counter(), time.process_time()
    bounded_text(session_id, "session id")
    if not isinstance(mode, str) or mode not in MODES or not isinstance(strategy, str) or strategy not in STRATEGIES:
        raise ValueError("explicit supported mode and strategy required")
    if mode != "off" and not isinstance(store, EpisodicStore):
        raise ValueError("an existing current authority store is required")
    if not isinstance(query, str) or len(query.encode()) > 2048:
        raise ValueError("bounded query required")
    if not isinstance(source_ids, (tuple, list)) or not 1 <= len(source_ids) <= 32:
        raise ValueError("explicit bounded source allowlist required")
    for source in source_ids:
        bounded_text(source, "source id")
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("duplicate source id")
    integer(limit, "retrieval limit", 1, 128)
    integer(max_context_bytes, "context byte bound", 0, 65536)
    integer(seed, "replay seed", 0, 2**63 - 1)
    if strategy == "exact_kv":
        bounded_text(key, "exact key")
    if association is not None:
        if not callable(association):
            raise ValueError("association must be a callable, not an inferred head")
        sha256(association_id)
    elif association_id is not None:
        raise ValueError("association identity supplied without an implementation")
    receipt = {
        "schema": "hepta.mem6.read-receipt.v1", "session_id": session_id,
        "mode": mode, "strategy": strategy, "source_ids": sorted(source_ids),
        "query_sha256": digest({"query": query, "key": key}), "limit": limit,
        "max_context_bytes": max_context_bytes, "replay_seed": seed,
        "store_read": False, "retrieval_executed": False, "view_receipt": None,
        "eligible_count": 0, "retrieved_ids": [], "selected_ids": [],
        "delivered_ids": [], "byte_dropped_ids": [], "context_bytes": 0,
        "association_status": ("disabled" if mode == "association_off" else
                               "not_run" if association is not None else "unavailable"),
        "association_id": association_id, "association_called": False,
        "association_authentication_established": False,
        "scientific_acceptance": "HOLD", "real_task_benefit_established": False,
    }
    selected, delivered, context = [], [], ""
    if mode != "off":
        view = store.view(snapshot_path=snapshot_path)
        receipt.update(store_read=True, view_receipt=view["receipt"])
        records = [r for r in view["records"] if r["source_id"] in set(source_ids)]
        receipt["eligible_count"] = len(records)
        if mode != "retrieval_off":
            receipt["retrieval_executed"] = True
            if strategy == "exact_kv":
                selected = exact_kv(records, key, limit)
            elif strategy == "bm25":
                selected = bm25(records, query, limit)
            elif strategy == "uniform_replay":
                ordered = sorted(records, key=lambda r: r["record_id"])
                selected = random.Random(seed).sample(ordered, min(limit, len(ordered)))
            else:
                selected = sorted(records, key=lambda r: (r["write_sequence"], r["record_id"]))[:limit]
            receipt["retrieved_ids"] = [r["record_id"] for r in selected]
            if mode != "association_off" and association is not None:
                # Deep-copy callback inputs so ranking cannot rewrite source facts.
                order = association(query, tuple(json.loads(canonical_bytes(selected))))
                ids = receipt["retrieved_ids"]
                if (not isinstance(order, (tuple, list)) or len(order) != len(ids)
                        or any(not isinstance(value, str) for value in order)
                        or set(order) != set(ids)):
                    raise ValueError("association must return an exact record-id permutation")
                by_id = {r["record_id"]: r for r in selected}
                selected = [by_id[record_id] for record_id in order]
                receipt.update(association_status="applied", association_called=True)
            receipt["selected_ids"] = [r["record_id"] for r in selected]
            if mode != "delivery_off":
                context, delivered, dropped = assemble_context(selected, max_context_bytes)
                receipt.update(delivered_ids=[r["record_id"] for r in delivered],
                               byte_dropped_ids=dropped, context_bytes=len(context.encode()))
    receipt.update(context_sha256=hashlib_sha(context),
                   decision_cpu_seconds=time.process_time() - cpu,
                   decision_wall_seconds=time.perf_counter() - wall,
                   provenance=[{"record_id": r["record_id"], **r["provenance"]} for r in delivered])
    receipt["receipt_sha256"] = digest(receipt)
    return {"records": delivered, "context": context, "receipt": receipt}


def hashlib_sha(text):
    # A content digest covers the actual delivered bytes, including the empty case.
    return hashlib.sha256(text.encode()).hexdigest()


def verify_read_receipt(result):
    """Check receipt consistency, not execution authentication or owner honesty."""
    try:
        receipt = result["receipt"]
        records = [validate_record(r) for r in result["records"]]
        context, _, dropped = assemble_context(records, receipt["max_context_bytes"])
        return (
            receipt["receipt_sha256"] == digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
            and receipt["context_sha256"] == hashlib_sha(result["context"])
            and receipt["context_bytes"] == len(result["context"].encode())
            and receipt["delivered_ids"] == [r["record_id"] for r in result["records"]]
            and set(receipt["delivered_ids"]) <= set(receipt["selected_ids"])
            and context == result["context"] and not dropped
        )
    except (KeyError, TypeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--key")
    parser.add_argument("--mode", choices=sorted(MODES), default="on")
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="bm25")
    parser.add_argument("--snapshot")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--max-context-bytes", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.mode != "off" and args.store is None:
        parser.error("--store is required whenever persistence is accessed")
    # Off must work even when no authority is available; it reads no state.
    store = None if args.mode == "off" else EpisodicStore(
        args.store, namespace=args.namespace, create=False)
    print(json.dumps(read_memory(
        store, session_id=args.session, source_ids=args.source, query=args.query,
        key=args.key, mode=args.mode, strategy=args.strategy, snapshot_path=args.snapshot,
        limit=args.limit, max_context_bytes=args.max_context_bytes, seed=args.seed,
    ), sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()

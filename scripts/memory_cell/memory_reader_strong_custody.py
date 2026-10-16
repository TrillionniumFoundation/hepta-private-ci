"""Fail-closed before-effect custody for the research-only Qwen six-arm Reader.

This proves internal journal consistency, not that an external model really ran,
that original evidence is true, or that a model deserves production selection.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re

import memory_reader_causal_panel as base

SCHEMA = "hepta.memory-reader-qwen3-before-effect-custody.research.v1"
MAX_START_BYTES = 128 * 1024


def event(row):
    """Bind a *tokenized* original request before the model invocation."""
    required = ("request_id", "plan_sha256", "model_spec_digest", "prompt_digest",
                "input_tokens", "input_ids_digest")
    if (not isinstance(row, dict) or any(k not in row for k in required)
        or any(not isinstance(row[k], str) or not row[k] for k in required[:4])
        or type(row["input_tokens"]) is not int or not 1 <= row["input_tokens"] <= 2048
        or not isinstance(row["input_ids_digest"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", row["input_ids_digest"])):
        raise ValueError("before-effect token identity unavailable")
    return {"schema": SCHEMA, **{k: row[k] for k in required},
            "production_accepted": False}


def check(plan, ph, rows, out_dir):
    """Require one durable intent per successful model call, in original order.

    Missing/duplicate/reordered/tampered/truncated events or source/model/input
    mismatches deny the entire batch. No unverified start may count as success.
    """
    if (not isinstance(plan, dict) or not isinstance(rows, list)
        or len(rows) != len(plan.get("requests", [])) or len(rows) != 120):
        raise ValueError("unregistered custody population")
    path = Path(out_dir) / "started.jsonl"
    # The sealed worker can legitimately have no starts only if every request
    # was unavailable. That special case has no evidence of model execution.
    predicted = [event(row) for req, row in zip(plan["requests"], rows, strict=True)
                 if not req["unavailable"] and row["status"] == "succeeded"]
    if path.exists() or path.is_symlink():
        raw = base.read(path, maximum=MAX_START_BYTES)
    else:
        raw = b""
    if (predicted and not raw) or (raw and not raw.endswith(b"\n")):
        raise ValueError("missing or truncated before-effect journal")
    expected = b"".join(base.canonical(e) for e in predicted)
    if raw != expected:
        raise ValueError("before-effect and sealed original responses disagree")
    if not predicted:
        raise ValueError("no original physical Reader calls established")
    if len({e["request_id"] for e in predicted}) != len(predicted):
        raise ValueError("duplicate before-effect request")
    return {"schema": SCHEMA, "plan_sha256": ph,
            "started_sha256": hashlib.sha256(raw).hexdigest(),
            "started_calls": len(predicted), "planned": len(rows),
            "external_model_execution_independently_attested": False,
            "source_truth_or_semantic_citation_certified": False,
            "production_accepted": False}


def main():
    import sys
    if len(sys.argv) != 3:
        raise SystemExit("usage: memory_reader_strong_custody.py PLAN_DIR OUTPUT_DIR")
    import memory_reader_strong_reference as strong
    plan, ph = strong.preflight(sys.argv[1])
    rows, _seal = strong.load_output(plan, ph, sys.argv[2])
    print(json.dumps(check(plan, ph, rows, sys.argv[2]), sort_keys=True))


if __name__ == "__main__":
    main()

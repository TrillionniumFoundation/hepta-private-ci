"""Deterministic source-inventory projection; never an execution receipt."""
from __future__ import annotations

import hashlib
import json

BEGIN = "<!-- BEGIN GENERATED LEARNING.EVAL SOURCE STATUS -->"
END = "<!-- END GENERATED LEARNING.EVAL SOURCE STATUS -->"


def canonical(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def projection(status: dict) -> str:
    if status.get("module") != "learning.eval":
        raise ValueError("wrong projection module")
    if any(value is not False for value in status["claims"].values()):
        raise ValueError("a source projection cannot self-issue acceptance")
    recovery = status["sourceFacts"]["recoverySource"]
    outcomes = status["sourceFacts"]["outcomeSource"]
    count = recovery["processKillFixtureCutCount"]
    if type(count) is not int or count < 1:
        raise ValueError("invalid source fixture cut count")
    digest = hashlib.sha256(canonical(status).encode("utf-8")).hexdigest()
    return "\n".join([
        BEGIN,
        "### Current candidate source inventory",
        "",
        "Canonical inventory: `docs/modules/learning.eval/CURRENT_STATUS.json`.",
        f"Inventory SHA-256: `{digest}`.",
        "",
        "This block is generated from lexical source facts, not test results.",
        "Default ingress: recorded runner with independently anchored journal capability.",
        "Raw runner: explicit `trusted-inprocess-eval` compatibility feature only.",
        "Recovery: durable intent, full-history validation, bounded cursor reconciliation,",
        "and signature-reverified decided-only publication resume.",
        f"Process-kill fixture cuts: `{count}`; their execution is separately qualified.",
        f"Outcome source: at most `{outcomes['maximumChannels']}` preregistered channels and",
        f"`{outcomes['maximumBatchRows']}` batch rows, with separate measured estimates.",
        "A deployed outcome-receipt consumer and authenticated measurement provenance",
        "are not established by the source inventory.",
        "",
        "Exact-head, ordered-parent merge, coverage and strict lint require immutable",
        "execution artifacts. Real target-host, future-window and independent acceptance",
        "evidence remain external. Production, activation and release claims remain false.",
        END,
    ]) + "\n"


def replace_projection(document: str, block: str) -> str:
    if document.count(BEGIN) != document.count(END) or document.count(BEGIN) > 1:
        raise ValueError("ambiguous source-status projection markers")
    if BEGIN not in document:
        return document + ("\n" if document.endswith("\n") else "\n\n") + block
    start = document.index(BEGIN)
    end = document.index(END)
    if end < start:
        raise ValueError("reversed source-status projection markers")
    end += len(END)
    if document[end:end + 1] == "\n":
        end += 1
    return document[:start] + block + document[end:]

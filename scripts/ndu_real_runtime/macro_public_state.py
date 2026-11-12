"""One shared public projection for deployed and retained complete macros.

The legacy ``context_belief`` field contains a deterministic one-hot task
category, ordered company/date/address/total. It is observed public goal
metadata, not a posterior, inferred answer, acquisition probability or label.
Pending evidence and freshness are unavailable in this initial-decision
protocol and retain their explicit fixed values.
"""

import math


CONTEXT_FIELDS = ("company", "date", "address", "total")


def project(features, metadata, remaining_seconds, legal_actions):
    """Project only the actor's current encoded features and public task metadata."""
    if (
        type(metadata) not in (list, tuple)
        or len(metadata) != 16
        or any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in metadata
        )
        or any(value not in (0.0, 1.0) for value in metadata[:4])
        or sum(metadata[:4]) != 1
    ):
        raise ValueError("Observed public metadata requires one exact task category")
    if not {"STOP", "WRITE_TEXT"} <= set(legal_actions):
        raise ValueError("A writable complete STOP finalizer is required")
    return {
        "features": list(features),
        "context_belief": [float(value) for value in metadata[:4]],
        "pending_evidence": False,
        "freshness_seconds": 0.0,
        "remaining_seconds": remaining_seconds,
        "legal_macros": ["STOP", "READ"]
        if "PREPARE_ROI" in legal_actions
        else ["STOP"],
    }

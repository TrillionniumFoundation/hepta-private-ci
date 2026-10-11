"""Research-only admission: bind actual pretrained source-loss parity to one write.

A SHA256 and an exact-source receipt are integrity checks, not reviewer approval.
Full-vocabulary writing remains the default; selected projection fails closed.
"""

import math
from pathlib import Path
import re

from event_memory_trial import read

_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA = "hepta.source-only.pretrained-loss-parity.v1"


def require_parity(
    backend,
    receipt_path,
    receipt_sha,
    *,
    source_sha,
    source_commit,
    model_identity,
    repository,
    revision,
):
    if backend == "full":
        if receipt_path is not None or receipt_sha is not None:
            raise ValueError("full source loss must not absorb an unrelated parity proof")
        return None
    if backend != "supervised_positions":
        raise ValueError("unregistered source loss backend")
    if (
        receipt_path is None
        or not isinstance(receipt_path, Path)
        or not isinstance(receipt_sha, str)
        or not _HEX64.fullmatch(receipt_sha)
        or not _HEX64.fullmatch(source_sha)
        or not _HEX40.fullmatch(source_commit)
        or not _HEX64.fullmatch(model_identity)
    ):
        raise ValueError("optimized source write requires an exact parity receipt")
    item = read(receipt_path, receipt_sha)
    bindings = {
        "schema": _SCHEMA,
        "generating_commit": source_commit,
        "source_sha256": source_sha,
        "model_inventory_digest": model_identity,
        "model_repository": repository,
        "model_revision": revision,
        "frozen_pretrained_base_unchanged": True,
        "matched_optimization_step": True,
        "original_task_plan_opened": False,
        "new_answer_generations": 0,
        "significant_task_gain": None,
        "independent_semantic_citation_precision": None,
        "production_accepted": False,
    }
    for field, expected in bindings.items():
        value = item.get(field)
        if type(value) is not type(expected) or value != expected:
            raise ValueError(f"pretrained parity binding disagrees: {field}")
    quantities = (
        "compared_input_tokens",
        "compared_supervised_tokens",
        "full_projection_positions",
        "selected_projection_positions",
    )
    if any(type(item.get(k)) is not int or item[k] <= 0 for k in quantities):
        raise ValueError("missing exact source exposure counts")
    if not (
        item["full_projection_positions"] == item["compared_input_tokens"]
        > item["compared_supervised_tokens"]
        == item["selected_projection_positions"]
    ):
        raise ValueError("optimized loss did not reduce only unused projections")
    measures = (
        "full_loss",
        "selected_loss",
        "maximum_gradient_absolute_difference",
        "maximum_updated_parameter_absolute_difference",
    )
    if any(
        type(item.get(k)) not in (int, float)
        or not math.isfinite(item[k])
        or item[k] < 0
        for k in measures
    ):
        raise ValueError("missing finite pretrained loss/gradient measurements")
    if abs(item["full_loss"] - item["selected_loss"]) > (
        0.001 + 0.001 * abs(item["full_loss"])
    ):
        raise ValueError("pretrained losses differ beyond the locked contract")
    # The comparison command itself checks per-tensor rtol and atol, which
    # cannot be reconstructed from these aggregate maxima alone. This consumer
    # verifies identity/integrity and must not issue an independent proof.
    return receipt_sha

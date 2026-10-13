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
_SCHEMA = "hepta.source-only.pretrained-loss-parity.v2"


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
    curriculum="single_hop",
    objective="completion_ce",
):
    if objective not in ("completion_ce", "source_margin"):
        raise ValueError("unregistered source write objective")
    if backend == "supervised_positions" and objective == "source_margin":
        raise ValueError(
            "source-margin optimized writing requires its own Qwen paired-forward parity"
        )
    if curriculum not in ("single_hop", "source_two_hop"):
        raise ValueError("unregistered source write curriculum")
    if backend == "supervised_positions" and curriculum != "single_hop":
        raise ValueError(
            "source-two-hop optimization requires its own pretrained parity"
        )
    if backend == "full":
        if receipt_path is not None or receipt_sha is not None:
            raise ValueError(
                "full source loss must not absorb an unrelated parity proof"
            )
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
        "curriculum": curriculum,
        "source_example_selected_from_write_schedule": True,
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
        item["full_projection_positions"]
        == item["compared_input_tokens"]
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
    # A necessary aggregate guard, not a replacement for per-tensor
    # torch.testing.assert_close in the original pretrained Qwen producer.
    # L2-clipped gradients and the producer's rtol=.02/atol=.002 imply
    # at most ~.022 absolute drift; allow .024 for BF16 rounding.
    versions = item.get("dependency_versions")
    expected_versions = {
        "torch": "2.5.1+cpu",
        "transformers": "4.57.1",
        "peft": "0.17.1",
    }
    if (
        type(versions) is not dict
        or versions != expected_versions
        or item["compared_input_tokens"] > 2112
        or item["maximum_gradient_absolute_difference"] > 0.024
        or item["maximum_updated_parameter_absolute_difference"] > 0.02
    ):
        raise ValueError("unregistered library, size, or pretrained parity drift")
    if abs(item["full_loss"] - item["selected_loss"]) > (
        0.001 + 0.001 * abs(item["full_loss"])
    ):
        raise ValueError("pretrained losses differ beyond the locked contract")
    # The comparison command itself checks per-tensor rtol and atol, which
    # cannot be reconstructed from these aggregate maxima alone. This consumer
    # verifies identity/integrity and must not issue an independent proof.
    return receipt_sha

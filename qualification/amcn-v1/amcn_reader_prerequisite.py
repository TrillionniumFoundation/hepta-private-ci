"""Fail-closed AMCN Reader-prerequisite research advisory.

Reuses the existing signed/dual-owner Reader gate in full_cell_matrix.
This is never a signature issuer, production Selector, parameter promoter or
independent semantic judge. An admitted test gate only permits formulating a
bounded *research* retrieval hypothesis; it cannot initiate model mutation.
"""
from __future__ import annotations

from amcn_core import digest, is_sha, require, shadow_disposition

PROFILE = "hepta.amcn.reader-prerequisite-advisory.v1"


def reader_prerequisite(
    gate_receipt=None,
    trust_manifest=None,
    reviewer_roster=None,
    *,
    externally_pinned_trust_sha256=None,
    externally_pinned_roster_sha256=None,
    expected_model_binding_sha256=None,
    original_answers_sha256=None,
    original_judgments_sha256=None,
):
    """Describe Reader/retrieval bottleneck only after existing external gate.

    Source IDs, model weights, evidence text and all original answer bytes are
    absent here. Neither source-root uniqueness nor the real-world identity of
    a reviewer can be inferred from caller-provided declarations alone.
    """
    from scripts.memory_cell.full_cell_matrix import evaluate_reader_gate

    for value in (
        externally_pinned_trust_sha256,
        externally_pinned_roster_sha256,
        expected_model_binding_sha256,
        original_answers_sha256,
        original_judgments_sha256,
    ):
        require(value is None or is_sha(value), "ill-formed external provenance pin")

    # Never synthesize a trust root or infer a pin from untrusted supplied JSON.
    verified = evaluate_reader_gate(
        gate_receipt,
        trust_manifest,
        trusted_review_sha256=externally_pinned_trust_sha256,
        reviewer_roster=reviewer_roster,
        trusted_roster_sha256=externally_pinned_roster_sha256,
    )
    binding = (
        isinstance(gate_receipt, dict)
        and isinstance(gate_receipt.get("model_binding"), dict)
        and digest(gate_receipt["model_binding"]) == expected_model_binding_sha256
        and verified.model_binding_digest == expected_model_binding_sha256
    )
    full_original_pins = (
        is_sha(original_answers_sha256) and is_sha(original_judgments_sha256)
    )
    # Failure to establish the independently pinned original-result lineage is
    # an immediate no-go even if the signature envelope itself is valid.
    if not verified.passed:
        disposition = "blocked_reader_adequacy"
    elif not binding:
        disposition = "blocked_model_binding"
    elif not full_original_pins:
        disposition = "blocked_original_answers_or_judgments"
    elif "text" not in verified.capabilities.get("modalities", []):
        disposition = "blocked_text_capability"
    elif verified.human_sufficient_grounded <= verified.ordinary_retrieval_grounded:
        disposition = "reader_adequate_but_no_retrieval_headroom"
    else:
        disposition = "reader_adequate_with_retrieval_headroom_research_only"

    suggestion = {
        "blocked_reader_adequacy": "obtain independently reviewed four-arm Reader evidence",
        "blocked_model_binding": "reconcile exact weights/tokenizer/prompt/data/decoder identities",
        "blocked_original_answers_or_judgments": "audit immutable original answer and independent score artifacts",
        "blocked_text_capability": "qualify frozen Reader text capability",
        "reader_adequate_but_no_retrieval_headroom": "test whether simple retrieval already saturates the Reader",
        "reader_adequate_with_retrieval_headroom_research_only":
            "run preregistered equal-cost strong-RAG versus fixed/learned Cell on new source families",
    }[disposition]
    return shadow_disposition(
        profile=PROFILE,
        disposition=disposition,
        reader_gate_reason=verified.reason,
        existing_reader_gate_passed=bool(verified.passed),
        existing_gate_cohort_size=verified.cohort_size,
        human_sufficient_grounded=verified.human_sufficient_grounded,
        ordinary_retrieval_grounded=verified.ordinary_retrieval_grounded,
        no_evidence_exact_refusal=verified.no_evidence_exact_refusal,
        critical_premise_removed_exact_refusal=verified.premise_removed_exact_refusal,
        matched_model_binding=bool(binding),
        supplied_original_pins_present=bool(full_original_pins),
        originals_independently_reopened_by_this_module=False,
        reviewer_real_world_identity_proven_by_this_module=False,
        allowed_next_research_diagnostic=suggestion,
        physical_reader_generations_executed=0,
        may_train_new_semantic_head_for_product=False,
        may_split_or_merge_product_cells=False,
        may_scale_cell_population=False,
        trial_only_benefit_claim=False,
        independently_observed_future_windows=0,
    )

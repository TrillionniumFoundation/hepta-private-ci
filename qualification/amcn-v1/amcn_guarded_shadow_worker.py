"""Source-revocation-fenced, physically executed Head-only *research* worker.

Acts as a prototype adapter for the existing Learning Artifacts and Neuron
Runtime owners; it is NOT wired to their production APIs and returns no model
activation, FinalUse or external effect permission. The journal's POSIX lock
can fence only local research workers. Production must bind an authoritative
CognitiveStore source frontier and InferenceControlModelPort inside its own
transaction, generation and CAS boundary.
"""
from __future__ import annotations

import math

import torch

from amcn_core import require, shadow_disposition, is_sha
from amcn_quarantine_ledger import ShadowQuarantineLedger
from amcn_revocation import CellGeneration
from experiments.shared_stem_cell.execution import (
    Head, measured, parameters, tensor_digest,
)

MAX_WORKER_BATCH = 32


def guarded_shadow_head_forward(ledger, artifact, all_artifacts, current_sources,
                                head, features, *, scope, generation,
                                externally_pinned_frontier_sha256,
                                expected_journal_head_sha256,
                                externally_pinned_feature_sha256,
                                externally_pinned_encoder_sha256):
    """Physically run a bounded frozen Head only while a local candidate hold is valid.

    Actual neural input is supplied by the caller; neither an original HF
    Encoder receipt nor semantic support truth is inferred from that tensor.
    """
    require(isinstance(ledger, ShadowQuarantineLedger)
            and isinstance(artifact, CellGeneration)
            and isinstance(head, Head) and not head.training,
            "research-only frozen Head/lineage pair required")
    require(isinstance(features, torch.Tensor) and features.dtype == torch.float32
            and features.device.type == "cpu" and features.ndim == 2
            and 1 <= len(features) <= MAX_WORKER_BATCH
            and features.shape[1] == head.base.in_features
            and bool(torch.isfinite(features).all()),
            "bounded physical source feature tensor required")
    require(is_sha(externally_pinned_feature_sha256)
            and is_sha(externally_pinned_encoder_sha256)
            and artifact.stem_sha256 == externally_pinned_encoder_sha256,
            "exact Encoder/model provenance binding required")
    require(tensor_digest(features) == externally_pinned_feature_sha256,
            "physical input feature differs from original Encoder receipt")
    require(artifact.kind in {"semantic_head", "split_child", "consolidation_student"},
            "not an executable linear SemanticCell Head")
    require(all(not p.requires_grad for p in head.parameters()),
            "a serving Head cannot mutate parameters")
    before = parameters(head)
    require(before["sha256"] == artifact.head_sha256,
            "physical Head differs from immutable trained artifact identity")
    input_sha = tensor_digest(features)
    with ledger.hold_shadow_candidate(
        artifact.artifact_id, all_artifacts, current_sources,
        scope=scope, generation=generation,
        externally_pinned_frontier_sha256=externally_pinned_frontier_sha256,
        expected_journal_head_sha256=expected_journal_head_sha256,
    ) as preflight:
        with measured() as resources, torch.no_grad():
            outputs = head(features.detach().clone()).softmax(-1)
            require(outputs.shape == (len(features), 2)
                    and bool(torch.isfinite(outputs).all()),
                    "invalid executed Head output")
            probabilities = outputs[:, 1].tolist()
            require(all(math.isfinite(p) and 0 <= p <= 1 for p in probabilities),
                    "unbounded Head score")
        require(parameters(head) == before,
                "Head mutated during frozen research execution")
        receipt = shadow_disposition(
            profile="hepta.amcn.local-shadow-head-forward.v1",
            preflight_sha256=preflight["metrics"]["journal_head_sha256"],
            artifact_id=artifact.artifact_id,
            physical_head_state_sha256=before["sha256"],
            physical_input_tensor_sha256=input_sha,
            externally_pinned_encoder_sha256=externally_pinned_encoder_sha256,
            original_pretrained_encoder_executed_here=False,
            physical_head_calls=1, physical_head_cases=len(features),
            local_quarantine_held_through_forward=True,
            output_probability_sha256=tensor_digest(outputs.detach().cpu()),
            resources=resources,
            independently_selected_model=False,
            actual_source_owner_fenced=False,
            product_model_execution_approved=False,
            original_answer_quality_evaluated=False,
        )
        return {"probabilities": probabilities, "receipt": receipt}

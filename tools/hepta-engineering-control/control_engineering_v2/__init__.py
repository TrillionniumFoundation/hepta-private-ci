"""Lane G engineering-control implementation exports."""
from .assimilation import (
    AssimilationProposal,
    ExternalManifestCandidate,
    OwnerConsentReceipt,
    SandboxParityReceipt,
    TypedOperation,
    build_manifest_candidate,
    propose_dormant_assimilation,
    synthesize_read_only_contracts,
    validate_consent,
)
from .candidate import (
    Candidate,
    CandidateEnvelope,
    Mutation,
    SandboxReceipt,
    generate_candidates,
    sandbox_candidate,
)
from .control_plane import (
    EngineeringError,
    EngineeringStore,
    LeaseReceipt,
    ScheduleReceipt,
    WorkEnvelope,
    WorkPackage,
    bounded_tuple,
    canonical_json,
    canonical_repo_path,
    canonical_paths,
    checked_id,
    checked_sha256,
    path_is_within,
    path_sets_overlap,
    paths_overlap,
    semantic_digest,
)
from .evidence import (
    CanonicalSourceReceipt,
    EvidenceDecision,
    EvaluatorIndependenceReceipt,
    ExecutionReceipt,
    HmacTrustStore,
    verify_integration_evidence,
)
from .facade import (
    ReviewRequest,
    execute_candidate_sandbox,
    generate_candidate,
    issue_work_envelope,
    prepare_assimilation_candidate,
    publish_audit_projection,
    record_integration_decision,
    request_independent_review,
    schedule_ready_packages,
)
from .hardening import (
    AttestedSandboxParity,
    BoundEvidenceDecision,
    CandidateEvidenceBindingReceipt,
    OwnerConsentAttestation,
    SandboxParityAttestation,
    assignment_frontier,
    bind_candidate_evidence,
    consent_payload_digest,
    hardened_execute_candidate_sandbox,
    hardened_prepare_assimilation_candidate,
    hardened_record_integration_decision,
    hardened_request_independent_review,
    hardened_sandbox_candidate,
    install_hardening,
)

# Install before exposing composition operations.  Low-level constructors remain
# importable for deterministic fixtures, while every authority-adjacent public
# transition below is the fail-closed hardened implementation.
install_hardening()
sandbox_candidate = hardened_sandbox_candidate
execute_candidate_sandbox = hardened_execute_candidate_sandbox
request_independent_review = hardened_request_independent_review
record_integration_decision = hardened_record_integration_decision
prepare_assimilation_candidate = hardened_prepare_assimilation_candidate

__all__ = [name for name in globals() if not name.startswith("_")]

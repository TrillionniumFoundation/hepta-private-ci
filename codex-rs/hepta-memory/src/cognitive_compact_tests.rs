use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GovernanceDecision;
use codex_hepta_contracts::GovernanceDecisionRecord;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::GovernanceReceipt;
use codex_hepta_contracts::HandlerOutcome;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_contracts::PolicyStamp;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::ToolAction;
use codex_hepta_contracts::ToolActionSource;
use pretty_assertions::assert_eq;
use sqlx::Executor;
use sqlx::Row;
use tempfile::TempDir;

use crate::COGNITIVE_COMPACT_HOOK_NAMESPACE;
use crate::CognitiveCompactError;
use crate::CognitiveRuntime;
use crate::CognitiveStore;
use crate::CognitiveUnavailableReason;
use crate::CompactCheckpoint;
use crate::CompactCommitDecision;
use crate::CompactConflictReason;
use crate::CompactFence;
use crate::CompactLease;
use crate::CompactLossReport;
use crate::CompactParentSnapshot;
use crate::CompactProtectedRef;
use crate::CompactSummaryReceipt;
use crate::IntuitionCandidate;
use crate::IntuitionDecision;
use crate::IntuitionMode;
use crate::IntuitionShadowInput;
use crate::NeuronFeature;
use crate::NeuronParameter;
use crate::NeuronPosition;
use crate::NeuronProposalDecision;
use crate::NeuronProposalInput;
use crate::RehydrationStatus;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::intuition_schema_digest;
use crate::shadow_intuition_decide;
use crate::shadow_neuron_propose;

fn fence() -> CompactFence {
    CompactFence::new(3, 8, 19, "fence:19").expect("valid fence")
}

fn snapshot() -> CompactParentSnapshot {
    CompactParentSnapshot::new(
        "ctx:local-development",
        20,
        30,
        7,
        Sha256Digest::for_bytes(b"parent-state"),
        fence(),
    )
    .expect("valid parent snapshot")
}

fn summary() -> CompactSummaryReceipt {
    CompactSummaryReceipt::new(
        Sha256Digest::for_bytes(b"summary"),
        Sha256Digest::for_bytes(b"model-receipt"),
        Sha256Digest::for_bytes(b"compact-policy:v1"),
    )
}

fn loss_report() -> CompactLossReport {
    CompactLossReport::new(vec!["event:29".to_string()], 1, Vec::new(), 0)
        .expect("valid loss report")
}

fn checkpoint() -> CompactCheckpoint {
    let protected = CompactProtectedRef::new("approval:1", "approval", true)
        .expect("valid protected reference");
    CompactCheckpoint::new(
        "ctxcp:local-development",
        CompactLease::from_snapshot(snapshot()),
        vec![protected],
        summary(),
        loss_report(),
        0,
    )
    .expect("valid checkpoint")
}

#[test]
fn pre_hook_is_deterministic_and_explicitly_local_only() {
    let first = CompactLease::from_snapshot(snapshot());
    let second = CompactLease::from_snapshot(snapshot());
    assert_eq!(first, second);
    assert_eq!(first.namespace, COGNITIVE_COMPACT_HOOK_NAMESPACE);
    assert_eq!(
        first.lease_id,
        format!("ctxlease:v1:{}", first.lease_sha256.as_str())
    );
    assert_eq!(
        CognitiveRuntime::Absent.pre_compact(snapshot()),
        Err(CognitiveCompactError::RuntimeAbsent)
    );
}

#[test]
fn deserialized_lease_identity_is_recomputed_before_compact_use() {
    let mut digest_tampered = checkpoint();
    digest_tampered.lease.lease_sha256 = Sha256Digest::for_bytes(b"tampered");
    assert!(matches!(
        digest_tampered.rehydration_plan(0),
        Err(CognitiveCompactError::Invalid { message })
            if message.contains("lease digest")
    ));

    let mut id_tampered = checkpoint();
    id_tampered.lease.lease_id.push_str(":tampered");
    assert!(matches!(
        id_tampered.rehydration_plan(0),
        Err(CognitiveCompactError::Invalid { message })
            if message.contains("lease id")
    ));
}

#[test]
fn compact_commit_validation_fences_parent_cas_and_generation() {
    let checkpoint = checkpoint();
    assert_eq!(
        checkpoint.validate_against(&snapshot()),
        CompactCommitDecision::Accepted {
            checkpoint_id: "ctxcp:local-development".to_string(),
            checkpoint_revision: 0,
        }
    );

    let mut revision_changed = snapshot();
    revision_changed.expected_parent_revision = 8;
    assert_eq!(
        checkpoint.validate_against(&revision_changed),
        CompactCommitDecision::Conflict {
            reason: CompactConflictReason::ParentRevisionChanged,
        }
    );

    let mut state_changed = snapshot();
    state_changed.expected_state_sha256 = Sha256Digest::for_bytes(b"new-state");
    assert_eq!(
        checkpoint.validate_against(&state_changed),
        CompactCommitDecision::Conflict {
            reason: CompactConflictReason::ParentStateChanged,
        }
    );

    let mut generation_changed = snapshot();
    generation_changed.fence.generation = 20;
    assert_eq!(
        checkpoint.validate_against(&generation_changed),
        CompactCommitDecision::StaleGeneration
    );
}

/// H5's deterministic proposal and H6's deterministic decision are joined by
/// explicit digests before a local postcondition is built.  The postcondition
/// is then checked against the Agent-local runtime fence: an owner or
/// generation rollover must reject it, even when all payload bytes are
/// otherwise unchanged.  This is qualification evidence only; no model,
/// KG write, scheduler, or external effect is involved.
#[tokio::test]
async fn qualification_h5_h6_typed_handoff_rejects_stale_fenced_postcondition() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(92);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("open Agent-local store");
    let before: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
        .fetch_one(&store.pool)
        .await
        .expect("memory count before seam");
    let runtime = CognitiveRuntime::from_open_result(Ok(store));

    // H5: produce a proposal from a fixed replay snapshot.  Its input and
    // proposal digests are the causal identifiers handed to H6 below.
    let h5_input = NeuronProposalInput {
        position: NeuronPosition::MemoryRetrievalRank,
        state_digest: Sha256Digest::for_bytes(b"agent-local-state:h5-h6:v1"),
        policy_digest: Sha256Digest::for_bytes(b"agent-local-policy:h5-h6:v1"),
        authority_epoch: 11,
        sample_count: 2,
        baseline_bps: 6_500,
        features: vec![
            NeuronFeature::new("retrieval_signal", 8_000).expect("feature"),
            NeuronFeature::new("freshness_signal", 9_000).expect("feature"),
        ],
    };
    let h5_proposal = match shadow_neuron_propose(&h5_input, NeuronParameter::RetrievalWeightBps)
        .expect("H5 proposal")
    {
        NeuronProposalDecision::Proposed(proposal) => proposal,
        NeuronProposalDecision::Abstained { .. } => panic!("fixed H5 input must propose"),
    };
    h5_proposal.validate().expect("proposal remains typed");
    assert!(h5_proposal.is_shadow_only());

    // H6: consume only the H5 proposal digest as its immutable snapshot.
    // The decision cannot be reconstructed from a different proposal or
    // policy because both are bound into this input and receipt.
    let h6_input = IntuitionShadowInput {
        snapshot_digest: h5_proposal.proposal_id.clone(),
        schema_digest: intuition_schema_digest(),
        policy_digest: h5_input.policy_digest.clone(),
        authority_epoch: h5_input.authority_epoch,
        mode: IntuitionMode::SuggestOnly,
        max_risk_bps: 2_000,
        min_confidence_bps: 1_000,
        require_evidence: true,
        candidates: vec![
            IntuitionCandidate::new(
                h5_proposal.proposal_id.as_str(),
                h5_proposal.confidence_bps,
                1_000,
                vec![IntuitionMode::SuggestOnly],
                true,
            )
            .expect("H6 candidate"),
        ],
    };
    let h6_receipt = shadow_intuition_decide(&h6_input).expect("H6 decision");
    h6_receipt
        .validate_against(&h6_input)
        .expect("H5 -> H6 binding");
    assert!(matches!(
        h6_receipt.decision,
        IntuitionDecision::Suggested { .. }
    ));
    assert!(h6_receipt.is_shadow_only());

    // Typed action handoff: preserve both causal IDs in the exact payload
    // digest while keeping the governance receipt non-executable.
    let handoff_payload = serde_json::json!({
        "h5_input_digest": h5_proposal.input_digest,
        "h5_proposal_id": h5_proposal.proposal_id,
        "h6_receipt_digest": h6_receipt.receipt_digest,
        "authority_epoch": h6_receipt.authority_epoch,
    });
    let handoff_bytes = serde_json::to_vec(&handoff_payload).expect("handoff payload");
    let action = ToolAction {
        schema_version: 1,
        action_id: ActionId::for_tool_call("thread:h5-h6", "turn:h5-h6", "call:h5-h6"),
        thread_id: "thread:h5-h6".to_string(),
        turn_id: "turn:h5-h6".to_string(),
        call_id: "call:h5-h6".to_string(),
        tool_name: "h5_h6_shadow_handoff".to_string(),
        source: ToolActionSource::Direct,
        payload_sha256: Sha256Digest::for_bytes(&handoff_bytes),
    };
    let admission = GovernanceDecisionRecord::new(
        action.clone(),
        PolicyPhase::Admission,
        GovernanceMode::Shadow,
        PolicyStamp::new("h5-h6-shadow-policy", 1, b"no-runtime-effect:v1"),
        GovernanceDecision::NotEvaluated,
    );
    let receipt = GovernanceReceipt::new(admission, None, false, HandlerOutcome::Aborted);
    assert_eq!(receipt.action_id, action.action_id);
    assert!(!receipt.host_accepted);
    assert!(matches!(receipt.outcome, HandlerOutcome::Aborted));

    // The H6 receipt digest is the summary/postcondition payload.  A matching
    // owner/generation fence accepts it; either rollover rejects it as stale.
    let fence = CompactFence::new(11, 23, 7, "h5-h6-owner-fence").expect("fence");
    let parent = CompactParentSnapshot::new(
        "ctx:h5-h6-postcondition",
        1,
        2,
        4,
        Sha256Digest::for_bytes(&handoff_bytes),
        fence,
    )
    .expect("parent snapshot");
    let checkpoint = CompactCheckpoint::new(
        "ctxcp:h5-h6-postcondition",
        CompactLease::from_snapshot(parent.clone()),
        Vec::new(),
        CompactSummaryReceipt::new(
            h6_receipt.receipt_digest.clone(),
            Sha256Digest::for_bytes(b"h5-h6-model-receipt"),
            h5_input.policy_digest.clone(),
        ),
        CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss report"),
        4,
    )
    .expect("postcondition");
    assert_eq!(
        runtime
            .validate_compact_commit(&checkpoint, &parent)
            .expect("local fence validation"),
        CompactCommitDecision::Accepted {
            checkpoint_id: "ctxcp:h5-h6-postcondition".to_string(),
            checkpoint_revision: 4,
        }
    );
    assert_eq!(
        runtime
            .post_compact(&checkpoint, 4)
            .expect("visible postcondition plan")
            .status,
        RehydrationStatus::NotStarted
    );

    let mut stale_owner = parent.clone();
    stale_owner.fence.owner_epoch += 1;
    assert_eq!(
        runtime
            .validate_compact_commit(&checkpoint, &stale_owner)
            .expect("stale owner is a validation result"),
        CompactCommitDecision::StaleGeneration
    );
    let mut stale_generation = parent.clone();
    stale_generation.fence.generation += 1;
    assert_eq!(
        runtime
            .validate_compact_commit(&checkpoint, &stale_generation)
            .expect("stale generation is a validation result"),
        CompactCommitDecision::StaleGeneration
    );

    let after: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
        .fetch_one(&runtime.available_store().expect("runtime store").pool)
        .await
        .expect("memory count after seam");
    assert_eq!(before, after, "H5/H6 shadow seam must not write the KG");
}

#[test]
fn post_hook_returns_visible_rehydration_plan_and_checks_revision() {
    let checkpoint = checkpoint();
    let plan = checkpoint
        .rehydration_plan(0)
        .expect("matching checkpoint revision");
    assert_eq!(plan.checkpoint_id, "ctxcp:local-development");
    assert_eq!(plan.protected_refs.len(), 1);
    assert_eq!(plan.status, RehydrationStatus::NotStarted);
    assert_eq!(
        checkpoint.rehydration_plan(1),
        Err(CognitiveCompactError::RevisionMismatch {
            expected: 1,
            actual: 0,
        })
    );
}

#[test]
fn summary_fact_admission_and_protected_loss_are_rejected() {
    let mut encoded = serde_json::to_value(summary()).expect("serialize summary");
    encoded["fact_admission"] = serde_json::Value::Bool(true);
    let fact_admitting_summary: CompactSummaryReceipt =
        serde_json::from_value(encoded).expect("decode summary");
    assert_eq!(
        CompactCheckpoint::new(
            "ctxcp:fact-admission",
            CompactLease::from_snapshot(snapshot()),
            Vec::new(),
            fact_admitting_summary,
            loss_report(),
            0,
        ),
        Err(CognitiveCompactError::SummaryFactAdmission)
    );

    let lost_refs = CompactLossReport::new(Vec::new(), 0, vec!["approval:1".to_string()], 0)
        .expect("loss report is structurally valid");
    assert_eq!(
        CompactCheckpoint::new(
            "ctxcp:lost-ref",
            CompactLease::from_snapshot(snapshot()),
            Vec::new(),
            summary(),
            lost_refs,
            0,
        ),
        Err(CognitiveCompactError::ProtectedReferenceLoss)
    );
}

#[tokio::test]
async fn available_runtime_hooks_are_read_only_for_the_cognitive_store() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(91);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("open cognitive store");
    let before: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
        .fetch_one(&store.pool)
        .await
        .expect("memory count before hooks");
    let runtime = CognitiveRuntime::from_open_result(Ok(store));
    let lease = runtime.pre_compact(snapshot()).expect("pre hook");
    let mut checkpoint = checkpoint();
    checkpoint.lease = lease;
    let plan = runtime.post_compact(&checkpoint, 0).expect("post hook");
    assert_eq!(plan.status, RehydrationStatus::NotStarted);
    assert_eq!(
        runtime
            .validate_compact_commit(&checkpoint, &snapshot())
            .expect("CAS validation"),
        CompactCommitDecision::Accepted {
            checkpoint_id: checkpoint.checkpoint_id.clone(),
            checkpoint_revision: 0,
        }
    );
    let after: i64 = runtime
        .available_store()
        .expect("available store")
        .pool
        .clone()
        .fetch_one(sqlx::query("SELECT COUNT(*) FROM memory_revisions"))
        .await
        .expect("memory count after hooks")
        .try_get(0)
        .expect("memory count column");
    assert_eq!(before, after);
}

#[test]
fn unavailable_runtime_keeps_hook_error_sanitized() {
    let runtime = CognitiveRuntime::Unavailable(CognitiveUnavailableReason::StorageUnavailable);
    assert_eq!(
        runtime.post_compact(&checkpoint(), 0),
        Err(CognitiveCompactError::RuntimeUnavailable {
            reason: CognitiveUnavailableReason::StorageUnavailable,
        })
    );
}

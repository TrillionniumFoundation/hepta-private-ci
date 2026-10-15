//! Shadow-only verification of independently retained Evidence minimums.
//! These keys are test fixtures, not independently administered deployment keys.
use super::*;
use base64::Engine as _;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

fn transcript() -> CellSplitExecutionTranscriptV1 {
    let plan = crate::CellSplitExecutionPlanV1 {
        split_id: "split.evidence.test".into(),
        scope_digest: "11".repeat(32),
        parent_generation: 7,
        child_generation: 8,
        parent_artifact_digest: "22".repeat(32),
        child_artifact_digest: "33".repeat(32),
        ndu_snapshot_digest: "44".repeat(32),
        route_fence_digest: "55".repeat(32),
        owner_ids: [
            "owner.cas".into(),
            "owner.migration".into(),
            "owner.cns".into(),
            "owner.supervisor".into(),
        ],
    };
    let digest = plan.digest().expect("valid frozen split");
    let steps = [
        crate::CellSplitExecutionStepV1::ArtifactCas,
        crate::CellSplitExecutionStepV1::ChildStateMigration,
        crate::CellSplitExecutionStepV1::CnsRouteCutover,
        crate::CellSplitExecutionStepV1::SupervisorGenerationFence,
    ];
    let receipts = steps
        .iter()
        .enumerate()
        .map(|(i, step)| crate::CellSplitExecutionReceiptV1 {
            intent: crate::CellSplitExecutionIntentV1 {
                schema: "hepta.learning.cell-split.execution-owner.v1".into(),
                plan_digest: digest.clone(),
                step: *step,
                owner_id: plan.owner_ids[i].clone(),
                idempotency_key: format!("{:02x}", i + 1).repeat(32),
                previous_receipt_digest: "66".repeat(32),
            },
            owner_sequence: 10 + i as u64,
            output_digest: "77".repeat(32),
            owner_receipt_bytes: Vec::new(),
            owner_signature_bytes: Vec::new(),
            receipt_digest: "88".repeat(32),
        })
        .collect();
    CellSplitExecutionTranscriptV1 {
        plan,
        receipts,
        transcript_digest: "99".repeat(32),
    }
}

fn candidate(
    step: usize,
) -> (
    CellSplitExecutionTranscriptV1,
    CellSplitEvidenceMetricBindingV1,
) {
    let source = transcript();
    let receipt = &source.receipts[step];
    let phase = match receipt.intent.step {
        crate::CellSplitExecutionStepV1::ArtifactCas => 3,
        crate::CellSplitExecutionStepV1::ChildStateMigration => 4,
        crate::CellSplitExecutionStepV1::CnsRouteCutover => 5,
        crate::CellSplitExecutionStepV1::SupervisorGenerationFence => 4,
    };
    let local = CellSplitEvidenceMetricBindingV1 {
        split_id: source.plan.split_id.clone(),
        plan_digest: source.plan.digest().unwrap(),
        scope_digest: source.plan.scope_digest.clone(),
        operation_digest: receipt.intent.idempotency_key.clone(),
        phase,
        succeeded: true,
        matching_rows: 1,
        first_group_sequence: 3,
        last_group_sequence: 3,
        last_group_head_digest: "aa".repeat(32),
        terminal_group_sequence: 5,
        terminal_head_digest: "bb".repeat(32),
        terminal_committed_rows: 8,
        terminal_journal_bytes: 512,
        wal_device: 1,
        wal_inode: 11,
        marker_device: 1,
        marker_inode: 12,
    };
    (source, local)
}

fn signed_retained(
    local: &CellSplitEvidenceMetricBindingV1,
    challenge: &str,
    key: &SigningKey,
) -> CellSplitEvidenceRetentionReadbackV1 {
    let mut proof = CellSplitEvidenceRetentionReadbackV1 {
        schema: CELL_SPLIT_EVIDENCE_RETENTION_SCHEMA_V1.into(),
        domain_id: "evidence-original-owner.scope".into(),
        challenge_nonce: challenge.into(),
        retained_binding_digest: sha256(&canonical_json(local).unwrap()),
        retained_record_digest: "cc".repeat(32),
        minimum_sequence: local.terminal_group_sequence,
        minimum_head_digest: local.terminal_head_digest.clone(),
        minimum_journal_bytes: local.terminal_journal_bytes,
        retained_revision: 10,
        signature: CellSplitTargetHostSignatureV1 {
            signer_id: "independent.evidence.retention".into(),
            verifying_key_base64: BASE64.encode(key.verifying_key().to_bytes()),
            signature_base64: String::new(),
        },
    };
    resign(&mut proof, key);
    proof
}

fn resign(proof: &mut CellSplitEvidenceRetentionReadbackV1, key: &SigningKey) {
    let payload = cell_split_evidence_retention_signing_payload_v1(proof)
        .expect("canonical independent retained record");
    proof.signature.signature_base64 = BASE64.encode(key.sign(&payload).to_bytes());
}

#[test]
fn exact_original_effect_metric_phase_requires_one_successful_fsynced_row() {
    for step in 0..4 {
        let (transcript, local) = candidate(step);
        assert!(validate_evidence_metric_binding_v1(&transcript, step, &local).is_ok());
        for change in 0..8 {
            let mut altered = local.clone();
            match change {
                0 => altered.scope_digest = "ee".repeat(32),
                1 => altered.operation_digest = "dd".repeat(32),
                2 => altered.phase = 8,
                3 => altered.succeeded = false,
                4 => altered.matching_rows = 2,
                5 => altered.last_group_sequence = 0,
                6 => altered.terminal_group_sequence = 2,
                _ => altered.split_id = "another.split".into(),
            }
            assert!(
                validate_evidence_metric_binding_v1(&transcript, step, &altered).is_err(),
                "case {change}: no fabricated original-effect Evidence acceptance"
            );
        }
    }
}

#[test]
fn retained_original_highwater_must_be_signed_with_fresh_challenge() {
    let (_, local) = candidate(0);
    let key = SigningKey::from_bytes(&[27_u8; 32]);
    let nonce = "ab".repeat(32);
    let proof = signed_retained(&local, &nonce, &key);
    assert!(
        verify_evidence_retention_readback_v1(
            &local,
            "evidence-original-owner.scope",
            &nonce,
            &proof,
            &key.verifying_key(),
        )
        .is_ok()
    );
    assert!(
        verify_evidence_retention_readback_v1(
            &local,
            "evidence-original-owner.scope",
            &"cd".repeat(32),
            &proof,
            &key.verifying_key(),
        )
        .is_err(),
        "a valid old signature is not a fresh readback"
    );
}

#[test]
fn independently_signed_stale_or_cross_bound_minimum_is_denied() {
    let (_, local) = candidate(0);
    let key = SigningKey::from_bytes(&[27_u8; 32]);
    let nonce = "ab".repeat(32);
    let original = signed_retained(&local, &nonce, &key);
    for change in 0..8 {
        let mut proof = original.clone();
        match change {
            0 => proof.minimum_sequence -= 1,
            1 => proof.minimum_sequence += 1,
            2 => proof.minimum_head_digest = "ff".repeat(32),
            3 => proof.minimum_journal_bytes -= 1,
            4 => proof.retained_binding_digest = "aa".repeat(32),
            5 => proof.domain_id = "other.scope".into(),
            6 => proof.retained_record_digest = "00".repeat(32),
            _ => proof.retained_revision = 0,
        }
        resign(&mut proof, &key);
        assert!(
            verify_evidence_retention_readback_v1(
                &local,
                "evidence-original-owner.scope",
                &nonce,
                &proof,
                &key.verifying_key(),
            )
            .is_err(),
            "case {change}: correctly signed stale/wrong minimum is not current"
        );
    }
}

#[test]
fn retained_binding_signature_cannot_be_swapped_or_tampered() {
    let (_, local) = candidate(2);
    let key = SigningKey::from_bytes(&[27_u8; 32]);
    let another = SigningKey::from_bytes(&[28_u8; 32]);
    let nonce = "ab".repeat(32);
    let mut proof = signed_retained(&local, &nonce, &key);
    assert!(
        verify_evidence_retention_readback_v1(
            &local,
            "evidence-original-owner.scope",
            &nonce,
            &proof,
            &another.verifying_key(),
        )
        .is_err()
    );
    proof.signature.signature_base64 = BASE64.encode([0_u8; 64]);
    assert!(
        verify_evidence_retention_readback_v1(
            &local,
            "evidence-original-owner.scope",
            &nonce,
            &proof,
            &key.verifying_key(),
        )
        .is_err()
    );
}

#[test]
fn local_binding_is_non_authorizing_even_when_retained_readback_is_valid() {
    let (_, local) = candidate(3);
    let key = SigningKey::from_bytes(&[27_u8; 32]);
    let nonce = "ab".repeat(32);
    let proof = signed_retained(&local, &nonce, &key);
    assert_eq!(proof.minimum_sequence, local.terminal_group_sequence);
    assert_ne!(
        proof.retained_binding_digest, local.operation_digest,
        "the retained minimum commits a complete typed observation"
    );
    assert!(
        verify_evidence_retention_readback_v1(
            &local,
            "evidence-original-owner.scope",
            &nonce,
            &proof,
            &key.verifying_key(),
        )
        .is_ok(),
        "fixture validates an offline signature, not live owner custody"
    );
}

fn fixture_metrics_ledger(
    transcript: &CellSplitExecutionTranscriptV1,
) -> crate::CellSplitVerifiedMetricsLedgerV1 {
    crate::CellSplitVerifiedMetricsLedgerV1 {
        plan_digest: transcript.plan.digest().expect("frozen plan"),
        transcript_digest: transcript.transcript_digest.clone(),
        acknowledged_steps: transcript
            .receipts
            .iter()
            .enumerate()
            .map(
                |(index, receipt)| crate::CellSplitMetricsAcknowledgedStepV1 {
                    index,
                    step: receipt.intent.step,
                    owner_id: receipt.intent.owner_id.clone(),
                    idempotency_key: receipt.intent.idempotency_key.clone(),
                    committed_owner_receipt_digest: receipt.receipt_digest.clone(),
                    original_metrics_ack_frame_digest: "ae".repeat(32),
                },
            )
            .collect(),
        all_four_original_signed_owner_readbacks: true,
        all_four_original_metrics_ack_frames: true,
        production_activation_authorized: false,
    }
}

#[test]
fn forensic_metrics_ack_binding_requires_all_four_original_commits() {
    let source = transcript();
    let ledger = fixture_metrics_ledger(&source);
    // Only a synthetic test for tuple consistency. Public production API
    // cannot accept this local struct: it re-reads the REAL locked owner.
    assert!(verify_evidence_original_ledger_binding_v1(&ledger, &source).is_ok());
    assert_eq!(ledger.acknowledged_steps.len(), 4);
    assert!(!ledger.production_activation_authorized);
    for change in 0..13 {
        let mut altered = ledger.clone();
        match change {
            0 => altered.plan_digest = "11".repeat(32),
            1 => altered.transcript_digest = "22".repeat(32),
            2 => {
                assert!(
                    altered.acknowledged_steps.pop().is_some(),
                    "four committed originals expected in test fixture"
                );
            }
            3 => altered.acknowledged_steps.swap(1, 2),
            4 => altered.acknowledged_steps[0].owner_id = "other.owner".into(),
            5 => altered.acknowledged_steps[1].idempotency_key = "be".repeat(32),
            6 => altered.acknowledged_steps[2].committed_owner_receipt_digest = "cc".repeat(32),
            7 => altered.acknowledged_steps[3].original_metrics_ack_frame_digest = "00".repeat(32),
            8 => {
                altered.acknowledged_steps[2].original_metrics_ack_frame_digest =
                    "not-a-canonical-digest".into()
            }
            9 => altered.all_four_original_signed_owner_readbacks = false,
            10 => altered.all_four_original_metrics_ack_frames = false,
            11 => altered.production_activation_authorized = true,
            _ => altered.acknowledged_steps[0].index = 2,
        }
        assert!(
            verify_evidence_original_ledger_binding_v1(&altered, &source).is_err(),
            "case {change}: fabricated or missing original ACK cannot qualify"
        );
    }
}

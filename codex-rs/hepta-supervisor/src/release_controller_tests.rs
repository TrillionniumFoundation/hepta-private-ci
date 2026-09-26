use super::*;
use crate::H7H89ProductionGrantSigner;
use codex_hepta_fleet::ReleaseBinding;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_memory::H7TrajectoryEvent;

fn request() -> ProductionReleaseRequestV1 {
    let mut runtime = H7QualificationRuntime::new();
    runtime
        .append_trajectory_event(
            H7TrajectoryEvent::new(
                "caller-trajectory",
                1,
                "reload",
                100,
                true,
                1,
                1,
                1,
                Sha256Digest::for_bytes(b"caller-fixture"),
            )
            .expect("event"),
        )
        .expect("append");
    runtime
        .evaluate_trajectory("caller-trajectory")
        .expect("evaluate");
    let artifact = runtime
        .propose_artifact("caller-artifact", "caller-trajectory", 1)
        .expect("artifact");
    let h7 = H7ArtifactSigner::from_seed("h7-fixture", 1, [2; 32]).expect("h7 signer");
    let envelope = h7
        .sign(
            &artifact,
            None,
            H7SignedArtifactTransition::Reload,
            0,
            None,
            100,
            200,
        )
        .expect("envelope");
    let signer =
        H7H89ProductionGrantSigner::from_seed("grant-fixture", 1, [3; 32]).expect("signer");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let grant = signer
        .sign(
            &agent_id,
            "source",
            "target",
            H7H89ProductionTransition::Upgrade,
            &envelope,
            0,
            2,
            1,
            100,
            200,
        )
        .expect("grant");
    ProductionReleaseRequestV1 {
        schema_version: 1,
        operation_id: "caller-1".to_string(),
        agent_id,
        grant,
        h7_envelope: envelope,
    }
}

fn terminal(request: &ProductionReleaseRequestV1) -> ProductionMutationState {
    let mut receipt = ProductionMutationReceipt::queued(&request.grant, 1);
    receipt.status = ProductionMutationStatus::Committed;
    ProductionMutationState {
        receipt,
        intent_sha256: Sha256Digest::for_bytes(b"intent"),
        release_transaction_sha256: Some(Sha256Digest::for_bytes(b"transaction")),
    }
}

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn recovery_fixture(
    request: &ProductionReleaseRequestV1,
) -> (
    ProductionRecoveryDecision,
    DurableReleaseTransaction,
    DurableReleaseTransaction,
    ProductionMutationState,
) {
    let frontier = digest("frontier");
    let source_manifest = digest("source-manifest");
    let source_agentd = digest("source-agentd");
    let source_matrixd = digest("source-matrixd");
    let target_manifest = digest("target-manifest");
    let target_agentd = digest("target-agentd");
    let target_matrixd = digest("target-matrixd");
    let source = ReleaseBinding {
        release_id: ReleaseId::parse("source").expect("source release"),
        manifest_sha256: source_manifest.as_str().to_string(),
        agentd_program_sha256: source_agentd.as_str().to_string(),
        matrixd_program_sha256: Some(source_matrixd.as_str().to_string()),
        admission_frontier_sha256: frontier.as_str().to_string(),
    };
    let target = ReleaseBinding {
        release_id: ReleaseId::parse("target").expect("target release"),
        manifest_sha256: target_manifest.as_str().to_string(),
        agentd_program_sha256: target_agentd.as_str().to_string(),
        matrixd_program_sha256: Some(target_matrixd.as_str().to_string()),
        admission_frontier_sha256: frontier.as_str().to_string(),
    };
    let pending = DurableReleaseTransaction::new(
        request.agent_id.to_string(),
        ReleaseTransactionKind::Upgrade,
        "source",
        "target",
        None,
        Some(source),
        Some(target),
        1,
        2,
    )
    .expect("transaction")
    .with_authority(
        request.grant.grant_sha256.clone(),
        request.grant.authority_epoch,
    )
    .expect("authority")
    .with_phase(ReleaseTransactionPhase::RecoveryRequired)
    .expect("recovery required");
    let intent = digest("recovery-intent");
    let signer = H7H89ProductionGrantSigner::from_seed("recovery-fixture", 2, [4; 32])
        .expect("recovery signer");
    let decision = signer
        .sign_recovery(
            &request.agent_id,
            request.grant.grant_sha256.clone(),
            intent.clone(),
            pending.transaction_sha256.clone(),
            "target",
            target_manifest,
            target_agentd,
            Some(target_matrixd),
            ProductionRecoveryOutcome::Committed,
            3,
            7,
            100,
            200,
        )
        .expect("decision");
    let resolved = pending
        .with_recovery_resolution(
            ReleaseTransactionPhase::Committed,
            decision.digest().clone(),
        )
        .expect("resolved transaction");
    let mut receipt = ProductionMutationReceipt::queued(&request.grant, 1);
    receipt.status = ProductionMutationStatus::Committed;
    let state = ProductionMutationState {
        receipt,
        intent_sha256: intent,
        release_transaction_sha256: Some(resolved.transaction_sha256.clone()),
    };
    (decision, pending, resolved, state)
}

#[tokio::test]
async fn terminal_history_does_not_query_or_downgrade_when_owner_is_unavailable() {
    let temp = tempfile::tempdir().expect("temp");
    let request = request();
    let client = SupervisordClient::new(temp.path().join("absent.sock")).expect("client");
    let controller = ProductionReleaseController::new(client, temp.path().join("journal.json"))
        .expect("controller");
    let mut journal =
        ProductionReleaseJournalV1::prepared(&request, request.digest().expect("digest"));
    journal
        .observe(&request, terminal(&request))
        .expect("terminal");
    write_journal(&controller.journal_path, &mut journal).expect("publish");
    assert_eq!(
        controller
            .recover(&request, Duration::ZERO)
            .await
            .expect("retained result"),
        journal
    );
    assert_eq!(
        controller
            .dispatch(&request, Duration::ZERO)
            .await
            .expect("no resend"),
        journal
    );
}

#[test]
fn every_receipt_context_field_is_checked_not_only_grant_digest() {
    let request = request();
    for variant in 0..4 {
        let mut state = terminal(&request);
        match variant {
            0 => state.receipt.source_release = "other-source".to_string(),
            1 => state.receipt.target_release = "other-target".to_string(),
            2 => state.receipt.control_revision += 1,
            3 => state.receipt.agent_id = "other-agent".to_string(),
            _ => unreachable!(),
        }
        let mut journal =
            ProductionReleaseJournalV1::prepared(&request, request.digest().expect("digest"));
        assert!(journal.observe(&request, state).is_err());
        assert_eq!(journal.status, ProductionReleaseCallerStatusV1::Prepared);
    }
}

#[test]
fn terminal_recovery_binds_decision_and_reconstructs_its_predecessor() {
    let request = request();
    let (decision, pending, resolved, state) = recovery_fixture(&request);
    validate_terminal_recovery(&request, &decision, &state, &resolved)
        .expect("terminal recovery evidence");
    assert_eq!(
        resolved
            .with_phase(ReleaseTransactionPhase::RecoveryRequired)
            .expect("reconstruct pending")
            .transaction_sha256,
        pending.transaction_sha256
    );

    let mismatched = pending
        .with_recovery_resolution(ReleaseTransactionPhase::Committed, digest("other-decision"))
        .expect("mismatched terminal");
    let mut mismatched_state = state;
    mismatched_state.release_transaction_sha256 = Some(mismatched.transaction_sha256.clone());
    assert!(
        validate_terminal_recovery(&request, &decision, &mismatched_state, &mismatched).is_err()
    );
}

#[test]
fn recovery_audit_boundary_round_trips_and_rejects_incoherent_replay_state() {
    let temp = tempfile::tempdir().expect("temp");
    let path = temp.path().join("journal.json");
    let request = request();
    let (decision, pending, _, _) = recovery_fixture(&request);
    let mut receipt = ProductionMutationReceipt::queued(&request.grant, 1);
    receipt.status = ProductionMutationStatus::RecoveryRequired;
    let pending_state = ProductionMutationState {
        receipt,
        intent_sha256: decision.intent_sha256.clone(),
        release_transaction_sha256: Some(pending.transaction_sha256),
    };
    let mut journal =
        ProductionReleaseJournalV1::prepared(&request, request.digest().expect("digest"));
    journal
        .observe(&request, pending_state)
        .expect("observe pending recovery");
    journal.recovery_decision_sha256 = Some(decision.digest().clone());
    journal.recovery_resolution_submitted = true;
    write_journal(&path, &mut journal).expect("publish recovery audit");
    assert_eq!(read_journal(&path).expect("read journal"), Some(journal.clone()));

    let mut incoherent = journal;
    incoherent.status = ProductionReleaseCallerStatusV1::Accepted;
    incoherent.journal_sha256 = incoherent.digest().expect("journal digest");
    assert!(
        incoherent
            .validate_request(&request, &request.digest().expect("request digest"))
            .is_err()
    );
}

#[test]
fn bounded_reader_accepts_only_tagged_production_recovery_output() {
    let temp = tempfile::tempdir().expect("temp");
    let request = request();
    let (decision, _, _, _) = recovery_fixture(&request);
    let path = temp.path().join("decision.json");
    std::fs::write(
        &path,
        serde_json::to_vec(&SignResponse::ProductionRecovery {
            decision: decision.clone(),
        })
        .expect("encode decision"),
    )
    .expect("write decision");
    assert_eq!(
        read_production_recovery_decision(&path).expect("read decision"),
        decision
    );

    std::fs::write(
        &path,
        serde_json::to_vec(&SignResponse::ProductionGrant {
            grant: request.grant.clone(),
        })
        .expect("encode grant"),
    )
    .expect("write wrong operation");
    assert!(read_production_recovery_decision(&path).is_err());
}

#[test]
fn corrupt_journal_is_not_reinterpreted_as_a_fresh_operation() {
    let temp = tempfile::tempdir().expect("temp");
    let path = temp.path().join("journal.json");
    let request = request();
    let mut journal =
        ProductionReleaseJournalV1::prepared(&request, request.digest().expect("digest"));
    write_journal(&path, &mut journal).expect("publish");
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).expect("read")).expect("json");
    value["status"] = serde_json::json!("committed");
    std::fs::write(&path, serde_json::to_vec(&value).expect("json")).expect("corrupt");
    assert!(read_journal(&path).is_err());
    std::fs::write(&path, b"{").expect("truncate");
    assert!(read_journal(&path).is_err());
}

#[cfg(unix)]
#[test]
fn symlink_journals_and_competing_writers_are_rejected() {
    let temp = tempfile::tempdir().expect("temp");
    let path = temp.path().join("journal.json");
    let lock = JournalLock::acquire(&path).expect("writer");
    assert!(matches!(
        JournalLock::acquire(&path),
        Err(ProductionReleaseControllerError::Busy)
    ));
    drop(lock);
    let _next = JournalLock::acquire(&path).expect("handoff");
    std::os::unix::fs::symlink(temp.path().join("absent"), &path).expect("dangling symlink");
    assert!(validate_journal_path(&path).is_err());
    assert!(read_journal(&path).is_err());
}

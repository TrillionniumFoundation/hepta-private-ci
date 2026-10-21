use super::*;
use crate::SignedIntentRecoveryDirective;
use crate::SignedIntentStatus;
use crate::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;
use crate::signed_intent::write_recovery_directive;
use pretty_assertions::assert_eq;

#[test]
fn signed_recovery_and_abort_do_not_spend_or_resume_pending_restart() -> Result<(), SupervisorError>
{
    for status in [
        SignedIntentStatus::RecoveryRequired,
        SignedIntentStatus::Aborted,
    ] {
        let fleet = TestFleet::new()?;
        let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
        let intent = SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"grant"),
            fleet.first.to_string(),
            crate::H7H89ProductionTransition::Upgrade,
            "source",
            "target",
            1,
            1,
            1,
            status,
        )
        .unwrap();
        write_intent(record.layout.run_root(), &intent).unwrap();
        crate::restart_budget::claim_restart(
            record.layout.run_root(),
            3,
            Duration::from_secs(60),
            Duration::ZERO,
        )
        .unwrap();
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut recovered, _) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert!(recovered.snapshot(&fleet.first).unwrap().restart_pending);
        assert_eq!(
            recovered.tick(now + Duration::from_secs(1)),
            TickReport::default()
        );
        assert_eq!(control.spawn_count(&fleet.first), 0);
        let pending = crate::restart_budget::pending_restart(
            record.layout.run_root(),
            /*maximum_attempts*/ 3,
        )
        .unwrap()
        .expect("unresolved restart remains durable");
        assert_eq!(pending.attempt, 1);
        assert_eq!(read_intent(record.layout.run_root()).unwrap(), Some(intent));
    }
    Ok(())
}

#[test]
fn exact_abort_fences_adopted_process_before_terminal_publication() -> Result<(), SupervisorError> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("abort-source")?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"grant"),
        fleet.first.to_string(),
        crate::H7H89ProductionTransition::Upgrade,
        "abort-source",
        "abort-target",
        1,
        record.lifecycle.generation,
        1,
        SignedIntentStatus::Queued,
    )
    .unwrap();
    write_intent(record.layout.run_root(), &intent).unwrap();
    write_recovery_directive(
        record.layout.run_root(),
        &SignedIntentRecoveryDirective::abort(intent.intent_sha256).unwrap(),
    )
    .unwrap();
    drop(supervisor);
    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(control.counts(&fleet.first), (0, 0, 1));
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 1));
    assert_eq!(control.counts(&fleet.second), (0, 0, 0));
    assert_eq!(control.matrix_counts(&fleet.second), (0, 0, 0));
    let snapshot = recovered.snapshot(&fleet.first).unwrap();
    assert!(snapshot.runtime_fenced);
    assert_eq!(
        snapshot.runtime_phase,
        Some(crate::ControlRuntimePhase::Killing)
    );
    assert!(recovered.production_recovery_required(&fleet.first)?);
    assert_eq!(
        read_intent(record.layout.run_root())
            .unwrap()
            .unwrap()
            .status,
        SignedIntentStatus::Aborted
    );
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .unwrap()
            .release_state,
        record.release_state
    );
    Ok(())
}

#[test]
fn signed_outcome_verifier_rejects_wrong_key_stale_intent_and_expiry() {
    let agent = AgentId::parse(FIRST_AGENT_ID).unwrap();
    let signer =
        crate::H7H89ProductionGrantSigner::from_seed("operator", /*signer_epoch*/ 4, [9; 32])
            .unwrap();
    let wrong =
        crate::H7H89ProductionGrantSigner::from_seed("operator", /*signer_epoch*/ 4, [8; 32])
            .unwrap();
    let decision = signer
        .sign_recovery(
            &agent,
            Sha256Digest::for_bytes(b"grant"),
            Sha256Digest::for_bytes(b"intent"),
            Sha256Digest::for_bytes(b"transaction"),
            "source",
            Sha256Digest::for_bytes(b"manifest"),
            Sha256Digest::for_bytes(b"agentd"),
            /*observed_matrixd_sha256*/ None,
            crate::ProductionRecoveryOutcome::RolledBack,
            /*expected_lifecycle_generation*/ 2,
            /*authority_epoch*/ 3,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 200,
        )
        .unwrap();
    let verify = |key, intent: &Sha256Digest, now| {
        crate::H7H89ProductionGrantVerifier::new("operator", /*signer_epoch*/ 4, key)
            .unwrap()
            .verify_recovery(
                &decision,
                &agent,
                &decision.grant_sha256,
                intent,
                &decision.release_transaction_sha256,
                "source",
                &decision.observed_manifest_sha256,
                &decision.observed_agentd_sha256,
                /*expected_matrixd_sha256*/ None,
                /*expected_lifecycle_generation*/ 2,
                /*expected_authority_epoch*/ 3,
                now,
            )
    };
    assert!(
        verify(
            signer.verifying_key(),
            &decision.intent_sha256,
            /*now*/ 150
        )
        .is_ok()
    );
    assert!(
        verify(
            wrong.verifying_key(),
            &decision.intent_sha256,
            /*now*/ 150
        )
        .is_err()
    );
    assert!(
        verify(
            signer.verifying_key(),
            &Sha256Digest::for_bytes(b"new intent"),
            /*now*/ 150
        )
        .is_err()
    );
    assert!(
        verify(
            signer.verifying_key(),
            &decision.intent_sha256,
            /*now*/ 200
        )
        .is_err()
    );
}

#[test]
fn aborted_intent_requires_signed_outcome_and_recovers_its_publication_crash_cut()
-> Result<(), SupervisorError> {
    use crate::release_transaction::*;
    for mode in ["signed resolution", "signed crash cut", "ordinary terminal"] {
        let fleet = TestFleet::new()?;
        let source = admitted_release(&fleet, &fleet.first, "signed-abort-source")?;
        let target = admitted_release(&fleet, &fleet.first, "signed-abort-target")?;
        fleet.registry.compare_and_set_release_state(
            &fleet.first,
            /*expected_generation*/ 0,
            Some(source.release_id().clone()),
            /*previous*/ None,
        )?;
        let starting = fleet.registry.compare_and_transition(
            &fleet.first,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )?;
        fleet.registry.compare_and_transition(
            &fleet.first,
            starting.generation,
            AgentLifecycle::Failed,
        )?;
        let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
        let source_binding = fleet
            .registry
            .resolve_release_binding(&fleet.first, source.release_id())?;
        let target_binding = fleet
            .registry
            .resolve_release_binding(&fleet.first, target.release_id())?;
        let intent = SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"grant"),
            fleet.first.to_string(),
            crate::H7H89ProductionTransition::Upgrade,
            source.identity(),
            target.identity(),
            /*expected_control_revision*/ 1,
            record.lifecycle.generation,
            /*authority_epoch*/ 3,
            SignedIntentStatus::Aborted,
        )
        .unwrap();
        write_intent(record.layout.run_root(), &intent).unwrap();
        let transaction = DurableReleaseTransaction::new(
            fleet.first.to_string(),
            ReleaseTransactionKind::Upgrade,
            source.identity(),
            target.identity(),
            /*rollback_predecessor*/ None,
            Some(source_binding.clone()),
            Some(target_binding),
            record.release_state.generation,
            record.lifecycle.generation,
        )
        .unwrap()
        .with_authority(intent.grant_sha256.clone(), /*authority_epoch*/ 3)
        .unwrap()
        .with_phase(ReleaseTransactionPhase::RecoveryRequired)
        .unwrap();
        write_release_transaction(record.layout.run_root(), &transaction).unwrap();
        let signer = crate::H7H89ProductionGrantSigner::from_seed(
            "operator", /*signer_epoch*/ 4, [9; 32],
        )
        .unwrap();
        let decision = signer
            .sign_recovery(
                &fleet.first,
                intent.grant_sha256.clone(),
                intent.intent_sha256.clone(),
                transaction.transaction_sha256.clone(),
                source.identity(),
                Sha256Digest::parse(source_binding.manifest_sha256).unwrap(),
                Sha256Digest::parse(source_binding.agentd_program_sha256).unwrap(),
                source_binding
                    .matrixd_program_sha256
                    .map(|value| Sha256Digest::parse(value).unwrap()),
                crate::ProductionRecoveryOutcome::RolledBack,
                record.lifecycle.generation,
                /*authority_epoch*/ 3,
                /*issued_at_unix_seconds*/ 100,
                /*expires_at_unix_seconds*/ 200,
            )
            .unwrap();
        if mode != "signed resolution" {
            let terminal = if mode == "signed crash cut" {
                transaction
                    .with_recovery_resolution(
                        ReleaseTransactionPhase::RolledBack,
                        decision.digest().clone(),
                    )
                    .unwrap()
            } else {
                transaction
                    .with_phase(ReleaseTransactionPhase::RolledBack)
                    .unwrap()
            };
            write_release_transaction(record.layout.run_root(), &terminal).unwrap();
        }
        let (mut recovered, _) = Supervisor::recover(
            fleet.registry.clone(),
            FakeControl::default().driver(),
            config(),
            Instant::now(),
        )?;
        if mode == "signed resolution" {
            let verifier = crate::H7H89ProductionGrantVerifier::new(
                "operator",
                /*signer_epoch*/ 4,
                signer.verifying_key(),
            )
            .unwrap();
            recovered.resolve_production_recovery(
                &fleet.first,
                &decision,
                &verifier,
                /*expected_authority_epoch*/ 3,
                /*now_unix_seconds*/ 150,
            )?;
            assert!(
                recovered
                    .resolve_production_recovery(
                        &fleet.first,
                        &decision,
                        &verifier,
                        /*expected_authority_epoch*/ 3,
                        /*now_unix_seconds*/ 150
                    )
                    .is_err()
            );
        }
        let expected = if mode == "ordinary terminal" {
            SignedIntentStatus::Aborted
        } else {
            SignedIntentStatus::RolledBack
        };
        assert_eq!(
            read_intent(record.layout.run_root())
                .unwrap()
                .unwrap()
                .status,
            expected
        );
        assert_eq!(
            recovered.production_recovery_required(&fleet.first)?,
            mode == "ordinary terminal"
        );
        assert_eq!(
            fleet
                .registry
                .load()?
                .agent(&fleet.first)
                .unwrap()
                .release_state,
            record.release_state
        );
    }
    Ok(())
}

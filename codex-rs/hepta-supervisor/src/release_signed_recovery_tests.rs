//! Exact signed recovery frontiers, receipt association, and publication retries.

use super::*;

use pretty_assertions::assert_eq;

fn recovery_signing_fixture() -> (
    crate::signed_authority::H7H89ProductionGrantSigner,
    codex_hepta_memory::H7SignedArtifactEnvelope,
    crate::H7H89ProductionGrantVerifier,
) {
    use codex_hepta_memory::H7ArtifactSigner;
    use codex_hepta_memory::H7QualificationRuntime;
    use codex_hepta_memory::H7SignedArtifactTransition;
    let mut runtime = H7QualificationRuntime::new();
    let event = codex_hepta_memory::H7TrajectoryEvent::new(
        "rollback-recovery-trajectory",
        /*event_seq*/ 1,
        "rollback",
        /*reward_bps*/ 100,
        /*safety_ok*/ true,
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        Sha256Digest::for_bytes(b"rollback-recovery-fence"),
    )
    .expect("trajectory event");
    runtime
        .append_trajectory_event(event)
        .expect("append trajectory");
    runtime
        .evaluate_trajectory("rollback-recovery-trajectory")
        .expect("evaluate trajectory");
    let artifact = runtime
        .propose_artifact(
            "rollback-recovery-artifact",
            "rollback-recovery-trajectory",
            /*generation*/ 1,
        )
        .expect("artifact");
    let h7_signer = H7ArtifactSigner::from_seed("recovery-h7", /*signer_epoch*/ 1, [67; 32])
        .expect("H7 signer");
    let envelope = h7_signer
        .sign(
            &artifact,
            /*ope*/ None,
            H7SignedArtifactTransition::Rollback,
            /*expected_runtime_generation*/ 0,
            Some(Sha256Digest::for_bytes(b"reviewed-H7-predecessor")),
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 200,
        )
        .expect("H7 envelope");
    let signer = crate::signed_authority::H7H89ProductionGrantSigner::from_seed(
        "recovery-operator",
        /*signer_epoch*/ 4,
        [71; 32],
    )
    .expect("operator signer");
    let verifier = crate::H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "recovery-operator",
        /*signer_epoch*/ 4,
        signer.verifying_key(),
        h7_signer.verifier(),
    )
    .expect("operator verifier");
    (signer, envelope, verifier)
}

#[test]
fn signed_explicit_rollback_source_restoration_can_recover_without_new_dispatch()
-> Result<(), SupervisorError> {
    for drift in [
        "none",
        "generation",
        "predecessor",
        "release_transaction.file_write",
        "release_transaction.file_sync",
        "release_transaction.rename",
        "release_transaction.directory_sync",
        "signed_intent.file_write",
        "signed_intent.file_sync",
        "signed_intent.rename",
        "signed_intent.directory_sync",
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        supervisor.upgrade(
            &fleet.first,
            admitted_release(&fleet, &fleet.first, "signed-rollback-source")?,
            now,
        )?;
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        let before = supervisor.record(&fleet.first)?;
        let source_selection = before.release_state.clone();
        let snapshot = supervisor.snapshot(&fleet.first).expect("source snapshot");
        let (signer, envelope, verifier) = recovery_signing_fixture();
        let grant = signer
            .sign(
                &fleet.first,
                "signed-rollback-source",
                "retry-source",
                H7H89ProductionTransition::Rollback,
                &envelope,
                snapshot.control_revision,
                before.lifecycle.generation,
                /*authority_epoch*/ 7,
                /*issued_at_unix_seconds*/ 100,
                /*expires_at_unix_seconds*/ 200,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let target = fleet
            .registry
            .resolve_release(&fleet.first, &ReleaseId::parse("retry-source")?)?;
        control.reject_spawn_program(target.program);
        supervisor.apply_production_grant(
            &fleet.first,
            &grant,
            &envelope,
            &verifier,
            /*expected_authority_epoch*/ 7,
            /*now_unix_seconds*/ 150,
            now,
        )?;
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        assert_eq!(control.spawn_count(&fleet.first), 3);
        control.set_healthy(&fleet.first);
        let failed =
            with_qualification_fault("release_transaction.file_write", ErrorKind::Other, || {
                supervisor.tick(now)
            });
        assert_eq!(failed.faults.len(), 1);
        assert_eq!(
            supervisor.record(&fleet.first)?.release_state,
            source_selection
        );
        drop(supervisor);
        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert!(recovered.production_recovery_required(&fleet.first)?);
        control.set_exit(&fleet.first);
        assert_eq!(recovered.tick(now), TickReport::default());
        let record = recovered.record(&fleet.first)?;
        let intent = read_intent(record.layout.run_root())
            .expect("quarantined intent")
            .expect("intent");
        let transaction = read_release_transaction(record.layout.run_root())
            .expect("quarantined transaction")
            .expect("transaction");
        assert_eq!(intent.status, SignedIntentStatus::RecoveryRequired);
        assert_eq!(transaction.phase, ReleaseTransactionPhase::RecoveryRequired);
        let binding = fleet
            .registry
            .resolve_release_binding(&fleet.first, &ReleaseId::parse("signed-rollback-source")?)?;
        let decision = signer
            .sign_recovery(
                &fleet.first,
                intent.grant_sha256.clone(),
                intent.intent_sha256.clone(),
                transaction.transaction_sha256.clone(),
                "signed-rollback-source",
                Sha256Digest::parse(binding.manifest_sha256).expect("validated manifest digest"),
                Sha256Digest::parse(binding.agentd_program_sha256)
                    .expect("validated agentd digest"),
                binding
                    .matrixd_program_sha256
                    .map(|value| Sha256Digest::parse(value).expect("validated Matrix digest")),
                crate::ProductionRecoveryOutcome::RolledBack,
                record.lifecycle.generation,
                /*authority_epoch*/ 8,
                /*issued_at_unix_seconds*/ 110,
                /*expires_at_unix_seconds*/ 190,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if matches!(drift, "generation" | "predecessor") {
            fleet.registry.compare_and_set_release_state(
                &fleet.first,
                record.release_state.generation,
                record.release_state.current.clone(),
                if drift == "generation" {
                    record.release_state.previous.clone()
                } else {
                    Some(ReleaseId::parse("other-predecessor")?)
                },
            )?;
        }
        let observed = recovered.record(&fleet.first)?.release_state;
        let revision = recovered
            .snapshot(&fleet.first)
            .expect("quarantined snapshot")
            .control_revision;
        if drift.contains('.') {
            let failed = with_qualification_fault(drift, ErrorKind::Other, || {
                recovered.resolve_production_recovery(
                    &fleet.first,
                    &decision,
                    &verifier,
                    /*expected_authority_epoch*/ 8,
                    /*now_unix_seconds*/ 150,
                )
            });
            assert!(failed.is_err(), "{drift}");
            assert!(
                recovered.production_recovery_required(&fleet.first)?,
                "{drift}"
            );
            assert_eq!(
                recovered
                    .snapshot(&fleet.first)
                    .expect("pending acknowledgment")
                    .control_revision,
                revision,
                "{drift}"
            );
            let published_transaction = read_release_transaction(record.layout.run_root())
                .expect("transaction after failed publication")
                .expect("transaction");
            let published_intent = read_intent(record.layout.run_root())
                .expect("intent after failed publication")
                .expect("intent");
            let terminal_transaction_published = drift.starts_with("signed_intent.")
                || drift == "release_transaction.directory_sync";
            assert_eq!(
                published_transaction.phase,
                if terminal_transaction_published {
                    ReleaseTransactionPhase::RolledBack
                } else {
                    ReleaseTransactionPhase::RecoveryRequired
                },
                "{drift}"
            );
            assert_eq!(
                published_intent.status,
                if drift == "signed_intent.directory_sync" {
                    SignedIntentStatus::RolledBack
                } else {
                    SignedIntentStatus::RecoveryRequired
                },
                "{drift}"
            );
            for (epoch, time) in [(8, 190), (9, 150)] {
                assert!(
                    recovered
                        .resolve_production_recovery(
                            &fleet.first,
                            &decision,
                            &verifier,
                            epoch,
                            time,
                        )
                        .is_err(),
                    "{drift} rejects changed authority or expired decision"
                );
            }
            let mut tampered = decision.clone();
            tampered.signature_base64 = "invalid-signature".to_string();
            assert!(
                recovered
                    .resolve_production_recovery(
                        &fleet.first,
                        &tampered,
                        &verifier,
                        /*expected_authority_epoch*/ 8,
                        /*now_unix_seconds*/ 150,
                    )
                    .is_err(),
                "{drift} rejects a tampered replay signature"
            );
            if terminal_transaction_published {
                let other_decision = signer
                    .sign_recovery(
                        &fleet.first,
                        decision.grant_sha256.clone(),
                        decision.intent_sha256.clone(),
                        decision.release_transaction_sha256.clone(),
                        decision.observed_release.clone(),
                        decision.observed_manifest_sha256.clone(),
                        decision.observed_agentd_sha256.clone(),
                        decision.observed_matrixd_sha256.clone(),
                        decision.outcome,
                        decision.expected_lifecycle_generation,
                        /*authority_epoch*/ 8,
                        /*issued_at_unix_seconds*/ 111,
                        /*expires_at_unix_seconds*/ 190,
                    )
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                assert_ne!(other_decision.digest(), decision.digest());
                assert!(
                    recovered
                        .resolve_production_recovery(
                            &fleet.first,
                            &other_decision,
                            &verifier,
                            /*expected_authority_epoch*/ 8,
                            /*now_unix_seconds*/ 150,
                        )
                        .is_err(),
                    "{drift} rejects another valid signed decision after publication"
                );
            }
            assert_eq!(
                read_release_transaction(record.layout.run_root())
                    .expect("unmodified transaction after denied retries")
                    .expect("transaction"),
                published_transaction,
                "{drift}"
            );
            assert_eq!(
                read_intent(record.layout.run_root())
                    .expect("unmodified intent after denied retries")
                    .expect("intent"),
                published_intent,
                "{drift}"
            );
        }
        let outcome = recovered.resolve_production_recovery(
            &fleet.first,
            &decision,
            &verifier,
            /*expected_authority_epoch*/ 8,
            /*now_unix_seconds*/ 150,
        );
        if matches!(drift, "generation" | "predecessor") {
            assert!(
                matches!(outcome, Err(SupervisorError::Invalid(_))),
                "{drift}"
            );
            assert!(recovered.production_recovery_required(&fleet.first)?);
            assert_eq!(
                read_release_transaction(record.layout.run_root())
                    .expect("unchanged transaction")
                    .expect("transaction"),
                transaction
            );
        } else {
            let receipt = outcome?;
            assert_eq!(receipt.status, crate::ProductionMutationStatus::RolledBack);
            assert_eq!(receipt.control_revision, revision + 1, "{drift}");
            assert!(!recovered.production_recovery_required(&fleet.first)?);
            let resolved = read_release_transaction(record.layout.run_root())
                .expect("resolved transaction")
                .expect("transaction");
            assert_eq!(resolved.phase, ReleaseTransactionPhase::RolledBack);
            assert_eq!(
                resolved.recovery_decision_sha256.as_ref(),
                Some(decision.digest())
            );
            let replay =
                with_qualification_fault("signed_intent.file_write", ErrorKind::Other, || {
                    recovered.resolve_production_recovery(
                        &fleet.first,
                        &decision,
                        &verifier,
                        /*expected_authority_epoch*/ 8,
                        /*now_unix_seconds*/ 150,
                    )
                })?;
            assert_eq!(replay, receipt, "{drift} acknowledged replay is idempotent");
            assert_eq!(
                recovered
                    .snapshot(&fleet.first)
                    .expect("resolved snapshot")
                    .control_revision,
                receipt.control_revision,
                "{drift}"
            );
            drop(recovered);
            let (next_owner, report) =
                Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
            assert_eq!(report, TickReport::default());
            recovered = next_owner;
            assert_eq!(
                recovered
                    .snapshot(&fleet.first)
                    .expect("new owner snapshot")
                    .control_revision,
                0
            );
            // Direct in-process callers supply the expected authority epoch.
            // The daemon supplies a fresh epoch and rejects this old decision.
            let new_owner_receipt = recovered.resolve_production_recovery(
                &fleet.first,
                &decision,
                &verifier,
                /*expected_authority_epoch*/ 8,
                /*now_unix_seconds*/ 150,
            )?;
            assert_eq!(new_owner_receipt.control_revision, 1, "{drift}");
            assert_eq!(
                recovered.resolve_production_recovery(
                    &fleet.first,
                    &decision,
                    &verifier,
                    /*expected_authority_epoch*/ 8,
                    /*now_unix_seconds*/ 150,
                )?,
                new_owner_receipt,
                "{drift} new owner acknowledgment charges once"
            );
            fleet
                .registry
                .revoke_release(&fleet.first, &ReleaseId::parse("signed-rollback-source")?)?;
            assert!(
                recovered
                    .resolve_production_recovery(
                        &fleet.first,
                        &decision,
                        &verifier,
                        /*expected_authority_epoch*/ 8,
                        /*now_unix_seconds*/ 150,
                    )
                    .is_err(),
                "{drift} replay rechecks current catalog admission"
            );
            assert_eq!(
                read_release_transaction(record.layout.run_root())
                    .expect("terminal transaction after revoked replay")
                    .expect("transaction"),
                resolved,
                "{drift}"
            );
        }
        assert_eq!(recovered.record(&fleet.first)?.release_state, observed);
        assert_eq!(control.spawn_count(&fleet.first), 3);
    }
    Ok(())
}

#[test]
fn prior_signed_receipt_does_not_report_a_later_unsigned_transaction_digest()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    queue_signed_change(
        &mut supervisor,
        &fleet,
        admitted_release(&fleet, &fleet.first, "signed-receipt-target")?,
        now,
        H7H89ProductionTransition::Upgrade,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let signed = supervisor
        .production_mutation_state(&fleet.first)?
        .expect("signed receipt");
    assert!(signed.release_transaction_sha256.is_some());
    supervisor.upgrade(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "later-unsigned-target")?,
        now,
    )?;
    let current = supervisor
        .production_mutation_state(&fleet.first)?
        .expect("prior signed receipt");
    assert_eq!(current.receipt, signed.receipt);
    assert_eq!(current.intent_sha256, signed.intent_sha256);
    assert_eq!(current.release_transaction_sha256, None);
    Ok(())
}

#[test]
fn terminal_signed_transaction_cannot_close_intent_after_unrelated_generation_change()
-> Result<(), SupervisorError> {
    for (transition, reject_target) in [
        (H7H89ProductionTransition::Upgrade, false),
        (H7H89ProductionTransition::Rollback, false),
        (H7H89ProductionTransition::Rollback, true),
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        let target = admitted_release(&fleet, &fleet.first, "constructor-frontier-target")?;
        if reject_target {
            control.reject_spawn_program(target.command().program.clone());
        }
        queue_signed_change(&mut supervisor, &fleet, target, now, transition)?;
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        control.set_healthy(&fleet.first);
        let failed = with_qualification_fault("signed_intent.file_write", ErrorKind::Other, || {
            supervisor.tick(now)
        });
        assert_eq!(failed.faults.len(), 1);
        let record = supervisor.record(&fleet.first)?;
        let transaction = read_release_transaction(record.layout.run_root())
            .expect("terminal transaction")
            .expect("transaction");
        assert!(matches!(
            transaction.phase,
            ReleaseTransactionPhase::Committed | ReleaseTransactionPhase::RolledBack
        ));
        assert_eq!(
            read_intent(record.layout.run_root())
                .expect("queued intent")
                .expect("intent")
                .status,
            SignedIntentStatus::Queued
        );
        let drifted = fleet.registry.compare_and_set_release_state(
            &fleet.first,
            record.release_state.generation,
            record.release_state.current,
            record.release_state.previous,
        )?;
        let spawns = control.spawn_count(&fleet.first);
        assert_eq!(supervisor.tick(now).faults.len(), 1);
        assert_eq!(
            read_intent(record.layout.run_root())
                .expect("still queued after live frontier rejection")
                .expect("intent")
                .status,
            SignedIntentStatus::Queued
        );
        drop(supervisor);
        let (recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert!(recovered.production_recovery_required(&fleet.first)?);
        assert_eq!(recovered.record(&fleet.first)?.release_state, drifted);
        assert_eq!(
            read_intent(record.layout.run_root())
                .expect("quarantined intent")
                .expect("intent")
                .status,
            SignedIntentStatus::RecoveryRequired
        );
        assert_eq!(
            read_release_transaction(record.layout.run_root())
                .expect("detached terminal transaction")
                .expect("transaction"),
            transaction
        );
        assert_eq!(control.spawn_count(&fleet.first), spawns);
    }
    Ok(())
}

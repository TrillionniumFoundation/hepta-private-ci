use super::*;
use crate::SignedIntentStatus;
use pretty_assertions::assert_eq;

fn signed_h7_envelope(
    transition: codex_hepta_memory::H7SignedArtifactTransition,
) -> (
    codex_hepta_memory::H7SignedArtifactEnvelope,
    codex_hepta_memory::H7ArtifactVerifier,
) {
    let mut runtime = codex_hepta_memory::H7QualificationRuntime::new();
    let event = codex_hepta_memory::H7TrajectoryEvent::new(
        "supervisor-production-trajectory",
        1,
        transition.as_str(),
        100,
        /*accepted*/ true,
        1,
        1,
        1,
        Sha256Digest::for_bytes(b"supervisor-production-fence"),
    )
    .expect("H7 trajectory event");
    runtime
        .append_trajectory_event(event)
        .expect("append H7 trajectory event");
    runtime
        .evaluate_trajectory("supervisor-production-trajectory")
        .expect("evaluate H7 trajectory");
    let artifact = runtime
        .propose_artifact(
            "supervisor-production-artifact",
            "supervisor-production-trajectory",
            1,
        )
        .expect("propose H7 artifact");
    let signer =
        codex_hepta_memory::H7ArtifactSigner::from_seed("supervisor-h7-signer", 3, [7; 32])
            .expect("H7 signer");
    let envelope = signer
        .sign(
            &artifact,
            None,
            transition,
            0,
            (transition == codex_hepta_memory::H7SignedArtifactTransition::Rollback)
                .then(|| artifact.body_sha256.clone()),
            100,
            200,
        )
        .expect("sign H7 envelope");
    (envelope, signer.verifier())
}

#[test]
fn signed_upgrade_rejects_stale_authority_before_effect_and_commits_valid_grant()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let source = admitted_release(&fleet, &fleet.first, "signed-upgrade-source")?;
    let target = admitted_release(&fleet, &fleet.first, "signed-upgrade-target")?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, recovered) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    supervisor.start_release(&fleet.first, source.clone(), now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    let generation = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .expect("registered Agent")
        .lifecycle
        .generation;
    let (envelope, h7_verifier) =
        signed_h7_envelope(codex_hepta_memory::H7SignedArtifactTransition::Reload);
    let signer =
        crate::H7H89ProductionGrantSigner::from_seed("supervisor-production-authority", 9, [9; 32])
            .expect("production grant signer");
    let verifier = crate::H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "supervisor-production-authority",
        9,
        signer.verifying_key(),
        h7_verifier,
    )
    .expect("production grant verifier");
    let authority_epoch = 77;

    let stale = signer
        .sign(
            &fleet.first,
            source.identity(),
            target.identity(),
            crate::H7H89ProductionTransition::Upgrade,
            &envelope,
            1,
            generation,
            authority_epoch,
            100,
            200,
        )
        .expect("stale signed grant");
    let stale_error = supervisor
        .apply_production_grant(
            &fleet.first,
            &stale,
            &envelope,
            &verifier,
            authority_epoch,
            150,
            now,
        )
        .expect_err("stale control revision must be rejected");
    assert!(matches!(
        stale_error,
        SupervisorError::ProductionAuthority(_)
    ));
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));
    let after_rejection = supervisor.snapshot(&fleet.first).expect("snapshot");
    assert_eq!(after_rejection.control_revision, 0);
    assert!(!after_rejection.release_change_pending);
    assert!(
        supervisor
            .production_mutation_state(&fleet.first)?
            .is_none()
    );

    let grant = signer
        .sign(
            &fleet.first,
            source.identity(),
            target.identity(),
            crate::H7H89ProductionTransition::Upgrade,
            &envelope,
            0,
            generation,
            authority_epoch,
            100,
            200,
        )
        .expect("valid signed grant");
    let receipt = supervisor.apply_production_grant(
        &fleet.first,
        &grant,
        &envelope,
        &verifier,
        authority_epoch,
        150,
        now,
    )?;
    assert_eq!(receipt.status, crate::ProductionMutationStatus::Queued);
    assert_eq!(receipt.control_revision, 1);
    assert_eq!(control.counts(&fleet.first), (1, 0, 0));
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("queued signed upgrade")
            .release_change_pending
    );

    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let committed = supervisor
        .production_mutation_state(&fleet.first)?
        .expect("committed production mutation");
    assert_eq!(
        committed.receipt.status,
        crate::ProductionMutationStatus::Committed
    );
    assert_eq!(
        supervisor
            .snapshot(&fleet.first)
            .expect("committed target")
            .active_release
            .as_deref(),
        Some(target.identity())
    );
    Ok(())
}

#[test]
fn signed_rollback_uses_borrowed_slot_and_persists_terminal_result() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let source = admitted_release(&fleet, &fleet.first, "signed-rollback-source")?;
    let target = admitted_release(&fleet, &fleet.first, "signed-rollback-target")?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, recovered) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    supervisor.start_release(&fleet.first, source.clone(), now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    supervisor.upgrade(&fleet.first, target.clone(), now)?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        supervisor
            .snapshot(&fleet.first)
            .expect("unsigned target")
            .previous_release
            .as_deref(),
        Some(source.identity())
    );

    let generation = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .expect("registered Agent")
        .lifecycle
        .generation;
    let (envelope, h7_verifier) =
        signed_h7_envelope(codex_hepta_memory::H7SignedArtifactTransition::Rollback);
    let signer =
        crate::H7H89ProductionGrantSigner::from_seed("supervisor-production-authority", 9, [9; 32])
            .expect("production grant signer");
    let verifier = crate::H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "supervisor-production-authority",
        9,
        signer.verifying_key(),
        h7_verifier,
    )
    .expect("production grant verifier");
    let authority_epoch = 78;
    let grant = signer
        .sign(
            &fleet.first,
            target.identity(),
            source.identity(),
            crate::H7H89ProductionTransition::Rollback,
            &envelope,
            0,
            generation,
            authority_epoch,
            100,
            200,
        )
        .expect("valid signed rollback grant");
    let receipt = supervisor.apply_production_grant(
        &fleet.first,
        &grant,
        &envelope,
        &verifier,
        authority_epoch,
        150,
        now,
    )?;
    assert_eq!(receipt.status, crate::ProductionMutationStatus::Queued);
    assert_eq!(control.counts(&fleet.first).0, 1);

    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let rolled_back = supervisor
        .production_mutation_state(&fleet.first)?
        .expect("terminal rollback state");
    assert_eq!(
        rolled_back.receipt.status,
        crate::ProductionMutationStatus::RolledBack
    );
    assert_eq!(
        supervisor
            .snapshot(&fleet.first)
            .expect("rolled back source")
            .active_release
            .as_deref(),
        Some(source.identity())
    );
    Ok(())
}

#[test]
fn explicit_stop_interrupts_queued_release_without_spawning_after_recovery()
-> Result<(), SupervisorError> {
    for kill in [false, true] {
        let fleet = TestFleet::new()?;
        let source = admitted_release(&fleet, &fleet.first, "interrupt-source")?;
        let target = admitted_release(&fleet, &fleet.first, "interrupt-target")?;
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut supervisor, _) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        supervisor.start_release(&fleet.first, source.clone(), now)?;
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        supervisor.upgrade(&fleet.first, target, now)?;
        if kill {
            supervisor.kill(&fleet.first)?;
        } else {
            supervisor.stop(&fleet.first, now)?;
        }
        control.set_exit(&fleet.first);
        assert_eq!(
            supervisor.tick(now + Duration::from_secs(1)),
            TickReport::default()
        );
        assert!(!supervisor.snapshot(&fleet.first).expect("stopped").active);
        drop(supervisor);
        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert_eq!(
            recovered.tick(now + Duration::from_secs(2)),
            TickReport::default()
        );
        assert!(!recovered.snapshot(&fleet.first).expect("recovered").active);
        assert_eq!(
            recovered
                .snapshot(&fleet.first)
                .expect("release")
                .active_release
                .as_deref(),
            Some(source.identity())
        );
    }
    Ok(())
}

#[test]
fn signed_transaction_publication_failure_after_prepared_is_recovery_required()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let source = admitted_release(&fleet, &fleet.first, "post-prepared-source")?;
    let target = admitted_release(&fleet, &fleet.first, "post-prepared-target")?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start_release(&fleet.first, source.clone(), now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = fleet.registry.load_agent(&fleet.first)?;
    let (envelope, h7_verifier) =
        signed_h7_envelope(codex_hepta_memory::H7SignedArtifactTransition::Reload);
    let signer =
        crate::H7H89ProductionGrantSigner::from_seed("post-prepared-authority", 9, [9; 32])
            .expect("signer");
    let verifier = crate::H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "post-prepared-authority",
        9,
        signer.verifying_key(),
        h7_verifier,
    )
    .expect("verifier");
    let grant = signer
        .sign(
            &fleet.first,
            source.identity(),
            target.identity(),
            crate::H7H89ProductionTransition::Upgrade,
            &envelope,
            0,
            record.lifecycle.generation,
            77,
            100,
            200,
        )
        .expect("grant");
    let transaction_path = record
        .layout
        .run_root()
        .join(crate::release_transaction::RELEASE_TRANSACTION_FILE);
    std::fs::create_dir(&transaction_path)?;
    let error = supervisor
        .apply_production_grant(&fleet.first, &grant, &envelope, &verifier, 77, 150, now)
        .expect_err("transaction publication must fail");
    assert!(matches!(
        error,
        SupervisorError::SignedIntentRecoveryRequired(_)
    ));
    let intent = crate::signed_intent::read_intent(record.layout.run_root())
        .expect("intent readable")
        .expect("Prepared crossed");
    assert_eq!(intent.status, SignedIntentStatus::RecoveryRequired);
    let snapshot = supervisor.snapshot(&fleet.first).expect("fenced slot");
    assert!(snapshot.runtime_fenced && !snapshot.healthy);
    assert!(!snapshot.release_change_pending);
    assert_eq!(snapshot.control_revision, 1);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.counts(&fleet.first).2, 1);
    std::fs::remove_dir(transaction_path)?;
    Ok(())
}

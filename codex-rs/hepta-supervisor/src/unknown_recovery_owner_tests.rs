use super::*;
use crate::signed_authority::*;
use crate::signed_intent::*;
use pretty_assertions::assert_eq;

struct Unresolved {
    fleet: TestFleet,
    owner: Supervisor<FakeDriver>,
    signer: H7H89ProductionGrantSigner,
    verifier: H7H89ProductionGrantVerifier,
    decision: ProductionRecoveryDecision,
    control: FakeControl,
    prior_lease: crate::lease::ProcessLease,
}

fn prepared_crash() -> Result<Unresolved, SupervisorError> {
    let fleet = TestFleet::new()?;
    let source = admitted_release(&fleet, &fleet.first, "unknown-source")?;
    let target = admitted_release(&fleet, &fleet.first, "unknown-target")?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    owner.start_release(&fleet.first, source.clone(), now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(owner.tick(now), TickReport::default());
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let prior_lease = crate::lease::read_lease(record.layout.run_root())?.unwrap();
    // The actual durable writer cut immediately after Prepared publication,
    // before upgrade_slot publishes any release transaction.
    let prepared = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"grant"),
        fleet.first.to_string(),
        H7H89ProductionTransition::Upgrade,
        source.identity(),
        target.identity(),
        /*expected_control_revision*/ 0,
        record.lifecycle.generation,
        /*authority_epoch*/ 3,
        SignedIntentStatus::Prepared,
    )
    .unwrap();
    write_intent(record.layout.run_root(), &prepared).unwrap();
    drop(owner);
    control.set_exit(&fleet.first);
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(owner.tick(now), TickReport::default());
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let intent = read_intent(record.layout.run_root()).unwrap().unwrap();
    assert_eq!(intent.status, SignedIntentStatus::RecoveryRequired);
    assert!(owner.release_selection_snapshot(&fleet.first)?.is_none());
    let binding = fleet
        .registry
        .resolve_release_binding(&fleet.first, source.release_id())?;
    let signer =
        H7H89ProductionGrantSigner::from_seed("operator", /*signer_epoch*/ 4, [9; 32]).unwrap();
    let verifier = H7H89ProductionGrantVerifier::new(
        "operator",
        /*signer_epoch*/ 4,
        signer.verifying_key(),
    )
    .unwrap();
    let decision = signer
        .sign_abandon_unknown(
            &intent,
            &binding,
            record.release_state.generation,
            record.lifecycle.generation,
            /*authority_epoch*/ 3,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 200,
        )
        .unwrap();
    Ok(Unresolved {
        fleet,
        owner,
        signer,
        verifier,
        decision,
        control,
        prior_lease,
    })
}

#[test]
fn prepared_without_transaction_is_disposed_atomically_and_unknown_survives_restart_and_next_grant()
-> Result<(), SupervisorError> {
    let Unresolved {
        fleet,
        mut owner,
        verifier,
        decision,
        ..
    } = prepared_crash()?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let receipt = owner.resolve_production_recovery(
        &fleet.first,
        &decision,
        &verifier,
        /*expected_authority_epoch*/ 3,
        /*now_unix_seconds*/ 150,
    )?;
    assert_eq!(receipt.status, ProductionMutationStatus::Aborted);
    assert!(!receipt.promotion);
    assert!(!owner.production_recovery_required(&fleet.first)?);
    let disposed = read_intent(record.layout.run_root()).unwrap().unwrap();
    assert_eq!(disposed.unknown_effects.len(), 1);
    assert_eq!(disposed.unknown_effects[0].decision, decision);
    assert!(
        write_intent(
            record.layout.run_root(),
            &disposed.with_status(SignedIntentStatus::Committed).unwrap()
        )
        .is_err()
    );
    assert!(
        write_intent(
            record.layout.run_root(),
            &disposed.with_status(SignedIntentStatus::Prepared).unwrap()
        )
        .is_err()
    );
    assert!(owner.release_selection_snapshot(&fleet.first)?.is_none());
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .unwrap()
            .release_state,
        record.release_state
    );
    drop(owner); // cut after the single atomic disposition publication
    let (mut owner, _) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert!(!owner.production_recovery_required(&fleet.first)?);
    assert!(
        owner
            .resolve_production_recovery(
                &fleet.first,
                &decision,
                &verifier,
                /*expected_authority_epoch*/ 3,
                /*now_unix_seconds*/ 150
            )
            .is_err()
    );
    let next = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"next grant"),
        fleet.first.to_string(),
        H7H89ProductionTransition::Upgrade,
        "unknown-source",
        "unknown-next",
        /*expected_control_revision*/ 2,
        record.lifecycle.generation,
        /*authority_epoch*/ 4,
        SignedIntentStatus::Prepared,
    )
    .unwrap();
    assert!(write_intent(record.layout.run_root(), &next).is_err());
    let next = next.inherit_unknown_effects(Some(&disposed)).unwrap();
    write_intent(record.layout.run_root(), &next).unwrap();
    drop(owner);
    let (owner, _) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert!(owner.production_recovery_required(&fleet.first)?);
    assert_eq!(
        owner
            .production_mutation_state(&fleet.first)?
            .unwrap()
            .unknown_effects,
        disposed.unknown_effects
    );
    Ok(())
}

#[test]
fn unknown_disposition_refuses_revoked_source_late_epoch_wrong_key_and_changed_lifecycle()
-> Result<(), SupervisorError> {
    for mode in [
        "revoked",
        "expired",
        "epoch",
        "key",
        "lifecycle",
        "late lease",
        "v1 downgrade",
    ] {
        let Unresolved {
            fleet,
            mut owner,
            mut verifier,
            mut decision,
            prior_lease,
            ..
        } = prepared_crash()?;
        let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
        let before = read_intent(record.layout.run_root()).unwrap();
        match mode {
            "revoked" => fleet
                .registry
                .revoke_release(&fleet.first, record.release_state.current.as_ref().unwrap())?,
            "key" => {
                verifier = H7H89ProductionGrantVerifier::new(
                    "operator",
                    /*signer_epoch*/ 4,
                    H7H89ProductionGrantSigner::from_seed(
                        "operator", /*signer_epoch*/ 4, [8; 32],
                    )
                    .unwrap()
                    .verifying_key(),
                )
                .unwrap()
            }
            "lifecycle" => {
                fleet.registry.compare_and_transition(
                    &fleet.first,
                    record.lifecycle.generation,
                    AgentLifecycle::Starting,
                )?;
            }
            "late lease" => crate::lease::write_lease(record.layout.run_root(), &prior_lease)?,
            "v1 downgrade" => {
                decision.schema_version = 1;
                decision.namespace = PRODUCTION_RECOVERY_NAMESPACE.to_string();
            }
            _ => {}
        }
        assert!(
            owner
                .resolve_production_recovery(
                    &fleet.first,
                    &decision,
                    &verifier,
                    if mode == "epoch" { 4 } else { 3 },
                    if mode == "expired" { 200 } else { 150 }
                )
                .is_err()
        );
        assert_eq!(read_intent(record.layout.run_root()).unwrap(), before);
        assert!(owner.production_recovery_required(&fleet.first)?);
    }
    Ok(())
}

#[test]
fn two_concurrent_dispositions_leave_exactly_one_durable_unknown_record()
-> Result<(), SupervisorError> {
    let Unresolved {
        fleet,
        owner,
        verifier,
        decision,
        ..
    } = prepared_crash()?;
    let owner = Arc::new(Mutex::new(owner));
    let barrier = Arc::new(std::sync::Barrier::new(2));
    // Spawn every participant before joining: joining a lazy iterator here
    // would block the first worker at the barrier before spawning the second.
    let mut jobs = Vec::new();
    for _ in 0..2 {
        let owner = owner.clone();
        let barrier = barrier.clone();
        let verifier = verifier.clone();
        let decision = decision.clone();
        let agent = fleet.first.clone();
        jobs.push(std::thread::spawn(move || {
            barrier.wait();
            owner
                .lock()
                .unwrap()
                .resolve_production_recovery(
                    &agent, &decision, &verifier, /*expected_authority_epoch*/ 3,
                    /*now_unix_seconds*/ 150,
                )
                .is_ok()
        }));
    }
    let passed = jobs
        .into_iter()
        .map(|job| job.join().unwrap())
        .filter(|passed| *passed)
        .count();
    assert_eq!(passed, 1);
    assert_eq!(
        owner
            .lock()
            .unwrap()
            .production_mutation_state(&fleet.first)?
            .unwrap()
            .unknown_effects
            .len(),
        1
    );
    Ok(())
}

#[test]
fn unknown_history_capacity_fails_closed_without_dropping_previous_facts()
-> Result<(), SupervisorError> {
    let Unresolved {
        fleet,
        mut owner,
        signer,
        verifier,
        mut decision,
        ..
    } = prepared_crash()?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let source = fleet
        .registry
        .resolve_release_binding(&fleet.first, record.release_state.current.as_ref().unwrap())?;
    for index in 0..=MAX_UNKNOWN_EFFECT_DISPOSITIONS {
        if index > 0 {
            let previous = read_intent(record.layout.run_root()).unwrap().unwrap();
            let next = SignedSupervisorIntent::new(
                Sha256Digest::for_bytes(index.to_string().as_bytes()),
                fleet.first.to_string(),
                H7H89ProductionTransition::Upgrade,
                "unknown-source",
                "unknown-target",
                index as u64,
                record.lifecycle.generation,
                /*authority_epoch*/ 3,
                SignedIntentStatus::RecoveryRequired,
            )
            .unwrap()
            .inherit_unknown_effects(Some(&previous))
            .unwrap();
            write_intent(record.layout.run_root(), &next).unwrap();
            (owner, _) = Supervisor::recover(
                fleet.registry.clone(),
                FakeControl::default().driver(),
                config(),
                Instant::now(),
            )?;
            decision = signer
                .sign_abandon_unknown(
                    &next,
                    &source,
                    record.release_state.generation,
                    record.lifecycle.generation,
                    /*authority_epoch*/ 3,
                    /*issued_at_unix_seconds*/ 100,
                    /*expires_at_unix_seconds*/ 200,
                )
                .unwrap();
        }
        let result = owner.resolve_production_recovery(
            &fleet.first,
            &decision,
            &verifier,
            /*expected_authority_epoch*/ 3,
            /*now_unix_seconds*/ 150,
        );
        if index < MAX_UNKNOWN_EFFECT_DISPOSITIONS {
            assert!(result.is_ok(), "{result:?}");
        } else {
            assert!(result.is_err());
        }
    }
    let last = read_intent(record.layout.run_root()).unwrap().unwrap();
    assert_eq!(last.unknown_effects.len(), MAX_UNKNOWN_EFFECT_DISPOSITIONS);
    assert!(owner.production_recovery_required(&fleet.first)?);
    assert!(
        write_intent(
            record.layout.run_root(),
            &SignedSupervisorIntent::new(
                Sha256Digest::for_bytes(b"drop history"),
                fleet.first.to_string(),
                H7H89ProductionTransition::Upgrade,
                "unknown-source",
                "other",
                /*expected_control_revision*/ 0,
                /*expected_lifecycle_generation*/ 1,
                /*authority_epoch*/ 3,
                SignedIntentStatus::Prepared
            )
            .unwrap()
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn disposed_generation_never_revives_late_worker_but_new_generation_can_start()
-> Result<(), SupervisorError> {
    let Unresolved {
        fleet,
        mut owner,
        verifier,
        decision,
        control,
        prior_lease,
        ..
    } = prepared_crash()?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    owner.resolve_production_recovery(
        &fleet.first,
        &decision,
        &verifier,
        /*expected_authority_epoch*/ 3,
        /*now_unix_seconds*/ 150,
    )?;
    drop(owner);
    // A delayed/stale exact lease arrives after the disposition was durable.
    control.update(&fleet.first, |state| state.exit = None);
    crate::lease::write_lease(record.layout.run_root(), &prior_lease)?;
    let now = Instant::now();
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let late = owner.snapshot(&fleet.first).unwrap();
    assert!(late.runtime_fenced);
    assert_eq!(
        late.runtime_phase,
        Some(crate::ControlRuntimePhase::Killing)
    );
    assert!(!late.healthy);
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .unwrap()
            .release_state,
        record.release_state
    );
    control.set_exit(&fleet.first);
    assert_eq!(owner.tick(now), TickReport::default());
    let source_id = record.release_state.current.as_ref().unwrap();
    let source = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, source_id)?)?;
    owner.start_release(&fleet.first, source, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(owner.tick(now), TickReport::default());
    assert!(
        owner
            .snapshot(&fleet.first)
            .unwrap()
            .spawn_generation
            .unwrap()
            > decision.expected_lifecycle_generation
    );
    drop(owner);
    let (owner, _) = Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert!(!owner.snapshot(&fleet.first).unwrap().runtime_fenced);
    assert_eq!(
        owner
            .production_mutation_state(&fleet.first)?
            .unwrap()
            .unknown_effects
            .len(),
        1
    );
    Ok(())
}

#[test]
fn crash_after_durable_disposition_before_memory_update_recovers_the_same_unknown_fact()
-> Result<(), SupervisorError> {
    let Unresolved {
        fleet,
        owner,
        decision,
        ..
    } = prepared_crash()?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let before = read_intent(record.layout.run_root()).unwrap().unwrap();
    // Exact single-file publication cut used by resolve_unknown_recovery_in_slot;
    // the original owner remains fenced in memory until the durable write wins.
    let published = before.abandon_unknown(&decision).unwrap();
    write_intent(record.layout.run_root(), &published).unwrap();
    assert!(owner.production_recovery_required(&fleet.first)?);
    drop(owner);
    let (owner, _) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert!(!owner.production_recovery_required(&fleet.first)?);
    assert_eq!(
        read_intent(record.layout.run_root()).unwrap(),
        Some(published)
    );
    assert!(owner.release_selection_snapshot(&fleet.first)?.is_none());
    Ok(())
}

#[test]
fn late_retired_worker_kill_failure_retains_handle_and_retries_after_restart()
-> Result<(), SupervisorError> {
    let Unresolved {
        fleet,
        mut owner,
        verifier,
        decision,
        control,
        prior_lease,
        ..
    } = prepared_crash()?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    owner.resolve_production_recovery(
        &fleet.first,
        &decision,
        &verifier,
        /*expected_authority_epoch*/ 3,
        /*now_unix_seconds*/ 150,
    )?;
    drop(owner);
    control.update(&fleet.first, |state| state.exit = None);
    control
        .world
        .lock()
        .unwrap()
        .reject_kill
        .insert(fleet.first.clone());
    crate::lease::write_lease(record.layout.run_root(), &prior_lease)?;
    let now = Instant::now();
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let failed = owner.snapshot(&fleet.first).unwrap();
    assert!(failed.runtime_fenced);
    assert_eq!(
        failed.runtime_phase,
        Some(crate::ControlRuntimePhase::Stopping)
    );
    assert!(failed.spawn_generation.is_some());
    let _ = owner.tick(now); // Continued failure must retain the same owned handle.
    assert_eq!(
        owner.snapshot(&fleet.first).unwrap().runtime_phase,
        failed.runtime_phase
    );
    drop(owner);
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(
        owner.snapshot(&fleet.first).unwrap().runtime_phase,
        failed.runtime_phase
    );
    control
        .world
        .lock()
        .unwrap()
        .reject_kill
        .remove(&fleet.first);
    assert_eq!(owner.tick(now), TickReport::default());
    assert_eq!(
        owner.snapshot(&fleet.first).unwrap().runtime_phase,
        Some(crate::ControlRuntimePhase::Killing)
    );
    control.set_exit(&fleet.first);
    assert_eq!(owner.tick(now), TickReport::default());
    assert!(
        owner
            .snapshot(&fleet.first)
            .unwrap()
            .spawn_generation
            .is_none()
    );
    assert_eq!(
        owner
            .production_mutation_state(&fleet.first)?
            .unwrap()
            .unknown_effects[0]
            .decision,
        decision
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn readable_unknown_after_failed_directory_sync_cannot_unfence_or_adopt_until_reconciled()
-> Result<(), SupervisorError> {
    let Unresolved {
        fleet,
        mut owner,
        verifier,
        decision,
        control,
        prior_lease,
        ..
    } = prepared_crash()?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let path = record.layout.run_root().join(SIGNED_INTENT_FILE);
    let result = with_rename_sync_fault(&path, || {
        owner.resolve_production_recovery(
            &fleet.first,
            &decision,
            &verifier,
            /*expected_authority_epoch*/ 3,
            /*now_unix_seconds*/ 150,
        )
    });
    assert!(matches!(
        result,
        Err(SupervisorError::SignedIntentRecoveryRequired(_))
    ));
    assert!(owner.production_recovery_required(&fleet.first)?);
    // The hook fires after the actual rename, at the parent sync boundary.
    // These complete bytes are observable even though no durable success was returned.
    let readable = read_intent(record.layout.run_root()).unwrap().unwrap();
    assert_eq!(readable.status, SignedIntentStatus::Aborted);
    assert_eq!(readable.unknown_effects.len(), 1);
    assert_eq!(readable.unknown_effects[0].decision, decision);
    drop(owner);
    control.update(&fleet.first, |state| state.exit = None);
    crate::lease::write_lease(record.layout.run_root(), &prior_lease)?;
    let before_adoption = control.world.lock().unwrap().adoption_requests;
    for _ in 0..2 {
        let result = with_rename_sync_fault(&path, || {
            Supervisor::recover(
                fleet.registry.clone(),
                control.driver(),
                config(),
                Instant::now(),
            )
        });
        assert!(matches!(
            result,
            Err(SupervisorError::SignedIntentRecoveryRequired(_))
        ));
        assert_eq!(
            control.world.lock().unwrap().adoption_requests,
            before_adoption
        );
        assert_eq!(
            read_intent(record.layout.run_root()).unwrap(),
            Some(readable.clone())
        );
    }
    let (mut recovered, _) = Supervisor::recover(
        fleet.registry.clone(),
        control.driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(
        read_intent(record.layout.run_root()).unwrap(),
        Some(readable)
    );
    assert!(!recovered.production_recovery_required(&fleet.first)?);
    assert!(recovered.snapshot(&fleet.first).unwrap().runtime_fenced);
    assert!(control.world.lock().unwrap().adoption_requests > before_adoption);
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
    Ok(())
}

#[test]
fn late_matrix_keeps_lease_and_blocks_unknown_until_observed_exit() -> Result<(), SupervisorError> {
    let (fleet, control, owner, now) = ready_paired_supervisor("late-matrix-source")?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let prepared = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"matrix grant"),
        fleet.first.to_string(),
        H7H89ProductionTransition::Upgrade,
        "late-matrix-source",
        "next",
        /*expected_control_revision*/ 0,
        record.lifecycle.generation,
        /*authority_epoch*/ 3,
        SignedIntentStatus::Prepared,
    )
    .unwrap();
    write_intent(record.layout.run_root(), &prepared).unwrap();
    fleet.registry.compare_and_transition(
        &fleet.first,
        record.lifecycle.generation,
        AgentLifecycle::Failed,
    )?;
    control.set_exit(&fleet.first);
    control
        .world
        .lock()
        .unwrap()
        .reject_kill
        .insert(fleet.first.clone());
    drop(owner);
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let _ = owner.tick(now);
    assert!(
        owner
            .slots
            .get(&fleet.first)
            .unwrap()
            .matrix
            .runtime
            .as_ref()
            .unwrap()
            .fenced
    );
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some());
    drop(owner);
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let _ = owner.tick(now);
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let intent = read_intent(record.layout.run_root()).unwrap().unwrap();
    let binding = fleet
        .registry
        .resolve_release_binding(&fleet.first, record.release_state.current.as_ref().unwrap())?;
    let signer =
        H7H89ProductionGrantSigner::from_seed("operator", /*signer_epoch*/ 4, [9; 32]).unwrap();
    let verifier = H7H89ProductionGrantVerifier::new(
        "operator",
        /*signer_epoch*/ 4,
        signer.verifying_key(),
    )
    .unwrap();
    let decision = signer
        .sign_abandon_unknown(
            &intent,
            &binding,
            record.release_state.generation,
            record.lifecycle.generation,
            /*authority_epoch*/ 3,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 200,
        )
        .unwrap();
    assert!(
        owner
            .resolve_production_recovery(
                &fleet.first,
                &decision,
                &verifier,
                /*expected_authority_epoch*/ 3,
                /*now_unix_seconds*/ 150
            )
            .is_err()
    );
    control
        .world
        .lock()
        .unwrap()
        .reject_kill
        .remove(&fleet.first);
    let _ = owner.tick(now + Duration::from_secs(/*secs*/ 1));
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some());
    assert!(
        owner
            .resolve_production_recovery(
                &fleet.first,
                &decision,
                &verifier,
                /*expected_authority_epoch*/ 3,
                /*now_unix_seconds*/ 150
            )
            .is_err()
    );
    control.set_matrix_exit(&fleet.first);
    let _ = owner.tick(now + Duration::from_secs(/*secs*/ 2));
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
    owner.resolve_production_recovery(
        &fleet.first,
        &decision,
        &verifier,
        /*expected_authority_epoch*/ 3,
        /*now_unix_seconds*/ 150,
    )?;
    assert_eq!(
        owner
            .production_mutation_state(&fleet.first)?
            .unwrap()
            .unknown_effects[0]
            .decision,
        decision
    );
    Ok(())
}

#[test]
fn primary_cleanup_failure_still_adopts_and_retains_late_matrix_in_same_recovery()
-> Result<(), SupervisorError> {
    let (fleet, control, owner, now) = ready_paired_supervisor("paired-retired-source")?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let main_lease = crate::lease::read_lease(record.layout.run_root())?.unwrap();
    let matrix_lease =
        crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.unwrap();
    let prepared = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"paired-retired-grant"),
        fleet.first.to_string(),
        H7H89ProductionTransition::Upgrade,
        "paired-retired-source",
        "next",
        /*expected_control_revision*/ 0,
        record.lifecycle.generation,
        /*authority_epoch*/ 3,
        SignedIntentStatus::Prepared,
    )
    .unwrap();
    write_intent(record.layout.run_root(), &prepared).unwrap();
    control.set_exit(&fleet.first);
    control.set_matrix_exit(&fleet.first);
    drop(owner);
    let (mut owner, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    let intent = read_intent(record.layout.run_root()).unwrap().unwrap();
    let source = fleet
        .registry
        .resolve_release_binding(&fleet.first, record.release_state.current.as_ref().unwrap())?;
    let signer =
        H7H89ProductionGrantSigner::from_seed("operator", /*signer_epoch*/ 4, [9; 32]).unwrap();
    let verifier = H7H89ProductionGrantVerifier::new(
        "operator",
        /*signer_epoch*/ 4,
        signer.verifying_key(),
    )
    .unwrap();
    let decision = signer
        .sign_abandon_unknown(
            &intent,
            &source,
            record.release_state.generation,
            record.lifecycle.generation,
            /*authority_epoch*/ 3,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 200,
        )
        .unwrap();
    owner.resolve_production_recovery(
        &fleet.first,
        &decision,
        &verifier,
        /*expected_authority_epoch*/ 3,
        /*now_unix_seconds*/ 150,
    )?;
    drop(owner);
    control.update(&fleet.first, |state| state.exit = None);
    control.update_role(&fleet.first, FakeRole::Matrixd, |state| state.exit = None);
    control
        .world
        .lock()
        .unwrap()
        .reject_kill
        .insert(fleet.first.clone());
    crate::lease::write_lease(record.layout.run_root(), &main_lease)?;
    crate::lease::write_matrix_lease(record.layout.matrixd_process_lease(), &matrix_lease)?;

    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert!(report.faults.len() >= 2);
    let snapshot = recovered.snapshot(&fleet.first).unwrap();
    assert!(snapshot.active && snapshot.runtime_fenced && snapshot.matrix.active);
    let slot = recovered.slots.get(&fleet.first).unwrap();
    assert!(slot.matrix.runtime.as_ref().unwrap().fenced);
    assert!(matches!(
        slot.runtime.as_ref().unwrap().phase,
        crate::runtime::RuntimePhase::Stopping { .. }
    ));
    assert!(matches!(
        slot.matrix.runtime.as_ref().unwrap().phase,
        crate::runtime::MatrixRuntimePhase::Stopping { .. }
    ));
    assert_eq!(
        recovered
            .production_mutation_state(&fleet.first)?
            .unwrap()
            .unknown_effects
            .len(),
        1
    );
    control
        .world
        .lock()
        .unwrap()
        .reject_kill
        .remove(&fleet.first);
    let _ = recovered.tick(now + Duration::from_secs(/*secs*/ 1));
    assert!(crate::lease::read_lease(record.layout.run_root())?.is_some());
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some());
    control.set_exit(&fleet.first);
    control.set_matrix_exit(&fleet.first);
    let _ = recovered.tick(now + Duration::from_secs(/*secs*/ 2));
    assert!(!recovered.snapshot(&fleet.first).unwrap().active);
    assert!(!recovered.snapshot(&fleet.first).unwrap().matrix.active);
    assert!(crate::lease::read_lease(record.layout.run_root())?.is_none());
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
    Ok(())
}

#[test]
fn failed_lifecycle_stop_error_retains_both_original_children_for_termination()
-> Result<(), SupervisorError> {
    let (fleet, control, owner, now) = ready_paired_supervisor("failed-stop-source")?;
    let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
    fleet.registry.compare_and_transition(
        &fleet.first,
        record.lifecycle.generation,
        AgentLifecycle::Failed,
    )?;
    {
        let mut world = control.world.lock().unwrap();
        world.reject_stop.insert(fleet.first.clone());
        world.reject_kill.insert(fleet.first.clone());
    }
    drop(owner);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert!(report.faults.len() >= 2);
    let snapshot = recovered.snapshot(&fleet.first).unwrap();
    assert!(snapshot.active && snapshot.runtime_fenced && snapshot.matrix.active);
    assert!(
        recovered
            .slots
            .get(&fleet.first)
            .unwrap()
            .matrix
            .runtime
            .as_ref()
            .unwrap()
            .fenced
    );
    assert!(crate::lease::read_lease(record.layout.run_root())?.is_some());
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some());
    control
        .world
        .lock()
        .unwrap()
        .reject_kill
        .remove(&fleet.first);
    let _ = recovered.tick(now + Duration::from_secs(/*secs*/ 1));
    control.set_exit(&fleet.first);
    control.set_matrix_exit(&fleet.first);
    let _ = recovered.tick(now + Duration::from_secs(/*secs*/ 2));
    assert!(!recovered.snapshot(&fleet.first).unwrap().active);
    assert!(!recovered.snapshot(&fleet.first).unwrap().matrix.active);
    Ok(())
}

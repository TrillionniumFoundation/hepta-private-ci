//! Real signed policy, authenticated frontier failures and cold owner reopen.
use super::*;
use crate::current_recovery_admission::CurrentRecoveryAdmission;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::release_transaction::read_release_transaction;
use crate::signed_intent_policy::digest_bytes;
use codex_hepta_fleet::ReleaseIntentPhaseV1;
use pretty_assertions::assert_eq;

fn reopen(h: Harness, reconciliation: bool) -> QualificationResult<Harness> {
    let Harness {
        publisher,
        mut fleet,
        control,
        supervisor,
        authority,
        grant,
        now,
    } = h;
    drop(supervisor);
    let root = fleet.registry.layout().fleet_root().clone();
    let state_only = FleetRegistry::open_existing(root.clone())?;
    drop(std::mem::replace(&mut fleet.registry, state_only));
    if reconciliation {
        assert!(matches!(
            FleetRegistry::open_existing_with_release_authority(root.clone(), publisher.config()),
            Err(codex_hepta_fleet::FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        fleet.registry =
            FleetRegistry::open_existing_for_release_intent_recovery(root, publisher.config())?;
    } else {
        fleet.registry =
            FleetRegistry::open_existing_with_release_authority(root, publisher.config())?;
    }
    let (supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    Ok(Harness {
        publisher,
        fleet,
        control,
        supervisor,
        authority,
        grant,
        now,
    })
}

fn stopped(h: &mut Harness) -> QualificationResult<()> {
    assert!(h.supervisor.production_recovery_required(&h.fleet.first)?);
    h.control.set_exit(&h.fleet.first);
    let _ = h.supervisor.tick(h.now);
    let record = h.supervisor.record(&h.fleet.first)?;
    assert!(crate::lease::read_lease(record.layout.run_root())?.is_none());
    assert!(!h.supervisor.snapshot(&h.fleet.first).unwrap().active);
    Ok(())
}

fn prepared(h: &Harness) -> QualificationResult<SignedSupervisorIntent> {
    Ok(SignedSupervisorIntent::new(
        h.grant.grant_sha256.clone(),
        h.fleet.first.to_string(),
        h.grant.transition,
        h.grant.source_release.clone(),
        h.grant.target_release.clone(),
        h.grant.expected_control_revision,
        h.grant.expected_lifecycle_generation,
        h.grant.authority_epoch,
        SignedIntentStatus::Prepared,
    )?
    .bind_authority(&h.grant, &h.authority.envelope, &h.authority.verifier)?)
}

fn unknown(
    h: &Harness,
    confirmation: bool,
    epoch: u64,
) -> QualificationResult<crate::ProductionRecoveryDecision> {
    let intent = h.intent()?;
    let record = h.supervisor.record(&h.fleet.first)?;
    let admission = CurrentRecoveryAdmission::acquire(&h.fleet.registry, &h.authority.verifier)?;
    let expected = admission.expected(&h.fleet.first)?;
    let predecessor = match expected {
        Some(anchor) => crate::UnknownRecoveryPredecessorV1::from_anchor(&anchor)?,
        None => crate::UnknownRecoveryPredecessorV1::from_absent(&h.fleet.first),
    };
    let binding = admission.binding(
        &h.fleet.registry,
        &h.fleet.first,
        &ReleaseId::parse(intent.source_release.clone())?,
    )?;
    let transaction = read_release_transaction(record.layout.run_root())?
        .map_or_else(crate::absent_release_transaction_digest, |transaction| {
            transaction.transaction_sha256
        });
    let unix = admission.now_seconds()?;
    if confirmation {
        Ok(h.authority.recovery.sign_confirm_unknown_publication(
            &intent,
            &binding,
            &predecessor,
            transaction,
            record.release_state.generation,
            record.lifecycle.generation,
            epoch,
            unix,
            unix + 60,
        )?)
    } else {
        Ok(h.authority
            .recovery
            .sign_abandon_unknown_after_predecessor(
                &intent,
                &binding,
                &predecessor,
                transaction,
                record.release_state.generation,
                record.lifecycle.generation,
                epoch,
                unix,
                unix + 60,
            )?)
    }
}

fn resolve(
    h: &mut Harness,
    decision: &crate::ProductionRecoveryDecision,
    epoch: u64,
) -> QualificationResult<()> {
    h.supervisor.resolve_production_recovery(
        &h.fleet.first,
        decision,
        &h.authority.verifier,
        epoch,
        /*now_unix_seconds*/ 0,
    )?;
    Ok(())
}

fn failed_first_publication() -> QualificationResult<Harness> {
    let mut h = Harness::ready()?;
    let before = h.publisher.frontier()?;
    let attempts = h.publisher.cas_attempts();
    h.publisher.drop_next_cas_without_commit();
    assert!(
        h.supervisor
            .apply_production_grant(
                &h.fleet.first,
                &h.grant,
                &h.authority.envelope,
                &h.authority.verifier,
                /*expected_authority_epoch*/ 47,
                /*now_unix_seconds*/ 0,
                h.now
            )
            .is_err()
    );
    assert_eq!(h.publisher.frontier()?, before);
    assert_eq!(h.publisher.cas_attempts(), attempts + 1);
    assert_eq!(h.intent()?.status, SignedIntentStatus::Prepared);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    let mut h = reopen(h, /*reconciliation*/ true)?;
    assert!(h.fleet.registry.is_release_intent_reconciliation());
    stopped(&mut h)?;
    Ok(h)
}

#[test]
fn actual_first_cas_error_cold_mode_contains_and_signed_absence_consumes_without_dispatch()
-> QualificationResult<()> {
    let mut h = failed_first_publication()?;
    let initial = h.intent()?;
    let record = h.supervisor.record(&h.fleet.first)?;
    assert!(read_release_transaction(record.layout.run_root())?.is_none());
    let decision = unknown(&h, /*confirmation*/ false, /*epoch*/ 91)?;
    let mut wrong_absence = decision.clone();
    wrong_absence
        .unknown_observation
        .as_mut()
        .unwrap()
        .predecessor
        .as_mut()
        .unwrap()
        .anchor_sha256 = Sha256Digest::for_bytes(b"missing local file");
    let attempts = h.publisher.cas_attempts();
    assert!(resolve(&mut h, &wrong_absence, /*epoch*/ 91).is_err());
    assert_eq!(h.publisher.cas_attempts(), attempts);
    assert_eq!(h.intent()?, initial);
    resolve(&mut h, &decision, /*epoch*/ 91)?;
    assert!(h.supervisor.production_recovery_required(&h.fleet.first)?);
    let closed = h.intent()?;
    assert_eq!(closed.status, SignedIntentStatus::Aborted);
    assert_eq!(closed.unknown_effects.len(), 1);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    let mut h = reopen(h, /*reconciliation*/ false)?;
    assert!(!h.supervisor.production_recovery_required(&h.fleet.first)?);
    let anchor = h
        .fleet
        .registry
        .release_intent_anchor(&h.fleet.first)?
        .unwrap();
    assert_eq!(anchor.intent_sha256, digest_bytes(&closed.intent_sha256)?);
    assert_eq!(anchor.phase, ReleaseIntentPhaseV1::Aborted);
    assert!(
        h.supervisor
            .apply_production_grant(
                &h.fleet.first,
                &h.grant,
                &h.authority.envelope,
                &h.authority.verifier,
                /*expected_authority_epoch*/ 47,
                /*now_unix_seconds*/ 0,
                h.now
            )
            .is_err()
    );
    assert_eq!(h.intent()?, closed);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[test]
fn crash_before_any_proposal_requires_fresh_absence_and_never_bootstraps_dispatch()
-> QualificationResult<()> {
    let h = Harness::ready()?;
    let intent = prepared(&h)?;
    let record = h.supervisor.record(&h.fleet.first)?;
    write_intent(record.layout.run_root(), &intent)?;
    let before = h.publisher.frontier()?;
    let mut h = reopen(h, /*reconciliation*/ false)?;
    assert_eq!(h.publisher.frontier()?, before);
    assert!(
        h.fleet
            .registry
            .release_intent_anchor(&h.fleet.first)?
            .is_none()
    );
    assert!(h.control.counts(&h.fleet.first).2 >= 1);
    stopped(&mut h)?;
    let decision = unknown(&h, /*confirmation*/ false, /*epoch*/ 92)?;
    resolve(&mut h, &decision, /*epoch*/ 92)?;
    let closed = h.intent()?;
    assert_eq!(closed.unknown_effects.len(), 1);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    std::fs::write(
        record
            .layout
            .run_root()
            .join(crate::signed_intent::SIGNED_INTENT_FILE),
        serde_json::to_vec(&intent)?,
    )?;
    let mut h = reopen(h, /*reconciliation*/ false)?;
    let attempts = h.publisher.cas_attempts();
    assert!(resolve(&mut h, &decision, /*epoch*/ 92).is_err());
    assert_eq!(h.publisher.cas_attempts(), attempts);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[test]
fn preproposal_recovery_refuses_a_retired_current_policy() -> QualificationResult<()> {
    let mut h = Harness::ready()?;
    let intent = prepared(&h)?;
    write_intent(
        h.supervisor.record(&h.fleet.first)?.layout.run_root(),
        &intent,
    )?;
    h = reopen(h, /*reconciliation*/ false)?;
    stopped(&mut h)?;
    let decision = unknown(&h, /*confirmation*/ false, /*epoch*/ 93)?;
    let mut replacement = h.authority.policy.clone();
    replacement.push(b' ');
    h.publisher.publish_protocol_configuration(
        &h.fleet.registry,
        &replacement,
        h.publisher.current_unix_seconds() + 3600,
    )?;
    let before = (
        h.publisher.frontier()?,
        h.publisher.cas_attempts(),
        h.intent()?,
    );
    assert!(resolve(&mut h, &decision, /*epoch*/ 93).is_err());
    assert_eq!(
        (
            h.publisher.frontier()?,
            h.publisher.cas_attempts(),
            h.intent()?
        ),
        before
    );
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[test]
fn pq_unknown_first_cas_failure_requires_fresh_confirmation_without_appending_history()
-> QualificationResult<()> {
    let h = Harness::ready()?;
    let intent = prepared(&h)?;
    write_intent(
        h.supervisor.record(&h.fleet.first)?.layout.run_root(),
        &intent,
    )?;
    let mut h = reopen(h, /*reconciliation*/ false)?;
    stopped(&mut h)?;
    let original = unknown(&h, /*confirmation*/ false, /*epoch*/ 94)?;
    h.publisher.drop_next_cas_without_commit();
    assert!(resolve(&mut h, &original, /*epoch*/ 94).is_err());
    let retained = h.intent()?;
    assert_eq!(retained.unknown_effects.len(), 1);
    assert_eq!(retained.status, SignedIntentStatus::Aborted);
    let mut h = reopen(h, /*reconciliation*/ true)?;
    h.publisher
        .advance_clock_to(original.expires_at_unix_seconds + 1);
    let attempts = h.publisher.cas_attempts();
    assert!(resolve(&mut h, &original, /*epoch*/ 95).is_err());
    assert_eq!(h.publisher.cas_attempts(), attempts);
    let confirmation = unknown(&h, /*confirmation*/ true, /*epoch*/ 95)?;
    resolve(&mut h, &confirmation, /*epoch*/ 95)?;
    assert_eq!(h.intent()?, retained);
    let h = reopen(h, /*reconciliation*/ false)?;
    assert!(!h.supervisor.production_recovery_required(&h.fleet.first)?);
    assert_eq!(h.intent()?, retained);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[path = "production_authority_pq_completion_tests.rs"]
mod completed;

#[path = "production_authority_pq_retained_tests.rs"]
mod retained;

#[test]
fn legacy_unresolved_history_cannot_acquire_a_production_completion_via_a_fresh_pq_signature()
-> QualificationResult<()> {
    use codex_hepta_memory::H7ArtifactSigner;
    use codex_hepta_memory::H7QualificationRuntime;
    use codex_hepta_memory::H7SignedArtifactTransition;
    use codex_hepta_memory::H7TrajectoryEvent;
    let mut h = Harness::ready()?;
    let unix = h.publisher.current_unix_seconds();
    let mut memory = H7QualificationRuntime::new();
    memory.append_trajectory_event(H7TrajectoryEvent::new(
        "legacy-cold",
        1,
        "reload",
        100,
        true,
        1,
        1,
        1,
        Sha256Digest::for_bytes(b"legacy-original-ceremony"),
    )?)?;
    memory.evaluate_trajectory("legacy-cold")?;
    let artifact = memory.propose_artifact("legacy-artifact", "legacy-cold", 1)?;
    let artifact_signer = H7ArtifactSigner::from_seed("legacy", 7, [109; 32])?;
    let envelope = artifact_signer.sign(
        &artifact,
        None,
        H7SignedArtifactTransition::Reload,
        0,
        None,
        unix,
        unix + 120,
    )?;
    let signer = crate::H7H89ProductionGrantSigner::from_seed("legacy", 7, [109; 32])?;
    let record = h.supervisor.record(&h.fleet.first)?;
    let grant = signer.sign(
        &h.fleet.first,
        "h7-v1",
        "h7-v2",
        crate::H7H89ProductionTransition::Upgrade,
        &envelope,
        3,
        record.lifecycle.generation,
        47,
        unix,
        unix + 120,
    )?;
    crate::H7H89ProductionGrantVerifier::new("legacy", 7, signer.verifying_key())?.verify(
        &grant,
        &envelope,
        &h.fleet.first,
        "h7-v1",
        "h7-v2",
        3,
        record.lifecycle.generation,
        47,
        unix,
    )?;
    assert!(grant.pq_authority.is_none());
    let intent = SignedSupervisorIntent::new(
        grant.grant_sha256.clone(),
        h.fleet.first.to_string(),
        grant.transition,
        "h7-v1",
        "h7-v2",
        3,
        record.lifecycle.generation,
        47,
        SignedIntentStatus::RecoveryRequired,
    )?;
    write_intent(record.layout.run_root(), &intent)?;
    let source = h
        .fleet
        .registry
        .resolve_release_binding(&h.fleet.first, &ReleaseId::parse("h7-v1")?)?;
    let target = h
        .fleet
        .registry
        .resolve_release_binding(&h.fleet.first, &ReleaseId::parse("h7-v2")?)?;
    let transaction = crate::release_transaction::DurableReleaseTransaction::new(
        h.fleet.first.to_string(),
        crate::release_transaction::ReleaseTransactionKind::Upgrade,
        "h7-v1",
        "h7-v2",
        None,
        Some(source.clone()),
        Some(target.clone()),
        record.release_state.generation,
        record.lifecycle.generation,
    )?
    .with_authority(grant.grant_sha256, 47)?
    .with_phase(ReleaseTransactionPhase::RecoveryRequired)?;
    crate::release_transaction::write_release_transaction(record.layout.run_root(), &transaction)?;
    h = reopen(h, /*reconciliation*/ false)?;
    stopped(&mut h)?;
    for (outcome, binding) in [
        (crate::ProductionRecoveryOutcome::Committed, &target),
        (crate::ProductionRecoveryOutcome::RolledBack, &source),
    ] {
        let record = h.supervisor.record(&h.fleet.first)?;
        let decision = h.authority.recovery.sign_recovery(
            &h.fleet.first,
            intent.grant_sha256.clone(),
            intent.intent_sha256.clone(),
            transaction.transaction_sha256.clone(),
            binding.release_id.as_str(),
            Sha256Digest::parse(binding.manifest_sha256.clone())?,
            Sha256Digest::parse(binding.agentd_program_sha256.clone())?,
            None,
            outcome,
            record.lifecycle.generation,
            131,
            unix,
            unix + 60,
        )?;
        crate::unknown_recovery_publication::verify_decision(
            &h.authority.verifier,
            &decision,
            &intent,
            &record,
            binding,
            &transaction.transaction_sha256,
            131,
            unix,
        )?;
        let before = (
            h.publisher.frontier()?,
            h.publisher.cas_attempts(),
            h.intent()?,
            read_release_transaction(record.layout.run_root())?,
            record.release_state.clone(),
        );
        assert!(resolve(&mut h, &decision, /*epoch*/ 131).is_err());
        assert_eq!(
            (
                h.publisher.frontier()?,
                h.publisher.cas_attempts(),
                h.intent()?,
                read_release_transaction(record.layout.run_root())?,
                h.supervisor.record(&h.fleet.first)?.release_state
            ),
            before
        );
        assert!(h.intent()?.pq_authority.is_none());
        assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    }
    Ok(())
}

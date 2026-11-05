//! Real ML-DSA grants and real M15 publication/clock/frontier fixtures drive the
//! ordinary Supervisor owner. FakeControl counts its exact process boundaries.
use super::release_authority_process_tests::pq_fleet;
use super::release_authority_process_tests::publish;
use super::*;
use crate::signed_authority::pq_tests::AuthorityFixture;
use crate::signed_authority::pq_tests::fixture_at;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;
use codex_hepta_fleet::PqReleaseQualification;
use codex_hepta_fleet::QualificationResult;
use pretty_assertions::assert_eq;

pub(super) struct Harness {
    pub(super) publisher: PqReleaseQualification,
    pub(super) fleet: TestFleet,
    pub(super) control: FakeControl,
    pub(super) supervisor: Supervisor<FakeDriver>,
    pub(super) authority: AuthorityFixture,
    pub(super) grant: crate::H7H89ProductionGrant,
    pub(super) now: Instant,
}

impl Harness {
    pub(super) fn ready() -> QualificationResult<Self> {
        let (mut publisher, fleet) = pq_fleet()?;
        let first = publish(&mut publisher, &fleet, "h7-v1", /*matrix*/ false)?;
        let second = publish(&mut publisher, &fleet, "h7-v2", /*matrix*/ false)?;
        let unix = publisher.current_unix_seconds();
        let authority = fixture_at(unix, unix + 500);
        publisher.publish_protocol_configuration(
            &fleet.registry,
            &authority.policy,
            unix + 3600,
        )?;
        let release =
            AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &first)?)?;
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut supervisor, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        supervisor.start_release(&fleet.first, release, now)?;
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now).faults, Vec::<crate::AgentFault>::new());
        let snapshot = supervisor.snapshot(&fleet.first).unwrap();
        let record = supervisor.record(&fleet.first)?;
        let grant = authority.grant.sign(
            &fleet.first,
            first.as_str(),
            second.as_str(),
            crate::H7H89ProductionTransition::Upgrade,
            &authority.envelope,
            snapshot.control_revision,
            record.lifecycle.generation,
            /*authority_epoch*/ 47,
            unix,
            unix + 120,
        )?;
        Ok(Self {
            publisher,
            fleet,
            control,
            supervisor,
            authority,
            grant,
            now,
        })
    }

    pub(super) fn queued() -> QualificationResult<Self> {
        let mut h = Self::ready()?;
        // The caller clock is intentionally unusable. Ordinary admission must
        // use the actual publication owner's trusted clock.
        h.supervisor.apply_production_grant(
            &h.fleet.first,
            &h.grant,
            &h.authority.envelope,
            &h.authority.verifier,
            /*expected_authority_epoch*/ 47,
            /*now_unix_seconds*/ 0,
            h.now,
        )?;
        Ok(h)
    }

    pub(super) fn intent(&self) -> QualificationResult<SignedSupervisorIntent> {
        Ok(read_intent(self.supervisor.record(&self.fleet.first)?.layout.run_root())?.unwrap())
    }

    pub(super) fn exit_source(&mut self) {
        self.control.set_drained(&self.fleet.first);
        let _ = self.supervisor.tick(self.now);
        self.control.set_exit(&self.fleet.first);
        let _ = self.supervisor.tick(self.now);
    }
}

#[test]
fn ordinary_pq_grant_retains_exact_proofs_and_does_not_consume_twice() -> QualificationResult<()> {
    let mut h = Harness::queued()?;
    let intent = h.intent()?;
    assert_eq!(intent.schema_version, 3);
    let proof = intent.pq_authority.as_ref().unwrap();
    assert_eq!(&proof.grant, &h.grant);
    assert_eq!(&proof.h7_envelope, &h.authority.envelope);
    assert_eq!(proof.policy_json.as_bytes(), h.authority.policy.as_slice());
    let frontier = h.publisher.frontier()?;
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
    assert_eq!(h.intent()?, intent);
    assert_eq!(h.publisher.frontier()?, frontier);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[test]
fn pending_grant_cannot_spawn_after_current_policy_replacement() -> QualificationResult<()> {
    let mut h = Harness::queued()?;
    let mut replacement = h.authority.policy.clone();
    replacement.push(b' ');
    h.publisher.publish_protocol_configuration(
        &h.fleet.registry,
        &replacement,
        h.publisher.current_unix_seconds() + 3600,
    )?;
    h.exit_source();
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    assert!(!h.supervisor.snapshot(&h.fleet.first).unwrap().healthy);
    Ok(())
}

#[test]
fn pending_grant_cannot_spawn_after_its_trusted_clock_window() -> QualificationResult<()> {
    let mut h = Harness::queued()?;
    h.publisher
        .advance_clock_to(h.grant.expires_at_unix_seconds);
    h.exit_source();
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[test]
fn recomputed_local_intent_hash_cannot_rebind_a_signature_to_new_policy_or_cas()
-> QualificationResult<()> {
    let mut h = Harness::queued()?;
    let original = h.intent()?;
    let mut policy = h.authority.policy.clone();
    policy.push(b' ');
    h.publisher.publish_protocol_configuration(
        &h.fleet.registry,
        &policy,
        h.publisher.current_unix_seconds() + 3600,
    )?;
    let mut changed = original;
    let proof = changed.pq_authority.as_mut().unwrap();
    proof.policy_json = String::from_utf8(policy.clone())?;
    proof.binding.policy_sha256 = Sha256Digest::for_bytes(&policy);
    proof.grant.pq_authority = Some(proof.binding.clone());
    proof.grant.expected_control_revision += 1;
    proof.grant.grant_sha256 = proof.grant.payload_digest();
    changed.expected_control_revision = proof.grant.expected_control_revision;
    changed.grant_sha256 = proof.grant.grant_sha256.clone();
    changed.intent_sha256 = changed.compute_digest()?;
    changed.validate()?; // The public local digest alone is deliberately coherent.
    let guard = h
        .fleet
        .registry
        .admit_release(&h.fleet.first, &ReleaseId::parse("h7-v2")?)?;
    assert!(
        crate::signed_intent_policy::revalidate_process_admission(
            Some(&guard),
            Some(&changed),
            &h.supervisor.record(&h.fleet.first)?,
            /*qualification*/ false
        )
        .is_err()
    );
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[test]
fn cold_pending_pq_intent_is_quarantined_and_old_daemon_epoch_cannot_reauthorize()
-> QualificationResult<()> {
    let h = Harness::queued()?;
    let prior = h.intent()?;
    drop(h.supervisor);
    let (mut supervisor, _) = Supervisor::recover(
        h.fleet.registry.clone(),
        h.control.driver(),
        config(),
        h.now,
    )?;
    assert!(supervisor.production_recovery_required(&h.fleet.first)?);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    let fresh_epoch =
        crate::authority_epoch_for_supervisor_epoch(crate::SupervisorEpoch::new().as_str());
    assert_ne!(fresh_epoch, prior.authority_epoch);
    assert!(matches!(
        h.authority.verifier.verify(
            &h.grant,
            &h.authority.envelope,
            &h.fleet.first,
            "h7-v1",
            "h7-v2",
            h.grant.expected_control_revision,
            h.grant.expected_lifecycle_generation,
            fresh_epoch,
            h.publisher.current_unix_seconds()
        ),
        Err(crate::signed_authority::ProductionAuthorityError::AuthorityEpochFence { .. })
    ));
    assert!(
        supervisor
            .apply_production_grant(
                &h.fleet.first,
                &h.grant,
                &h.authority.envelope,
                &h.authority.verifier,
                fresh_epoch,
                /*now_unix_seconds*/ 0,
                h.now
            )
            .is_err()
    );
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    Ok(())
}

#[test]
fn terminal_history_expiry_does_not_replace_current_release_permission() -> QualificationResult<()>
{
    let mut h = Harness::queued()?;
    h.exit_source();
    assert_eq!(h.control.spawn_count(&h.fleet.first), 2);
    h.control.set_healthy(&h.fleet.first);
    let _ = h.supervisor.tick(h.now);
    assert_eq!(h.intent()?.status, SignedIntentStatus::Committed);
    h.publisher
        .advance_clock_to(h.grant.expires_at_unix_seconds + 1);
    h.control.set_exit(&h.fleet.first);
    let _ = h.supervisor.tick(h.now);
    let target = AgentRelease::try_from(
        h.fleet
            .registry
            .resolve_release(&h.fleet.first, &ReleaseId::parse("h7-v2")?)?,
    )?;
    h.supervisor
        .start_release(&h.fleet.first, target.clone(), h.now)?;
    assert_eq!(h.control.spawn_count(&h.fleet.first), 3);
    h.control.set_exit(&h.fleet.first);
    let _ = h.supervisor.tick(h.now);
    h.publisher.publish_member_ids(
        &h.fleet.registry,
        &[ReleaseId::parse("h7-v1")?],
        h.publisher.current_unix_seconds() + 3600,
    )?;
    assert!(
        h.supervisor
            .start_release(&h.fleet.first, target, h.now)
            .is_err()
    );
    assert_eq!(h.control.spawn_count(&h.fleet.first), 3);
    Ok(())
}

#[test]
fn full_unknown_history_and_current_pq_proofs_fit_original_journal_bound() -> QualificationResult<()>
{
    let h = Harness::queued()?;
    let source = h
        .fleet
        .registry
        .resolve_release_binding(&h.fleet.first, &ReleaseId::parse("h7-v1")?)?;
    let unix = h.publisher.current_unix_seconds();
    let mut previous = None;
    for index in 0..crate::MAX_UNKNOWN_EFFECT_DISPOSITIONS {
        let revision = index as u64 + 100;
        let grant = h.authority.grant.sign(
            &h.fleet.first,
            "h7-v1",
            "h7-v2",
            crate::H7H89ProductionTransition::Upgrade,
            &h.authority.envelope,
            revision,
            /*expected_lifecycle_generation*/ 5,
            /*authority_epoch*/ 47,
            unix,
            unix + 120,
        )?;
        let intent = SignedSupervisorIntent::new(
            grant.grant_sha256.clone(),
            h.fleet.first.to_string(),
            grant.transition,
            "h7-v1",
            "h7-v2",
            revision,
            /*expected_lifecycle_generation*/ 5,
            /*authority_epoch*/ 47,
            SignedIntentStatus::RecoveryRequired,
        )?
        .bind_authority(&grant, &h.authority.envelope, &h.authority.verifier)?
        .inherit_unknown_effects(previous.as_ref())?;
        // Exercise the larger explicitly observed-predecessor wire shape as
        // well as real PQ signatures. This size fixture grants no live owner
        // permission; the ordinary daemon test uses actual protected anchors.
        let anchor = crate::signed_intent_anchor::next_anchor(
            None,
            &intent,
            &h.supervisor.record(&h.fleet.first)?,
        )?;
        let predecessor = crate::UnknownRecoveryPredecessorV1::from_anchor(&anchor)?;
        let decision = h
            .authority
            .recovery
            .sign_abandon_unknown_after_predecessor(
                &intent,
                &source,
                &predecessor,
                crate::absent_release_transaction_digest(),
                /*release_state_generation*/ 1,
                /*lifecycle_generation*/ 5,
                /*authority_epoch*/ 47,
                unix,
                unix + 120,
            )?;
        previous = Some(intent.abandon_unknown(&decision)?);
    }
    let final_intent = previous.unwrap();
    assert_eq!(final_intent.unknown_effects.len(), 32);
    let bytes = serde_json::to_vec(&final_intent)?;
    assert!(bytes.len() > 65_536);
    assert!(bytes.len() <= 262_144, "{}", bytes.len());
    let root = tempfile::tempdir()?;
    write_intent(root.path(), &final_intent)?;
    assert_eq!(read_intent(root.path())?, Some(final_intent.clone()));
    let grant = h.authority.grant.sign(
        &h.fleet.first,
        "h7-v1",
        "h7-v2",
        crate::H7H89ProductionTransition::Upgrade,
        &h.authority.envelope,
        /*expected_control_revision*/ 200,
        /*expected_lifecycle_generation*/ 5,
        /*authority_epoch*/ 47,
        unix,
        unix + 120,
    )?;
    let next = SignedSupervisorIntent::new(
        grant.grant_sha256.clone(),
        h.fleet.first.to_string(),
        grant.transition,
        "h7-v1",
        "h7-v2",
        /*expected_control_revision*/ 200,
        /*expected_lifecycle_generation*/ 5,
        /*authority_epoch*/ 47,
        SignedIntentStatus::RecoveryRequired,
    )?
    .bind_authority(&grant, &h.authority.envelope, &h.authority.verifier)?
    .inherit_unknown_effects(Some(&final_intent))?;
    let overflow = h.authority.recovery.sign_abandon_unknown(
        &next,
        &source,
        /*release_state_generation*/ 1,
        /*lifecycle_generation*/ 5,
        /*authority_epoch*/ 47,
        unix,
        unix + 120,
    )?;
    assert!(next.abandon_unknown(&overflow).is_err());
    assert_eq!(read_intent(root.path())?, Some(final_intent));
    Ok(())
}

#[test]
fn recomputed_terminal_labels_cannot_skip_the_external_pending_owner() -> QualificationResult<()> {
    for status in [
        SignedIntentStatus::Committed,
        SignedIntentStatus::RolledBack,
    ] {
        let mut h = Harness::queued()?;
        let forged = h.intent()?.with_status(status)?;
        forged.validate()?;
        let record = h.supervisor.record(&h.fleet.first)?;
        // Model replacement of locally writable, publicly hashed bytes. This
        // intentionally bypasses the honest intent writer, not the external CAS.
        std::fs::write(
            record
                .layout
                .run_root()
                .join(crate::signed_intent::SIGNED_INTENT_FILE),
            serde_json::to_vec(&forged)?,
        )?;
        drop(h.supervisor);
        let root = h.fleet.registry.layout().fleet_root().clone();
        let state_only = FleetRegistry::open_existing(root.clone())?;
        drop(std::mem::replace(&mut h.fleet.registry, state_only));
        h.fleet.registry =
            FleetRegistry::open_existing_with_release_authority(root, h.publisher.config())?;
        let recovered = Supervisor::recover(
            h.fleet.registry.clone(),
            h.control.driver(),
            config(),
            h.now,
        );
        if let Ok((supervisor, _)) = recovered {
            assert!(supervisor.production_recovery_required(&h.fleet.first)?);
            assert!(!supervisor.snapshot(&h.fleet.first).unwrap().healthy);
        }
        assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
        assert_eq!(h.control.counts(&h.fleet.first).2, 1);
    }
    Ok(())
}

#[test]
fn coherent_local_terminal_transaction_and_release_cas_cannot_forge_completion()
-> QualificationResult<()> {
    let mut h = Harness::queued()?;
    let record = h.supervisor.record(&h.fleet.first)?;
    let forged_intent = h.intent()?.with_status(SignedIntentStatus::Committed)?;
    let original_transaction =
        crate::release_transaction::read_release_transaction(record.layout.run_root())?.unwrap();
    let forged_transaction = original_transaction
        .with_phase(crate::release_transaction::ReleaseTransactionPhase::Committed)?;
    crate::release_transaction::write_release_transaction(
        record.layout.run_root(),
        &forged_transaction,
    )?;
    std::fs::write(
        record
            .layout
            .run_root()
            .join(crate::signed_intent::SIGNED_INTENT_FILE),
        serde_json::to_vec(&forged_intent)?,
    )?;
    h.fleet.registry.compare_and_set_release_state(
        &h.fleet.first,
        record.release_state.generation,
        Some(ReleaseId::parse("h7-v2")?),
        Some(ReleaseId::parse("h7-v1")?),
    )?;
    let forged_record = h.supervisor.record(&h.fleet.first)?;
    assert!(crate::signed_intent_policy::terminal_owner_matches(
        &forged_intent,
        &forged_transaction,
        &forged_record
    ));
    // All original local consistency checks agree, but no actual target was
    // started and the external owner still anchors the unresolved operation.
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    drop(h.supervisor);
    let root = h.fleet.registry.layout().fleet_root().clone();
    let state_only = FleetRegistry::open_existing(root.clone())?;
    drop(std::mem::replace(&mut h.fleet.registry, state_only));
    h.fleet.registry =
        FleetRegistry::open_existing_with_release_authority(root, h.publisher.config())?;
    let recovered = Supervisor::recover(
        h.fleet.registry.clone(),
        h.control.driver(),
        config(),
        h.now,
    );
    if let Ok((supervisor, _)) = recovered {
        assert!(supervisor.production_recovery_required(&h.fleet.first)?);
        assert!(!supervisor.snapshot(&h.fleet.first).unwrap().healthy);
    }
    assert_eq!(h.control.spawn_count(&h.fleet.first), 1);
    assert_eq!(h.control.counts(&h.fleet.first).2, 1);
    Ok(())
}

#[path = "production_authority_pq_recovery_tests.rs"]
mod recovery_cuts;

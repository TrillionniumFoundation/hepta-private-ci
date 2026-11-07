//! The next grant may be durable before its own transaction exists. The old
//! true completion transaction is observed as itself, never erased or absent.
use super::*;
use pretty_assertions::assert_eq;

fn next_grant(h: &mut Harness) -> QualificationResult<SignedSupervisorIntent> {
    publish(&mut h.publisher, &h.fleet, "h7-v3", /*matrix*/ false)?;
    let previous = h.intent()?;
    let record = h.supervisor.record(&h.fleet.first)?;
    let snapshot = h.supervisor.snapshot(&h.fleet.first).unwrap();
    let source = record.release_state.current.as_ref().unwrap();
    let unix = h.publisher.current_unix_seconds();
    h.grant = h.authority.grant.sign(
        &h.fleet.first,
        source.as_str(),
        "h7-v3",
        crate::H7H89ProductionTransition::Upgrade,
        &h.authority.envelope,
        snapshot.control_revision,
        record.lifecycle.generation,
        /*authority_epoch*/ 47,
        unix,
        unix + 120,
    )?;
    Ok(prepared(h)?.inherit_unknown_effects(Some(&previous))?)
}

#[test]
fn new_prepared_cas_error_recovers_against_actual_old_completed_transaction()
-> QualificationResult<()> {
    for rollback in [false, true] {
        let mut h = completed(rollback, /*fail_publication*/ false)?;
        let old = h.intent()?;
        let record = h.supervisor.record(&h.fleet.first)?;
        let old_transaction = read_release_transaction(record.layout.run_root())?.unwrap();
        let _next = next_grant(&mut h)?;
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
        let next = h.intent()?;
        assert_eq!(next.status, SignedIntentStatus::Prepared);
        assert_ne!(next.grant_sha256, old.grant_sha256);
        assert_eq!(
            crate::signed_intent::predecessor::read(record.layout.run_root())?,
            Some(old)
        );
        assert_eq!(
            read_release_transaction(record.layout.run_root())?,
            Some(old_transaction.clone())
        );
        let spawns = h.control.spawn_count(&h.fleet.first);
        let mut h = reopen(h, /*reconciliation*/ true)?;
        stopped(&mut h)?;
        let decision = unknown(&h, /*confirmation*/ false, /*epoch*/ 111)?;
        assert_eq!(
            decision.release_transaction_sha256,
            old_transaction.transaction_sha256
        );
        let mut absent = decision.clone();
        absent.release_transaction_sha256 = crate::absent_release_transaction_digest();
        let attempts = h.publisher.cas_attempts();
        assert!(resolve(&mut h, &absent, /*epoch*/ 111).is_err());
        assert_eq!(h.publisher.cas_attempts(), attempts);
        resolve(&mut h, &decision, /*epoch*/ 111)?;
        let h = reopen(h, /*reconciliation*/ false)?;
        assert!(!h.supervisor.production_recovery_required(&h.fleet.first)?);
        assert_eq!(
            read_release_transaction(record.layout.run_root())?,
            Some(old_transaction)
        );
        assert_eq!(h.control.spawn_count(&h.fleet.first), spawns);
        assert_eq!(h.intent()?.unknown_effects.len(), 1);
    }
    Ok(())
}

#[test]
fn confirmed_new_prepared_anchor_recovers_before_new_transaction_using_protected_previous_completion()
-> QualificationResult<()> {
    for rollback in [false, true] {
        let mut h = completed(rollback, /*fail_publication*/ false)?;
        let previous = h.intent()?;
        let next = next_grant(&mut h)?;
        let record = h.supervisor.record(&h.fleet.first)?;
        let old_transaction = read_release_transaction(record.layout.run_root())?.unwrap();
        // This is the same actual local-write/external-CAS stage called by
        // apply_production_grant; the crash is before upgrade_slot creates TX.
        let guard = crate::signed_intent_policy::MutationPolicyAdmission::acquire(
            &h.fleet.registry,
            &h.authority.verifier,
            /*qualification_now_seconds*/ 0,
        )?;
        drop(guard.publish_current(&record, Some(&previous), &next)?);
        assert!(crate::signed_intent::predecessor::read(record.layout.run_root())?.is_none());
        assert_eq!(
            h.fleet
                .registry
                .release_intent_anchor(&h.fleet.first)?
                .unwrap()
                .intent_sha256,
            digest_bytes(&next.intent_sha256)?
        );
        assert_eq!(
            read_release_transaction(record.layout.run_root())?,
            Some(old_transaction.clone())
        );
        let spawns = h.control.spawn_count(&h.fleet.first);
        let mut h = reopen(h, /*reconciliation*/ false)?;
        stopped(&mut h)?;
        assert_eq!(h.intent()?.status, SignedIntentStatus::RecoveryRequired);
        let decision = unknown(&h, /*confirmation*/ false, /*epoch*/ 112)?;
        assert_eq!(
            decision.release_transaction_sha256,
            old_transaction.transaction_sha256
        );
        resolve(&mut h, &decision, /*epoch*/ 112)?;
        let h = reopen(h, /*reconciliation*/ false)?;
        assert!(!h.supervisor.production_recovery_required(&h.fleet.first)?);
        assert_eq!(
            read_release_transaction(record.layout.run_root())?,
            Some(old_transaction)
        );
        assert_eq!(h.control.spawn_count(&h.fleet.first), spawns);
    }
    Ok(())
}

#[test]
fn completion_confirmation_material_survives_the_next_grant_publication_cut()
-> QualificationResult<()> {
    let h = completed(/*rollback*/ false, /*fail_publication*/ true)?;
    let mut h = reopen(h, /*reconciliation*/ true)?;
    stopped(&mut h)?;
    let decision = completion(&h, /*epoch*/ 113, /*wrong_pending*/ false)?;
    resolve(&mut h, &decision, /*epoch*/ 113)?;
    let mut h = reopen(h, /*reconciliation*/ false)?;
    let record = h.supervisor.record(&h.fleet.first)?;
    let material =
        crate::signed_intent_confirmation::read_current(record.layout.run_root())?.unwrap();
    let release = AgentRelease::try_from(h.fleet.registry.resolve_release(
        &h.fleet.first,
        record.release_state.current.as_ref().unwrap(),
    )?)?;
    h.supervisor.start_release(&h.fleet.first, release, h.now)?;
    h.control.set_healthy(&h.fleet.first);
    let _ = h.supervisor.tick(h.now);
    let _next = next_grant(&mut h)?;
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
    assert_eq!(
        crate::signed_intent_confirmation::read_predecessor(record.layout.run_root())?,
        Some(material)
    );
    let mut h = reopen(h, /*reconciliation*/ true)?;
    stopped(&mut h)?;
    let decision = unknown(&h, /*confirmation*/ false, /*epoch*/ 114)?;
    resolve(&mut h, &decision, /*epoch*/ 114)?;
    let h = reopen(h, /*reconciliation*/ false)?;
    assert!(!h.supervisor.production_recovery_required(&h.fleet.first)?);
    assert_eq!(h.intent()?.unknown_effects.len(), 1);
    Ok(())
}

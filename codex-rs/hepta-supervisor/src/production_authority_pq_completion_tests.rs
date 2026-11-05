//! Actual hot health/CAS completion followed by a failed publication and cold
//! explicit confirmation. No locally relabelled terminal state can authorize it.
use super::*;
use pretty_assertions::assert_eq;

pub(super) fn digest(value: [u8; 32]) -> Sha256Digest {
    Sha256Digest::parse(
        value
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>(),
    )
    .unwrap()
}

pub(super) fn completed(rollback: bool, fail_publication: bool) -> QualificationResult<Harness> {
    let mut h = Harness::queued()?;
    if rollback {
        let target = h
            .fleet
            .registry
            .resolve_release(&h.fleet.first, &ReleaseId::parse("h7-v2")?)?;
        h.control.reject_spawn_program(target.program);
    }
    h.exit_source();
    h.control.set_healthy(&h.fleet.first);
    if fail_publication {
        h.publisher.drop_next_cas_without_commit();
    }
    let report = h.supervisor.tick(h.now);
    if fail_publication {
        assert!(!report.faults.is_empty());
    } else {
        assert_eq!(report, TickReport::default());
    }
    let intent = h.intent()?;
    assert_eq!(
        intent.status,
        if rollback {
            SignedIntentStatus::RolledBack
        } else {
            SignedIntentStatus::Committed
        }
    );
    let record = h.supervisor.record(&h.fleet.first)?;
    let transaction = read_release_transaction(record.layout.run_root())?.unwrap();
    assert_eq!(
        transaction.phase,
        if rollback {
            ReleaseTransactionPhase::RolledBack
        } else {
            ReleaseTransactionPhase::Committed
        }
    );
    assert!(crate::signed_intent_policy::terminal_owner_matches(
        &intent,
        &transaction,
        &record
    ));
    Ok(h)
}

pub(super) fn completion(
    h: &Harness,
    epoch: u64,
    wrong_pending: bool,
) -> QualificationResult<crate::ProductionRecoveryDecision> {
    let intent = h.intent()?;
    let record = h.supervisor.record(&h.fleet.first)?;
    let guard = CurrentRecoveryAdmission::acquire(&h.fleet.registry, &h.authority.verifier)?;
    let predecessor = crate::UnknownRecoveryPredecessorV1::from_anchor(
        &guard.expected(&h.fleet.first)?.unwrap(),
    )?;
    let observed = guard.binding(
        &h.fleet.registry,
        &h.fleet.first,
        record.release_state.current.as_ref().unwrap(),
    )?;
    let mut observation = crate::CompletionPublicationObservationV1 {
        schema_version: 1,
        predecessor,
        pending_publication_sha256: digest(guard.pending_publication_sha256()?),
        release_state_sha256: crate::unknown_recovery_publication::state_sha256(&record)?,
        release_state_generation: record.release_state.generation,
        admission_frontier_sha256: Sha256Digest::parse(observed.admission_frontier_sha256.clone())?,
    };
    if wrong_pending {
        observation.pending_publication_sha256 =
            Sha256Digest::for_bytes(b"different retained proposal");
    }
    let transaction = read_release_transaction(record.layout.run_root())?.unwrap();
    let unix = guard.now_seconds()?;
    Ok(h.authority.recovery.sign_confirm_completion_publication(
        &intent,
        &observed,
        &observation,
        transaction.transaction_sha256,
        record.lifecycle.generation,
        epoch,
        unix,
        unix + 60,
    )?)
}

#[test]
fn actual_hot_completion_cas_error_requires_exact_fresh_confirmation_and_preserves_all_original_bytes()
-> QualificationResult<()> {
    for rollback in [false, true] {
        let h = completed(rollback, /*fail_publication*/ true)?;
        let intent = h.intent()?;
        let record = h.supervisor.record(&h.fleet.first)?;
        let transaction = read_release_transaction(record.layout.run_root())?.unwrap();
        let state = record.release_state.clone();
        let spawns = h.control.spawn_count(&h.fleet.first);
        let mut h = reopen(h, /*reconciliation*/ true)?;
        stopped(&mut h)?;
        let invalid = completion(&h, /*epoch*/ 101, /*wrong_pending*/ true)?;
        let before = (h.publisher.frontier()?, h.publisher.cas_attempts());
        assert!(resolve(&mut h, &invalid, /*epoch*/ 101).is_err());
        assert_eq!(
            (h.publisher.frontier()?, h.publisher.cas_attempts()),
            before
        );
        assert_eq!(h.intent()?, intent);
        let decision = completion(&h, /*epoch*/ 101, /*wrong_pending*/ false)?;
        resolve(&mut h, &decision, /*epoch*/ 101)?;
        assert_eq!(h.intent()?, intent);
        let record = h.supervisor.record(&h.fleet.first)?;
        assert_eq!(
            read_release_transaction(record.layout.run_root())?,
            Some(transaction.clone())
        );
        assert_eq!(record.release_state, state);
        assert_eq!(h.control.spawn_count(&h.fleet.first), spawns);
        assert!(h.supervisor.production_recovery_required(&h.fleet.first)?);
        let mut h = reopen(h, /*reconciliation*/ false)?;
        assert!(!h.supervisor.production_recovery_required(&h.fleet.first)?);
        h.publisher
            .advance_clock_to(h.grant.expires_at_unix_seconds + 1);
        let release = AgentRelease::try_from(
            h.fleet
                .registry
                .resolve_release(&h.fleet.first, state.current.as_ref().unwrap())?,
        )?;
        h.supervisor.start_release(&h.fleet.first, release, h.now)?;
        assert_eq!(h.control.spawn_count(&h.fleet.first), spawns + 1);
        assert_eq!(h.intent()?, intent);
    }
    Ok(())
}

#[test]
fn unrelated_local_terminal_label_cannot_match_an_original_hot_completion_proposal()
-> QualificationResult<()> {
    let h = completed(/*rollback*/ false, /*fail_publication*/ true)?;
    let original = h.intent()?;
    let forged = original.with_status(SignedIntentStatus::RolledBack)?;
    let path = h
        .supervisor
        .record(&h.fleet.first)?
        .layout
        .run_root()
        .join(crate::signed_intent::SIGNED_INTENT_FILE);
    std::fs::write(&path, serde_json::to_vec(&forged)?)?;
    let mut h = reopen(h, /*reconciliation*/ true)?;
    stopped(&mut h)?;
    let attempts = h.publisher.cas_attempts();
    // A forged status cannot supply a valid completion signer input for the
    // actual current target, nor can the original proposal be overwritten.
    assert!(completion(&h, /*epoch*/ 102, /*wrong_pending*/ false).is_err());
    assert_eq!(h.publisher.cas_attempts(), attempts);
    assert_eq!(h.intent()?, forged);
    assert_eq!(h.control.spawn_count(&h.fleet.first), 2);
    Ok(())
}

#[path = "production_authority_pq_predecessor_tests.rs"]
mod predecessors;

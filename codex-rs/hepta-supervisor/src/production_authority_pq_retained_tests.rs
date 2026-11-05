//! Two genuine no-commit CAS errors leave one original and one replacement.
//! A new signature may retry that exact replacement without rewriting history.
use super::completed::completed;
use super::completed::completion;
use super::completed::digest;
use super::*;
use pretty_assertions::assert_eq;

fn retry(
    h: &Harness,
    epoch: u64,
    wrong_retained: bool,
) -> QualificationResult<crate::ProductionRecoveryDecision> {
    let intent = h.intent()?;
    let record = h.supervisor.record(&h.fleet.first)?;
    let guard = CurrentRecoveryAdmission::acquire(&h.fleet.registry, &h.authority.verifier)?;
    let predecessor = match guard.expected(&h.fleet.first)? {
        Some(anchor) => crate::UnknownRecoveryPredecessorV1::from_anchor(&anchor)?,
        None => crate::UnknownRecoveryPredecessorV1::from_absent(&h.fleet.first),
    };
    let binding = guard.binding(
        &h.fleet.registry,
        &h.fleet.first,
        record.release_state.current.as_ref().unwrap(),
    )?;
    let mut observation = crate::RetainedPublicationObservationV1 {
        schema_version: 1,
        predecessor,
        original_pending_sha256: digest(guard.pending_publication_sha256()?),
        replacement_pending_sha256: digest(guard.replacement_publication_sha256()?.unwrap()),
        retained_state_sha256: digest(guard.retained_reconciliation_sha256()?.unwrap()),
        replacement_anchor_sha256: digest(guard.replacement().unwrap().sha256()?),
        release_state_sha256: crate::unknown_recovery_publication::state_sha256(&record)?,
        release_state_generation: record.release_state.generation,
        admission_frontier_sha256: Sha256Digest::parse(binding.admission_frontier_sha256.clone())?,
    };
    if wrong_retained {
        observation.retained_state_sha256 = Sha256Digest::for_bytes(b"different attempt presence");
    }
    let transaction = read_release_transaction(record.layout.run_root())?
        .map_or_else(crate::absent_release_transaction_digest, |transaction| {
            transaction.transaction_sha256
        });
    let unix = guard.now_seconds()?;
    Ok(h.authority.recovery.sign_retry_retained_publication(
        &intent,
        &binding,
        &observation,
        transaction,
        record.lifecycle.generation,
        epoch,
        unix,
        unix + 60,
    )?)
}

type LocalMaterial = (
    Vec<u8>,
    Option<Vec<u8>>,
    Option<crate::signed_intent_confirmation::SignedIntentPublicationConfirmation>,
);

fn local_material(h: &Harness) -> QualificationResult<LocalMaterial> {
    let record = h.supervisor.record(&h.fleet.first)?;
    Ok((
        std::fs::read(
            record
                .layout
                .run_root()
                .join(crate::signed_intent::SIGNED_INTENT_FILE),
        )?,
        read_release_transaction(record.layout.run_root())?
            .map(|transaction| serde_json::to_vec(&transaction))
            .transpose()?,
        crate::signed_intent_confirmation::read_current(record.layout.run_root())?,
    ))
}

#[test]
fn actual_second_cas_error_cold_retry_never_replaces_original_completion_or_unknown_material()
-> QualificationResult<()> {
    for complete in [false, true] {
        let mut h = if complete {
            let h = completed(/*rollback*/ false, /*fail_publication*/ true)?;
            let mut h = reopen(h, /*reconciliation*/ true)?;
            stopped(&mut h)?;
            h
        } else {
            failed_first_publication()?
        };
        let decision = if complete {
            completion(&h, /*epoch*/ 121, /*wrong_pending*/ false)?
        } else {
            unknown(&h, /*confirmation*/ false, /*epoch*/ 121)?
        };
        h.publisher.drop_next_cas_without_commit();
        let frontier = h.publisher.frontier()?;
        assert!(resolve(&mut h, &decision, /*epoch*/ 121).is_err());
        assert_eq!(h.publisher.frontier()?, frontier);
        let unchanged = local_material(&h)?;
        let directory = h
            .fleet
            .registry
            .layout()
            .state_root()
            .join("pq-release-authority-v1");
        let proposal = std::fs::read(directory.join("intent-reconciliation-proposal.v1.json"))?;
        let attempt = std::fs::read(directory.join("intent-reconciliation-attempt.v1.json"))?;
        let spawns = h.control.spawn_count(&h.fleet.first);
        let mut h = reopen(h, /*reconciliation*/ true)?;
        let count = h.publisher.cas_attempts();
        // The old confirmation method must reject before overwriting the
        // exact public material named by the retained replacement proposal.
        assert!(resolve(&mut h, &decision, /*epoch*/ 122).is_err());
        let wrong = retry(&h, /*epoch*/ 122, /*wrong_retained*/ true)?;
        assert!(resolve(&mut h, &wrong, /*epoch*/ 122).is_err());
        assert_eq!(h.publisher.cas_attempts(), count);
        assert_eq!(local_material(&h)?, unchanged);
        assert_eq!(
            std::fs::read(directory.join("intent-reconciliation-proposal.v1.json"))?,
            proposal
        );
        assert_eq!(
            std::fs::read(directory.join("intent-reconciliation-attempt.v1.json"))?,
            attempt
        );
        let expired = retry(&h, /*epoch*/ 122, /*wrong_retained*/ false)?;
        h.publisher
            .advance_clock_to(expired.expires_at_unix_seconds);
        assert!(resolve(&mut h, &expired, /*epoch*/ 122).is_err());
        assert_eq!(h.publisher.cas_attempts(), count);
        let current = retry(&h, /*epoch*/ 123, /*wrong_retained*/ false)?;
        resolve(&mut h, &current, /*epoch*/ 123)?;
        assert_eq!(h.publisher.cas_attempts(), count + 1);
        assert_eq!(local_material(&h)?, unchanged);
        assert_eq!(std::fs::read(directory.join("journal.v1.json"))?, proposal);
        assert_eq!(h.control.spawn_count(&h.fleet.first), spawns);
        let h = reopen(h, /*reconciliation*/ false)?;
        assert!(!h.supervisor.production_recovery_required(&h.fleet.first)?);
        assert_eq!(local_material(&h)?, unchanged);
        assert_eq!(h.control.spawn_count(&h.fleet.first), spawns);
    }
    Ok(())
}

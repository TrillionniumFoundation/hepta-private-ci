use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_authority_tests::Fixture;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::queue;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_anchor_tests::witness;
use crate::release_qualification_trust::NOW;

#[test]
fn uncertain_intent_cas_retains_original_proposal_and_only_actual_winner_completes()
-> QualificationResult<()> {
    for committed in [true, false] {
        let (f, _id, policy) = setup()?;
        let journal = f.journal();
        let old = std::fs::read(&journal)?;
        let old_frontier = f.publisher.frontier()?;
        let value = prepared(&f, policy, 8, 1);
        if committed {
            f.publisher.drop_next_committed_cas_reply();
        } else {
            f.publisher.drop_next_cas_without_commit();
        }
        assert!(matches!(
            f.registry
                .admit_protocol_configuration(policy)?
                .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
                .anchor_intent(None, &value),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        assert_eq!(std::fs::read(&journal)?, old);
        assert!(matches!(
            f.registry.release_intent_anchor(&f.agent),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        let directory = journal
            .parent()
            .ok_or("owner directory missing")?
            .to_owned();
        let retained = (
            std::fs::read(directory.join("attempt.v1.json"))?,
            std::fs::read(directory.join("proposal.v1.json"))?,
            f.publisher.cas_attempts(),
        );
        let future = f.publisher.frontier()?;
        let Fixture {
            registry,
            publisher,
            root,
            agent,
            _temp,
            ..
        } = f;
        drop(registry);
        assert!(matches!(
            FleetRegistry::open_existing_with_release_authority(root.clone(), publisher.config()),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        if committed {
            assert_ne!(future, old_frontier);
            let recovered =
                FleetRegistry::recover_completed_release_update(root, publisher.config())?;
            assert_eq!(recovered.release_intent_anchor(&agent)?, Some(value));
            assert_eq!(publisher.cas_attempts(), retained.2);
            assert_eq!(publisher.frontier()?, future);
        } else {
            assert_eq!(future, old_frontier);
            for _ in 0..2 {
                assert!(matches!(
                    FleetRegistry::recover_completed_release_update(
                        root.clone(),
                        publisher.config()
                    ),
                    Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
                ));
                assert_eq!(
                    (
                        std::fs::read(directory.join("attempt.v1.json"))?,
                        std::fs::read(directory.join("proposal.v1.json"))?,
                        publisher.cas_attempts()
                    ),
                    retained
                );
                assert_eq!(publisher.frontier()?, old_frontier);
            }
        }
    }
    Ok(())
}

#[test]
fn pre_cas_unanchored_unknown_requires_explicit_predecessor_and_consumes_new_grant()
-> QualificationResult<()> {
    // This is specifically the cut before Fleet prepares a CAS. A separate
    // reconciliation test covers a real failed CAS with retained marker files.
    let (f, id, policy) = setup()?;
    let first = prepared(&f, policy, 9, 1);
    let queued = queue(&f, &id, policy, &first)?;
    let mut terminal = advance(&queued, Phase::Committed);
    terminal.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    f.registry.record_intent_history(&queued, &terminal)?;
    let mut abandoned = prepared(&f, policy, 10, terminal.generation + 1);
    abandoned.phase = Phase::Aborted;
    abandoned.terminal_witness = Some(witness(WitnessKind::AbandonUnknown, Some([84; 32])));
    let attempts = f.publisher.cas_attempts();
    assert!(
        f.registry
            .record_intent_history(&terminal, &abandoned)
            .is_err()
    );
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .recover_intent(Some(&terminal), &abandoned, [84; 32])
            .is_err()
    );
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .recover_unanchored_intent(&terminal, &abandoned, [84; 32], [85; 32])
            .is_err()
    );
    assert_eq!(f.publisher.cas_attempts(), attempts);
    let digest = terminal.sha256()?;
    let mut changed = terminal.clone();
    changed.intent_sha256[1] ^= 1;
    assert_ne!(changed.sha256()?, digest);
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .recover_unanchored_intent(&terminal, &abandoned, [84; 32], digest)?,
    );
    assert_eq!(
        f.registry.release_intent_anchor(&f.agent)?,
        Some(abandoned.clone())
    );
    let replay = prepared(&f, policy, 10, abandoned.generation + 1);
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&abandoned), &replay)
            .is_err()
    );
    Ok(())
}

#[test]
fn already_durable_unknown_confirmation_is_distinct_from_dispatch_or_original_recovery()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let first = prepared(&f, policy, 11, 1);
    let queued = queue(&f, &id, policy, &first)?;
    let quarantine = advance(&queued, Phase::RecoveryRequired);
    f.registry.record_intent_history(&queued, &quarantine)?;
    let mut closed = advance(&quarantine, Phase::Aborted);
    let mut proof = witness(WitnessKind::AbandonUnknown, Some([86; 32]));
    proof.publication_confirmation_sha256 = Some([87; 32]);
    closed.terminal_witness = Some(proof);
    assert!(
        f.registry
            .record_intent_history(&quarantine, &closed)
            .is_err()
    );
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .recover_intent(Some(&quarantine), &closed, [86; 32])
            .is_err()
    );
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .confirm_abandon_unknown_publication(&quarantine, &closed, [87; 32], [88; 32])
            .is_err()
    );
    let mut dispatch = closed.clone();
    dispatch.phase = Phase::Committed;
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .confirm_abandon_unknown_publication(
                &quarantine,
                &dispatch,
                [87; 32],
                quarantine.sha256()?
            )
            .is_err()
    );
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .confirm_abandon_unknown_publication(
                &quarantine,
                &closed,
                [87; 32],
                quarantine.sha256()?,
            )?,
    );
    let reopened =
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config())?;
    assert_eq!(reopened.release_intent_anchor(&f.agent)?, Some(closed));
    Ok(())
}

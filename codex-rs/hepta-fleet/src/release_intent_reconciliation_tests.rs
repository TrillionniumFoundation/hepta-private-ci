//! Native owner/component cuts. The service authenticates real PQ frames and
//! persists real exact CAS results; fixture custody is not production custody.

use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_trust_unix::UnixPqReleaseFrontier;
use codex_hepta_paths::HeptaFleetRoot;

use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::PqReleaseQualification;
use crate::QualificationResult;
use crate::ReleaseBinding;
use crate::ReleaseId;
use crate::ReleaseIntentAnchorV1 as Anchor;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_authority::PendingUpdate;
use crate::release_authority_tests::Fixture;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::queue;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_anchor_tests::witness;
use crate::release_qualification_trust::NOW;

pub(super) struct ColdPending {
    pub _temp: tempfile::TempDir,
    pub root: HeptaFleetRoot,
    pub publisher: PqReleaseQualification,
    pub agent: AgentId,
    pub source: PathBuf,
    pub release: ReleaseId,
    pub policy: [u8; 32],
    pub pending: Anchor,
    pub attempt: PendingUpdate,
    pub binding: ReleaseBinding,
    pub directory: PathBuf,
}

impl ColdPending {
    pub fn capture(
        f: Fixture,
        release: ReleaseId,
        policy: [u8; 32],
        pending: Anchor,
        binding: ReleaseBinding,
    ) -> QualificationResult<Self> {
        let directory = f
            .journal()
            .parent()
            .ok_or("owner directory missing")?
            .to_owned();
        let attempt = serde_json::from_slice(&std::fs::read(directory.join("attempt.v1.json"))?)?;
        let Fixture {
            registry,
            publisher,
            root,
            agent,
            source,
            _temp,
        } = f;
        drop(registry); // close the actual local owner before cold recovery
        Ok(Self {
            _temp,
            root,
            publisher,
            agent,
            source,
            release,
            policy,
            pending,
            attempt,
            binding,
            directory,
        })
    }
    pub fn first(deferred: bool) -> QualificationResult<Self> {
        let (f, release, policy) = setup()?;
        let pending = prepared(&f, policy, 21, 1);
        let binding = f.registry.resolve_release_binding(&f.agent, &release)?;
        if deferred {
            f.publisher.defer_next_cas_until_competing_attempt();
        } else {
            f.publisher.drop_next_cas_without_commit();
        }
        assert!(matches!(
            f.registry
                .admit_protocol_configuration(policy)?
                .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
                .anchor_intent(None, &pending),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        Self::capture(f, release, policy, pending, binding)
    }
    pub fn mode(&self) -> QualificationResult<FleetRegistry> {
        Ok(FleetRegistry::open_existing_for_release_intent_recovery(
            self.root.clone(),
            self.publisher.config(),
        )?)
    }
    pub fn ordinary(&self) -> Result<FleetRegistry, FleetRegistryError> {
        FleetRegistry::open_existing_with_release_authority(
            self.root.clone(),
            self.publisher.config(),
        )
    }
    pub fn unknown(&self, confirmation: Option<[u8; 32]>) -> Anchor {
        let mut next = self.pending.clone();
        next.phase = Phase::Aborted;
        next.intent_sha256[0] ^= 64;
        let mut proof = witness(WitnessKind::AbandonUnknown, Some([91; 32]));
        proof.publication_confirmation_sha256 = confirmation;
        next.terminal_witness = Some(proof);
        next
    }
    pub fn pending_bytes(&self) -> QualificationResult<(Vec<u8>, Vec<u8>)> {
        Ok((
            std::fs::read(self.directory.join("attempt.v1.json"))?,
            std::fs::read(self.directory.join("proposal.v1.json"))?,
        ))
    }
}

#[test]
fn first_none_anchor_actual_failed_cas_closes_only_by_explicit_signed_reconciliation()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    let original = f.pending_bytes()?;
    let before = f.publisher.frontier()?;
    assert_eq!(before, f.attempt.expected);
    assert!(matches!(
        f.ordinary(),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    let mode = f.mode()?;
    assert!(mode.is_release_intent_reconciliation());
    assert!(mode.resolve_release(&f.agent, &f.release).is_err());
    assert!(mode.allow_release(&f.agent, &f.release).is_err());
    assert!(mode.admit_protocol_configuration(f.policy).is_err());
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert!(guard.expected_intent_anchor().is_none());
    assert_eq!(guard.pending_intent_anchor(), &f.pending);
    assert_eq!(guard.release_binding(&f.agent, &f.release)?, f.binding);
    assert_eq!(guard.revalidate()?, NOW * 1000);
    let next = f.unknown(None);
    guard.reconcile_abandon_unknown(&next, [91; 32], None, Anchor::absent_sha256(&f.agent))?;
    assert!(mode.resolve_release(&f.agent, &f.release).is_err());
    drop(mode);
    let reopened = f.ordinary()?;
    assert_eq!(reopened.release_intent_anchor(&f.agent)?, Some(next));
    assert_eq!(
        reopened.resolve_release_binding(&f.agent, &f.release)?,
        f.binding
    );
    let future = f.publisher.frontier()?;
    assert_ne!(future, before);
    assert_eq!(
        future.ok_or("missing frontier")?.checkpoint_sha256,
        before.ok_or("missing old frontier")?.checkpoint_sha256
    );
    // The actual late original request cannot consume the old value now.
    let client = UnixPqReleaseFrontier::new(f.publisher.config().frontier)?;
    assert_eq!(
        client.compare_and_set(
            &f.publisher.config().owner_id,
            &f.attempt.expected,
            &Some(f.attempt.proposed)
        ),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(f.publisher.frontier()?, future);
    // The retained delta reconstructs exactly the old proposal bytes.
    let journal: crate::release_authority_state::Journal =
        serde_json::from_slice(&std::fs::read(f.directory.join("journal.v1.json"))?)?;
    let Some(crate::release_authority_state::JournalEntry::IntentReconciliation { record }) =
        journal.entries.last()
    else {
        return Err("missing retained reconciliation".into());
    };
    let mut prefix = journal.clone();
    prefix.entries.pop();
    assert_eq!(
        crate::release_authority_set::record_bytes(&record.original.original_attempt)?,
        original.0
    );
    assert_eq!(
        crate::release_authority_set::record_bytes(&record.original.reconstruct(&prefix)?)?,
        original.1
    );
    Ok(())
}

#[test]
fn actual_deferred_original_wins_after_old_reads_and_replacement_stays_uncommitted()
-> QualificationResult<()> {
    let f = ColdPending::first(true)?;
    let original = f.pending_bytes()?;
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(f.publisher.frontier()?, f.attempt.expected);
    assert_eq!(guard.release_binding(&f.agent, &f.release)?, f.binding);
    let next = f.unknown(None);
    assert!(matches!(
        guard.reconcile_abandon_unknown(&next, [91; 32], None, Anchor::absent_sha256(&f.agent)),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert_eq!(f.publisher.frontier()?, Some(f.attempt.proposed));
    assert_eq!(f.pending_bytes()?, original);
    assert!(
        f.directory
            .join("intent-reconciliation-attempt.v1.json")
            .exists()
    );
    assert!(
        f.directory
            .join("intent-reconciliation-proposal.v1.json")
            .exists()
    );
    let attempts = f.publisher.cas_attempts();
    drop(mode);
    let recovered =
        FleetRegistry::recover_completed_release_update(f.root.clone(), f.publisher.config())?;
    // A known original winner is its original Prepared snapshot, never a
    // fabricated Unknown or successful completion. H7 must still quarantine it.
    assert_eq!(
        recovered.release_intent_anchor(&f.agent)?,
        Some(f.pending.clone())
    );
    assert_eq!(f.publisher.cas_attempts(), attempts);
    let quarantine = advance(&f.pending, Phase::RecoveryRequired);
    recovered.record_intent_history(&f.pending, &quarantine)?;
    assert_eq!(recovered.release_intent_anchor(&f.agent)?, Some(quarantine));
    Ok(())
}

#[test]
fn lost_replacement_reply_cold_recovery_completes_the_exact_winner_without_another_cas()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    let original = f.pending_bytes()?;
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    f.publisher.drop_next_committed_cas_reply();
    let next = f.unknown(Some([92; 32]));
    assert!(matches!(
        guard.reconcile_abandon_unknown(
            &next,
            [91; 32],
            Some([92; 32]),
            Anchor::absent_sha256(&f.agent)
        ),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert_eq!(f.pending_bytes()?, original);
    let proposal = std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?;
    let future = f.publisher.frontier()?;
    let attempts = f.publisher.cas_attempts();
    drop(mode);
    assert!(matches!(
        f.ordinary(),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    let recovered =
        FleetRegistry::recover_completed_release_update(f.root.clone(), f.publisher.config())?;
    assert_eq!(recovered.release_intent_anchor(&f.agent)?, Some(next));
    assert_eq!(
        std::fs::read(f.directory.join("journal.v1.json"))?,
        proposal
    );
    assert_eq!(
        (f.publisher.frontier()?, f.publisher.cas_attempts()),
        (future, attempts)
    );
    Ok(())
}

#[test]
fn second_uncertain_no_commit_keeps_both_attempts_and_never_allocates_a_third_proposal()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    f.publisher.drop_next_cas_without_commit();
    assert!(
        guard
            .reconcile_abandon_unknown(
                &f.unknown(None),
                [91; 32],
                None,
                Anchor::absent_sha256(&f.agent)
            )
            .is_err()
    );
    let retained = (
        f.pending_bytes()?,
        std::fs::read(f.directory.join("intent-reconciliation-attempt.v1.json"))?,
        std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?,
        f.publisher.cas_attempts(),
    );
    drop(mode);
    for _ in 0..2 {
        let cold = f.mode()?;
        let guard = cold
            .admit_pending_intent_reconciliation(f.policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
        assert!(guard.replacement_intent_anchor().is_some());
        assert!(
            guard
                .reconcile_abandon_unknown(
                    &f.unknown(None),
                    [91; 32],
                    None,
                    Anchor::absent_sha256(&f.agent)
                )
                .is_err()
        );
        assert!(
            FleetRegistry::recover_completed_release_update(f.root.clone(), f.publisher.config())
                .is_err()
        );
        assert_eq!(
            (
                f.pending_bytes()?,
                std::fs::read(f.directory.join("intent-reconciliation-attempt.v1.json"))?,
                std::fs::read(f.directory.join("intent-reconciliation-proposal.v1.json"))?,
                f.publisher.cas_attempts()
            ),
            retained
        );
        assert_eq!(f.publisher.frontier()?, f.attempt.expected);
    }
    Ok(())
}

#[test]
fn retained_original_set_reconstructs_after_a_later_signed_set_replaces_current_set()
-> QualificationResult<()> {
    let mut f = ColdPending::first(false)?;
    let original = f.pending_bytes()?;
    let mode = f.mode()?;
    mode.admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
        .reconcile_abandon_unknown(
            &f.unknown(None),
            [91; 32],
            None,
            Anchor::absent_sha256(&f.agent),
        )?;
    drop(mode);
    let ordinary = f.ordinary()?;
    let second = ReleaseId::parse("later-current-set")?;
    f.publisher
        .install_release(&ordinary, second.clone(), &f.source, Vec::new())?;
    ordinary.allow_release(&f.agent, &second)?;
    f.publisher
        .publish_member_ids(&ordinary, std::slice::from_ref(&second), NOW + 3600)?;
    drop(ordinary);
    let reopened = f.ordinary()?;
    assert!(reopened.resolve_release(&f.agent, &second).is_ok());
    assert!(reopened.resolve_release(&f.agent, &f.release).is_err());
    let journal: crate::release_authority_state::Journal =
        serde_json::from_slice(&std::fs::read(f.directory.join("journal.v1.json"))?)?;
    let (index, record) = journal
        .entries
        .iter()
        .enumerate()
        .find_map(|(index, entry)| match entry {
            crate::release_authority_state::JournalEntry::IntentReconciliation { record } => {
                Some((index, record))
            }
            _ => None,
        })
        .ok_or("retained reconciliation missing")?;
    let mut prefix = journal.clone();
    prefix.entries.truncate(index);
    assert_eq!(
        crate::release_authority_set::record_bytes(&record.original.reconstruct(&prefix)?)?,
        original.1
    );
    Ok(())
}

#[test]
fn same_owner_policy_observation_matches_ordinary_binding_and_protected_closed_predecessor()
-> QualificationResult<()> {
    let (f, release, policy) = setup()?;
    let first = prepared(&f, policy, 22, 1);
    let queued = queue(&f, &release, policy, &first)?;
    let mut terminal = advance(&queued, Phase::Committed);
    terminal.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    f.registry.record_intent_history(&queued, &terminal)?;
    let next = prepared(&f, policy, 23, terminal.generation + 1);
    drop(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&terminal), &next)?,
    );
    let expected = f.registry.resolve_release_binding(&f.agent, &release)?;
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(
        guard.previous_closed_intent_anchor(&f.agent)?,
        Some(terminal.clone())
    );
    assert_eq!(
        f.registry
            .release_binding_with_protocol_configuration(&guard, &f.agent, &release)?,
        expected
    );
    drop(guard);
    let release_guard = f.registry.admit_release(&f.agent, &release)?;
    assert_eq!(
        release_guard.previous_closed_intent_anchor()?,
        Some(terminal)
    );
    assert_eq!(release_guard.intent_anchor()?, Some(next));
    Ok(())
}

use std::os::unix::fs::PermissionsExt;

use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::ReleaseIntentAnchorV1 as Anchor;
use crate::ReleaseIntentPhaseV1 as Phase;
use crate::ReleaseIntentWitnessKindV1 as WitnessKind;
use crate::release_intent_anchor_tests::advance;
use crate::release_intent_anchor_tests::prepared;
use crate::release_intent_anchor_tests::queue;
use crate::release_intent_anchor_tests::setup;
use crate::release_intent_anchor_tests::witness;
use crate::release_intent_reconciliation_tests::ColdPending;
use crate::release_qualification_trust::NOW;

#[test]
fn actual_committed_cas_failure_requires_exact_pending_publication_confirmation()
-> QualificationResult<()> {
    check_hot_terminal_cas_confirmation(Phase::Committed)
}

#[test]
fn actual_rolled_back_cas_failure_requires_exact_pending_publication_confirmation()
-> QualificationResult<()> {
    check_hot_terminal_cas_confirmation(Phase::RolledBack)
}

fn check_hot_terminal_cas_confirmation(phase: Phase) -> QualificationResult<()> {
    let (f, release, policy) = setup()?;
    let first = prepared(&f, policy, 24, 1);
    let queued = queue(&f, &release, policy, &first)?;
    let binding = f.registry.resolve_release_binding(&f.agent, &release)?;
    let mut terminal = advance(&queued, phase);
    terminal.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    f.publisher.drop_next_cas_without_commit();
    assert!(matches!(
        f.registry.record_intent_history(&queued, &terminal),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    let f = ColdPending::capture(f, release, policy, terminal, binding)?;
    let original = f.pending_bytes()?;
    let mode = f.mode()?;
    let mut confirmed = f.pending.clone();
    confirmed
        .terminal_witness
        .as_mut()
        .ok_or("terminal witness missing")?
        .publication_confirmation_sha256 = Some([93; 32]);
    let guard = mode
        .admit_pending_intent_reconciliation(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    let pending_sha = guard.pending_publication_sha256()?;
    let expected_sha = guard
        .expected_intent_anchor()
        .ok_or("queued anchor missing")?
        .sha256()?;
    assert_eq!(guard.release_binding(&f.agent, &f.release)?, f.binding);
    assert!(
        guard
            .reconcile_completed_publication(&confirmed, [93; 32], expected_sha, [94; 32])
            .is_err()
    );
    let mut substituted = confirmed.clone();
    substituted.intent_sha256[0] ^= 1;
    assert!(
        mode.admit_pending_intent_reconciliation(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .reconcile_completed_publication(&substituted, [93; 32], expected_sha, pending_sha)
            .is_err()
    );
    let mut substituted = confirmed.clone();
    substituted
        .terminal_witness
        .as_mut()
        .ok_or("witness missing")?
        .release_state_generation += 1;
    assert!(
        mode.admit_pending_intent_reconciliation(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .reconcile_completed_publication(&substituted, [93; 32], expected_sha, pending_sha)
            .is_err()
    );
    assert_eq!(f.pending_bytes()?, original);
    assert!(
        !f.directory
            .join("intent-reconciliation-proposal.v1.json")
            .exists()
    );
    mode.admit_pending_intent_reconciliation(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
        .reconcile_completed_publication(&confirmed, [93; 32], expected_sha, pending_sha)?;
    assert!(mode.admit_release(&f.agent, &f.release).is_err());
    drop(mode);
    let ordinary = f.ordinary()?;
    assert_eq!(ordinary.release_intent_anchor(&f.agent)?, Some(confirmed));
    assert_eq!(
        ordinary.resolve_release_binding(&f.agent, &f.release)?,
        f.binding
    );
    Ok(())
}

#[test]
fn prepared_unknown_cannot_be_confirmed_as_a_completed_effect_or_change_its_original_grant()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    let pending = guard.pending_publication_sha256()?;
    let mut forged = f.pending.clone();
    forged.phase = Phase::Committed;
    let mut proof = witness(WitnessKind::CompletedReleaseCas, None);
    proof.publication_confirmation_sha256 = Some([95; 32]);
    forged.terminal_witness = Some(proof);
    assert!(
        guard
            .reconcile_completed_publication(
                &forged,
                [95; 32],
                Anchor::absent_sha256(&f.agent),
                pending
            )
            .is_err()
    );
    let mut different_grant = f.unknown(None);
    different_grant.grant_sha256[0] ^= 1;
    assert!(
        mode.admit_pending_intent_reconciliation(f.policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .reconcile_abandon_unknown(
                &different_grant,
                [91; 32],
                None,
                Anchor::absent_sha256(&f.agent)
            )
            .is_err()
    );
    assert!(
        !f.directory
            .join("intent-reconciliation-proposal.v1.json")
            .exists()
    );
    assert_eq!(f.publisher.frontier()?, f.attempt.expected);
    Ok(())
}

#[test]
fn explicit_recovery_observation_rechecks_actual_allowance_manifest_and_program_bytes()
-> QualificationResult<()> {
    let f = ColdPending::first(false)?;
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(guard.release_binding(&f.agent, &f.release)?, f.binding);
    let catalog = mode.layout().releases_root().join(f.release.as_str());
    let record = mode
        .load()?
        .agent(&f.agent)
        .cloned()
        .ok_or("agent missing")?;
    let allowance = record
        .layout
        .releases_root()
        .join(format!("allow-{}.json", f.release));
    let paths = [
        catalog.join("bin/hepta-agentd"),
        catalog.join("release.json"),
        allowance,
    ];
    for (index, path) in paths.iter().enumerate() {
        let original = std::fs::read(path)?;
        let permissions = std::fs::metadata(path)?.permissions();
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        let changed = if index == 2 {
            let mut value: serde_json::Value = serde_json::from_slice(&original)?;
            value["manifest_sha256"] = "11".repeat(32).into();
            serde_json::to_vec(&value)?
        } else {
            let mut value = original.clone();
            value.push(b' ');
            value
        };
        std::fs::write(path, changed)?;
        std::fs::set_permissions(path, permissions.clone())?;
        assert!(guard.release_binding(&f.agent, &f.release).is_err());
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        std::fs::write(path, &original)?;
        std::fs::set_permissions(path, permissions)?;
        assert_eq!(guard.release_binding(&f.agent, &f.release)?, f.binding);
    }
    assert_eq!(f.publisher.frontier()?, f.attempt.expected);
    Ok(())
}

#[test]
fn pending_non_intent_update_and_expired_recovery_policy_cannot_use_special_open_or_cas()
-> QualificationResult<()> {
    let (f, release, _policy) = setup()?;
    f.publisher.drop_next_cas_without_commit();
    assert!(matches!(
        f.registry.revoke_release(&f.agent, &release),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    let before = (
        std::fs::read(f.journal())?,
        f.publisher.frontier()?,
        f.publisher.cas_attempts(),
    );
    assert!(
        FleetRegistry::open_existing_for_release_intent_recovery(
            f.root.clone(),
            f.publisher.config()
        )
        .is_err()
    );
    assert_eq!(
        (
            std::fs::read(f.journal())?,
            f.publisher.frontier()?,
            f.publisher.cas_attempts()
        ),
        before
    );
    drop(f);

    let f = ColdPending::first(false)?;
    let mode = f.mode()?;
    assert!(mode.admit_pending_intent_reconciliation([96; 32]).is_err());
    let guard = mode
        .admit_pending_intent_reconciliation(f.policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    let old = f.pending_bytes()?;
    f.publisher.advance_clock_to(NOW + 60);
    assert!(guard.revalidate().is_err());
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
    assert_eq!(f.pending_bytes()?, old);
    assert!(
        !f.directory
            .join("intent-reconciliation-proposal.v1.json")
            .exists()
    );
    Ok(())
}

#[test]
fn cold_completed_only_recovery_finishes_interrupted_cleanup_for_either_actual_winner()
-> QualificationResult<()> {
    for original_wins in [true, false] {
        let f = ColdPending::first(original_wins)?;
        let mode = f.mode()?;
        let guard = mode
            .admit_pending_intent_reconciliation(f.policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
        if !original_wins {
            f.publisher.drop_next_committed_cas_reply();
        }
        let unknown = f.unknown(None);
        assert!(
            guard
                .reconcile_abandon_unknown(
                    &unknown,
                    [91; 32],
                    None,
                    Anchor::absent_sha256(&f.agent)
                )
                .is_err()
        );
        let future = f.publisher.frontier()?;
        let attempts = f.publisher.cas_attempts();
        drop(mode);
        // Reproduce the post-rename, pre-final-marker-removal cut only after
        // closing every local owner. The external owner is retained unchanged.
        let winning_file = if original_wins {
            "proposal.v1.json"
        } else {
            "intent-reconciliation-proposal.v1.json"
        };
        let bytes = std::fs::read(f.directory.join(winning_file))?;
        std::fs::rename(
            f.directory.join(winning_file),
            f.directory.join("journal.v1.json"),
        )?;
        std::fs::File::open(&f.directory)?.sync_all()?;
        for name in [
            "proposal.v1.json",
            "intent-reconciliation-proposal.v1.json",
            "attempt.v1.json",
        ] {
            let path = f.directory.join(name);
            if path.exists() {
                std::fs::remove_file(path)?;
            }
        }
        std::fs::File::open(&f.directory)?.sync_all()?;
        assert!(matches!(
            f.ordinary(),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        let recovered =
            FleetRegistry::recover_completed_release_update(f.root.clone(), f.publisher.config())?;
        assert_eq!(
            recovered.release_intent_anchor(&f.agent)?,
            Some(if original_wins {
                f.pending.clone()
            } else {
                unknown
            })
        );
        assert_eq!(std::fs::read(f.directory.join("journal.v1.json"))?, bytes);
        assert_eq!(
            (f.publisher.frontier()?, f.publisher.cas_attempts()),
            (future, attempts)
        );
    }
    Ok(())
}

#[test]
fn closed_predecessor_remains_protected_when_the_next_grants_prepare_cas_never_commits()
-> QualificationResult<()> {
    let (f, release, policy) = setup()?;
    let first = prepared(&f, policy, 26, 1);
    let queued = queue(&f, &release, policy, &first)?;
    let mut terminal = advance(&queued, Phase::Committed);
    terminal.terminal_witness = Some(witness(WitnessKind::CompletedReleaseCas, None));
    f.registry.record_intent_history(&queued, &terminal)?;
    let binding = f.registry.resolve_release_binding(&f.agent, &release)?;
    let next = prepared(&f, policy, 27, terminal.generation + 1);
    f.publisher.drop_next_cas_without_commit();
    assert!(
        f.registry
            .admit_protocol_configuration(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .anchor_intent(Some(&terminal), &next)
            .is_err()
    );
    let f = ColdPending::capture(f, release, policy, next, binding)?;
    let mode = f.mode()?;
    let guard = mode
        .admit_pending_intent_reconciliation(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(guard.expected_intent_anchor(), Some(&terminal));
    assert_eq!(guard.previous_closed_intent_anchor(), Some(&terminal));
    assert_eq!(guard.release_binding(&f.agent, &f.release)?, f.binding);
    let unknown = f.unknown(None);
    guard.reconcile_abandon_unknown(&unknown, [91; 32], None, terminal.sha256()?)?;
    drop(mode);
    let ordinary = f.ordinary()?;
    let policy_guard = ordinary
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    assert_eq!(policy_guard.intent_anchor(&f.agent)?, Some(unknown));
    assert_eq!(
        policy_guard.previous_closed_intent_anchor(&f.agent)?,
        Some(terminal)
    );
    Ok(())
}

#[test]
fn first_unknown_publication_failure_requires_fresh_confirmation_and_preserves_legacy_identity()
-> QualificationResult<()> {
    for legacy in [true, false] {
        let (f, release, policy) = setup()?;
        let binding = f.registry.resolve_release_binding(&f.agent, &release)?;
        let mut unknown = prepared(&f, policy, 28, 1);
        unknown.phase = Phase::Aborted;
        if legacy {
            unknown.original_grant_policy_sha256 = None;
        }
        unknown.terminal_witness = Some(witness(WitnessKind::AbandonUnknown, Some([97; 32])));
        f.publisher.drop_next_cas_without_commit();
        assert!(
            f.registry
                .admit_protocol_configuration(policy)?
                .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
                .recover_intent(None, &unknown, [97; 32])
                .is_err()
        );
        let f = ColdPending::capture(f, release, policy, unknown, binding)?;
        let mode = f.mode()?;
        let original = f.pending_bytes()?;
        assert!(
            mode.admit_pending_intent_reconciliation(policy)?
                .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
                .reconcile_abandon_unknown(
                    &f.pending,
                    [97; 32],
                    None,
                    Anchor::absent_sha256(&f.agent)
                )
                .is_err()
        );
        assert_eq!(f.pending_bytes()?, original);
        let mut confirmed = f.pending.clone();
        confirmed
            .terminal_witness
            .as_mut()
            .ok_or("unknown witness missing")?
            .publication_confirmation_sha256 = Some([98; 32]);
        mode.admit_pending_intent_reconciliation(policy)?
            .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?
            .reconcile_abandon_unknown(
                &confirmed,
                [97; 32],
                Some([98; 32]),
                Anchor::absent_sha256(&f.agent),
            )?;
        drop(mode);
        let actual = f
            .ordinary()?
            .release_intent_anchor(&f.agent)?
            .ok_or("confirmed anchor missing")?;
        assert_eq!(actual, confirmed);
        assert_eq!(actual.intent_sha256, f.pending.intent_sha256);
        assert_eq!(
            actual.original_grant_policy_sha256,
            if legacy { None } else { Some(policy) }
        );
    }
    Ok(())
}

//! Native lineage/prefix projections supply no current authority or signatures.
use super::*;
use pretty_assertions::assert_eq;

fn scope() -> HostResult<DatasetWithdrawalRegistry> {
    Ok(DatasetWithdrawalRegistry::new_scoped(
        DatasetWithdrawalScopeV1 {
            authority_domain_id: id("authority")?,
            registry_id: id("registry")?,
            scope_id: id("scope")?,
        },
    ))
}
fn notice(name: &str) -> super::super::Notice {
    let pin = Digest32::of_bytes(name.as_bytes()).to_string();
    super::super::Notice {
        notice_id: name.into(),
        dataset_digest: pin.clone(),
        source_tombstone_digest: pin.clone(),
        authority_id: "authority".into(),
        credential_chain_digest: pin.clone(),
        signing_key_digest: pin,
        authority_epoch: 1,
        issued_at: 1,
    }
}
#[test]
fn later_current_prefix_keeps_original_notice_and_rejects_forks_and_repeats() -> HostResult<()> {
    let first = notice("first");
    let second = notice("second");
    let mut historical = scope()?;
    historical.append(first.native()?)?;
    let notices = vec![first, second];
    let current = current_prefix(scope()?, historical.clone(), Some(&notices))?;
    assert_eq!(
        current.snapshot().records()[..1],
        historical.snapshot().records()[..]
    );
    assert!(current_prefix(scope()?, historical.clone(), Some(&vec![notice("second")])).is_err());
    assert!(
        current_prefix(
            scope()?,
            historical.clone(),
            Some(&vec![notice("first"), notice("first")])
        )
        .is_err()
    );
    assert_eq!(
        current_prefix(scope()?, historical.clone(), /*notices*/ None)?.snapshot(),
        historical.snapshot()
    );
    Ok(())
}
#[test]
fn actual_affected_lineage_includes_shared_parent_but_excludes_unrelated_prefix() -> HostResult<()>
{
    let mut registry = ArtifactRegistry::new();
    for (name, parent, generation) in [
        ("shared", None, 1),
        ("left", Some("shared"), 2),
        ("right", Some("shared"), 2),
        ("independent", None, 1),
    ] {
        registry.append(ArtifactEvent::Register {
            event_id: id(&format!("register-{name}"))?,
            manifest: ArtifactManifest {
                artifact_id: id(name)?,
                kind: ArtifactKind::Model,
                generation: codex_hepta_types::Generation::new(generation)?,
                predecessor_id: parent.map(id).transpose()?,
                content_digest: Digest32::of_bytes(name.as_bytes()),
                objective_digest: Digest32::of_bytes(b"objective"),
                support_digest: Digest32::of_bytes(name.as_bytes()),
                producer_id: id("producer")?,
                compatibility_digest: Digest32::of_bytes(b"compatible"),
                encoded_size_bytes: 1,
            },
        })?;
    }
    let left = id("left")?;
    let right = id("right")?;
    let independent = id("independent")?;
    let left_events = artifact_events(&registry, [&left].into_iter())?;
    let right_events = artifact_events(&registry, [&right].into_iter())?;
    let independent_events = artifact_events(&registry, [&independent].into_iter())?;
    assert_eq!(
        left_events
            .intersection(&right_events)
            .copied()
            .collect::<BTreeSet<_>>(),
        BTreeSet::from([registry.records()[0].event_digest])
    );
    assert!(left_events.is_disjoint(&independent_events));
    assert!(artifact_events(&registry, [&id("missing")?].into_iter()).is_err());
    Ok(())
}

#[test]
fn corrected_outcomes_share_original_decision_and_support_without_joining_other_episodes()
-> HostResult<()> {
    use codex_hepta_agent_components::learning_ledger as ledger;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;
    let mut native = ledger::LearningLedger::new();
    for episode in ["left", "right"] {
        let pin = Digest32::of_bytes(episode.as_bytes());
        native.append(ledger::LedgerEvent::AuthenticatedDecisionV2(
            ledger::AuthenticatedDecisionRecordV2 {
                record_id: id(&format!("decision-{episode}"))?,
                episode_id: id(episode)?,
                run_snapshot_digest: pin,
                objective_digest: pin,
                policy_digest: pin,
                generator_id: id("generator")?,
                generator_controller_id: id("generator-controller")?,
                generator_credential_chain_digest: Digest32::of_bytes(b"generator-credential"),
                generator_signing_key_digest: Digest32::of_bytes(b"generator-key"),
                generator_scope_digest: Digest32::of_bytes(b"scope"),
                generator_authority_epoch: 1,
                candidate_ids: vec![id("action")?, id("abstain")?],
                selected_candidate_id: id("action")?,
                selected_propensity: ProbabilityQ32::ONE,
                candidate_completeness_digest: pin,
                support_digest: pin,
                authentication_digest: pin,
            },
        ))?;
        for version in 0..if episode == "left" { 2 } else { 1 } {
            native.append(ledger::LedgerEvent::AuthenticatedOutcomeV2(
                ledger::AuthenticatedOutcomeRecordV2 {
                    record_id: id(&format!("record-{episode}-{version}"))?,
                    outcome_id: id(&format!("outcome-{episode}-{version}"))?,
                    episode_id: id(episode)?,
                    observer_id: id("observer")?,
                    observer_controller_id: id("observer-controller")?,
                    observer_credential_chain_digest: Digest32::of_bytes(b"observer-credential"),
                    observer_signing_key_digest: Digest32::of_bytes(b"observer-key"),
                    observer_scope_digest: Digest32::of_bytes(b"scope"),
                    observer_authority_epoch: 1,
                    observed_at: Some(1),
                    value: Some(FixedQ32::ONE),
                    unit_profile_digest: pin,
                    support_digest: Digest32::of_bytes(
                        format!("support-{episode}-{version}").as_bytes(),
                    ),
                    latest_observable_at: 2,
                    expected_delay_profile_digest: pin,
                    terminality: ledger::AuthenticatedOutcomeTerminality::Terminal,
                    censoring_reason: None,
                    correction_predecessor: if version == 0 {
                        None
                    } else {
                        Some(id("outcome-left-0")?)
                    },
                    finalized_at: Some(3),
                    authentication_digest: pin,
                },
            ))?;
        }
    }
    let snapshot = native.snapshot();
    let (first, first_support) = source_events(&snapshot, &id("record-left-0")?)?;
    let (corrected, corrected_support) = source_events(&snapshot, &id("record-left-1")?)?;
    let (other, other_support) = source_events(&snapshot, &id("record-right-0")?)?;
    assert!(first.is_subset(&corrected));
    assert!(first_support.is_subset(&corrected_support));
    assert_eq!(
        corrected,
        snapshot.records()[..3]
            .iter()
            .map(|record| record.event_digest)
            .collect()
    );
    assert!(corrected.is_disjoint(&other));
    assert!(corrected_support.is_disjoint(&other_support));
    assert!(source_events(&snapshot, &id("absent")?).is_err());
    Ok(())
}

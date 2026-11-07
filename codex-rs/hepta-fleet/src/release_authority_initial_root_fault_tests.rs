use super::*;
use pretty_assertions::assert_eq;

#[test]
fn initial_root_warm_owner_rejects_local_journal_and_signed_frontier_drift()
-> QualificationResult<()> {
    let (f, id, _) = setup()?;
    let expected = observe(&f, &f.registry, &id)?;
    let bytes = std::fs::read(f.journal())?;
    let original = f.publisher.frontier()?.ok_or("missing frontier")?;
    let attempts = f.publisher.cas_attempts();
    let mut changed = bytes.clone();
    changed.push(b' ');
    write_synced(&f.journal(), &changed)?;
    assert!(matches!(
        f.registry.admit_release(&f.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    write_synced(&f.journal(), &bytes)?;
    for field in 0..3 {
        let mut drifted = original;
        match field {
            0 => drifted.generation += 1,
            1 => drifted.initial_root_sha256[0] ^= 1,
            _ => drifted.checkpoint_sha256[0] ^= 1,
        }
        write_synced(
            &f.publisher.trust.frontier_path,
            &serde_json::to_vec(&drifted)?,
        )?;
        assert!(matches!(
            f.registry.admit_release(&f.agent, &id),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
        write_synced(
            &f.publisher.trust.frontier_path,
            &serde_json::to_vec(&original)?,
        )?;
        assert_eq!(observe(&f, &f.registry, &id)?, expected);
    }
    assert_eq!(f.publisher.cas_attempts(), attempts);
    assert_eq!(std::fs::read(f.journal())?, bytes);
    assert!(!f.journal().with_file_name("attempt.v1.json").exists());
    assert!(!f.journal().with_file_name("proposal.v1.json").exists());
    Ok(())
}

#[test]
fn initial_root_warm_replay_checks_original_time_root_and_each_real_signature()
-> QualificationResult<()> {
    let (f, id, _) = setup()?;
    let expected = observe(&f, &f.registry, &id)?;
    let original_bytes = std::fs::read(f.journal())?;
    let original: Journal = serde_json::from_slice(&original_bytes)?;
    let frontier = f.publisher.frontier()?.ok_or("missing frontier")?;
    let attempts = f.publisher.cas_attempts();
    let same_owner = owner(&f.registry)?;
    let material = same_owner
        .initial_root_material
        .keys
        .get()
        .ok_or("unprepared root")?;
    for fault in 0..4 {
        let mut changed = original.clone();
        let expected_error = match fault {
            0 => {
                changed.initial_root.expires_at -= 1;
                "PQ release authority: M15 recovery root rejected:"
            }
            1 => {
                changed.initialized_at -= 1;
                "PQ release authority: M15 retained bundle rejected:"
            }
            _ => {
                let signatures = changed
                    .entries
                    .iter_mut()
                    .find_map(|entry| match entry {
                        JournalEntry::Authority {
                            event: AuthorityEventRecord::ProtocolConfiguration { signatures, .. },
                        } => Some(signatures),
                        _ => None,
                    })
                    .ok_or("missing actual signed protocol publication")?;
                if fault == 2 {
                    signatures.pop().ok_or("missing second signer")?;
                    assert_eq!(signatures.len(), 1);
                } else {
                    signatures[0].signature[22] ^= 1;
                }
                "PQ release authority: M15 recovery publication rejected:"
            }
        };
        let changed_bytes = serde_json::to_vec(&changed)?;
        let mut observed = frontier;
        observed.state_sha256 = Sha256::digest(&changed_bytes).into();
        // The independent fixture really signs this new state hash. The old
        // M15 signatures/checkpoint remain, so full replay must still reject it.
        write_synced(&f.journal(), &changed_bytes)?;
        write_synced(
            &f.publisher.trust.frontier_path,
            &serde_json::to_vec(&observed)?,
        )?;
        assert!(matches!(f.registry.admit_release(&f.agent, &id),
            Err(FleetRegistryError::Invalid(message)) if message.starts_with(expected_error)));
        assert!(std::ptr::eq(
            material,
            same_owner
                .initial_root_material
                .keys
                .get()
                .ok_or("lost root")?
        ));
        write_synced(&f.journal(), &original_bytes)?;
        write_synced(
            &f.publisher.trust.frontier_path,
            &serde_json::to_vec(&frontier)?,
        )?;
        assert_eq!(observe(&f, &f.registry, &id)?, expected);
    }
    assert_eq!(f.publisher.cas_attempts(), attempts);
    assert!(!f.journal().with_file_name("attempt.v1.json").exists());
    assert!(!f.journal().with_file_name("proposal.v1.json").exists());
    Ok(())
}

#[test]
fn initial_root_warm_material_never_extends_current_roles_window_or_clock()
-> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let initial = prepared(&f, policy, 103, 1);
    let queued = queue(&f, &id, policy, &initial)?;
    let guard = f
        .registry
        .admit_release(&f.agent, &id)?
        .with_verified_decision_window(NOW * 1000, (NOW + 1) * 1000)?;
    let bytes = std::fs::read(f.journal())?;
    let frontier = f.publisher.frontier()?;
    let attempts = f.publisher.cas_attempts();
    f.publisher.advance_clock_to(NOW + 1);
    assert!(
        matches!(guard.revalidate(), Err(FleetRegistryError::Invalid(message))
        if message == "PQ release authority: verified decision is outside its exact validity window")
    );
    drop(guard);
    f.publisher.advance_clock_to(NOW + 60);
    assert!(matches!(f.registry.admit_protocol_configuration(policy),
        Err(FleetRegistryError::Invalid(message))
            if message.starts_with("PQ release authority: M15 current protocol configuration rejected:")
                && message.ends_with("Expired")));
    drop(f.registry.admit_release(&f.agent, &id)?);
    assert_eq!(
        f.registry.release_intent_anchor(&f.agent)?,
        Some(queued.clone())
    );
    f.publisher.advance_clock_to(NOW + 3600);
    assert!(matches!(f.registry.admit_release(&f.agent, &id),
        Err(FleetRegistryError::Invalid(message))
            if message.starts_with("PQ release authority: M15 current publication rejected:")
                && message.ends_with("Expired")));
    assert_eq!(f.registry.release_intent_anchor(&f.agent)?, Some(queued));
    f.publisher.advance_clock_to(NOW + 3599);
    assert!(matches!(f.registry.admit_release(&f.agent, &id),
        Err(FleetRegistryError::Invalid(message))
            if message.starts_with("PQ release authority: release clock unavailable:")));
    assert_eq!(f.publisher.frontier()?, frontier);
    assert_eq!(std::fs::read(f.journal())?, bytes);
    assert_eq!(f.publisher.cas_attempts(), attempts);
    Ok(())
}

#[test]
fn initial_root_warm_material_cannot_unfence_a_real_unknown_cas() -> QualificationResult<()> {
    let (f, id, policy) = setup()?;
    let same_owner = owner(&f.registry)?;
    let material = same_owner
        .initial_root_material
        .keys
        .get()
        .ok_or("unprepared root")?;
    let bytes = std::fs::read(f.journal())?;
    let frontier = f.publisher.frontier()?;
    let attempts = f.publisher.cas_attempts();
    let next = prepared(&f, policy, 104, 1);
    let guard = f
        .registry
        .admit_protocol_configuration(policy)?
        .with_verified_decision_window(NOW * 1000, (NOW + 60) * 1000)?;
    f.publisher.drop_next_cas_without_commit();
    assert!(matches!(
        guard.anchor_intent(None, &next),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(same_owner.fenced.load(std::sync::atomic::Ordering::Acquire));
    let attempt = f.journal().with_file_name("attempt.v1.json");
    let proposal = f.journal().with_file_name("proposal.v1.json");
    let retained = (std::fs::read(&attempt)?, std::fs::read(&proposal)?);
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    assert_eq!(f.publisher.frontier()?, frontier);
    assert_eq!(std::fs::read(f.journal())?, bytes);
    assert!(matches!(
        f.registry.admit_release(&f.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(matches!(
        FleetRegistry::open_existing_with_release_authority(f.root.clone(), f.publisher.config()),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(matches!(
        FleetRegistry::recover_completed_release_update(f.root.clone(), f.publisher.config()),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert_eq!(
        (std::fs::read(&attempt)?, std::fs::read(&proposal)?),
        retained
    );
    assert!(std::ptr::eq(
        material,
        same_owner
            .initial_root_material
            .keys
            .get()
            .ok_or("lost root")?
    ));
    assert_eq!(f.publisher.cas_attempts(), attempts + 1);
    assert_eq!(f.publisher.frontier()?, frontier);
    assert_eq!(std::fs::read(f.journal())?, bytes);
    Ok(())
}

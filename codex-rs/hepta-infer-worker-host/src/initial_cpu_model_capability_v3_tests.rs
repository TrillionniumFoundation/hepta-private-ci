use super::*;

fn identity(generation: u64, body: &[u8]) -> WireIdentity {
    WireIdentity {
        generation,
        configuration_digest: Digest32::of_bytes(b"exact original runtime").to_string(),
        body_digest: Digest32::of_bytes(body).to_string(),
        subject: "original-agent".into(),
    }
}
fn entry(identity: WireIdentity) -> Registration {
    Registration {
        identity,
        installation: Source {
            path: "/etc/original/complete-installed-source.json".into(),
            digest: Digest32::of_bytes(b"full installed source").to_string(),
        },
        operational_reader: "original-installed-model-use.v2".into(),
        registered_model_use: None,
        tick_provider: None,
        weights: None,
        compiled_body: None,
        original_profile: None,
    }
}

#[test]
fn new_goal_cannot_use_old_header_and_recovery_cannot_infer_unregistered_material() -> HostResult<()>
{
    let original = identity(1, b"original body");
    let successor = identity(2, b"successor body");
    let registry = Registry {
        schema: "hepta.cpu-neuron.registered-model-head.v3".into(),
        current: successor.clone(),
        registrations: vec![entry(original.clone()), entry(successor.clone())],
    };
    assert!(
        registry
            .registration(
                &original.typed()?,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal
            )
            .is_err()
    );
    // This is only an index lookup; original stores, S/E and CURRENT checks
    // remain required before ProtectedReader can return any capability.
    registry.registration(
        &original.typed()?,
        CpuNeuronModelUsePurposeV3::HistoricalRecovery,
    )?;
    assert!(
        registry
            .registration(
                &identity(1, b"unregistered historical body").typed()?,
                CpuNeuronModelUsePurposeV3::HistoricalRecovery
            )
            .is_err()
    );
    assert!(
        registry
            .registration(
                &successor.typed()?,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal
            )
            .is_err()
    );
    Ok(())
}

#[test]
fn root_registry_cannot_turn_a_stage_signature_or_duplicate_identity_into_operational_use()
-> HostResult<()> {
    let original = identity(1, b"original body");
    let mut registry = Registry {
        schema: "hepta.cpu-neuron.registered-model-head.v3".into(),
        current: original.clone(),
        registrations: vec![entry(original.clone())],
    };
    registry.registrations[0].operational_reader = "self-iteration-stage-selection.v1".into();
    assert!(
        registry
            .registration(
                &original.typed()?,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal
            )
            .is_err()
    );
    registry.registrations[0] = entry(original.clone());
    registry.registrations.push(entry(original.clone()));
    assert!(
        registry
            .registration(
                &original.typed()?,
                CpuNeuronModelUsePurposeV3::HistoricalRecovery
            )
            .is_err()
    );
    registry.registrations.pop();
    registry.registrations[0].identity.subject = "another-agent".into();
    assert!(
        registry
            .registration(
                &original.typed()?,
                CpuNeuronModelUsePurposeV3::HistoricalRecovery
            )
            .is_err()
    );
    Ok(())
}

#[test]
fn installed_material_source_still_requires_actual_root_custody() -> HostResult<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("claimed-root-source.json");
    let bytes = b"exact matching public descriptor bytes";
    std::fs::write(&path, bytes)?;
    let source = Source {
        path,
        digest: Digest32::of_bytes(bytes).to_string(),
    };
    assert!(source.read(32 * 1024).is_err());
    assert_eq!(std::fs::read(&source.path)?, bytes);
    Ok(())
}

#[test]
fn successor_index_requires_the_distinct_whole_material_purpose_before_original_admission()
-> HostResult<()> {
    let successor = identity(2, b"successor full body");
    let source = || Source {
        path: "/etc/original/complete-source".into(),
        digest: Digest32::of_bytes(b"original complete source").to_string(),
    };
    let mut registered = entry(successor.clone());
    registered.operational_reader = "original-registered-model-use.v3".into();
    registered.registered_model_use = Some(RegisteredSources {
        configuration: source(),
        selection: source(),
    });
    registered.tick_provider = Some(source());
    registered.weights = Some(source());
    registered.compiled_body = Some(source());
    registered.original_profile = Some(source());
    let mut registry = Registry {
        schema: "hepta.cpu-neuron.registered-model-head.v3".into(),
        current: successor.clone(),
        registrations: vec![registered],
    };
    // An index match grants no capability. ProtectedReader must still verify
    // actual sources, E/S/CURRENT and the same original physical composition.
    registry.registration(
        &successor.typed()?,
        CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
    )?;
    registry.registrations[0].compiled_body = None;
    assert!(
        registry
            .registration(
                &successor.typed()?,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal
            )
            .is_err()
    );
    Ok(())
}

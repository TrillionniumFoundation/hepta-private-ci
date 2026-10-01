use super::*;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use serde_json::json;

fn profile() -> HostResult<Profile> {
    Ok(serde_json::from_value(json!({
        "schema":"hepta.cpu-neuron.fixed-initial-product-profile.v1",
        "generation":1,"predecessor":null,"frozen_at_ms":100,"expires_at_ms":400,
        "program":{"path":"/original-program","digest":Digest32::of_bytes(b"program").to_string()},
        "model":{"path":"/original-model","digest":Digest32::of_bytes(b"model").to_string()},
        "weights":{"path":"/original-weights","digest":Digest32::of_bytes(b"weights").to_string()},
        "training_code":{"path":"/original-code","digest":Digest32::of_bytes(b"code").to_string()},
        "owner_root":"/artifacts","original_owner_state":"/original-private-root-state",
        "registry_id":"same-registry","withdrawal_authority":"same-authority",
        "withdrawal_registry":"same-withdrawals","withdrawal_scope":"same-scope",
        "owner":{"id":"same-owner","uid":0,"gid":0,
            "public_key_hex":state::hex(SigningKey::from_bytes(&[31;32]).verifying_key().as_bytes()),
            "credential_digest":Digest32::of_bytes(b"owner-credential").to_string(),"private_key_path":"/private-owner-key"},
        "selector":{"id":"same-selector","uid":985,"gid":974,
            "public_key_hex":state::hex(SigningKey::from_bytes(&[32;32]).verifying_key().as_bytes()),
            "credential_digest":Digest32::of_bytes(b"selector-credential").to_string(),"private_key_path":"/private-selector-key"},
        "artifact_ids":["old-model","old-calibration","old-ood"],"config_id":"same-native-config",
        "normalization_digest":Digest32::of_bytes(b"original-normalization").to_string(),
        "native":{"top_k":1,"temporal_decay_q24":0,"inhibition_gain_q24":0,
            "activity_decay_q24":0,"target_activity_q24":0,"threshold_rate_q24":0,
            "threshold_min_q24":0,"threshold_max_q24":16777216,"eligibility_decay_q24":0},
        "calibration":{"valid_from_sequence":0,"expires_after_sequence":9999,
            "zero_confidence_error_q24":0,"maximum_in_domain_error_q24":16777216,
            "minimum_confidence_ppm":900000,"maximum_ood_ppm":500000,"minimum_active_ppm":0,
            "maximum_active_ppm":1000000,"maximum_projection_count":10,
            "maximum_ece_ppm":1000000,"maximum_false_acceptance_ppm":0},
        "resources":{"p95_latency_micros":100,"p99_latency_micros":200,"transient_allocation_bytes":16384,
            "checkpoint_bytes":65536,"write_amplification_ppm":1000000}
    }))?)
}

#[test]
fn frozen_profile_rejects_invalid_runtime_resources_before_files_or_roles() -> HostResult<()> {
    let mut value = profile()?;
    value.resources.write_amplification_ppm = 10_000_000;
    let error = value
        .validate(/*now*/ 200)
        .err()
        .ok_or("invalid envelope accepted")?;
    assert!(matches!(
        error.downcast_ref::<codex_hepta_neuron::NeuronRuntimeError>(),
        Some(codex_hepta_neuron::NeuronRuntimeError::InvalidConfig)
    ));
    value.resources.write_amplification_ppm = 4_000_000;
    // The fixture deliberately has no Root source files. A valid envelope must
    // proceed to actual custody checks instead of passing the entire profile.
    let error = value
        .validate(/*now*/ 200)
        .err()
        .ok_or("missing Root custody accepted")?;
    assert!(
        error
            .downcast_ref::<codex_hepta_neuron::NeuronRuntimeError>()
            .is_none()
    );
    Ok(())
}

#[test]
fn first_physical_installation_corrects_only_an_unusable_write_envelope() -> HostResult<()> {
    let mut old = profile()?;
    old.resources.write_amplification_ppm = 10_000_000;
    let mut corrected = profile()?;
    corrected.resources.write_amplification_ppm = 4_000_000;
    corrected.first_physical_installation = Some(Source {
        path: "/root-first-installation-statement".into(),
        digest: Digest32::of_bytes(b"separate Root declaration").to_string(),
    });
    validate_first_installation_profile(&old, &corrected)?;
    assert!(validate_unchanged_profile(&old, &corrected).is_err());
    for change in 0..6 {
        let mut value: Profile = serde_json::from_value(serde_json::to_value(&corrected)?)?;
        match change {
            0 => value.weights.digest = Digest32::of_bytes(b"other weights").to_string(),
            1 => value.normalization_digest = Digest32::of_bytes(b"other transform").to_string(),
            2 => value.selector.uid += 1,
            3 => value.calibration.maximum_ood_ppm += 1,
            4 => value.resources.p99_latency_micros += 1,
            5 => value.resources.write_amplification_ppm = 5_000_000,
            _ => unreachable!(),
        }
        assert!(validate_first_installation_profile(&old, &value).is_err());
    }
    old.resources.write_amplification_ppm = 4_000_000;
    assert!(validate_first_installation_profile(&old, &corrected).is_err());
    Ok(())
}

#[test]
fn fresh_operational_scope_cannot_change_model_normalization_roles_or_gates() -> HostResult<()> {
    let original = profile()?;
    let mut fresh = profile()?;
    fresh.frozen_at_ms = 500;
    fresh.expires_at_ms = 800;
    fresh.original_owner_state = "/new-private-state".into();
    fresh.program.path = "/new-fixed-purpose-program".into();
    fresh.program.digest = Digest32::of_bytes(b"new program").to_string();
    fresh.artifact_ids = [
        "fresh-model".into(),
        "fresh-calibration".into(),
        "fresh-ood".into(),
    ];
    validate_unchanged_profile(&original, &fresh)?;
    for change in [
        "model",
        "normalization",
        "owner",
        "selector",
        "gate",
        "native",
        "store",
    ] {
        let mut changed: Profile = serde_json::from_value(serde_json::to_value(&fresh)?)?;
        match change {
            "model" => changed.weights.digest = Digest32::of_bytes(b"other weights").to_string(),
            "normalization" => {
                changed.normalization_digest =
                    Digest32::of_bytes(b"other normalization").to_string()
            }
            "owner" => changed.owner.uid = 1000,
            "selector" => changed.selector.public_key_hex = original.owner.public_key_hex.clone(),
            "gate" => changed.calibration.maximum_false_acceptance_ppm = 1,
            "native" => changed.native.top_k = 2,
            "store" => changed.owner_root = "/another-store".into(),
            _ => unreachable!(),
        }
        assert!(
            validate_unchanged_profile(&original, &changed).is_err(),
            "{change}"
        );
    }
    Ok(())
}

#[test]
fn expired_original_floor_retains_its_exact_signature_and_context_only() -> HostResult<()> {
    let original = profile()?;
    let source = Source {
        path: "/original-frozen-profile".into(),
        digest: Digest32::of_bytes(b"original profile").to_string(),
    };
    let binding = Digest32::of_bytes(b"original storage binding");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: original.withdrawals()?.scope_digest().ok_or("scope")?,
        binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: id(&original.registry_id)?,
            generation: Generation::new(3)?,
            head_digest: Digest32::of_bytes(b"original acknowledged head"),
            predecessor_head_digest: Digest32::of_bytes(b"original predecessor"),
            authority_epoch: 1,
            signer_id: id(&original.owner.id)?,
            signing_key_digest: Digest32::of_bytes(&public(&original.owner.public_key_hex)?),
            issued_at: 200,
            expires_at: 300,
        },
        signature: [0; 64],
    };
    signed.signature = SigningKey::from_bytes(&[31; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    let record = json!({
        "time":{"profile_digest":source.digest,"evidence_digest":Digest32::of_bytes(b"old E").to_string(),
            "issued_at":200,"expires_at":300,"signature_hex":state::hex(&signed.signature)},
        "generation":3,"predecessor":signed.witness.predecessor_head_digest.to_string(),
        "head":signed.witness.head_digest.to_string()
    });
    let head: state::OriginalHead = serde_json::from_value(record.clone())?;
    assert_eq!(head.historical(&source, &original, binding)?, signed);
    assert!(original.validate(500).is_err());
    for (field, value) in [
        (
            "profile_digest",
            json!(Digest32::of_bytes(b"wrong original").to_string()),
        ),
        ("issued_at", json!(99)),
        ("expires_at", json!(401)),
        ("signature_hex", json!(state::hex(&[0; 64]))),
    ] {
        let mut changed = record.clone();
        changed["time"][field] = value;
        let head: state::OriginalHead = serde_json::from_value(changed)?;
        assert!(
            head.historical(&source, &original, binding).is_err(),
            "{field}"
        );
    }
    assert!(
        head.historical(&source, &original, Digest32::of_bytes(b"wrong store"))
            .is_err()
    );
    Ok(())
}

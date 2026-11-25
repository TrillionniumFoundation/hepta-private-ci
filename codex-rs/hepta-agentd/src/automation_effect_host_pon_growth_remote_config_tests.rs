#[cfg(unix)]
use super::super::super::AutomationEffectHostFile;
#[cfg(unix)]
use super::super::super::read_host_file;
use super::*;
use ed25519_dalek::Signer;
use serde_json::Value;
use serde_json::json;

fn config_value() -> Value {
    json!({
        "schema_version":5, "provider_kind":PROVIDER_KIND,
        "provider_scope":"pon", "destination_id":"live-growth", "final_use_scope_sha256":"01".repeat(32),
        "chain_binary":"/chain", "chain_binary_sha256":"02".repeat(32),
        "chain_transport_profile":TRANSPORT_PROFILE, "chain_peer":"127.0.0.1:8123",
        "chain_server_public_key_hex":"03".repeat(32), "chain_resource_profile_sha256":"04".repeat(32),
        "chain_client_secret_file":"/operator/secret", "chain_client_secret_sha256":"05".repeat(32),
        "chain_client_public_key_hex":"06".repeat(32), "chain_admission_bits":8, "chain_admission_ttl_ms":2000,
        "chain_growth_namespace":"growth", "chain_network_sha256":"11".repeat(32),
        "chain_parameters_sha256":"22".repeat(32), "chain_genesis_sha256":"33".repeat(32),
        "chain_genesis_time":1, "chain_min_confirmation_depth":1,
        "chain_min_confirmation_work_depth_hex":format!("{}01", "00".repeat(63)), "timeout_ms":30000,
        "contract_id":"live-contract", "contract_sha256":"07".repeat(32), "contract_authority_epoch":1,
        "contract_signature_hex":"08".repeat(64), "contract_verifying_key_hex":"09".repeat(32),
        "final_use_signer_id":"owner", "final_use_verifying_key_hex":"0a".repeat(32),
        "final_use_revocations_file":"/operator/revocations.json",
    })
}

#[test]
fn live_contract_binds_transport_credential_context_deadline_and_final_use_roots() {
    let value = config_value();
    let config: HostFileV5 = serde_json::from_value(value.clone()).expect("v5 config");
    let original = contract_digest(&config).expect("digest");
    for (field, field_value) in value.as_object().unwrap() {
        if field == "schema_version" || field.starts_with("contract_") {
            continue;
        }
        let mut changed = value.clone();
        changed[field] = match field_value {
            Value::String(text) => json!(format!("{text}-changed")),
            Value::Number(number) => json!(number.as_u64().unwrap() + 1),
            _ => panic!("unexpected contract field {field}"),
        };
        let config: HostFileV5 = serde_json::from_value(changed).expect("changed config");
        assert_ne!(
            contract_digest(&config).expect("changed digest"),
            original,
            "unbound {field}"
        );
    }
    // Controlled test key signs only a provider contract statement. It issues
    // no FinalUse grant, model qualification, or successful production effect.
    let key = ed25519_dalek::SigningKey::from_bytes(&[71; 32]);
    let statement = HttpProviderEffectContractAttestation::statement_for(
        "live-contract",
        &original,
        /*authority_epoch*/ 1,
    );
    let signature = key.sign(&statement).to_bytes();
    assert!(
        HttpProviderEffectContractAttestation::verify_signed(
            "live-contract",
            original.clone(),
            /*authority_epoch*/ 1,
            &signature,
            &key.verifying_key().to_bytes(),
        )
        .is_ok()
    );
    assert!(
        HttpProviderEffectContractAttestation::verify_signed(
            "different-contract",
            original.clone(),
            /*authority_epoch*/ 1,
            &signature,
            &key.verifying_key().to_bytes(),
        )
        .is_err()
    );
    assert!(
        HttpProviderEffectContractAttestation::verify_signed(
            "live-contract",
            original,
            /*authority_epoch*/ 2,
            &signature,
            &key.verifying_key().to_bytes(),
        )
        .is_err()
    );
}

#[cfg(unix)]
#[test]
fn live_host_parser_is_explicit_and_never_reinterprets_v4_local_fields() -> anyhow::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir()?;
    let path = directory.path().canonicalize()?.join("provider.json");
    let value = config_value();
    fs::write(&path, serde_json::to_vec(&value)?)?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    assert!(matches!(
        read_host_file(&path)?,
        AutomationEffectHostFile::PonGrowthRemote(_)
    ));
    for field in [
        "chain_store",
        "chain_state_backend",
        "chain_workers",
        "reliable_submit",
    ] {
        let mut changed = value.clone();
        changed[field] = json!("forbidden");
        assert!(
            serde_json::from_value::<HostFileV5>(changed).is_err(),
            "accepted {field}"
        );
    }
    let mut local = value;
    local["schema_version"] = json!(4);
    fs::write(&path, serde_json::to_vec(&local)?)?;
    assert!(read_host_file(&path).is_err());
    Ok(())
}

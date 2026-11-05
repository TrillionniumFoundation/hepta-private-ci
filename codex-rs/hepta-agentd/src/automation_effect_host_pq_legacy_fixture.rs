//! Complete original classical configurations, used only as downgrade controls.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::Duration;

use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_model_provider::HttpProviderEffectConfig;
use codex_model_provider::HttpProviderEffectContractAttestation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use http::HeaderMap;
use serde_json::Value;

use super::super::super::AutomationEffectHostFileV3;
use super::super::super::pon_contract_digest;
use super::support::write_private;

/// Actual ELF identity, but only a loader fixture. No Chain process is executed.
pub(super) fn pon_provider(root: &Path) -> anyhow::Result<Value> {
    let binary = root.join("pinned-loader-fixture");
    fs::copy(Path::new("/bin/true").canonicalize()?, &binary)?;
    fs::set_permissions(&binary, fs::Permissions::from_mode(0o700))?;
    let bytes = fs::read(&binary)?;
    anyhow::ensure!(bytes.starts_with(b"\x7fELF"), "fixture must be an actual ELF");
    let store = root.join("chain-store");
    fs::create_dir(&store)?;
    fs::set_permissions(&store, fs::Permissions::from_mode(0o700))?;
    write_private(&store.join("native.sqlite"), b"loader-only namespace fixture")?;
    Ok(serde_json::json!({
        "provider_kind": "trillionnium-pon-local-v1", "chain_binary": binary.canonicalize()?,
        "chain_binary_sha256": Sha256Digest::for_bytes(&bytes).as_str(), "chain_store": store.canonicalize()?,
        "chain_state_backend": "authenticated-v1", "chain_genesis_time": 1,
        "chain_evaluation_policy": "eval", "chain_task_profile": "task", "chain_model_profile": "model",
        "chain_workers": 1, "chain_min_confirmation_depth": 6,
        "chain_min_confirmation_work_depth_hex": format!("{}01", "00".repeat(63)), "timeout_ms": 5000,
    }))
}

pub(super) fn configurations(
    root: &Path,
    uri: &str,
    scope: &Sha256Digest,
    head: &FinalUseRevocations,
) -> anyhow::Result<[Value; 2]> {
    let contract_signer = SigningKey::from_bytes(&[83; 32]);
    let issuer = SigningKey::from_bytes(&[84; 32]);
    let revocations = root.join("legacy-revocations.json");
    write_private(&revocations, &serde_json::to_vec(head)?)?;
    let common = serde_json::json!({
        "provider_scope": "provider/fixture-v1", "destination_id": "provider:fixture",
        "final_use_scope_sha256": scope.as_str(), "contract_id": "legacy-valid-contract",
        "contract_sha256": Sha256Digest::for_bytes(b"unsigned").as_str(),
        "contract_authority_epoch": 9, "contract_signature_hex": "",
        "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
        "final_use_signer_id": "legacy-issuer",
        "final_use_verifying_key_hex": hex(&issuer.verifying_key().to_bytes()),
        "final_use_revocations_file": revocations,
    });
    let provider = HttpProviderEffectConfig {
        dispatch_url: format!("{uri}/dispatch"),
        lookup_url_template: format!("{uri}/status/{{key}}"),
        headers: HeaderMap::new(),
        timeout: Duration::from_secs(2),
        contract_id: "legacy-valid-contract".to_string(),
        attestation: None,
    };
    let mut http = common.clone();
    http.as_object_mut().expect("HTTP config").extend(
        serde_json::json!({ "schema_version": 1, "dispatch_url": provider.dispatch_url,
            "lookup_url_template": provider.lookup_url_template, "headers": {}, "timeout_ms": 2000 })
            .as_object().expect("HTTP fields").clone(),
    );
    sign(&mut http, &provider.contract_sha256().map_err(anyhow::Error::msg)?, &contract_signer);
    let mut pon = common;
    pon["schema_version"] = serde_json::json!(3);
    pon.as_object_mut().expect("PoN config").extend(
        pon_provider(root)?.as_object().expect("PoN fields").clone(),
    );
    let parsed: AutomationEffectHostFileV3 = serde_json::from_value(pon.clone())?;
    sign(&mut pon, &pon_contract_digest(&parsed)?, &contract_signer);
    Ok([http, pon])
}

fn sign(config: &mut Value, digest: &Sha256Digest, signer: &SigningKey) {
    config["contract_sha256"] = serde_json::json!(digest.as_str());
    let statement = HttpProviderEffectContractAttestation::statement_for(
        "legacy-valid-contract", digest, /*authority_epoch*/ 9,
    );
    config["contract_signature_hex"] = serde_json::json!(hex(&signer.sign(&statement).to_bytes()));
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

//! Existing deterministic AuthBus text test identity; no persisted private key.
use anyhow::Context;
use anyhow::Result;
use codex_hepta_agentd::AuthBusTextBody;
use codex_hepta_agentd::AuthBusTextIngress;
use codex_hepta_agentd::authbus_text_claims;
use codex_hepta_contracts::AgentId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
const ISSUER_ID: &str = "issuer:native-authbus-test";
pub(crate) const TEXT: &str = "AuthBus native signed text: exactly this body reaches the model.";
pub(crate) fn write_trust(
    path: &Path,
    agent_id: &AgentId,
    key: &SigningKey,
    thread_ids: &[String],
    revoked: bool,
) -> Result<()> {
    let registration = serde_json::json!({
        "schema_version": 1,
        "agent_id": agent_id.to_string(),
        "issuer_id": ISSUER_ID,
        "key_epoch": 1,
        "public_key_hex": hex(key.verifying_key().as_bytes()),
        "revoked": revoked,
        "thread_ids": thread_ids,
    });
    let mut temporary =
        tempfile::NamedTempFile::new_in(path.parent().context("trust parent missing")?)?;
    temporary
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    serde_json::to_writer(temporary.as_file_mut(), &registration)?;
    temporary.as_file().sync_all()?;
    temporary.persist(path)?;
    Ok(())
}

pub(crate) fn write_checkpoint(
    path: &Path,
    agent_id: &AgentId,
    generation: u64,
    digest: codex_hepta_types::Digest32,
) -> Result<()> {
    use std::io::Write;

    let document = serde_json::json!({
        "schema_version": 1,
        "agent_id": agent_id.to_string(),
        "generation": generation,
        "digest": digest.to_string(),
    });
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer(&mut file, &document)?;
    file.flush()?;
    file.sync_all()?;
    Ok(())
}

pub(crate) fn signed_text(
    agent_id: &AgentId,
    key: &SigningKey,
    thread_id: &str,
    sequence: u64,
) -> Result<AuthBusTextIngress> {
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let mut request = AuthBusTextIngress {
        issuer_id: ISSUER_ID.to_string(),
        key_epoch: 1,
        message_id: format!("message:native-authbus:{sequence}"),
        sequence,
        expires_at_ms: now + 300_000,
        signature_hex: String::new(),
        body: AuthBusTextBody {
            spawn_generation: 1,
            thread_id: thread_id.to_string(),
            text: TEXT.to_string(),
        },
    };
    request.signature_hex = hex(&key
        .sign(&authbus_text_claims(agent_id, &request)?.signing_bytes())
        .to_bytes());
    Ok(request)
}

pub(crate) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

//! Compare the durable dispatch to the exact adapted operation and claimed
//! authority without consuming or retaining the final-use token.

use codex_hepta_codex_adapter::APP_SERVER_V2_PROTOCOL_ID;
use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;

use super::Result;

pub(super) fn verify_persisted_dispatch_binding(
    control: &DurableInferenceControl,
    request_id: &str,
    intent: &CodexOperationIntent,
    request_digest: Digest32,
    verified_use: &VerifiedUseToken,
) -> Result<()> {
    let dispatch = control
        .native_record(request_id)
        .and_then(|record| record.dispatch.as_ref())
        .ok_or("runtime.codex dispatch binding was not durably published")?;
    let binding = intent
        .app_server_binding
        .as_ref()
        .ok_or("runtime.codex product binding is required for durable dispatch verification")?;
    let payload_digest = intent.payload_digest.to_string();
    let request_digest = request_digest.to_string();
    let source_admission_digest = binding.source_admission_digest.to_string();
    let codex_home_digest = binding.codex_home_digest.to_string();
    let revocation_head_digest =
        Digest32::from_array(verified_use.claimed_revocation_head_sha256()).to_string();
    let authority_witness = Digest32::from_array(verified_use.witness_sha256()).to_string();
    let exact = dispatch.codex_payload_digest.as_deref() == Some(payload_digest.as_str())
        && dispatch.codex_request_digest.as_deref() == Some(request_digest.as_str())
        && dispatch.codex_source_admission_digest.as_deref()
            == Some(source_admission_digest.as_str())
        && dispatch.codex_home_digest.as_deref() == Some(codex_home_digest.as_str())
        && dispatch.codex_connection_id == Some(binding.connection_id)
        && dispatch.codex_session_id.as_deref() == Some(binding.session_id.as_str())
        && dispatch.codex_deadline_ms == Some(intent.deadline_ms)
        && dispatch.codex_authority_epoch == Some(verified_use.claimed_authority_epoch())
        && dispatch.codex_revocation_revision == Some(verified_use.claimed_revocation_revision())
        && dispatch.codex_revocation_head_sha256.as_deref()
            == Some(revocation_head_digest.as_str())
        && dispatch.codex_authority_witness_sha256.as_deref() == Some(authority_witness.as_str())
        && dispatch.app_server_version.as_deref() == Some(binding.app_server_version.as_str())
        && dispatch.protocol_id.as_deref() == Some(APP_SERVER_V2_PROTOCOL_ID);
    if !exact {
        return Err("durable runtime.codex dispatch binding changed before physical send".into());
    }
    Ok(())
}

//! Pure native input bounds, canonical payload hashing and bounded diagnostics.

use codex_hepta_types::Digest32;
use codex_hepta_types::IdProfileV1;
use codex_hepta_types::StableId;
use sha2::Digest;
use sha2::Sha256;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

// Existing adapter/native dispatch version profile; printable Unicode is valid.
const MAX_APP_SERVER_VERSION_BYTES: usize = 128;
// The existing journal diagnostic budget is at most 4096 UTF-8 bytes.
const MAX_DIAGNOSTIC_CHARS: usize = 1024;

pub(super) fn app_server_version_valid(version: &str) -> bool {
    !version.is_empty()
        && version.len() <= MAX_APP_SERVER_VERSION_BYTES
        && !version.bytes().any(|byte| byte.is_ascii_control())
}

/// Retain the existing diagnostic prefix while formatting, before an oversized
/// service message or Display implementation can allocate an entire copy.
pub(super) fn bounded_diagnostic(arguments: std::fmt::Arguments<'_>) -> String {
    let mut writer = NativeDiagnosticWriter {
        text: String::new(),
        remaining: MAX_DIAGNOSTIC_CHARS,
    };
    // The writer intentionally stops formatting with fmt::Error at its limit.
    let _ = std::fmt::write(&mut writer, arguments);
    writer.text
}

struct NativeDiagnosticWriter {
    text: String,
    remaining: usize,
}

impl std::fmt::Write for NativeDiagnosticWriter {
    fn write_str(&mut self, text: &str) -> std::fmt::Result {
        let end = text
            .char_indices()
            .nth(self.remaining)
            .map_or(text.len(), |(offset, _)| offset);
        let retained = &text[..end];
        self.text.push_str(retained);
        self.remaining -= retained.chars().count();
        if end < text.len() {
            Err(std::fmt::Error)
        } else {
            Ok(())
        }
    }
}

/// Exact Agentd intelligence handoff that must already be attached before a
/// physical App Server turn can start.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeIntelligenceRunBinding {
    pub run_id: String,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

/// Validate borrowed handoff fields before request hashing or owner RPCs.
/// The stable V1 identifier and canonical Digest32 profiles own their bounds.
pub(super) fn validate_intelligence_binding(binding: &NativeIntelligenceRunBinding) -> Result<()> {
    if binding.run_id.is_empty()
        || binding.expected_revision == 0
        || binding.context_digest.is_empty()
        || binding.envelope_digest.is_empty()
    {
        return Err("invalid intelligence execution binding".into());
    }
    StableId::with_profile(&binding.run_id, IdProfileV1::Stable)?;
    let context: Digest32 = binding.context_digest.parse()?;
    let envelope: Digest32 = binding.envelope_digest.parse()?;
    if context.is_zero() || envelope.is_zero() {
        return Err("zero intelligence binding".into());
    }
    Ok(())
}

pub(super) fn native_source_payload_digest(
    prompt: &str,
    context_query: &Option<String>,
    socket: &std::path::Path,
    timeout_ms: u128,
    intelligence: Option<&NativeIntelligenceRunBinding>,
) -> Result<String> {
    if let Some(binding) = intelligence {
        validate_intelligence_binding(binding)?;
    }
    let mut writer = NativePayloadHasher(Sha256::new());
    match intelligence {
        None => serde_json::to_writer(
            &mut writer,
            &(
                "hepta.native-request.v1",
                prompt,
                context_query,
                socket,
                timeout_ms,
            ),
        )?,
        Some(binding) => serde_json::to_writer(
            &mut writer,
            &(
                "hepta.native-intelligence-request.v2",
                prompt,
                context_query,
                socket,
                timeout_ms,
                &binding.run_id,
                binding.expected_revision,
                &binding.context_digest,
                &binding.envelope_digest,
            ),
        )?,
    };
    Ok(format!("{:x}", writer.0.finalize()))
}

/// Preserve the exact JSON digest without copying an entire serialized payload.
/// Operator-selected socket paths have no declared length limit in this API.
struct NativePayloadHasher(Sha256);

impl std::io::Write for NativePayloadHasher {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.update(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "native_input_tests.rs"]
mod tests;

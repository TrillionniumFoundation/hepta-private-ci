//! Explicit owner-context delivery; retrieval and final revalidation stay intact.

use std::collections::HashMap;

use codex_app_server_protocol::AdditionalContextEntry;
use codex_app_server_protocol::AdditionalContextKind;
use codex_hepta_agentd::CognitiveContextSnapshot;
use codex_hepta_agentd::MAX_COGNITIVE_CONTEXT_BYTES;

use super::Result;
use super::control;

/// Whether a successfully retrieved owner snapshot is attached to this turn.
/// This does not control the host's other memory, history or tool paths.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeContextDelivery {
    /// Preserve the original owner-checked attachment and admission identity.
    Attach,
    /// Retrieve and revalidate normally, but send no explicit owner attachment.
    Withhold,
}

pub(super) struct NativeContextRequest {
    pub(super) query: Option<String>,
    pub(super) delivery: NativeContextDelivery,
}

pub(super) struct PreparedContext {
    pub(super) owner_context_digest: Option<String>,
    pub(super) additional_context: Option<HashMap<String, AdditionalContextEntry>>,
}

pub(super) fn prepare_attachment(
    context: Option<&CognitiveContextSnapshot>,
    delivery: NativeContextDelivery,
) -> Result<PreparedContext> {
    let owner_digest = context
        .map(|snapshot| -> Result<_> { Ok(control::digest(&serde_json::to_vec(snapshot)?)) })
        .transpose()?;
    let attachment = context
        .map(|snapshot| -> Result<_> {
            // Both arms perform the same serialization and bound check. The
            // intervention suppresses only delivery, not retrieval or admission.
            let value = serde_json::to_string(snapshot)?;
            if value.len() > MAX_COGNITIVE_CONTEXT_BYTES {
                return Err("verified context exceeds the model attachment byte limit".into());
            }
            Ok(HashMap::from([(
                "hepta-cognitive-owner".to_string(),
                AdditionalContextEntry {
                    value,
                    kind: AdditionalContextKind::Untrusted,
                },
            )]))
        })
        .transpose()?;
    // The journal retains owner_digest even when its actual attachment digest
    // describes None. Retrieval therefore does not claim actor consumption.
    #[cfg(all(test, unix))]
    tests::observe_prepared_context(context, delivery);
    Ok(PreparedContext {
        owner_context_digest: owner_digest,
        additional_context: match delivery {
            NativeContextDelivery::Attach => attachment,
            NativeContextDelivery::Withhold => None,
        },
    })
}

#[cfg(all(test, unix))]
#[path = "native_context_tests.rs"]
mod tests;

//! Historical neural evidence uses non-prompt metadata. Original context bytes,
//! learning-ledger joins, revalidation and FinalUse domains remain unchanged.

use super::*;
use codex_hepta_agentd::AgentdCapabilitySet;
use codex_hepta_agentd::CognitiveContextExecutionV1;

pub(super) const EXECUTION_METADATA_KEY: &str = "hepta_cognitive_execution_v1";

pub(super) fn require_capabilities(capabilities: &AgentdCapabilitySet) -> Result<()> {
    capabilities.validate()?;
    for required in [
        COGNITIVE_CONTEXT_REVALIDATION_CAPABILITY,
        COGNITIVE_CONTEXT_EXECUTION_CAPABILITY_V1,
    ] {
        if !capabilities
            .capabilities
            .iter()
            .any(|capability| capability.id == required && capability.major == 1)
        {
            return Err(format!("owning Agent lacks required capability {required}").into());
        }
    }
    Ok(())
}

pub(super) struct CognitiveAttachmentV1 {
    pub(super) additional_context: HashMap<String, AdditionalContextEntry>,
    pub(super) metadata: HashMap<String, String>,
    pub(super) owner_context_digest: String,
}

pub(super) fn prepare(
    request_id: &str,
    context: &CognitiveContextExecutionV1,
) -> Result<CognitiveAttachmentV1> {
    let snapshot = serde_json::to_string(&context.snapshot)?;
    if snapshot.len() > MAX_COGNITIVE_CONTEXT_BYTES {
        return Err("verified context exceeds the model attachment byte limit".into());
    }
    let binding = serde_json::to_vec(&(
        "hepta.native.cognitive-context-execution.v1",
        request_id,
        context,
    ))?;
    // The AppServer setter only removes reserved keys. This owner constructs
    // exactly one fixed, nonreserved ASCII key and one 64-hex value itself:
    // within 16 entries/64 key bytes/128 value bytes without config validation.
    Ok(CognitiveAttachmentV1 {
        owner_context_digest: control::digest(snapshot.as_bytes()),
        additional_context: HashMap::from([(
            "hepta-cognitive-owner".to_owned(),
            AdditionalContextEntry {
                value: snapshot,
                kind: AdditionalContextKind::Untrusted,
            },
        )]),
        metadata: HashMap::from([(
            EXECUTION_METADATA_KEY.to_owned(),
            Digest32::of_bytes(&binding).to_string(),
        )]),
    })
}

impl CognitiveAttachmentV1 {
    pub(super) fn observe_dispatch(
        &self,
        request_id: &str,
        context: &CognitiveContextExecutionV1,
        payload: Digest32,
        request: Digest32,
    ) {
        // A bounded historical log, not an atomic journal record, durable
        // retention guarantee, provider acceptance, terminal receipt or grant.
        // No query, memory text or instruction enters this audit observation.
        eprintln!(
            "{}",
            serde_json::json!({
                "schema":"hepta-native-cognitive-dispatch-observation-v1",
                "stage":"dispatch-recorded-before-final-revalidation",
                "native_request_id":request_id,
                "execution_digest":self.metadata[EXECUTION_METADATA_KEY],
                "owner_context_digest":self.owner_context_digest,
                "snapshot_digest":context.snapshot.snapshot_digest,
                "read_digest":context.snapshot.read_digest,
                "neural":context.neural,
                "codex_payload_digest":payload.to_string(),
                "codex_request_digest":request.to_string(),
                "execution_authority":false,"atomic_durable_binding":false,
            })
        );
    }
}

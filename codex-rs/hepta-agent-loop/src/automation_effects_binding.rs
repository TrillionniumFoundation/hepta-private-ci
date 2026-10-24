//! Caller-supplied immutable admission for one status-returning effect.

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use std::collections::BTreeSet;

use crate::Error;
use crate::Frame;
use crate::Phase;
use crate::Result;
use crate::ToolCall;
use crate::TurnBinding;
use crate::runner::operation_key;

pub const AUTOMATION_STATUS_TOOL_NAME: &str = "hepta_automation_status_v1";
const MAXIMUM_CALLS: usize = 64;
const MAXIMUM_ARGUMENT_BYTES: usize = 65_536;

/// Integrity mapping for an independently admitted effect run in the same
/// AutomationStore. This computes no authority and creates no run or grant.
/// The original intent/grant must bind this exact run ID before attachment.
pub fn automation_status_effect_run_id(frame: &Frame) -> Result<String> {
    let (_, _, mapping) = selection(frame)?;
    Ok(format!("native-effect:{mapping}"))
}

/// Trusted-host input, deliberately not deserializable from a model tool call.
/// Every value must come from the existing admission/authority/TaskFlow owners.
/// Construction verifies an integrity binding; only the original FinalUse
/// authority can authenticate and consume the supplied signed grant.
pub struct PreboundAutomationStatusEffect {
    pub(super) binding: TurnBinding,
    pub(super) call: ToolCall,
    pub(super) operation_key: Digest32,
    pub(super) mapping_digest: Digest32,
    pub(super) selected_index: usize,
    pub(super) intent: AuthorizedEffectIntent,
    pub(super) intent_digest: Sha256Digest,
    pub(super) payload: Vec<u8>,
    pub(super) fence: TaskFlowFence,
    pub(super) grant: SignedFinalUseGrant,
    pub(super) final_use_binding: FinalUseBinding,
    pub(super) provider_key: ProviderEffectKey,
    pub(super) command_id: String,
}

impl PreboundAutomationStatusEffect {
    /// Freeze the selected call and consume only caller-supplied admission.
    /// The effect run must already be prepared/claimed by its original owner.
    /// It is separate from the native turn run: original effect settlement
    /// terminalizes its enclosing TaskFlow run and must not end the agent turn.
    pub fn new(
        frame: &Frame,
        intent: AuthorizedEffectIntent,
        wire_payload: Vec<u8>,
        fence: TaskFlowFence,
        signed_grant: SignedFinalUseGrant,
        command_id: String,
    ) -> Result<Self> {
        let (selected_index, call, mapping_digest) = selection(frame)?;
        let key = operation_key(frame, call);
        if intent.run_id != format!("native-effect:{mapping_digest}")
            || intent.run_id == frame.binding.run_id.as_str()
            || wire_payload.as_slice() != call.arguments.as_bytes()
            || Sha256Digest::for_bytes(&wire_payload) != intent.payload_digest
            || fence.generation != frame.binding.generation.get()
            || command_id.is_empty()
            || command_id.len() > 256
            || command_id.bytes().any(|byte| byte < 0x20)
        {
            return Err(Error::Contract("pre-admitted automation effect mapping"));
        }
        let intent_digest = intent
            .digest()
            .map_err(|_| Error::Contract("original automation effect intent"))?;
        let final_use_binding = intent
            .final_use_binding()
            .map_err(|_| Error::Contract("original final-use binding"))?;
        if signed_grant.grant.binding != final_use_binding {
            return Err(Error::Contract("original signed grant binding"));
        }
        let provider_key = ProviderEffectKey::for_logical_effect(
            &intent.destination_id,
            &format!("taskflow:{}:{}", intent.run_id, intent.step_id),
        )
        .map_err(|_| Error::Contract("original provider occurrence key"))?;
        Ok(Self {
            binding: frame.binding.clone(),
            call: call.clone(),
            operation_key: key,
            mapping_digest,
            selected_index,
            intent,
            intent_digest,
            payload: wire_payload,
            fence,
            grant: signed_grant,
            final_use_binding,
            provider_key,
            command_id,
        })
    }

    pub fn operation_key(&self) -> Digest32 {
        self.operation_key
    }

    pub(super) fn validate_call(
        &self,
        binding: &TurnBinding,
        key: Digest32,
        call: &ToolCall,
    ) -> Result<()> {
        if *binding != self.binding || key != self.operation_key || *call != self.call {
            return Err(Error::Contract("original native effect identity changed"));
        }
        Ok(())
    }
}

fn selection(frame: &Frame) -> Result<(usize, &ToolCall, Digest32)> {
    let Phase::Tools { calls, next } = &frame.phase else {
        return Err(Error::Contract(
            "automation status requires the current tool frame",
        ));
    };
    let call = calls
        .get(*next)
        .ok_or(Error::Contract("original tool selection"))?;
    if call.name.as_str() != AUTOMATION_STATUS_TOOL_NAME {
        return Err(Error::Contract(
            "output-bearing or unregistered effect tool",
        ));
    }
    if calls.len() > MAXIMUM_CALLS
        || calls
            .iter()
            .any(|call| call.arguments.len() > MAXIMUM_ARGUMENT_BYTES)
    {
        return Err(Error::Limit("pre-admitted automation effect frame"));
    }
    if frame.binding.admission_digest.is_zero() || frame.binding.deadline_unix_ms == 0 {
        return Err(Error::Contract("original native admission"));
    }
    let mut ids = BTreeSet::new();
    let mut bytes = b"hepta.native-agent.automation-status-binding.v1\0".to_vec();
    // The actual runner owns operation identity; do not reproduce its hash.
    bytes.extend_from_slice(operation_key(frame, call).as_array());
    bytes.extend_from_slice(&frame.revision.to_be_bytes());
    bytes.extend_from_slice(&frame.consumed_tokens.to_be_bytes());
    bytes.extend_from_slice(&frame.binding.deadline_unix_ms.to_be_bytes());
    bytes.extend_from_slice(
        &u64::try_from(*next)
            .map_err(|_| Error::Limit("tool selection index"))?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u64::try_from(calls.len())
            .map_err(|_| Error::Limit("tool selection count"))?
            .to_be_bytes(),
    );
    for candidate in calls {
        if !ids.insert(&candidate.call_id) {
            return Err(Error::Contract("duplicate original tool call ID"));
        }
        for part in [
            candidate.call_id.as_str(),
            candidate.name.as_str(),
            candidate.arguments.as_str(),
        ] {
            bytes.extend_from_slice(
                &u64::try_from(part.len())
                    .map_err(|_| Error::Limit("tool selection bytes"))?
                    .to_be_bytes(),
            );
            // Bind all bytes without allocating another copy of every call's
            // potentially large arguments merely to compute this mapping.
            bytes.extend_from_slice(Digest32::of_bytes(part.as_bytes()).as_array());
        }
    }
    Ok((*next, call, Digest32::of_bytes(&bytes)))
}

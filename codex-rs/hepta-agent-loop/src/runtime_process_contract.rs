//! Typed port to an existing process owner. This module launches no process.

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use std::future::Future;

use super::super::binding::PreboundAutomationStatusEffect;
use super::super::binding::effect_run_id;
use crate::Error;
use crate::Frame;
use crate::Result;

pub const RUNTIME_PROCESS_TOOL_NAME: &str = "hepta_runtime_process_v1";
const BINDING_DOMAIN: &[u8] = b"hepta.native-agent.runtime-process-binding.v1\0";
const MAXIMUM_OUTPUT_BYTES: usize = 65_536;

pub fn runtime_process_effect_run_id(frame: &Frame) -> Result<String> {
    effect_run_id(frame, RUNTIME_PROCESS_TOOL_NAME, BINDING_DOMAIN)
}

/// Independent original admission, bound to this exact native tool frame.
/// This constructor creates no run, lease, grant or process authorization.
/// This initial adapter requires the native and effect runs to have the same
/// full original owner fence; it reads both original owners before contact.
pub struct PreboundRuntimeProcessEffect(pub(super) PreboundAutomationStatusEffect);

impl PreboundRuntimeProcessEffect {
    pub fn new(
        frame: &Frame,
        intent: AuthorizedEffectIntent,
        wire_payload: Vec<u8>,
        fence: TaskFlowFence,
        signed_grant: SignedFinalUseGrant,
        command_id: String,
    ) -> Result<Self> {
        PreboundAutomationStatusEffect::new_for_tool(
            frame,
            intent,
            wire_payload,
            fence,
            signed_grant,
            command_id,
            (RUNTIME_PROCESS_TOOL_NAME, BINDING_DOMAIN),
        )
        .map(Self)
    }

    pub fn operation_key(&self) -> Digest32 {
        self.0.operation_key()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeProcessStatus {
    Succeeded,
    Failed,
}

/// Only the registered original owner may construct this terminal evidence.
/// `output` is bounded JSON read from the original job and predeclared artifact
/// resolver. A path string is not evidence of an artifact's bytes or version.
/// The port must verify the request key/payload, terminal witness, log bytes,
/// and artifact version/digests before returning this value, including replay.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeProcessResult {
    pub status: RuntimeProcessStatus,
    pub job_identity_digest: Sha256Digest,
    pub owner_receipt_digest: Sha256Digest,
    pub output: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeProcessObservation {
    /// Missing local keys, accepted submissions, lost replies and unavailable
    /// evidence are unresolved. None of them proves absence or permits retry.
    Unresolved,
    Terminal(RuntimeProcessResult),
}

/// Trusted host port, implemented beside the real runtime, outside this crate.
/// Dispatch is called only through the existing FinalUse and TaskFlow seam.
/// Observe and cancel must locate the original immutable key/request without
/// calling start. Cancellation acknowledgements are not terminal observations.
/// All contact ambiguity returns Unresolved; no post-contact error permits a
/// fresh dispatch. Implementations must impose bounded I/O deadlines.
pub trait RuntimeProcessOwner: Send + Sync {
    fn dispatch(
        &self,
        intent: &ProviderEffectIntent,
        wire_payload: &[u8],
    ) -> impl Future<Output = RuntimeProcessObservation> + Send;
    fn observe(
        &self,
        intent: &ProviderEffectIntent,
        wire_payload: &[u8],
    ) -> impl Future<Output = RuntimeProcessObservation> + Send;
    fn cancel(
        &self,
        intent: &ProviderEffectIntent,
        wire_payload: &[u8],
    ) -> impl Future<Output = RuntimeProcessObservation> + Send;
}

impl RuntimeProcessResult {
    pub(super) fn receipt(
        &self,
        intent: &ProviderEffectIntent,
    ) -> Result<AuthorizedEffectProviderReceipt> {
        if self.output.len() > MAXIMUM_OUTPUT_BYTES {
            return Err(Error::Limit("original runtime output"));
        }
        if !serde_json::from_str::<serde_json::Value>(&self.output)
            .map_err(|_| Error::Contract("original runtime output JSON"))?
            .is_object()
            || self
                .job_identity_digest
                .as_str()
                .bytes()
                .all(|byte| byte == b'0')
            || self
                .owner_receipt_digest
                .as_str()
                .bytes()
                .all(|byte| byte == b'0')
        {
            return Err(Error::Contract("original runtime evidence"));
        }
        let mut bytes = b"hepta.native-agent.runtime-process-receipt.v1\0".to_vec();
        for part in [
            intent.key.as_str(),
            intent.payload_sha256.as_str(),
            self.status_name(),
            self.job_identity_digest.as_str(),
            self.owner_receipt_digest.as_str(),
            self.output.as_str(),
        ] {
            bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
            bytes.extend_from_slice(part.as_bytes());
        }
        Ok(AuthorizedEffectProviderReceipt {
            outcome: match self.status {
                RuntimeProcessStatus::Succeeded => AuthorizedEffectOutcome::Succeeded,
                RuntimeProcessStatus::Failed => AuthorizedEffectOutcome::Failed,
            },
            receipt_digest: Sha256Digest::for_bytes(&bytes),
        })
    }

    pub(super) fn status_name(&self) -> &'static str {
        match self.status {
            RuntimeProcessStatus::Succeeded => "succeeded",
            RuntimeProcessStatus::Failed => "failed",
        }
    }
}

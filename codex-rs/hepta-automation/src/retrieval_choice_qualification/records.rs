use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::ACTIVITY;
use super::FixtureError;
use super::FixtureRootCapability;
use super::RUN_ID;
use super::encoding::MAX_RETAINED_BYTES;
use crate::TaskFlowFence;
use crate::TaskFlowStepReceipt;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum PhaseOperation {
    Prepare,
    Claim,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseCommand {
    pub(crate) version: u32,
    pub(crate) operation: PhaseOperation,
    pub(crate) command_id: String,
    pub(crate) run_id: String,
    pub(crate) activation_id: String,
    pub(crate) node: String,
    pub(crate) revision: u64,
    pub(crate) fence: TaskFlowFence,
    pub(crate) definition_digest: Sha256Digest,
    pub(crate) intent_digest: Sha256Digest,
    pub(crate) payload_digest: Sha256Digest,
    pub(crate) body_generation: u64,
    pub(crate) prepare_digest: Option<Sha256Digest>,
    pub(crate) now_ms: u64,
    pub(crate) bootstrap_event_seq: u64,
}

impl PhaseCommand {
    pub(super) fn prepare(capability: &FixtureRootCapability) -> Result<Self, FixtureError> {
        let run = capability.activation.get().ok_or(FixtureError::Invalid)?;
        let fence = TaskFlowFence::new(
            run.owner_agent_id.clone(),
            run.owner_id.clone().ok_or(FixtureError::Invalid)?,
            run.owner_epoch.ok_or(FixtureError::Invalid)?,
            run.generation.ok_or(FixtureError::Invalid)?,
            run.fencing_token.clone().ok_or(FixtureError::Invalid)?,
        )?;
        Ok(Self {
            version: 1,
            operation: PhaseOperation::Prepare,
            command_id: "prep0001".to_owned(),
            run_id: RUN_ID.to_owned(),
            activation_id: "act00001".to_owned(),
            node: ACTIVITY.to_owned(),
            revision: run.revision,
            fence,
            definition_digest: run.definition_digest.clone(),
            intent_digest: Sha256Digest::for_bytes(b"prepare-claim-v1-intent"),
            payload_digest: Sha256Digest::for_bytes(b"synthetic-fixed-retrieve-choice"),
            body_generation: 1,
            prepare_digest: None,
            now_ms: capability.now_ms(),
            bootstrap_event_seq: *capability
                .bootstrap_event_seq
                .get()
                .ok_or(FixtureError::Invalid)?,
        })
    }

    pub(super) fn claim(&self, now_ms: u64) -> Result<Self, FixtureError> {
        if self.operation != PhaseOperation::Prepare {
            return Err(FixtureError::Invalid);
        }
        let mut claim = self.clone();
        claim.operation = PhaseOperation::Claim;
        claim.command_id = "claim001".to_owned();
        claim.prepare_digest = Some(self.canonical()?.1);
        claim.now_ms = now_ms;
        Ok(claim)
    }

    pub(crate) fn validate(&self, capability: &FixtureRootCapability) -> Result<(), FixtureError> {
        let frozen = Self::prepare(capability)?;
        if let Some(digest) = &self.prepare_digest
            && (digest.as_str().len() != 64 || Sha256Digest::parse(digest.as_str()).is_err())
        {
            return Err(FixtureError::Invalid);
        }
        let safe_id = |id: &str| {
            !id.is_empty()
                && id.len() <= 8
                && id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        };
        if self.version != 1
            || !safe_id(&self.command_id)
            || !safe_id(&self.activation_id)
            || self.activation_id != frozen.activation_id
            || self.bootstrap_event_seq != frozen.bootstrap_event_seq
            || self.run_id != frozen.run_id
            || self.node != frozen.node
            || self.revision != frozen.revision
            || self.fence != frozen.fence
            || self.definition_digest != frozen.definition_digest
            || self.intent_digest != frozen.intent_digest
            || self.payload_digest != frozen.payload_digest
            || self.body_generation != 1
            || self.now_ms > i64::MAX as u64
            || self.now_ms > capability.now_ms()
            || (self.operation == PhaseOperation::Prepare) != self.prepare_digest.is_none()
        {
            return Err(FixtureError::Invalid);
        }
        Ok(())
    }

    pub(crate) fn canonical(&self) -> Result<(Vec<u8>, Sha256Digest), FixtureError> {
        let bytes = serde_json::to_vec(self).map_err(|_| FixtureError::Invalid)?;
        if bytes.len() > MAX_RETAINED_BYTES {
            return Err(FixtureError::Budget);
        }
        let mut domain = b"taskflow-prepare-claim-command-v1\0".to_vec();
        domain.extend_from_slice(&bytes);
        Ok((bytes, Sha256Digest::for_bytes(&domain)))
    }
}

#[derive(Debug)]
pub(crate) struct PhaseReceipt {
    pub(crate) native: TaskFlowStepReceipt,
    pub(crate) command_digest: Sha256Digest,
    pub(crate) retained_bytes: usize,
}

/// An in-process observation of a fresh committed claim, with no consumer.
/// It cannot be cloned/serialized and grants no physical read or dispatch right.
#[derive(Debug)]
pub(crate) struct FreshClaim {
    pub(crate) receipt: PhaseReceipt,
}

#[derive(Debug)]
pub(crate) enum PhaseOutcome {
    Applied(PhaseReceipt),
    Fresh(FreshClaim),
    Historical(PhaseReceipt),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PhaseFault {
    None,
    AfterNativeAppend,
    AfterCorrelationInsert,
    BeforeCommit,
    AfterCommitAckLoss,
}

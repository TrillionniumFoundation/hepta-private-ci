//! Supervisor generation-finalization owner, after CNS route publication.
//!
//! Old-writer admission and result fences MUST already be closed before CNS
//! publication. This step requires the actual durable writer-handoff journal
//! to advance from RoutePublished to Retired. It authenticates the original
//! terminal checkpoint and rereads current generation/result fences.
//! This adapter never manufactures a Supervisor operation receipt or authority.

use crate::CellSplitDurableEffectBackendV1;
use crate::CellSplitExecutionIntentV1;
use crate::CellSplitExecutionPlanV1;
use crate::CellSplitExecutionStepV1;
use crate::CellSplitOwnedEffectV1;
use crate::durable::SIDECAR_LOCK_FILE;
use crate::durable::SidecarLock;
use crate::durable::canonical_json;
use crate::durable::lock_sidecar;
use crate::durable::reject_recreated_sidecar_for_owner_history;
use crate::durable::secure_read;
use crate::durable::secure_root;
use crate::durable::sha256;
use crate::durable::write_private_new;
use serde::Deserialize;
use serde::Serialize;
use std::fs;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;
use thiserror::Error;

const FROZEN: &str = "cell-split-supervisor-frozen.json";
const MAX_FROZEN_BYTES: usize = 64 * 1024;
const MAX_PROOF_BYTES: usize = 24 * 1024;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSupervisorFenceBindingV1 {
    pub supervisor_id: String,
    pub domain_id: String,
    pub authority_epoch: u64,
    pub handoff_plan_digest: String,
    pub successor_route_digest: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CellSplitSupervisorPhaseV1 {
    RoutePublished,
    Retired,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSupervisorLiveFenceV1 {
    pub supervisor_id: String,
    pub domain_id: String,
    pub old_generation: u64,
    pub new_generation: u64,
    pub authority_epoch: u64,
    pub route_fence_digest: String,
    pub handoff_plan_digest: String,
    pub phase: CellSplitSupervisorPhaseV1,
    pub old_writer_admission_closed: bool,
    pub old_writer_result_fenced: bool,
    pub new_writer_admission_open: bool,
    pub unknown_effect_count: u32,
    pub current_revision: u64,
    pub challenge_nonce: String,
    pub signed_live_checkpoint_bytes: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSupervisorCommitV1 {
    pub idempotency_key: String,
    pub domain_id: String,
    pub handoff_plan_digest: String,
    pub old_generation: u64,
    pub new_generation: u64,
    pub authority_epoch: u64,
    pub committed_revision: u64,
    pub original_checkpoint_bytes: Vec<u8>,
    pub original_checkpoint_signature_bytes: Vec<u8>,
}

/// Production implementations must delegate to DurableWriterHandoffJournalV1
/// and validate WriterHandoffCheckpointV1 plus current CNS/Selector authority.
/// They must not use a generated digest as proof of finalizing the handoff.
/// No allow-all or simulated production implementation is provided.
pub trait CellSplitSupervisorRuntimePortV1 {
    type Error: std::fmt::Display;

    fn verify_preconditions(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
        binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error>;

    fn read_live(
        &mut self,
        supervisor_id: &str,
        domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorLiveFenceV1, Self::Error>;

    fn verify_live(&mut self, live: &CellSplitSupervisorLiveFenceV1) -> Result<(), Self::Error>;

    fn finalize_once(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
        binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error>;

    fn read_original_commit(
        &mut self,
        idempotency_key: &str,
    ) -> Result<Option<CellSplitSupervisorCommitV1>, Self::Error>;

    fn verify_original_commit(
        &mut self,
        receipt: &CellSplitSupervisorCommitV1,
    ) -> Result<(), Self::Error>;

    fn durable_revision(&mut self, supervisor_id: &str) -> Result<u64, Self::Error>;
}

#[derive(Debug, Error)]
pub enum CellSplitSupervisorFenceErrorV1 {
    #[error("Supervisor handoff or cutover binding mismatch")]
    Invalid,
    #[error("Supervisor authority, durable handoff or CNS readback denied: {0}")]
    External(String),
    #[error("Supervisor retired without an original committed handoff receipt")]
    Ambiguous,
    #[error(transparent)]
    Durable(#[from] crate::AcceptanceError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

/// Stores only an immutable local plan and lock; all real side effects and
/// original acknowledgements remain owned by the canonical Supervisor.
pub struct CellSplitSupervisorFenceOwnerV1<P: CellSplitSupervisorRuntimePortV1> {
    root: PathBuf,
    plan: CellSplitExecutionPlanV1,
    plan_digest: String,
    binding: CellSplitSupervisorFenceBindingV1,
    port: P,
    _lock: SidecarLock,
}

impl<P: CellSplitSupervisorRuntimePortV1> CellSplitSupervisorFenceOwnerV1<P> {
    pub fn open(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        binding: CellSplitSupervisorFenceBindingV1,
        port: P,
    ) -> Result<Self, CellSplitSupervisorFenceErrorV1> {
        // Require the coordinator's complete frozen-plan contract even when
        // this effect owner is opened independently of Agentd.
        let plan_digest = plan.digest().map_err(|_| CellSplitSupervisorFenceErrorV1::Invalid)?;
        if binding.supervisor_id.is_empty()
            || binding.domain_id.is_empty()
            || binding.supervisor_id.len() > 256
            || binding.domain_id.len() > 256
            || binding.authority_epoch == 0
            || !digest_shape(&binding.handoff_plan_digest)
            || !digest_shape(&binding.successor_route_digest)
            || !digest_shape(&plan.scope_digest)
            || !digest_shape(&plan.route_fence_digest)
            || plan.parent_generation == 0
            || plan.parent_generation.checked_add(1) != Some(plan.child_generation)
            || plan.owner_ids[3].is_empty()
        {
            return Err(CellSplitSupervisorFenceErrorV1::Invalid);
        }
        let root = secure_root(root, "Supervisor generation owner root")?;
        // An existing sidecar means this owner namespace has been initialized.
        // If its frozen binding disappeared, silently rewriting it would let
        // an interrupted or already-retired handoff be rebound on recovery.
        // The original independent Supervisor journal must be reconciled.
        let initialized_before = match fs::symlink_metadata(root.join(SIDECAR_LOCK_FILE)) {
            Ok(_) => true,
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        reject_recreated_sidecar_for_owner_history(
            &root,
            initialized_before,
            &[FROZEN],
            &["cell-split-supervisor-"],
        )?;
        let lock = lock_sidecar(&root)?;
        reject_recreated_sidecar_for_owner_history(
            &root,
            initialized_before,
            &[FROZEN],
            &["cell-split-supervisor-"],
        )?;
        let frozen = canonical_json(&(plan.clone(), binding.clone()))?;
        match fs::symlink_metadata(root.join(FROZEN)) {
            Ok(_) if secure_read(&root.join(FROZEN), MAX_FROZEN_BYTES)? != frozen => {
                return Err(CellSplitSupervisorFenceErrorV1::Invalid);
            }
            Ok(_) => {}
            Err(error) if error.kind() == ErrorKind::NotFound => {
                if initialized_before {
                    return Err(CellSplitSupervisorFenceErrorV1::Invalid);
                }
                write_private_new(&root.join(FROZEN), &frozen)?;
            }
            Err(error) => return Err(error.into()),
        }

        Ok(Self {
            root,
            plan,
            plan_digest,
            binding,
            port,
            _lock: lock,
        })
    }

    fn intent_valid(
        &self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), CellSplitSupervisorFenceErrorV1> {
        let expected_key = sha256(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                self.plan_digest,
                CellSplitExecutionStepV1::SupervisorGenerationFence.index(),
                intent.previous_receipt_digest,
            )
            .as_bytes(),
        );
        if intent.schema != "hepta.learning.cell-split.execution-owner.v1"
            || intent.step != CellSplitExecutionStepV1::SupervisorGenerationFence
            || intent.owner_id != self.plan.owner_ids[3]
            || intent.plan_digest != self.plan_digest
            || !digest_shape(&intent.idempotency_key)
            || !digest_shape(&intent.previous_receipt_digest)
            || intent.idempotency_key != expected_key
            || secure_read(&self.root.join(FROZEN), MAX_FROZEN_BYTES)?
                != canonical_json(&(self.plan.clone(), self.binding.clone()))?
        {
            return Err(CellSplitSupervisorFenceErrorV1::Invalid);
        }
        Ok(())
    }

    fn checked_live(
        &mut self,
    ) -> Result<CellSplitSupervisorLiveFenceV1, CellSplitSupervisorFenceErrorV1> {
        let nonce = rand::random::<[u8; 32]>()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let live = self
            .port
            .read_live(&self.binding.supervisor_id, &self.binding.domain_id, &nonce)
            .map_err(|e| CellSplitSupervisorFenceErrorV1::External(e.to_string()))?;
        if live.supervisor_id != self.binding.supervisor_id
            || live.domain_id != self.binding.domain_id
            || live.old_generation != self.plan.parent_generation
            || live.new_generation != self.plan.child_generation
            || live.authority_epoch != self.binding.authority_epoch
            || live.route_fence_digest != self.plan.route_fence_digest
            || live.handoff_plan_digest != self.binding.handoff_plan_digest
            || !live.old_writer_admission_closed
            || !live.old_writer_result_fenced
            || !live.new_writer_admission_open
            || live.challenge_nonce != nonce
            || live.unknown_effect_count != 0
            || live.current_revision == 0
            || live.signed_live_checkpoint_bytes.is_empty()
            || live.signed_live_checkpoint_bytes.len() > MAX_PROOF_BYTES
        {
            return Err(CellSplitSupervisorFenceErrorV1::Invalid);
        }
        self.port
            .verify_live(&live)
            .map_err(|e| CellSplitSupervisorFenceErrorV1::External(e.to_string()))?;
        Ok(live)
    }

    fn original(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitSupervisorCommitV1>, CellSplitSupervisorFenceErrorV1> {
        let original = self
            .port
            .read_original_commit(&intent.idempotency_key)
            .map_err(|e| CellSplitSupervisorFenceErrorV1::External(e.to_string()))?;
        if let Some(ref receipt) = original {
            if receipt.idempotency_key != intent.idempotency_key
                || receipt.domain_id != self.binding.domain_id
                || receipt.handoff_plan_digest != self.binding.handoff_plan_digest
                || receipt.old_generation != self.plan.parent_generation
                || receipt.new_generation != self.plan.child_generation
                || receipt.authority_epoch != self.binding.authority_epoch
                || receipt.committed_revision == 0
                || receipt.original_checkpoint_bytes.is_empty()
                || receipt.original_checkpoint_bytes.len() > MAX_PROOF_BYTES
                || receipt.original_checkpoint_signature_bytes.len() != 64
            {
                return Err(CellSplitSupervisorFenceErrorV1::Invalid);
            }
            self.port
                .verify_original_commit(receipt)
                .map_err(|e| CellSplitSupervisorFenceErrorV1::External(e.to_string()))?;
        }
        Ok(original)
    }

    fn actual_effect(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, CellSplitSupervisorFenceErrorV1> {
        self.intent_valid(intent)?;
        self.port
            .verify_preconditions(&self.plan, intent, &self.binding)
            .map_err(|e| CellSplitSupervisorFenceErrorV1::External(e.to_string()))?;
        let original = self.original(intent)?;
        let live = self.checked_live()?;
        match (original, live.phase) {
            (Some(receipt), CellSplitSupervisorPhaseV1::Retired)
                if live.current_revision == receipt.committed_revision =>
            {
                Ok(Some(CellSplitOwnedEffectV1 {
                    owner_sequence: receipt.committed_revision,
                    owner_receipt_bytes: canonical_json(&receipt)?,
                }))
            }
            (None, CellSplitSupervisorPhaseV1::RoutePublished) => Ok(None),
            (None, CellSplitSupervisorPhaseV1::Retired) => {
                Err(CellSplitSupervisorFenceErrorV1::Ambiguous)
            }
            _ => Err(CellSplitSupervisorFenceErrorV1::Invalid),
        }
    }
}

impl<P: CellSplitSupervisorRuntimePortV1> CellSplitDurableEffectBackendV1
    for CellSplitSupervisorFenceOwnerV1<P>
{
    type Error = CellSplitSupervisorFenceErrorV1;

    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        let _ = self.actual_effect(intent)?;
        Ok(())
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        if self.actual_effect(intent)?.is_some() {
            // Finalization already exists; only a fresh signed ReadBack may
            // reconcile it. It is not evidence caused by this new Execute.
            return Err(CellSplitSupervisorFenceErrorV1::Ambiguous);
        }
        // Production finalization must be an actual durable writer-handoff
        // transition. The independent port must reverify CNS and final-use
        // immediately before mutating the authoritative handoff journal.
        self.port
            .finalize_once(&self.plan, intent, &self.binding)
            .map_err(|e| CellSplitSupervisorFenceErrorV1::External(e.to_string()))?;
        if self.actual_effect(intent)?.is_none() {
            return Err(CellSplitSupervisorFenceErrorV1::Ambiguous);
        }
        Ok(())
    }

    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        self.actual_effect(intent)
    }

    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        Ok(self.actual_effect(intent)?.as_ref() == Some(effect))
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        self.checked_live()?;
        let sequence = self
            .port
            .durable_revision(&self.binding.supervisor_id)
            .map_err(|e| CellSplitSupervisorFenceErrorV1::External(e.to_string()))?;
        if sequence == 0 {
            return Err(CellSplitSupervisorFenceErrorV1::Invalid);
        }
        Ok(sequence)
    }
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        && value.bytes().any(|b| b != b'0')
}

#[cfg(test)]
#[path = "cell_split_supervisor_fence_tests.rs"]
mod tests;

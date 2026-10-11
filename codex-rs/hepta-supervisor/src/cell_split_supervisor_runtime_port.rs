//! Real Supervisor-backed CellSplit effect port.
//!
//! The source of truth is the existing fsync-backed writer-handoff journal,
//! recovered with an independently retained minimum checkpoint. This adapter
//! never publishes a synthetic Retired state or trusts a local digest ledger.
//! Both route and NDU/Selector authority checks are delegated to the separate
//! authenticated finalizer port on every mutation and readback.
//!
//! This is an executable owner adapter, not a daemon startup composition or
//! a production authorization grant. Deployments must provision a separate
//! Supervisor signer, signed CNS/selection readers and a trusted minimum.

use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorCommitV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorFenceBindingV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorLiveFenceV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorPhaseV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorRuntimePortV1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use sha2::Digest as _;
use sha2::Sha256;

use crate::CellSplitFinalizationAuthorityV1;
use crate::CellSplitSupervisorJournalFinalizerV1;
use crate::WriterHandoffPhaseV1;

/// Adapter to a single real journal under a separately held writer lock.
///
/// The expected intent and accepted handoff digest must be obtained from an
/// independently authenticated registry/Selector; unpinned split requests
/// cannot reuse this owner. All positive evidence comes from the journal.
pub struct CellSplitSupervisorJournalRuntimePortV1<A: CellSplitFinalizationAuthorityV1> {
    plan: CellSplitExecutionPlanV1,
    binding: CellSplitSupervisorFenceBindingV1,
    intent: CellSplitExecutionIntentV1,
    finalizer: CellSplitSupervisorJournalFinalizerV1<A>,
    signer: SigningKey,
}

impl<A: CellSplitFinalizationAuthorityV1> CellSplitSupervisorJournalRuntimePortV1<A> {
    pub fn new(
        plan: CellSplitExecutionPlanV1,
        binding: CellSplitSupervisorFenceBindingV1,
        intent: CellSplitExecutionIntentV1,
        accepted_handoff_plan_digest: Digest32,
        finalizer: CellSplitSupervisorJournalFinalizerV1<A>,
        signer: SigningKey,
    ) -> Result<Self, String> {
        let original = finalizer.binding();
        let plan_digest = plan.digest().map_err(|e| e.to_string())?;
        let expected_key = format!(
            "{:x}",
            Sha256::digest(
                format!(
                    "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                    plan_digest,
                    CellSplitExecutionStepV1::SupervisorGenerationFence.index(),
                    intent.previous_receipt_digest
                )
                .as_bytes()
            )
        );
        if accepted_handoff_plan_digest.is_zero()
            || intent.schema != "hepta.learning.cell-split.execution-owner.v1"
            || intent.step != CellSplitExecutionStepV1::SupervisorGenerationFence
            || intent.owner_id != plan.owner_ids[3]
            || intent.plan_digest != plan_digest
            || intent.idempotency_key != expected_key
            || original.operation_id.as_str() != plan.split_id
            || original.domain_id.as_str() != binding.domain_id
            || original.old_generation.get() != plan.parent_generation
            || original.new_generation.get() != plan.child_generation
            || original.authority_epoch != binding.authority_epoch
            || original.cns_cutover_receipt_digest.to_string() != intent.previous_receipt_digest
            || original.successor_route_digest.to_string() != binding.successor_route_digest
            || accepted_handoff_plan_digest.to_string() != binding.handoff_plan_digest
            || binding.supervisor_id.is_empty()
        {
            return Err("supervisor journal and frozen CellSplit intent mismatch".into());
        }
        Ok(Self {
            plan,
            binding,
            intent,
            finalizer,
            signer,
        })
    }

    fn verify_identity(
        &self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
        binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), String> {
        if plan != &self.plan || intent != &self.intent || binding != &self.binding {
            return Err("request differs from independently pinned journal identity".into());
        }
        Ok(())
    }

    fn make_live(
        &mut self,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorLiveFenceV1, String> {
        if !canonical_nonce(challenge_nonce) {
            return Err("supervisor readback challenge is malformed".into());
        }
        // read_retired authenticates CNS and final-use even when it returns
        // None for RoutePublished. The journal is the actual live checkpoint.
        let _ = self.finalizer.read_retired().map_err(|e| e.to_string())?;
        let checkpoint = self.finalizer.checkpoint();
        let phase = match checkpoint.phase {
            WriterHandoffPhaseV1::RoutePublished => CellSplitSupervisorPhaseV1::RoutePublished,
            WriterHandoffPhaseV1::Retired => CellSplitSupervisorPhaseV1::Retired,
            _ => return Err("journal is not published or retired".into()),
        };
        let actual = checkpoint
            .canonical_receipt_bytes_v1()
            .map_err(|e| e.to_string())?;
        let signed = self
            .signer
            .sign(&live_signing_payload(challenge_nonce, &actual))
            .to_bytes()
            .to_vec();
        Ok(CellSplitSupervisorLiveFenceV1 {
            supervisor_id: self.binding.supervisor_id.clone(),
            domain_id: checkpoint.plan.domain_id.to_string(),
            old_generation: checkpoint.plan.old_generation.get(),
            new_generation: checkpoint.plan.new_generation.get(),
            authority_epoch: checkpoint.plan.authority_epoch,
            route_fence_digest: self.plan.route_fence_digest.clone(),
            handoff_plan_digest: self.binding.handoff_plan_digest.clone(),
            phase,
            old_writer_admission_closed: !checkpoint.old_writer_admission_open(),
            old_writer_result_fenced: checkpoint.issue_old_result_fence().is_none(),
            new_writer_admission_open: checkpoint.new_writer_admission_open(),
            unknown_effect_count: checkpoint.unknown_effect_count,
            current_revision: checkpoint.revision,
            challenge_nonce: challenge_nonce.to_owned(),
            signed_live_checkpoint_bytes: signed,
        })
    }

    fn committed_record(
        &mut self,
    ) -> Result<Option<CellSplitSupervisorCommitV1>, String> {
        let Some(original) = self
            .finalizer
            .read_retired_receipt_bytes()
            .map_err(|e| e.to_string())?
        else {
            return Ok(None);
        };
        let checkpoint = self.finalizer.checkpoint();
        let signed = self
            .signer
            .sign(&commit_signing_payload(&self.intent.idempotency_key, &original))
            .to_bytes()
            .to_vec();
        Ok(Some(CellSplitSupervisorCommitV1 {
            idempotency_key: self.intent.idempotency_key.clone(),
            domain_id: checkpoint.plan.domain_id.to_string(),
            handoff_plan_digest: self.binding.handoff_plan_digest.clone(),
            old_generation: checkpoint.plan.old_generation.get(),
            new_generation: checkpoint.plan.new_generation.get(),
            authority_epoch: checkpoint.plan.authority_epoch,
            committed_revision: checkpoint.revision,
            original_checkpoint_bytes: original,
            original_checkpoint_signature_bytes: signed,
        }))
    }
}

impl<A: CellSplitFinalizationAuthorityV1> CellSplitSupervisorRuntimePortV1
    for CellSplitSupervisorJournalRuntimePortV1<A>
{
    type Error = String;

    fn verify_preconditions(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
        binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error> {
        self.verify_identity(plan, intent, binding)?;
        let _ = self.finalizer.read_retired().map_err(|e| e.to_string())?;
        Ok(())
    }

    fn read_live(
        &mut self,
        supervisor_id: &str,
        domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorLiveFenceV1, Self::Error> {
        if supervisor_id != self.binding.supervisor_id || domain_id != self.binding.domain_id {
            return Err("unexpected Supervisor generation owner".into());
        }
        self.make_live(challenge_nonce)
    }

    fn verify_live(
        &mut self,
        observed: &CellSplitSupervisorLiveFenceV1,
    ) -> Result<(), Self::Error> {
        let fresh = self.make_live(&observed.challenge_nonce)?;
        if observed != &fresh {
            return Err("Supervisor live handoff changed across verification".into());
        }
        let original = self
            .finalizer
            .checkpoint()
            .canonical_receipt_bytes_v1()
            .map_err(|e| e.to_string())?;
        let signature = Signature::from_slice(&observed.signed_live_checkpoint_bytes)
            .map_err(|e| e.to_string())?;
        self.signer
            .verifying_key()
            .verify_strict(
                &live_signing_payload(&observed.challenge_nonce, &original),
                &signature,
            )
            .map_err(|e| e.to_string())
    }

    fn finalize_once(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
        binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error> {
        self.verify_preconditions(plan, intent, binding)?;
        self.finalizer.finalize_once().map_err(|e| e.to_string())?;
        Ok(())
    }

    fn read_original_commit(
        &mut self,
        idempotency_key: &str,
    ) -> Result<Option<CellSplitSupervisorCommitV1>, Self::Error> {
        if idempotency_key != self.intent.idempotency_key {
            return Err("Supervisor original idempotency key changed".into());
        }
        self.committed_record()
    }

    fn verify_original_commit(
        &mut self,
        receipt: &CellSplitSupervisorCommitV1,
    ) -> Result<(), Self::Error> {
        let signature = Signature::from_slice(&receipt.original_checkpoint_signature_bytes)
            .map_err(|e| e.to_string())?;
        self.signer
            .verifying_key()
            .verify_strict(
                &commit_signing_payload(
                    &receipt.idempotency_key,
                    &receipt.original_checkpoint_bytes,
                ),
                &signature,
            )
            .map_err(|e| e.to_string())?;
        if self.committed_record()?.as_ref() != Some(receipt) {
            return Err("Supervisor receipt is not the original durable journal record".into());
        }
        Ok(())
    }

    fn durable_revision(&mut self, supervisor_id: &str) -> Result<u64, Self::Error> {
        if supervisor_id != self.binding.supervisor_id {
            return Err("Supervisor owner identity mismatch".into());
        }
        let _ = self.finalizer.read_retired().map_err(|e| e.to_string())?;
        Ok(self.finalizer.checkpoint().revision)
    }
}

fn canonical_nonce(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

fn live_signing_payload(nonce: &str, checkpoint: &[u8]) -> Vec<u8> {
    let mut result = b"hepta.supervisor.cell-split.live-journal.v1\0".to_vec();
    result.extend_from_slice(&(nonce.len() as u64).to_be_bytes());
    result.extend_from_slice(nonce.as_bytes());
    result.extend_from_slice(&(checkpoint.len() as u64).to_be_bytes());
    result.extend_from_slice(checkpoint);
    result
}

fn commit_signing_payload(idempotency_key: &str, checkpoint: &[u8]) -> Vec<u8> {
    let mut result = b"hepta.supervisor.cell-split.original-journal.v1\0".to_vec();
    result.extend_from_slice(&(idempotency_key.len() as u64).to_be_bytes());
    result.extend_from_slice(idempotency_key.as_bytes());
    result.extend_from_slice(&(checkpoint.len() as u64).to_be_bytes());
    result.extend_from_slice(checkpoint);
    result
}

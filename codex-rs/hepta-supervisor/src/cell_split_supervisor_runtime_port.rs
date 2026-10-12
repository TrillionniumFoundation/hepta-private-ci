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

use codex_hepta_operator_acceptance::CellSplitCnsRuntimeAttestationV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimeCommitV1;
use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionReceiptV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorCommitV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorFenceBindingV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorLiveFenceV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorPhaseV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorRuntimePortV1;
use codex_hepta_operator_acceptance::verify_cell_split_cns_step_receipt_v1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;
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

/// Verify the original CNS runtime's signature independently of the outer
/// effect-owner signature, with a separately pinned non-weak public key.
/// The original runtime payload is intentionally opaque and is signed byte
/// for byte by the canonical runtime, not reconstructed from an untrusted
/// caller's declared digest.
fn verify_independent_cns_runtime_signature(
    original_bytes: &[u8],
    signature_bytes: &[u8],
    outer_effect_key: &VerifyingKey,
    original_runtime_key: &VerifyingKey,
    supervisor_key: &VerifyingKey,
) -> Result<(), String> {
    if original_bytes.is_empty()
        || original_bytes.len() > 32 * 1024
        || signature_bytes.len() != 64
        || original_runtime_key.is_weak()
        || outer_effect_key.is_weak()
        || supervisor_key.is_weak()
        || original_runtime_key == outer_effect_key
        || original_runtime_key == supervisor_key
        || outer_effect_key == supervisor_key
    {
        return Err("CNS original runtime signer is absent, weak, or not independent".into());
    }
    let signature = Signature::from_slice(signature_bytes)
        .map_err(|_| "malformed original CNS runtime signature")?;
    original_runtime_key
        .verify_strict(original_bytes, &signature)
        .map_err(|_| "CNS original runtime signature does not authenticate committed bytes".into())
}

impl<A: CellSplitFinalizationAuthorityV1> CellSplitSupervisorJournalRuntimePortV1<A> {
    /// Qualification-only constructor for deliberately identical digest
    /// fixtures. Production cannot call this entry to skip the signed CNS
    /// predecessor bridge; use new_with_signed_cns_predecessor instead.
    #[cfg(test)]
    pub fn new(
        plan: CellSplitExecutionPlanV1,
        binding: CellSplitSupervisorFenceBindingV1,
        intent: CellSplitExecutionIntentV1,
        accepted_handoff_plan_digest: Digest32,
        finalizer: CellSplitSupervisorJournalFinalizerV1<A>,
        signer: SigningKey,
    ) -> Result<Self, String> {
        Self::new_inner(
            plan,
            binding,
            intent,
            accepted_handoff_plan_digest,
            finalizer,
            signer,
            None,
        )
    }

    /// Bind the Supervisor journal to TWO independently authenticated CNS
    /// signatures: the outer CellSplit effect-owner envelope and the original
    /// runtime cutover bytes. A signed outer envelope must not launder forged
    /// inner runtime evidence. Live CNS and NDU/Selector final-use verification
    /// remain separately mandatory.
    pub fn new_with_signed_cns_predecessor(
        plan: CellSplitExecutionPlanV1,
        binding: CellSplitSupervisorFenceBindingV1,
        intent: CellSplitExecutionIntentV1,
        accepted_handoff_plan_digest: Digest32,
        finalizer: CellSplitSupervisorJournalFinalizerV1<A>,
        signer: SigningKey,
        cns_receipt: &CellSplitExecutionReceiptV1,
        pinned_cns_key: &VerifyingKey,
        pinned_cns_runtime_key: &VerifyingKey,
    ) -> Result<Self, String> {
        verify_cell_split_cns_step_receipt_v1(&plan, cns_receipt, pinned_cns_key)
            .map_err(|e| e.to_string())?;
        if intent.previous_receipt_digest != cns_receipt.receipt_digest {
            return Err("Supervisor predecessor is not the signed CNS coordinator receipt".into());
        }
        let original: CellSplitCnsRuntimeCommitV1 =
            serde_json::from_slice(&cns_receipt.owner_receipt_bytes)
                .map_err(|_| "CNS owner did not return a typed original cutover")?;
        if original.idempotency_key != cns_receipt.intent.idempotency_key
            || original.predecessor_generation != plan.parent_generation
            || original.successor_generation != plan.child_generation
            || original.authority_epoch != binding.authority_epoch
            || original.committed_sequence != cns_receipt.owner_sequence
            || original.successor_route_digest != binding.successor_route_digest
            || original.original_runtime_receipt_bytes.is_empty()
            || original.original_runtime_receipt_bytes.len() > 32 * 1024
            || original.original_runtime_signature_bytes.len() != 64
        {
            return Err(
                "signed CNS predecessor contains inconsistent original runtime evidence".into(),
            );
        }
        // The inner runtime signature MUST authenticate typed cutover facts,
        // not an arbitrary valid CNS message unrelated to this split.
        CellSplitCnsRuntimeAttestationV1::verify_original_bytes(&plan, &original)?;
        verify_independent_cns_runtime_signature(
            &original.original_runtime_receipt_bytes,
            &original.original_runtime_signature_bytes,
            pinned_cns_key,
            pinned_cns_runtime_key,
            &signer.verifying_key(),
        )?;
        // Both the signed outer receipt and the independently signed original
        // runtime payload are checked before the journal records this digest.
        // Live CNS/Selector readback is still required at every final use.
        let original_digest = Digest32::of_bytes(&original.original_runtime_receipt_bytes);
        Self::new_inner(
            plan,
            binding,
            intent,
            accepted_handoff_plan_digest,
            finalizer,
            signer,
            Some(original_digest),
        )
    }

    fn new_inner(
        plan: CellSplitExecutionPlanV1,
        binding: CellSplitSupervisorFenceBindingV1,
        intent: CellSplitExecutionIntentV1,
        accepted_handoff_plan_digest: Digest32,
        finalizer: CellSplitSupervisorJournalFinalizerV1<A>,
        signer: SigningKey,
        verified_original_cns_digest: Option<Digest32>,
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
            || (match verified_original_cns_digest {
                Some(digest) => original.cns_cutover_receipt_digest != digest,
                None => {
                    // Source-only compatibility. A real cross-owner cutover
                    // has two distinct digest layers and must use the signed
                    // CNS predecessor constructor below.
                    original.cns_cutover_receipt_digest.to_string()
                        != intent.previous_receipt_digest
                }
            })
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

    fn committed_record(&mut self) -> Result<Option<CellSplitSupervisorCommitV1>, String> {
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
            .sign(&commit_signing_payload(
                &self.intent.idempotency_key,
                &original,
            ))
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

#[cfg(test)]
mod original_cns_signature_tests {
    use super::*;
    use ed25519_dalek::Signer as _;

    #[test]
    fn real_journal_port_requires_independent_original_runtime_signature() {
        let outer = SigningKey::from_bytes(&[31; 32]);
        let runtime = SigningKey::from_bytes(&[41; 32]);
        let alternate = SigningKey::from_bytes(&[51; 32]);
        let supervisor = SigningKey::from_bytes(&[22; 32]);
        let evidence = b"original fsynced CNS runtime cutover";
        let valid = runtime.sign(evidence).to_bytes();

        assert!(
            verify_independent_cns_runtime_signature(
                evidence,
                &valid,
                &outer.verifying_key(),
                &runtime.verifying_key(),
                &supervisor.verifying_key(),
            )
            .is_ok()
        );
        assert!(
            verify_independent_cns_runtime_signature(
                b"forged runtime cutover",
                &valid,
                &outer.verifying_key(),
                &runtime.verifying_key(),
                &supervisor.verifying_key(),
            )
            .is_err()
        );
        let mut tampered = valid;
        tampered[0] ^= 0x80;
        assert!(
            verify_independent_cns_runtime_signature(
                evidence,
                &tampered,
                &outer.verifying_key(),
                &runtime.verifying_key(),
                &supervisor.verifying_key(),
            )
            .is_err()
        );
        assert!(
            verify_independent_cns_runtime_signature(
                evidence,
                &valid,
                &outer.verifying_key(),
                &alternate.verifying_key(),
                &supervisor.verifying_key(),
            )
            .is_err()
        );
        assert!(
            verify_independent_cns_runtime_signature(
                evidence,
                &outer.sign(evidence).to_bytes(),
                &outer.verifying_key(),
                &outer.verifying_key(),
                &supervisor.verifying_key(),
            )
            .is_err()
        );
        assert!(
            verify_independent_cns_runtime_signature(
                evidence,
                &valid[..63],
                &outer.verifying_key(),
                &runtime.verifying_key(),
                &supervisor.verifying_key(),
            )
            .is_err()
        );
        assert!(
            verify_independent_cns_runtime_signature(
                evidence,
                &valid,
                &outer.verifying_key(),
                &runtime.verifying_key(),
                &runtime.verifying_key(),
            )
            .is_err()
        );
        assert!(
            verify_independent_cns_runtime_signature(
                evidence,
                &valid,
                &outer.verifying_key(),
                &runtime.verifying_key(),
                &outer.verifying_key(),
            )
            .is_err()
        );
    }
}

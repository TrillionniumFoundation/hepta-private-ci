//! Real CNS execution bridge for the admitted CellSplit cutover protocol.
//!
//! This opt-in port invokes HeptaRuntime::apply_governed_topology on the
//! *serving* CNS host. It never treats a sidecar route file as an effect.
//! A separate authenticated source owns the original signed runtime commit,
//! current Artifact/Scope/WAL frontier, old-writer drain and final-use grant.
//!
//! Runtime route publication may precede the external durable commit record
//! if the process crashes: that condition remains AMBIGUOUS, cannot be
//! retried as a second cutover, and must be recovered by the runtime owner.
//! This module does not activate the default runtime or supply an issuer.

use std::fmt;
use std::io::Read as _;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_control_plane::NduPublicationOwnerV1;
use codex_hepta_operator_acceptance::CellSplitCnsLiveRouteV1;
use codex_hepta_operator_acceptance::CellSplitCnsRouteBindingV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimeAttestationV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimeCommitV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimePortV1;
use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use codex_hepta_plasticity::TopologyCandidateKindV2;
use codex_hepta_plasticity::TopologyCandidateV2;
use codex_hepta_plasticity::TopologyOperationV2;
use codex_hepta_types::AuthorityPosture;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest as _;
use sha2::Sha256;

use crate::HeptaRuntime;
use crate::RuntimeTopologyApplyReceiptV1;
use crate::RuntimeTopologyApplyRequestV1;
use crate::RuntimeTopologySnapshotV1;

/// Independently authenticated registry and durable CNS commit source.
///
/// Implementations must bind a fresh signed observation to the actual
/// runtime snapshot, supply an independently admitted (and single-use)
/// final-use grant, and fsync the ORIGINAL runtime commit before returning.
/// No in-memory-only, allow-all or digest-only implementation is provided.
pub trait CellSplitCnsKernelWitnessV1 {
    type Error: fmt::Display;

    fn verify_preconditions(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error>;

    fn signed_current_route(
        &mut self,
        runtime: &RuntimeTopologySnapshotV1,
        nonce: &str,
    ) -> Result<CellSplitCnsLiveRouteV1, Self::Error>;

    fn take_admitted_successor(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        binding: &CellSplitCnsRouteBindingV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(SignedFinalUseGrant, RuntimeTopologyApplyRequestV1), Self::Error>;

    fn persist_actual_runtime_receipt(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        binding: &CellSplitCnsRouteBindingV1,
        intent: &CellSplitExecutionIntentV1,
        actual: &RuntimeTopologyApplyReceiptV1,
    ) -> Result<(), Self::Error>;

    fn read_original_commit(
        &mut self,
        idempotency_key: &str,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, Self::Error>;

    /// Independently persisted anti-rollback sequence, not the generation of
    /// the process-local CNS host or the highest file in a directory.
    fn current_durable_sequence(&mut self, cns_id: &str) -> Result<u64, Self::Error>;
}

/// The runtime itself owns dispatch and generation replacement. This adapter
/// only supplies the exact control boundary and verifies external signatures.
pub struct CellSplitCnsKernelRuntimePortV1<W: CellSplitCnsKernelWitnessV1> {
    runtime: HeptaRuntime,
    authority: Arc<FinalUseAuthority>,
    plan: CellSplitExecutionPlanV1,
    binding: CellSplitCnsRouteBindingV1,
    intent: CellSplitExecutionIntentV1,
    runtime_key: VerifyingKey,
    witness: W,
    // A route observed by the runtime is NOT a Control/CNS cutover transaction.
    // This optional owner is intentionally unconstructable via the current
    // serving builder: until a real two-phase same-owner handoff is wired,
    // the physical CNS mutation entry fails before Final-use or dispatch.
    atomic_control_cutover_owner: Option<Arc<NduPublicationOwnerV1>>,
}

impl<W: CellSplitCnsKernelWitnessV1> CellSplitCnsKernelRuntimePortV1<W> {
    pub fn new(
        runtime: HeptaRuntime,
        authority: Arc<FinalUseAuthority>,
        plan: CellSplitExecutionPlanV1,
        binding: CellSplitCnsRouteBindingV1,
        intent: CellSplitExecutionIntentV1,
        runtime_key: VerifyingKey,
        witness: W,
    ) -> Result<Self, String> {
        let digest = plan.digest().map_err(|error| error.to_string())?;
        let key = format!(
            "{:x}",
            Sha256::digest(
                format!(
                    "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                    digest,
                    CellSplitExecutionStepV1::CnsRouteCutover.index(),
                    intent.previous_receipt_digest,
                )
                .as_bytes(),
            )
        );
        if runtime_key.is_weak()
            || plan.owner_ids[2] != intent.owner_id
            || intent.schema != "hepta.learning.cell-split.execution-owner.v1"
            || intent.step != CellSplitExecutionStepV1::CnsRouteCutover
            || intent.plan_digest != digest
            || intent.idempotency_key != key
            || binding.cns_id.is_empty()
            || binding.authority_epoch == 0
            || binding.predecessor_route_digest == binding.successor_route_digest
            || binding.predecessor_route_digest.len() != 64
            || binding.successor_route_digest.len() != 64
            || plan.parent_generation.checked_add(1) != Some(plan.child_generation)
        {
            return Err("unbound CNS runtime port configuration".into());
        }
        Ok(Self {
            runtime,
            authority,
            plan,
            binding,
            intent,
            runtime_key,
            witness,
            atomic_control_cutover_owner: None,
        })
    }

    /// Read-only dual-owner qualification. Verify the original CNS runtime
    /// signature and independent durable owner readback, require a fresh signed
    /// serving successor route, then join those ORIGINAL receipt bytes to the
    /// fsynced Control C binding. Never attempts the physical cutover, claims
    /// Final-use or acknowledges a pending/poisoned Control Begin.
    ///
    /// This API is evidence for an independent Observer, not an authorization
    /// to activate or promote a Cell.
    pub fn verify_original_cns_control_commit_v1(
        &mut self,
        control: &NduPublicationOwnerV1,
    ) -> Result<(), String> {
        let original = self
            .witness
            .read_original_commit(&self.intent.idempotency_key)
            .map_err(|error| error.to_string())?
            .ok_or("CNS original durable effect receipt is missing")?;
        self.verify_original_commit(&original)?;
        let current = self.signed_route(&secure_cns_nonce()?)?;
        if current.generation != self.plan.child_generation
            || current.artifact_digest != self.plan.child_artifact_digest
            || current.route_digest != self.binding.successor_route_digest
            || current.route_fence_digest != self.plan.route_fence_digest
        {
            return Err("CNS does not currently serve the signed successor".into());
        }
        let original_bytes = cell_split_cns_control_original_receipt_bytes_v1(&original)?;
        let control_before = control
            .verify_original_cns_receipt_frontier_v1(&original_bytes)
            .map_err(|error| format!("Control original CNS Commit binding rejected: {error}"))?;
        // Control readback and independent CNS verification can race a later
        // rollback. Demand a second current signed original-owner observation
        // before exporting even read-only acceptance.
        self.verify_original_commit(&original)?;
        let still_live = self.signed_route(&secure_cns_nonce()?)?;
        if still_live.generation != self.plan.child_generation
            || still_live.route_digest != self.binding.successor_route_digest
            || still_live.route_fence_digest != self.plan.route_fence_digest
        {
            return Err("signed CNS successor changed during Control join".into());
        }
        let control_after = control
            .verify_original_cns_receipt_frontier_v1(&original_bytes)
            .map_err(|error| format!("Control CNS binding changed during join: {error}"))?;
        // Identical CNS receipt bytes do not establish one Control revision:
        // a Neuron checkpoint CAS may have fsynced P between the two signed
        // runtime reads. Reject that cross-frontier join, including inode,
        // original WAL sequence/head/bytes and NDU checkpoint drift.
        if control_before != control_after {
            return Err("original Control WAL frontier changed during CNS readback".into());
        }
        Ok(())
    }

    fn live_runtime(&self) -> Result<RuntimeTopologySnapshotV1, String> {
        let observed = self
            .runtime
            .topology_snapshot()
            .map_err(|e| e.to_string())?;
        if observed.route.cns.as_str() != self.binding.cns_id {
            return Err("CNS runtime identity differs from frozen split".into());
        }
        Ok(observed)
    }

    fn verify_pin(
        &self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), String> {
        if plan != &self.plan || intent != &self.intent {
            return Err("CNS runtime request does not match admitted split".into());
        }
        Ok(())
    }

    fn signed_route(&mut self, nonce: &str) -> Result<CellSplitCnsLiveRouteV1, String> {
        if nonce.len() != 64
            || !nonce
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err("invalid CNS live-state challenge".into());
        }
        let actual = self.live_runtime()?;
        let signed = self
            .witness
            .signed_current_route(&actual, nonce)
            .map_err(|e| e.to_string())?;
        if signed.cns_id != self.binding.cns_id
            || signed.scope_digest != self.plan.scope_digest
            || signed.generation != actual.generation().get()
            || signed.route_digest != actual.hierarchy_digest().to_string()
            || signed.authority_epoch != self.binding.authority_epoch
            || signed.challenge_nonce != nonce
            || signed.unknown_effect_count != 0
            || !signed.old_writer_fenced
        {
            return Err("authenticated CNS route does not match actual serving host".into());
        }
        // Cryptographically authenticated metadata alone is insufficient:
        // it must name exactly one of the two frozen Artifact/route states.
        // Old route fences may legitimately differ from the new plan fence.
        let valid_generation = if signed.generation == self.plan.parent_generation {
            signed.artifact_digest == self.plan.parent_artifact_digest
                && signed.route_digest == self.binding.predecessor_route_digest
        } else if signed.generation == self.plan.child_generation {
            signed.artifact_digest == self.plan.child_artifact_digest
                && signed.route_digest == self.binding.successor_route_digest
                && signed.route_fence_digest == self.plan.route_fence_digest
        } else {
            false
        };
        if !valid_generation {
            return Err("signed CNS state does not match frozen Artifact and route".into());
        }
        self.verify_route_signature(&signed)?;
        Ok(signed)
    }

    fn verify_route_signature(&self, route: &CellSplitCnsLiveRouteV1) -> Result<(), String> {
        let signature =
            Signature::from_slice(&route.live_runtime_proof_bytes).map_err(|e| e.to_string())?;
        self.runtime_key
            .verify_strict(&signed_route_payload(route)?, &signature)
            .map_err(|_| "CNS runtime live-state signature is invalid".into())
    }
}

/// A generic Update candidate can contain Add/Replace/Rewire operations.
/// CellSplit must bind the *typed* Split mutation before invoking the live
/// generation replacement, not infer a split from a successor generation.
fn is_typed_cell_split_candidate_v1(candidate: &TopologyCandidateV2) -> bool {
    candidate.kind == TopologyCandidateKindV2::Update
        && candidate.changes.len() == 1
        && candidate.changes[0].operation == TopologyOperationV2::Split
}

impl<W: CellSplitCnsKernelWitnessV1> CellSplitCnsRuntimePortV1
    for CellSplitCnsKernelRuntimePortV1<W>
{
    type Error = String;

    fn verify_preconditions(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.verify_pin(plan, intent)?;
        self.witness
            .verify_preconditions(plan, intent)
            .map_err(|e| e.to_string())
    }

    fn inspect_live(
        &mut self,
        cns_id: &str,
        scope_digest: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitCnsLiveRouteV1, Self::Error> {
        if cns_id != self.binding.cns_id || scope_digest != self.plan.scope_digest {
            return Err("unexpected CNS scope or identity".into());
        }
        self.signed_route(challenge_nonce)
    }

    fn verify_live(&mut self, observed: &CellSplitCnsLiveRouteV1) -> Result<(), Self::Error> {
        self.verify_route_signature(observed)?;
        if self.signed_route(&observed.challenge_nonce)? != *observed {
            return Err("CNS serving route changed before verification".into());
        }
        Ok(())
    }

    fn publish_once(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        binding: &CellSplitCnsRouteBindingV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        // No live CNS generation replacement may happen under an unrelated
        // route owner. A signed route observation, signed Final-use grant and
        // digest-only predecessor are NOT a linearization transaction.
        //
        // This slot cannot be populated by any public API. It must remain
        // unavailable until a reviewed, durable pre-effect Prepare / post-
        // effect Commit protocol holds the SAME Control owner as Neuron CAS,
        // and recovery quarantines a crash between the two writes.
        self.atomic_control_cutover_owner
            .as_ref()
            .ok_or("CNS mutation denied: no shared durable Control/Neuron cutover transaction")?;
        self.verify_pin(plan, intent)?;
        if binding != &self.binding {
            return Err("CNS cutover binding changed".into());
        }
        self.verify_preconditions(plan, intent)?;
        // A direct kernel caller must enforce the same fresh independent
        // old-writer fence as the outer CellSplit RPC owner.
        let pinned_predecessor = self.signed_route(&secure_cns_nonce()?)?;
        let before = self.live_runtime()?;
        if pinned_predecessor.generation != plan.parent_generation
            || before.generation().get() != plan.parent_generation
            || before.hierarchy_digest().to_string() != binding.predecessor_route_digest
        {
            return Err("predecessor CNS host no longer serves the frozen route".into());
        }
        if self
            .witness
            .read_original_commit(&intent.idempotency_key)
            .map_err(|e| e.to_string())?
            .is_some()
        {
            return Err("already committed CNS cutover cannot run again".into());
        }
        let (grant, request) = self
            .witness
            .take_admitted_successor(plan, binding, intent)
            .map_err(|e| e.to_string())?;
        let selected = request
            .governed
            .proposal
            .candidates
            .iter()
            .find(|candidate| candidate.candidate_id == request.candidate_id)
            .ok_or("admitted topology omits selected CellSplit candidate")?;
        if !is_typed_cell_split_candidate_v1(selected) {
            return Err("CellSplit CNS requires exactly one typed Split operation".into());
        }
        let expected = request.successor.snapshot();
        // Match the actual predecessor/successor graph identities before
        // consuming the one-shot final-use grant. The generic Update envelope
        // alone is not proof that a CellSplit operation was selected.
        let change = &selected.changes[0];
        if change.predecessor_digest != Some(before.hierarchy_digest())
            || change.candidate_digest != Some(expected.hierarchy_digest())
        {
            return Err("typed CellSplit graph transition differs from CNS host".into());
        }
        if expected.generation().get() != plan.child_generation
            || expected.hierarchy_digest().to_string() != binding.successor_route_digest
            || expected.cns_id() != before.cns_id()
        {
            return Err("CNS successor differs from admitted routing plan".into());
        }
        // An admitted request can be prepared before revocation or another
        // concurrent route writer changes the runtime. Recheck both sources
        // immediately before consuming the signed final-use grant.
        self.verify_preconditions(plan, intent)?;
        let refreshed = self.signed_route(&secure_cns_nonce()?)?;
        if refreshed.generation != plan.parent_generation || self.live_runtime()? != before {
            return Err("CNS route changed after admitted successor preparation".into());
        }
        let actual = self
            .runtime
            .apply_governed_topology(&self.authority, &grant, request)
            .map_err(|e| e.to_string())?;
        // This is the genuine live runtime operation receipt, *not* a digest
        // fixture. It must describe precisely the transition just observed.
        if actual.authority != AuthorityPosture::DENY_ALL
            || actual.predecessor_generation.get() != plan.parent_generation
            || actual.successor_generation.get() != plan.child_generation
            || actual.predecessor_hierarchy_digest != before.hierarchy_digest()
            || actual.successor_hierarchy_digest.to_string() != binding.successor_route_digest
        {
            return Err("runtime reported a different topology effect".into());
        }
        let observed_successor = self.signed_route(&secure_cns_nonce()?)?;
        let after = self.live_runtime()?;
        if observed_successor.generation != plan.child_generation
            || after.generation().get() != plan.child_generation
            || after.hierarchy_digest().to_string() != binding.successor_route_digest
        {
            return Err("runtime cutover is not serving the admitted successor".into());
        }
        // If this externally owned durable fsync fails after runtime mutation,
        // the effect is ambiguous; no second cutover or positive receipt.
        self.witness
            .persist_actual_runtime_receipt(plan, binding, intent, &actual)
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    fn read_original_commit(
        &mut self,
        key: &str,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, Self::Error> {
        if key != self.intent.idempotency_key {
            return Err("unexpected CNS original idempotency key".into());
        }
        self.witness
            .read_original_commit(key)
            .map_err(|e| e.to_string())
    }

    fn verify_original_commit(
        &mut self,
        commit: &CellSplitCnsRuntimeCommitV1,
    ) -> Result<(), Self::Error> {
        CellSplitCnsRuntimeAttestationV1::verify_original_bytes(&self.plan, commit)
            .map_err(str::to_string)?;
        if commit.idempotency_key != self.intent.idempotency_key
            || commit.cns_id != self.binding.cns_id
            || commit.predecessor_route_digest != self.binding.predecessor_route_digest
            || commit.successor_route_digest != self.binding.successor_route_digest
            || commit.authority_epoch != self.binding.authority_epoch
            || commit.original_runtime_signature_bytes.len() != 64
        {
            return Err("original CNS runtime commit is not bound to the split".into());
        }
        let signature = Signature::from_slice(&commit.original_runtime_signature_bytes)
            .map_err(|e| e.to_string())?;
        self.runtime_key
            .verify_strict(&commit.original_runtime_receipt_bytes, &signature)
            .map_err(|_| "original CNS runtime commit signature invalid".to_string())?;
        let readback = self
            .witness
            .read_original_commit(&self.intent.idempotency_key)
            .map_err(|e| e.to_string())?;
        if readback.as_ref() != Some(commit) {
            return Err("original CNS commit no longer exists in durable owner".into());
        }
        let frontier = self
            .witness
            .current_durable_sequence(&self.binding.cns_id)
            .map_err(|e| e.to_string())?;
        if frontier == 0 || frontier < commit.committed_sequence {
            return Err("signed CNS receipt exceeds independently retained frontier".into());
        }
        Ok(())
    }

    fn committed_sequence(&mut self, cns_id: &str) -> Result<u64, Self::Error> {
        if cns_id != self.binding.cns_id {
            return Err("CNS sequence owner changed".into());
        }
        self.witness
            .current_durable_sequence(cns_id)
            .map_err(|e| e.to_string())
    }
}

fn secure_cns_nonce() -> Result<String, String> {
    // This feature is Unix-only; read the host CSPRNG and never derive
    // freshness from a timestamp, generation, PID or cached effect digest.
    let mut bytes = [0_u8; 32];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut source| source.read_exact(&mut bytes))
        .map_err(|e| format!("CNS challenge entropy unavailable: {e}"))?;
    Ok(bytes.iter().map(|value| format!("{value:02x}")).collect())
}

/// Canonical, versioned evidence bytes to link an original *already signed*
/// CNS runtime commit with the independent durable Control C record. A caller
/// must first verify the exact original runtime signature and fresh owner
/// readback; producing these bytes does NOT authorize a physical cutover.
pub fn cell_split_cns_control_original_receipt_bytes_v1(
    original: &CellSplitCnsRuntimeCommitV1,
) -> Result<Vec<u8>, String> {
    let serialized = serde_json::to_vec(original).map_err(|error| error.to_string())?;
    let mut bound = b"hepta.runtime.cns-control-original-commit.v1\0".to_vec();
    bound.extend_from_slice(&(serialized.len() as u64).to_be_bytes());
    bound.extend_from_slice(&serialized);
    Ok(bound)
}

/// Domain-separated signing payload for a fresh, runtime-bound route
/// observation. The signature field is empty while signing; all other
/// fields, including the nonce, are authenticated.
pub fn cell_split_cns_live_route_signing_bytes_v1(
    observed: &CellSplitCnsLiveRouteV1,
) -> Result<Vec<u8>, String> {
    signed_route_payload(observed)
}

fn signed_route_payload(route: &CellSplitCnsLiveRouteV1) -> Result<Vec<u8>, String> {
    let mut unsigned = route.clone();
    unsigned.live_runtime_proof_bytes.clear();
    let encoded = serde_json::to_vec(&unsigned).map_err(|e| e.to_string())?;
    let mut output = b"hepta.runtime.cell-split.actual-cns-live.v1\0".to_vec();
    output.extend_from_slice(&(encoded.len() as u64).to_be_bytes());
    output.extend_from_slice(&encoded);
    Ok(output)
}

#[cfg(test)]
#[path = "cell_split_cns_runtime_port_tests.rs"]
mod tests;

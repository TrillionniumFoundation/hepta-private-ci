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
use std::path::Path;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
#[cfg(test)]
use codex_hepta_control_plane::NduPublicationLocalFrontierV1;
use codex_hepta_control_plane::NduPublicationOwnerV1;
use codex_hepta_control_plane::NduPublicationPendingBeginV1;
use codex_hepta_operator_acceptance::CellSplitCnsLiveRouteV1;
use codex_hepta_operator_acceptance::CellSplitCnsRouteBindingV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimeAttestationV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimeCommitV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimePortV1;
use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use codex_hepta_plasticity::TopologyCandidateKindV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::NduSnapshotRefV1;
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

/// A separately administered Observer must read its OWN retained Control
/// high-water, then sign a fresh challenge. Never send it a caller-provided
/// frontier to echo; neither a repository digest nor local WAL marker is an
/// independent rollback witness.
pub trait CellSplitIndependentControlObserverV1 {
    type Error: fmt::Display;

    fn read_signed_highwater(
        &mut self,
        split_id: &str,
        scope_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSignedControlHighwaterV1, Self::Error>;
}

/// External Observer claim about its separately retained original Control
/// history. No signer, key material or executable effect is present here.
/// This is read-only evidence; it cannot grant CNS mutation or Final-use.
pub const CELL_SPLIT_SIGNED_CONTROL_HIGHWATER_SCHEMA_V1: &str =
    "hepta.runtime.cell-split.control-independent-highwater.v1";

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSignedControlHighwaterV1 {
    pub schema: String,
    pub observer_id: String,
    pub plan_digest: String,
    pub split_id: String,
    pub scope_id: String,
    pub ndu_owner_id: String,
    pub ndu_snapshot_digest: String,
    pub generation: u64,
    pub route_fence: u64,
    pub revocation_epoch: u64,
    pub sequence: u64,
    pub wal_head: String,
    pub checkpoint_digest: String,
    pub wal_bytes: u64,
    pub wal_device: u64,
    pub wal_inode: u64,
    pub marker_device: u64,
    pub marker_inode: u64,
    pub original_cns_receipt_binding: Option<String>,
    pub challenge_nonce: String,
    pub observer_signature_bytes: Vec<u8>,
}

/// Deterministic, domain-separated bytes signed ONLY by an independent
/// Observer owner. Producing these bytes does not mint a witness or an effect.
pub fn cell_split_control_highwater_signing_bytes_v1(
    proof: &CellSplitSignedControlHighwaterV1,
) -> Result<Vec<u8>, String> {
    let mut unsigned = proof.clone();
    unsigned.observer_signature_bytes.clear();
    let encoded = serde_json::to_vec(&unsigned).map_err(|error| error.to_string())?;
    let mut bytes = b"hepta.runtime.cell-split.control-independent-highwater.v1\0".to_vec();
    bytes.extend_from_slice(&(encoded.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&encoded);
    Ok(bytes)
}

/// Read-only diagnostic from TWO independent original storage owners.
/// The Control WAL is still orphaned: the presence of an authenticated CNS
/// record and serving child does NOT resolve B, grant Final-use, append C,
/// unlock Neuron CAS, or authorize a second physical cutover.
///
/// These fields are local evidence for a separate recovery authority, NOT
/// a signed cross-owner transaction or a production activation receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitOrphanCnsReadOnlyObservationV1 {
    pub original_pending_begin: NduPublicationPendingBeginV1,
    pub original_cns_commit: CellSplitCnsRuntimeCommitV1,
    pub signed_serving_route: CellSplitCnsLiveRouteV1,
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

    /// Read-only Control high-water qualification against an *external*
    /// independently signed and challenge-bound Observer response. The remote
    /// reader must fetch its OWN durable high-water before signing; this
    /// verifier never forwards the local original WAL frontier as input.
    ///
    /// Equality is deliberate: a stale remote minimum or rolled-back local
    /// Control state is rejected instead of accepting a digest-only prefix.
    /// The independent signer/key custody and persistent monotonic store must
    /// still be audited; this method cannot authorize physical Cell Split.
    pub fn verify_independent_control_highwater_v1<O: CellSplitIndependentControlObserverV1>(
        &mut self,
        control: &NduPublicationOwnerV1,
        observer: &mut O,
        pinned_observer_key: &VerifyingKey,
        expected_observer_id: &str,
    ) -> Result<(), String> {
        if pinned_observer_key.is_weak()
            || pinned_observer_key == &self.runtime_key
            || expected_observer_id.is_empty()
            || expected_observer_id == self.binding.cns_id
            || expected_observer_id == self.intent.owner_id
        {
            return Err("Control Observer signer is not independently pinned".into());
        }
        let original_before = control
            .read_original_local_frontier_v1()
            .map_err(|error| format!("original Control high-water unavailable: {error}"))?;
        if original_before.snapshot.snapshot_digest.to_string() != self.plan.ndu_snapshot_digest {
            return Err("Control snapshot differs from the frozen NDU plan".into());
        }

        let nonce = secure_cns_nonce()?;
        let claimed = observer
            .read_signed_highwater(
                &self.plan.split_id,
                original_before.snapshot.scope_id.as_str(),
                &nonce,
            )
            .map_err(|error| format!("independent Control high-water unavailable: {error}"))?;
        if claimed.schema != CELL_SPLIT_SIGNED_CONTROL_HIGHWATER_SCHEMA_V1
            || claimed.observer_id != expected_observer_id
            || claimed.plan_digest != self.intent.plan_digest
            || claimed.split_id != self.plan.split_id
            || claimed.scope_id != original_before.snapshot.scope_id.as_str()
            || claimed.ndu_owner_id != original_before.snapshot.owner_id.as_str()
            || claimed.ndu_snapshot_digest != self.plan.ndu_snapshot_digest
            || claimed.generation != original_before.snapshot.generation.get()
            || claimed.route_fence != original_before.snapshot.route_fence
            || claimed.revocation_epoch != original_before.snapshot.revocation_epoch
            || claimed.sequence != original_before.sequence
            || claimed.wal_head != original_before.head.to_string()
            || claimed.checkpoint_digest != original_before.checkpoint.to_string()
            || claimed.wal_bytes != original_before.wal_bytes
            || claimed.wal_device != original_before.wal_device
            || claimed.wal_inode != original_before.wal_inode
            || claimed.marker_device != original_before.marker_device
            || claimed.marker_inode != original_before.marker_inode
            || claimed.original_cns_receipt_binding
                != original_before
                    .original_cns_receipt_binding
                    .map(|value| value.to_string())
            || claimed.challenge_nonce != nonce
        {
            return Err("independent Control high-water mismatches original owner".into());
        }
        let signature = Signature::from_slice(&claimed.observer_signature_bytes)
            .map_err(|error| error.to_string())?;
        pinned_observer_key
            .verify_strict(
                &cell_split_control_highwater_signing_bytes_v1(&claimed)?,
                &signature,
            )
            .map_err(|_| "independent Control Observer signature is invalid".to_string())?;
        // An independently signed answer is not current if model checkpoint
        // CAS or Control C advanced while the remote observer was responding.
        let original_after = control
            .read_original_local_frontier_v1()
            .map_err(|error| format!("original Control recheck unavailable: {error}"))?;
        if original_before != original_after {
            return Err("Control WAL changed during independent Observer readback".into());
        }
        Ok(())
    }

    /// Read-only double-collect join across three independent facts:
    /// (1) original signed CNS runtime effect and serving successor,
    /// (2) exact original Control WAL Commit and full-history frontier,
    /// (3) separately signed and challenge-bound Control high-water.
    ///
    /// None of the individual read APIs constitutes this joined evidence.
    /// Before and after the full read sequence, replay the original locked
    /// Control WAL and reject intervening Neuron checkpoint/CNS revisions.
    /// An absent original CNS commit must fail BEFORE contacting the remote
    /// high-water Observer; remote availability cannot launder that absence.
    ///
    /// This is only bounded observational consistency, NOT cross-owner
    /// atomicity, external rollback custody, Final-use or effect authority.
    /// No physical Cell Split can be admitted through this API.
    pub fn verify_original_cns_control_independent_highwater_join_v1<
        O: CellSplitIndependentControlObserverV1,
    >(
        &mut self,
        control: &NduPublicationOwnerV1,
        observer: &mut O,
        pinned_observer_key: &VerifyingKey,
        expected_observer_id: &str,
    ) -> Result<(), String> {
        let before = control
            .read_original_local_frontier_v1()
            .map_err(|error| format!("original Control WAL unavailable before join: {error}"))?;
        // First demand a real original CNS signed effect, not a digest-only
        // Control frontier or a successful remote Observer callback.
        self.verify_original_cns_control_commit_v1(control)?;
        self.verify_independent_control_highwater_v1(
            control,
            observer,
            pinned_observer_key,
            expected_observer_id,
        )?;
        // Revalidate original CNS effect, its durable sequence and current
        // signed serving route AFTER the potentially slow external RPC.
        self.verify_original_cns_control_commit_v1(control)?;
        let after = control
            .read_original_local_frontier_v1()
            .map_err(|error| format!("original Control WAL unavailable after join: {error}"))?;
        if before != after {
            return Err("original Control WAL changed across signed CNS/Observer join".into());
        }
        Ok(())
    }

    /// Audit an unresolved ORIGINAL Control B against the current, signed CNS
    /// runtime without creating a Control C or touching a live route. The
    /// independently pinned predecessor and successor snapshots are required:
    /// a caller's arbitrary digest cannot re-identify the original Begin.
    ///
    /// An orphan B is NEVER a completion/activation receipt, even if the
    /// current CNS has an authentic matching original commit. The separate
    /// recovery owner must still resolve the fsynced Control transaction,
    /// independent rollback custody, Final-use and Supervisor fence.
    ///
    /// Recheck the same original WAL inode/bytes and original CNS revision
    /// around each potentially slow signed RPC. This bounded double-collect
    /// is NOT a distributed linearization point or an anti-rollback witness.
    pub fn inspect_orphan_control_and_signed_cns_v1(
        &mut self,
        original_control_wal: &Path,
        pinned_predecessor: &NduSnapshotRefV1,
        pinned_successor: &NduSnapshotRefV1,
        original_checkpoint: Digest32,
    ) -> Result<CellSplitOrphanCnsReadOnlyObservationV1, String> {
        pinned_predecessor
            .validate()
            .map_err(|error| format!("original predecessor snapshot invalid: {error}"))?;
        pinned_successor
            .validate()
            .map_err(|error| format!("original successor snapshot invalid: {error}"))?;
        if pinned_predecessor.snapshot_digest.to_string() != self.plan.ndu_snapshot_digest
            || pinned_predecessor.generation.get() != self.plan.parent_generation
            || pinned_successor.generation.get() != self.plan.child_generation
            || pinned_predecessor.scope_id != pinned_successor.scope_id
            || pinned_predecessor.owner_id != pinned_successor.owner_id
            || pinned_predecessor.policy_digest != pinned_successor.policy_digest
            || pinned_successor.route_fence <= pinned_predecessor.route_fence
            || pinned_successor.revocation_epoch < pinned_predecessor.revocation_epoch
        {
            return Err("orphan Control lineage is not bound to frozen split".into());
        }
        let expected_parent = pinned_predecessor
            .semantic_digest()
            .map_err(|error| format!("cannot bind predecessor: {error}"))?;
        let expected_child = pinned_successor
            .semantic_digest()
            .map_err(|error| format!("cannot bind successor: {error}"))?;
        let pending = NduPublicationOwnerV1::inspect_original_pending_begin_v1(
            original_control_wal,
            pinned_predecessor,
            original_checkpoint,
        )
        .map_err(|error| format!("original Control orphan Begin unavailable: {error}"))?;
        if pending.predecessor_semantic_digest != expected_parent
            || pending.successor_semantic_digest != expected_child
            || pending.previous_checkpoint != original_checkpoint
            || pending.migrated_checkpoint.is_zero()
        {
            return Err("original orphan Begin differs from frozen Control handoff".into());
        }

        // A missing original durable CNS record is UNKNOWN, not a negative
        // physical-effect ACK. Never replay a missing or ambiguous cutover.
        let original = self
            .witness
            .read_original_commit(&self.intent.idempotency_key)
            .map_err(|error| error.to_string())?
            .ok_or("original CNS effect is unresolved; never replay")?;
        self.verify_original_commit(&original)?;
        let first = self.signed_route(&secure_cns_nonce()?)?;
        if first.generation != self.plan.child_generation
            || first.artifact_digest != self.plan.child_artifact_digest
            || first.route_digest != self.binding.successor_route_digest
            || first.route_fence_digest != self.plan.route_fence_digest
        {
            return Err("original CNS is not serving the authenticated child".into());
        }
        let during = NduPublicationOwnerV1::inspect_original_pending_begin_v1(
            original_control_wal,
            pinned_predecessor,
            original_checkpoint,
        )
        .map_err(|error| format!("Control orphan changed after signed CNS read: {error}"))?;
        if pending != during {
            return Err("original Control orphan frontier drifted during signed CNS read".into());
        }
        self.verify_original_commit(&original)?;
        let current = self.signed_route(&secure_cns_nonce()?)?;
        if current.generation != first.generation
            || current.artifact_digest != first.artifact_digest
            || current.route_digest != first.route_digest
            || current.route_fence_digest != first.route_fence_digest
            || current.authority_epoch != first.authority_epoch
        {
            return Err("CNS serving child changed between signed observations".into());
        }
        let final_control = NduPublicationOwnerV1::inspect_original_pending_begin_v1(
            original_control_wal,
            pinned_predecessor,
            original_checkpoint,
        )
        .map_err(|error| format!("Control orphan changed during final readback: {error}"))?;
        if final_control != pending {
            return Err("original Control orphan changed during final CNS verification".into());
        }
        Ok(CellSplitOrphanCnsReadOnlyObservationV1 {
            original_pending_begin: pending,
            original_cns_commit: original,
            signed_serving_route: current,
        })
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
        // A non-test serving build has no original same-owner Control
        // Begin -> physical CNS effect -> Control Commit capability. Merely
        // populating atomic_control_cutover_owner in a future constructor
        // cannot enable this dangerous path without a separately reviewed
        // product transaction. Deny before preflight, Final-use or dispatch.
        if !cfg!(test) {
            return Err(
                "CNS mutation denied: original same-owner Control B/effect/C is not production-composed"
                    .into(),
            );
        }
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
        // Read-only direct callers require the same current revision as the
        // durable CNS effect adapter. A valid old signature and unchanged
        // route digest cannot hide an intervening CNS WAL revision / ABA.
        if frontier != commit.committed_sequence {
            return Err("signed CNS receipt is not the current durable frontier".into());
        }
        // Original commit bytes and the independently durable CNS revision
        // must survive a second read: the first valid signed response is not
        // a linearizable snapshot if the writer advances during the RPC.
        let repeated = self
            .witness
            .read_original_commit(&self.intent.idempotency_key)
            .map_err(|e| e.to_string())?;
        let final_frontier = self
            .witness
            .current_durable_sequence(&self.binding.cns_id)
            .map_err(|e| e.to_string())?;
        if repeated.as_ref() != Some(commit) || final_frontier != frontier {
            return Err("original CNS commitment changed during signed readback".into());
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

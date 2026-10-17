//! Signed Cell Split CNS cutover boundary backed by the *live* runtime owner.
//!
//! Unlike a local route-file toggle, this module requires the existing CNS
//! runtime to return its original durable cutover receipt and a fresh,
//! authenticated observation of the currently serving route. An operator
//! cannot manufacture either from a digest. No production CNS port is supplied
//! here: the deployment must implement it using the current authoritative
//! runtime route writer, independent NDU/Selector, and writer-fence owner.
//!
//! The ordering constraint is critical. The predecessor writer must already
//! be admission-closed and drained/fenced *before* CNS route publication;
//! the subsequent Supervisor step is final generation confirmation, not the
//! first time the old writer is fenced.

use std::fs;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

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

const FROZEN: &str = "cell-split-cns-frozen.json";
const RECEIPT_MAX_BYTES: usize = 64 * 1024;
const MAX_RUNTIME_PROOF: usize = 24 * 1024;

/// Immutable routing identity sourced from the admitted runtime successor.
/// Both topology route digests must identify real, independently registered
/// routes. The new route fence binds the original CellSplit execution plan.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitCnsRouteBindingV1 {
    pub cns_id: String,
    pub predecessor_route_digest: String,
    pub successor_route_digest: String,
    pub authority_epoch: u64,
}

/// Fresh, independently authenticated state of the actual serving CNS route.
/// The runtime-provided proof is not an optional sidecar and may vary on each
/// read. The port must verify its origin, timestamp and generation/epoch.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitCnsLiveRouteV1 {
    pub cns_id: String,
    pub scope_digest: String,
    pub generation: u64,
    pub artifact_digest: String,
    pub route_digest: String,
    pub route_fence_digest: String,
    pub authority_epoch: u64,
    pub old_writer_fenced: bool,
    pub unknown_effect_count: u32,
    pub challenge_nonce: String,
    pub live_runtime_proof_bytes: Vec<u8>,
}

/// Original durable cutover acknowledgement retained by the canonical
/// runtime owner, not synthesized by this adapter or a client-side cache.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitCnsRuntimeCommitV1 {
    pub idempotency_key: String,
    pub cns_id: String,
    pub predecessor_route_digest: String,
    pub successor_route_digest: String,
    pub predecessor_generation: u64,
    pub successor_generation: u64,
    pub authority_epoch: u64,
    pub committed_sequence: u64,
    pub original_runtime_receipt_bytes: Vec<u8>,
    pub original_runtime_signature_bytes: Vec<u8>,
}

/// Runtime-origin proof with every security-critical field bound directly
/// inside the bytes signed by the independent CNS runtime key. A valid
/// signature on unrelated opaque bytes is NOT evidence of this cutover.
pub const CELL_SPLIT_CNS_RUNTIME_ATTESTATION_SCHEMA_V1: &str =
    "hepta.learning.cell-split.cns-runtime-attestation.v1";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitCnsRuntimeAttestationV1 {
    pub schema: String,
    pub idempotency_key: String,
    pub cns_id: String,
    pub scope_digest: String,
    pub predecessor_route_digest: String,
    pub successor_route_digest: String,
    pub predecessor_generation: u64,
    pub successor_generation: u64,
    pub predecessor_artifact_digest: String,
    pub successor_artifact_digest: String,
    pub route_fence_digest: String,
    pub authority_epoch: u64,
    pub committed_sequence: u64,
}

impl CellSplitCnsRuntimeAttestationV1 {
    /// Canonical projection for the actual CNS runtime to sign after it has
    /// durably committed the route. This constructor grants no authority.
    pub fn for_commit(
        plan: &CellSplitExecutionPlanV1,
        commit: &CellSplitCnsRuntimeCommitV1,
    ) -> Self {
        Self {
            schema: CELL_SPLIT_CNS_RUNTIME_ATTESTATION_SCHEMA_V1.into(),
            idempotency_key: commit.idempotency_key.clone(),
            cns_id: commit.cns_id.clone(),
            scope_digest: plan.scope_digest.clone(),
            predecessor_route_digest: commit.predecessor_route_digest.clone(),
            successor_route_digest: commit.successor_route_digest.clone(),
            predecessor_generation: commit.predecessor_generation,
            successor_generation: commit.successor_generation,
            predecessor_artifact_digest: plan.parent_artifact_digest.clone(),
            successor_artifact_digest: plan.child_artifact_digest.clone(),
            route_fence_digest: plan.route_fence_digest.clone(),
            authority_epoch: commit.authority_epoch,
            committed_sequence: commit.committed_sequence,
        }
    }

    /// Produce the same sorted-key canonical encoding required by the
    /// durable owner. Ordinary serde_json struct serialization preserves
    /// declaration order and is NOT necessarily canonical.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, &'static str> {
        canonical_json(self).map_err(|_| "cannot canonicalize CNS runtime attestation")
    }

    /// Check signed inner bytes and typed outer claims against the exact
    /// frozen plan. The caller MUST additionally verify the original runtime
    /// signature against a separately pinned key and inspect the live CNS.
    pub fn verify_original_bytes(
        plan: &CellSplitExecutionPlanV1,
        commit: &CellSplitCnsRuntimeCommitV1,
    ) -> Result<(), &'static str> {
        let attested: Self = serde_json::from_slice(&commit.original_runtime_receipt_bytes)
            .map_err(|_| "original CNS runtime attestation is not typed JSON")?;
        if attested != Self::for_commit(plan, commit)
            || attested.canonical_bytes()? != commit.original_runtime_receipt_bytes
            || commit.predecessor_generation != plan.parent_generation
            || commit.successor_generation != plan.child_generation
            || commit.committed_sequence == 0
        {
            return Err("signed CNS runtime bytes do not bind the exact cutover");
        }
        Ok(())
    }
}

/// Implementations MUST issue a real CNS runtime cutover using exact
/// generation/fence-bound authority, durably retain its original operation
/// receipt, and inspect the *serving* route on readback. Neither a local
/// digest record nor a route file unobserved by dispatch is acceptable.
///
/// verify_preconditions must independently reread the signed migration batch,
/// signed final-use permission, and the old-writer drain/fence evidence.
/// verify_live must authenticate the fresh observation and must not accept a
/// copied prior snapshot as current.
pub trait CellSplitCnsRuntimePortV1 {
    type Error: std::fmt::Display;

    fn verify_preconditions(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error>;

    fn inspect_live(
        &mut self,
        cns_id: &str,
        scope_digest: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitCnsLiveRouteV1, Self::Error>;

    fn verify_live(&mut self, observation: &CellSplitCnsLiveRouteV1) -> Result<(), Self::Error>;

    fn publish_once(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        binding: &CellSplitCnsRouteBindingV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error>;

    fn read_original_commit(
        &mut self,
        idempotency_key: &str,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, Self::Error>;

    fn verify_original_commit(
        &mut self,
        commit: &CellSplitCnsRuntimeCommitV1,
    ) -> Result<(), Self::Error>;

    /// Durable runtime-owner sequence, never a locally guessed generation.
    fn committed_sequence(&mut self, cns_id: &str) -> Result<u64, Self::Error>;
}

#[derive(Debug, Error)]
pub enum CellSplitCnsCutoverErrorV1 {
    #[error("CNS owner rejected frozen identity or live route")]
    Invalid,
    #[error("CNS authority, signed owner, or live runtime unavailable: {0}")]
    External(String),
    #[error("CNS route changed without a matching original durable cutover receipt")]
    Ambiguous,
    #[error(transparent)]
    Durable(#[from] crate::AcceptanceError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

/// One locked frozen route transition. The remote runtime remains the sole
/// effect owner; this adapter never stores a positive effect in place of the
/// runtime's original authenticated commit receipt.
pub struct CellSplitCnsCutoverOwnerV1<P: CellSplitCnsRuntimePortV1> {
    root: PathBuf,
    plan: CellSplitExecutionPlanV1,
    plan_digest: String,
    binding: CellSplitCnsRouteBindingV1,
    port: P,
    _lock: SidecarLock,
}

impl<P: CellSplitCnsRuntimePortV1> CellSplitCnsCutoverOwnerV1<P> {
    pub fn open(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        binding: CellSplitCnsRouteBindingV1,
        port: P,
    ) -> Result<Self, CellSplitCnsCutoverErrorV1> {
        // Require the coordinator's complete frozen-plan contract even when
        // this effect owner is opened independently of Agentd.
        let plan_digest = plan
            .digest()
            .map_err(|_| CellSplitCnsCutoverErrorV1::Invalid)?;
        if binding.cns_id.is_empty()
            || binding.cns_id.len() > 256
            || !digest_shape(&plan.scope_digest)
            || !digest_shape(&plan.parent_artifact_digest)
            || !digest_shape(&plan.child_artifact_digest)
            || !digest_shape(&plan.route_fence_digest)
            || !digest_shape(&binding.predecessor_route_digest)
            || !digest_shape(&binding.successor_route_digest)
            || binding.predecessor_route_digest == binding.successor_route_digest
            || binding.authority_epoch == 0
            || plan.parent_generation == 0
            || plan.parent_generation.checked_add(1) != Some(plan.child_generation)
            || plan.owner_ids[2].is_empty()
        {
            return Err(CellSplitCnsCutoverErrorV1::Invalid);
        }
        let root = secure_root(root, "CNS cutover owner root")?;
        // The lock inode outlives an owner instance. If it already exists,
        // losing the frozen binding is an ambiguous interrupted lifecycle:
        // a fresh observation of the old route cannot prove that the caller
        // supplied the same plan and independent owner trust as before.
        let initialized_before = match fs::symlink_metadata(root.join(SIDECAR_LOCK_FILE)) {
            Ok(_) => true,
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        reject_recreated_sidecar_for_owner_history(
            &root,
            initialized_before,
            &[FROZEN],
            &["cell-split-cns-"],
        )?;
        let lock = lock_sidecar(&root)?;
        reject_recreated_sidecar_for_owner_history(
            &root,
            initialized_before,
            &[FROZEN],
            &["cell-split-cns-"],
        )?;
        let frozen = canonical_json(&(plan.clone(), binding.clone()))?;
        let frozen_path = root.join(FROZEN);
        let mut owner = Self {
            root,
            plan,
            plan_digest,
            binding,
            port,
            _lock: lock,
        };
        match fs::symlink_metadata(&frozen_path) {
            Ok(_) if secure_read(&frozen_path, RECEIPT_MAX_BYTES)? != frozen => {
                return Err(CellSplitCnsCutoverErrorV1::Invalid);
            }
            Ok(_) => {}
            Err(error) if error.kind() == ErrorKind::NotFound => {
                // Refuse any re-initialization after the durable lock first
                // existed, including before a cutover or after a lost ack.
                // Recovery must reconcile against the original independent
                // owner; never silently supply a replacement frozen plan.
                if initialized_before {
                    return Err(CellSplitCnsCutoverErrorV1::Invalid);
                }
                // Losing the local frozen binding after a real cutover must
                // not allow an attacker (or stale caller) to reinitialize the
                // owner under a new routing plan. Require a fresh nonce-bound
                // signed observation of the *predecessor* serving route.
                // An unavailable runtime, already-selected child or unknown
                // effect stays fail closed without recreating local evidence.
                let live = owner.checked_live()?;
                if !owner.is_parent(&live) {
                    return Err(CellSplitCnsCutoverErrorV1::Invalid);
                }
                write_private_new(&frozen_path, &frozen)?;
            }
            Err(error) => return Err(error.into()),
        }
        Ok(owner)
    }

    fn check_intent(
        &self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), CellSplitCnsCutoverErrorV1> {
        let expected_key = sha256(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                self.plan_digest,
                CellSplitExecutionStepV1::CnsRouteCutover.index(),
                intent.previous_receipt_digest,
            )
            .as_bytes(),
        );
        if intent.schema != "hepta.learning.cell-split.execution-owner.v1"
            || intent.step != CellSplitExecutionStepV1::CnsRouteCutover
            || intent.owner_id != self.plan.owner_ids[2]
            || intent.plan_digest != self.plan_digest
            || !digest_shape(&intent.previous_receipt_digest)
            || !digest_shape(&intent.idempotency_key)
            || intent.idempotency_key != expected_key
            || secure_read(&self.root.join(FROZEN), RECEIPT_MAX_BYTES)?
                != canonical_json(&(self.plan.clone(), self.binding.clone()))?
        {
            return Err(CellSplitCnsCutoverErrorV1::Invalid);
        }
        Ok(())
    }

    fn checked_live(&mut self) -> Result<CellSplitCnsLiveRouteV1, CellSplitCnsCutoverErrorV1> {
        let nonce = rand::random::<[u8; 32]>()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let live = self
            .port
            .inspect_live(&self.binding.cns_id, &self.plan.scope_digest, &nonce)
            .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
        if live.cns_id != self.binding.cns_id
            || live.scope_digest != self.plan.scope_digest
            || live.authority_epoch != self.binding.authority_epoch
            || live.challenge_nonce != nonce
            || live.unknown_effect_count != 0
            || !live.old_writer_fenced
            || live.live_runtime_proof_bytes.is_empty()
            || live.live_runtime_proof_bytes.len() > MAX_RUNTIME_PROOF
        {
            return Err(CellSplitCnsCutoverErrorV1::Invalid);
        }
        self.port
            .verify_live(&live)
            .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
        Ok(live)
    }

    fn is_parent(&self, live: &CellSplitCnsLiveRouteV1) -> bool {
        live.generation == self.plan.parent_generation
            && live.artifact_digest == self.plan.parent_artifact_digest
            && live.route_digest == self.binding.predecessor_route_digest
    }

    fn is_child(&self, live: &CellSplitCnsLiveRouteV1) -> bool {
        live.generation == self.plan.child_generation
            && live.artifact_digest == self.plan.child_artifact_digest
            && live.route_digest == self.binding.successor_route_digest
            && live.route_fence_digest == self.plan.route_fence_digest
    }

    fn checked_original(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, CellSplitCnsCutoverErrorV1> {
        let result = self
            .port
            .read_original_commit(&intent.idempotency_key)
            .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
        if let Some(ref record) = result {
            if record.idempotency_key != intent.idempotency_key
                || record.cns_id != self.binding.cns_id
                || record.predecessor_route_digest != self.binding.predecessor_route_digest
                || record.successor_route_digest != self.binding.successor_route_digest
                || record.predecessor_generation != self.plan.parent_generation
                || record.successor_generation != self.plan.child_generation
                || record.authority_epoch != self.binding.authority_epoch
                || record.committed_sequence == 0
                || record.original_runtime_receipt_bytes.is_empty()
                || record.original_runtime_receipt_bytes.len() > MAX_RUNTIME_PROOF
                || record.original_runtime_signature_bytes.len() != 64
            {
                return Err(CellSplitCnsCutoverErrorV1::Invalid);
            }
            // An independently signed but unrelated runtime message must
            // never be laundered by the outer CNS effect-owner envelope.
            CellSplitCnsRuntimeAttestationV1::verify_original_bytes(&self.plan, record)
                .map_err(|_| CellSplitCnsCutoverErrorV1::Invalid)?;
            self.port
                .verify_original_commit(record)
                .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
            // Direct backend consumers must get the same anti-rollback check
            // as the outer RPC service. A valid old signature cannot prove
            // a committed cutover if the CNS durable frontier has regressed.
            let current_sequence = self
                .port
                .committed_sequence(&self.binding.cns_id)
                .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
            // A later CNS journal revision is not evidence that this older
            // signed cutover remains the currently committed route. Even
            // when the serving route's digest happens to match again, an
            // advanced frontier may conceal rollback / ABA replacement.
            // Demand the exact original runtime commitment revision.
            if current_sequence != record.committed_sequence {
                return Err(CellSplitCnsCutoverErrorV1::Invalid);
            }
        }
        Ok(result)
    }

    fn verified_effect(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, CellSplitCnsCutoverErrorV1> {
        self.check_intent(intent)?;
        self.port
            .verify_preconditions(&self.plan, intent)
            .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
        let original = self.checked_original(intent)?;
        let live = self.checked_live()?;
        match original {
            Some(record) if self.is_child(&live) => Ok(Some(CellSplitOwnedEffectV1 {
                owner_sequence: record.committed_sequence,
                owner_receipt_bytes: canonical_json(&record)?,
            })),
            Some(_) => Err(CellSplitCnsCutoverErrorV1::Invalid),
            None if self.is_parent(&live) => Ok(None),
            None => Err(CellSplitCnsCutoverErrorV1::Ambiguous),
        }
    }
}

impl<P: CellSplitCnsRuntimePortV1> CellSplitDurableEffectBackendV1
    for CellSplitCnsCutoverOwnerV1<P>
{
    type Error = CellSplitCnsCutoverErrorV1;

    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        let _ = self.verified_effect(intent)?;
        Ok(())
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        if self.verified_effect(intent)?.is_some() {
            // Current state may belong to another racing writer. Do not
            // acknowledge a fresh Execute for an already published route.
            return Err(CellSplitCnsCutoverErrorV1::Ambiguous);
        }
        // The authoritative CNS port must use its own durable one-shot
        // final-use guard. A lost acknowledgement cannot cause a second
        // runtime generation replacement in this adapter.
        self.port
            .publish_once(&self.plan, &self.binding, intent)
            .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
        if self.verified_effect(intent)?.is_none() {
            return Err(CellSplitCnsCutoverErrorV1::Ambiguous);
        }
        Ok(())
    }

    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        self.verified_effect(intent)
    }

    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        Ok(self.verified_effect(intent)?.as_ref() == Some(effect))
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        self.checked_live()?;
        let sequence = self
            .port
            .committed_sequence(&self.binding.cns_id)
            .map_err(|e| CellSplitCnsCutoverErrorV1::External(e.to_string()))?;
        if sequence == 0 {
            return Err(CellSplitCnsCutoverErrorV1::Invalid);
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
#[path = "cell_split_cns_cutover_tests.rs"]
mod tests;

//! Bounded read-mostly AMCN epoch experiment. Feature-gated, DENY ALL.
//!
//! A full SQLite CognitiveRecoveryAnchor or append-only Artifact ledger can take
//! O(corpus/chain) work to revalidate. This index is an *observation cache*
//! with O(1) steady-state header comparisons and hash-set quarantine lookup.
//! It is not a source of authority and cannot authenticate an owner-supplied
//! epoch or external witness. A real Source/Artifacts/Runtime host MUST retain
//! independently signed CURRENT floors and serialize every mutation with this
//! read lock; otherwise the cache can serve stale or rolled-back data.
//!
//! The feature never installs into the default product Neuron Runtime.

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};

use codex_hepta_types::{Digest32, Generation, StableId};

use crate::{
    AmcnFencedModelBindingV1, AmcnSourceArtifactFence, NeuronModelError, NeuronModelRequestV1,
};

pub const AMCN_EPOCH_SHADOW_PRODUCTION_ACCEPTED: bool = false;
pub const AMCN_EPOCH_QUARANTINE_LIMIT: usize = 16_384;
pub const AMCN_EPOCH_MANIFEST_LIMIT: usize = 65_536;
const ENROLLED_DOMAIN: &[u8] = b"hepta.amcn.epoch.enrolled-manifests.v1";
const QUARANTINED_DOMAIN: &[u8] = b"hepta.amcn.epoch.quarantined-manifests.v1";

/// Canonical, count-framed and order-independent COMPLETE set commitment.
/// This is recomputed only on enrollment or owner updates, never per inference.
/// Stop adversarial iterators at their FIRST out-of-budget element. A late
/// length check after collect() can allocate unbounded memory before refusal.
fn bounded_manifest_set(
    values: impl IntoIterator<Item = Digest32>,
    maximum: usize,
) -> Result<HashSet<Digest32>, NeuronModelError> {
    let mut result = HashSet::new();
    for value in values {
        if result.len() >= maximum || value.is_zero() || !result.insert(value) {
            return Err(NeuronModelError::Rejected);
        }
    }
    Ok(result)
}

fn digest_manifest_set(domain: &[u8], members: &HashSet<Digest32>) -> Digest32 {
    let mut sorted: Vec<_> = members.iter().copied().collect();
    sorted.sort_unstable();
    let mut bytes = Vec::with_capacity(domain.len() + 8 + sorted.len() * 32);
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&(sorted.len() as u64).to_be_bytes());
    for digest in sorted {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

/// Small immutable witness needed by every candidate. This is not a signature.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AmcnEpochHeaderV1 {
    pub scope: StableId,
    pub generation: Generation,
    pub sequence: u64,
    pub source_epoch: u64,
    pub withdrawal_epoch: u64,
    pub artifacts_epoch: u64,
    pub source_frontier_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub quarantine_head_digest: Digest32,
    /// Commit the COMPLETE enrolled and quarantine populations to this epoch.
    /// Without these fields, a legitimate signed header could be paired with
    /// a forged restored index omitting one revoked Cell, resurrecting it.
    pub enrolled_manifest_set_digest: Digest32,
    pub quarantined_manifest_set_digest: Digest32,
    pub runtime_anchor_digest: Digest32,
    pub event_digest: Digest32,
    pub predecessor_event_digest: Digest32,
}

impl AmcnEpochHeaderV1 {
    fn validate(&self) -> Result<(), NeuronModelError> {
        if self.sequence == 0 || self.source_epoch == 0
            || self.withdrawal_epoch == 0 || self.artifacts_epoch == 0
            || (self.sequence > 1 && self.predecessor_event_digest.is_zero())
            || [
                self.source_frontier_digest,
                self.withdrawal_head_digest,
                self.quarantine_head_digest,
                self.enrolled_manifest_set_digest,
                self.quarantined_manifest_set_digest,
                self.runtime_anchor_digest,
                self.event_digest,
            ].iter().any(|x| x.is_zero())
        {
            return Err(NeuronModelError::Rejected);
        }
        Ok(())
    }

    fn same_owner_binding(
        &self,
        binding: &AmcnFencedModelBindingV1,
    ) -> bool {
        self.scope == binding.scope && self.generation == binding.generation
            && self.source_frontier_digest == binding.source_frontier_digest
            && self.withdrawal_head_digest == binding.withdrawal_registry_head_digest
            && self.quarantine_head_digest == binding.quarantine_journal_head_digest
            && self.runtime_anchor_digest == binding.runtime_anchor_digest
    }
}

/// One cache owned by an ALREADY trusted upstream caller. A caller-created
/// snapshot is never itself an independently witnessed or production grant.
struct CurrentEpoch {
    header: AmcnEpochHeaderV1,
    enrolled_manifests: HashSet<Digest32>,
    quarantined_manifests: HashSet<Digest32>,
}

/// The only mutation method requires compare-and-swap and monotonic successor
/// information while holding the same lock as every candidate execution.
/// Its caller MUST first authorize and persist the original Source/Artifact
/// transition through their real owners. This type does neither.
#[derive(Clone)]
pub struct AmcnShadowEpochIndex {
    state: Arc<RwLock<CurrentEpoch>>,
    pending_owner_change: Arc<AtomicBool>,
}

impl AmcnShadowEpochIndex {
    /// The floor MUST be retained by an INDEPENDENT authoritative owner.
    /// Exact equality on startup prevents a locally restored, stale snapshot
    /// from being treated as current when the independent floor has advanced.
    /// Both arguments are still unauthenticated inputs to this research API.
    pub fn from_external_floor(
        current: AmcnEpochHeaderV1,
        minimum_current: &AmcnEpochHeaderV1,
        enrolled: impl IntoIterator<Item = Digest32>,
        quarantined: impl IntoIterator<Item = Digest32>,
    ) -> Result<Self, NeuronModelError> {
        current.validate()?;
        if &current != minimum_current {
            return Err(NeuronModelError::Rejected);
        }
        let enrolled = bounded_manifest_set(enrolled, AMCN_EPOCH_MANIFEST_LIMIT)?;
        let blocked = bounded_manifest_set(quarantined, AMCN_EPOCH_QUARANTINE_LIMIT)?;
        if enrolled.is_empty() || !blocked.is_subset(&enrolled)
            || current.enrolled_manifest_set_digest
                != digest_manifest_set(ENROLLED_DOMAIN, &enrolled)
            || current.quarantined_manifest_set_digest
                != digest_manifest_set(QUARANTINED_DOMAIN, &blocked)
        {
            return Err(NeuronModelError::Rejected);
        }
        Ok(Self {
            state: Arc::new(RwLock::new(CurrentEpoch {
                header: current,
                enrolled_manifests: enrolled,
                quarantined_manifests: blocked,
            })),
            pending_owner_change: Arc::new(AtomicBool::new(false)),
        })
    }

    /// Prefer the ORIGINAL signed Artifact current-view projection over a
    /// caller-assembled list of Cell candidates. The projection type is
    /// opaque outside Learning Artifacts and only produced from a verified
    /// current registry view. Expected pins remain independent host inputs.
    ///
    /// Source revisions, V2 withdrawal datasets, actual selection and the
    /// Runtime Witness still have SEPARATE owners; this is research ONLY.
    #[cfg(feature = "amcn-artifact-owner-shadow")]
    pub fn from_verified_artifact_owner_view(
        current: AmcnEpochHeaderV1,
        independently_witnessed_floor: &AmcnEpochHeaderV1,
        population: &codex_hepta_learning_artifacts::AmcnVerifiedRegistryEpochPopulationV1,
        expected_registry_head: Digest32,
        expected_registry_witness: Digest32,
        expected_registry_trust: Digest32,
    ) -> Result<Self, NeuronModelError> {
        if population.production_accepted()
            || population.authority().grants_any()
            || expected_registry_head.is_zero()
            || expected_registry_witness.is_zero()
            || expected_registry_trust.is_zero()
            || population.current_registry_head_digest() != expected_registry_head
            || population.current_witness_digest() != expected_registry_witness
            || population.current_trust_digest() != expected_registry_trust
            || population.enrolled_manifest_set_digest()
                != current.enrolled_manifest_set_digest
            || population.quarantined_manifest_set_digest()
                != current.quarantined_manifest_set_digest
        {
            return Err(NeuronModelError::Rejected);
        }
        Self::from_external_floor(
            current,
            independently_witnessed_floor,
            population.enrolled_model_and_head_manifests()
                .iter().map(|(_, digest)| *digest),
            population.quarantined_model_and_head_manifest_digests()
                .iter().copied(),
        )
    }

    /// Exact O(1) current header read, not a claim that this was signed.
    pub fn header(&self) -> Result<AmcnEpochHeaderV1, NeuronModelError> {
        // Fast refusal BEFORE joining a queued writer behind long-lived
        // in-flight Cell readers. This is a contention/latency bound, not
        // cross-process owner authentication.
        if self.pending_owner_change.load(Ordering::Acquire) {
            return Err(NeuronModelError::Indeterminate);
        }
        let guard = self.state.read().map_err(|_| NeuronModelError::Indeterminate)?;
        if self.pending_owner_change.load(Ordering::Acquire) {
            return Err(NeuronModelError::Indeterminate);
        }
        Ok(guard.header.clone())
    }

    /// True while the source owner is waiting for active Cells to finish.
    /// This is observable mechanism state, not proof of an authenticated owner.
    pub fn owner_change_pending(&self) -> bool {
        self.pending_owner_change.load(Ordering::Acquire)
    }

    /// Research replay of an externally authenticated and DURABLY written
    /// owner transition. Never silently reduce epochs or lift quarantine.
    /// This function itself does not persist/source-sign that external event.
    pub fn observe_committed_owner_change(
        &self,
        expected: &AmcnEpochHeaderV1,
        next: AmcnEpochHeaderV1,
        newly_enrolled: impl IntoIterator<Item = Digest32>,
        additional_quarantined: impl IntoIterator<Item = Digest32>,
    ) -> Result<(), NeuronModelError> {
        // Set pending BEFORE waiting on the RwLock writer. This prevents a
        // high-volume reader stream from starving an already requested
        // withdrawal. Even if validation fails, this index remains fenced
        // until an independent-current-floor rebootstrap; no silent rollback
        // or clearance of adverse source-change evidence is permitted.
        if self.pending_owner_change.compare_exchange(
            false, true, Ordering::AcqRel, Ordering::Acquire,
        ).is_err() {
            return Err(NeuronModelError::Indeterminate);
        }
        next.validate()?;
        let mut guard = self.state.write().map_err(|_| NeuronModelError::Indeterminate)?;
        let old = &guard.header;
        if old != expected || next.scope != old.scope
            || next.generation != old.generation
            || old.sequence.checked_add(1) != Some(next.sequence)
            || next.source_epoch < old.source_epoch
            || next.withdrawal_epoch < old.withdrawal_epoch
            || next.artifacts_epoch < old.artifacts_epoch
            || next.predecessor_event_digest != old.event_digest
            || next.event_digest == old.event_digest
            || !epoch_head_consistent(
                old.source_epoch, next.source_epoch,
                old.source_frontier_digest, next.source_frontier_digest,
            )
            || !epoch_head_consistent(
                old.withdrawal_epoch, next.withdrawal_epoch,
                old.withdrawal_head_digest, next.withdrawal_head_digest,
            )
            || !epoch_head_consistent(
                old.artifacts_epoch, next.artifacts_epoch,
                old.quarantine_head_digest, next.quarantine_head_digest,
            )
        {
            return Err(NeuronModelError::Rejected);
        }
        let enrolled = bounded_manifest_set(newly_enrolled, AMCN_EPOCH_MANIFEST_LIMIT)?;
        let additional = bounded_manifest_set(
            additional_quarantined, AMCN_EPOCH_QUARANTINE_LIMIT,
        )?;
        let total_enrolled = guard.enrolled_manifests.len().saturating_add(enrolled.len());
        let total_blocked = guard.quarantined_manifests.len().saturating_add(additional.len());
        if enrolled.contains(&Digest32::ZERO)
            || additional.contains(&Digest32::ZERO)
            || total_enrolled > AMCN_EPOCH_MANIFEST_LIMIT
            || total_blocked > AMCN_EPOCH_QUARANTINE_LIMIT
            || !enrolled.is_disjoint(&guard.enrolled_manifests)
            || !additional.iter().all(|id| guard.enrolled_manifests.contains(id)
                                      || enrolled.contains(id))
            || (!enrolled.is_empty() || !additional.is_empty())
                && next.artifacts_epoch == old.artifacts_epoch
        {
            return Err(NeuronModelError::Rejected);
        }
        let mut next_enrolled = guard.enrolled_manifests.clone();
        next_enrolled.extend(enrolled);
        let mut next_quarantined = guard.quarantined_manifests.clone();
        next_quarantined.extend(additional);
        // Verify EVERY returned set element is committed to the CURRENT
        // header, not just the quarantine log head or a caller's asserted
        // total. This prevents an exact-header cold restore from omitting
        // a previously withdrawn Head while preserving O(1) hot reads.
        if next.enrolled_manifest_set_digest
                != digest_manifest_set(ENROLLED_DOMAIN, &next_enrolled)
            || next.quarantined_manifest_set_digest
                != digest_manifest_set(QUARANTINED_DOMAIN, &next_quarantined)
        {
            return Err(NeuronModelError::Rejected);
        }
        guard.enrolled_manifests = next_enrolled;
        guard.quarantined_manifests = next_quarantined;
        guard.header = next;
        self.pending_owner_change.store(false, Ordering::Release);
        Ok(())
    }

    /// Bind one small Cell access to a specific previously grounded version.
    /// Read lease stays held during the full inference or whole-tick callback.
    pub fn candidate_fence(&self, header: AmcnEpochHeaderV1) -> AmcnShadowEpochFence {
        AmcnShadowEpochFence { index: self.clone(), expected: header }
    }
}

fn epoch_head_consistent(old_epoch: u64, next_epoch: u64, old: Digest32, next: Digest32) -> bool {
    (old_epoch == next_epoch) == (old == next)
}

/// Feature-only implementation of the original Neuron source-fence contract.
/// The read lock alone is NOT a cross-process source/withdrawal owner lease.
pub struct AmcnShadowEpochFence {
    index: AmcnShadowEpochIndex,
    expected: AmcnEpochHeaderV1,
}

impl AmcnSourceArtifactFence for AmcnShadowEpochFence {
    fn with_fenced_candidate<T, E>(
        &mut self,
        binding: &AmcnFencedModelBindingV1,
        request: &NeuronModelRequestV1,
        action: impl FnOnce() -> Result<T, E>,
    ) -> Result<T, E>
    where
        E: From<NeuronModelError>,
    {
        binding.validate_request(request).map_err(E::from)?;
        // The writer announces revocation BEFORE attempting to acquire the
        // exclusive lock. Do not make new readers queue while an earlier model
        // owns the read side: refuse in bounded time even while it is running.
        if self.index.pending_owner_change.load(Ordering::Acquire) {
            return Err(E::from(NeuronModelError::Rejected));
        }
        let current = self.index.state.read()
            .map_err(|_| E::from(NeuronModelError::Indeterminate))?;
        // Recheck AFTER lock acquisition to close the announce/acquire race.
        if self.index.pending_owner_change.load(Ordering::Acquire) {
            return Err(E::from(NeuronModelError::Rejected));
        }
        if current.header != self.expected
            || !current.header.same_owner_binding(binding)
            || !current.enrolled_manifests.contains(&binding.artifact_manifest_digest)
            || current.quarantined_manifests.contains(&binding.artifact_manifest_digest)
        {
            return Err(E::from(NeuronModelError::Rejected));
        }
        // Guard is intentionally alive throughout the complete real callback;
        // an owner mutation on this in-process index must wait to obtain its
        // exclusive write lock until this invocation returns.
        let result = action();
        drop(current);
        result
    }
}

#[cfg(test)]
#[path = "amcn_shadow_epoch_tests.rs"]
mod tests;

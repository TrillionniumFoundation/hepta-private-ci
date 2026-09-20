//! Concrete owner-evidence adapters for governed Agentd plasticity.
//!
//! This layer deliberately resolves only facts that already have authoritative
//! repository stores: DatasetSnapshotReceiptV3 against the current DurableLedger
//! frontier, and immutable Policy artifacts against the current ArtifactRegistry
//! frontier. Dynamic modulator/eligibility/signal facts are delegated to a
//! mandatory owner adapter rather than being reclassified as artifacts.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, RwLock};

use codex_hepta_learning_artifacts::{ArtifactKind, ArtifactManifest, ArtifactRegistry};
use codex_hepta_learning_ledger::{DatasetSnapshotReceiptV3, verify_dataset_snapshot_receipt_v3};
use codex_hepta_ndu::NduProjectionJournalV1;
use codex_hepta_neuron::{JournalAnchor, SparseCheckpoint, SparseJournal};
use codex_hepta_types::{Digest32, FixedQ32, StableId};

use crate::{
    PlasticityOwnerEvidenceErrorV1, PlasticityOwnerEvidenceKindV1, PlasticityOwnerEvidenceQueryV1,
    PlasticityOwnerEvidenceResolverV1, VerifiedPlasticityOwnerEvidenceV1,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityArtifactOwnerBindingV1 {
    pub kind: PlasticityOwnerEvidenceKindV1,
    pub artifact_id: StableId,
}

/// Resolver that closes the owner boundary for durable dataset and immutable
/// policy artifacts, while requiring another real owner for dynamic signals.
pub struct ConcretePlasticityOwnerEvidenceResolverV1 {
    dataset: DatasetSnapshotReceiptV3,
    artifacts: ArtifactRegistry,
    artifact_observed_at: u64,
    artifact_expires_at: u64,
    artifact_bindings: BTreeMap<PlasticityOwnerEvidenceKindV1, StableId>,
    dynamic: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
}

impl ConcretePlasticityOwnerEvidenceResolverV1 {
    pub fn new(
        dataset: DatasetSnapshotReceiptV3,
        artifacts: ArtifactRegistry,
        artifact_observed_at: u64,
        artifact_expires_at: u64,
        bindings: Vec<PlasticityArtifactOwnerBindingV1>,
        dynamic: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    ) -> Result<Self, PlasticityOwnerEvidenceErrorV1> {
        if artifact_observed_at > artifact_expires_at {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
        }
        let mut artifact_bindings = BTreeMap::new();
        for binding in bindings {
            if !matches!(
                binding.kind,
                PlasticityOwnerEvidenceKindV1::UpdateRule
                    | PlasticityOwnerEvidenceKindV1::MutationPolicy
            ) {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
            if artifact_bindings
                .insert(binding.kind, binding.artifact_id)
                .is_some()
            {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
        for required in [
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            PlasticityOwnerEvidenceKindV1::MutationPolicy,
        ] {
            if !artifact_bindings.contains_key(&required) {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
        Ok(Self {
            dataset,
            artifacts,
            artifact_observed_at,
            artifact_expires_at,
            artifact_bindings,
            dynamic,
        })
    }

    fn resolve_dataset(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        verify_dataset_snapshot_receipt_v3(&self.dataset, query.now)
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Missing)?;
        let snapshot = &self.dataset.snapshot;
        if snapshot.dataset_digest != query.evidence_digest
            || snapshot.dataset_digest != query.dataset_digest
            || snapshot.objective_digest != query.objective_digest
            || snapshot.ledger_head_digest != query.qualification_evidence_head_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(receipt_from_query(
            query,
            self.dataset.producer.principal_id.clone(),
            snapshot.ledger_head_digest,
            snapshot.dataset_digest,
            self.dataset.producer.authenticated_at,
            self.dataset.producer.expires_at,
        ))
    }

    fn resolve_artifact(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        let current_head = self.artifacts.snapshot().head_digest;
        if current_head.is_zero() || current_head != query.artifact_registry_head_digest {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let artifact_id = self
            .artifact_bindings
            .get(&query.kind)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        let manifest = self
            .artifacts
            .manifest(artifact_id)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        if !self.artifacts.is_eligible(artifact_id)
            || manifest.kind != ArtifactKind::Policy
            || manifest.content_digest != query.evidence_digest
            || manifest.objective_digest != query.objective_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(receipt_from_query(
            query,
            manifest.producer_id.clone(),
            current_head,
            artifact_manifest_receipt_digest(manifest),
            self.artifact_observed_at,
            self.artifact_expires_at,
        ))
    }
}

impl PlasticityOwnerEvidenceResolverV1 for ConcretePlasticityOwnerEvidenceResolverV1 {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        match query.kind {
            PlasticityOwnerEvidenceKindV1::Dataset => self.resolve_dataset(query),
            PlasticityOwnerEvidenceKindV1::UpdateRule
            | PlasticityOwnerEvidenceKindV1::MutationPolicy => self.resolve_artifact(query),
            PlasticityOwnerEvidenceKindV1::Modulator
            | PlasticityOwnerEvidenceKindV1::ModulatorBroadcast
            | PlasticityOwnerEvidenceKindV1::Eligibility
            | PlasticityOwnerEvidenceKindV1::ParameterSignal => self.dynamic.resolve(query),
        }
    }
}


#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityDynamicSignalBindingV1 {
    pub layer_id: StableId,
    pub parameter_id: StableId,
    pub eligibility_index: u32,
    /// Q32 row over the bounded NDU-owned modulator vector. L1 must be <= 1.
    pub modulator_weights: Vec<FixedQ32>,
}

/// Concrete dynamic owner composition.
///
/// utility.ndu owns the selected low-dimensional modulator projection through
/// its append/reopen-verified projection journal. neuron.runtime owns
/// eligibility through its anchored SparseJournal. The explicit broadcast
/// mapping is an immutable Policy artifact bound to the current ArtifactRegistry
/// head. Per-parameter signal evidence is recomputed from those owner facts and
/// the exact generator values; no caller-authored digest is trusted as proof.
pub struct PlasticityDynamicOwnerEvidenceResolverV1 {
    objective_digest: Digest32,
    ndu_subject_digest: Digest32,
    ndu_owner_id: StableId,
    neuron_owner_id: StableId,
    ndu_journal: Arc<RwLock<NduProjectionJournalV1>>,
    ndu_prefix: Vec<Digest32>,
    modulator_values: Vec<FixedQ32>,
    neuron_journal: Arc<Mutex<SparseJournal>>,
    acknowledged_neuron_anchor: JournalAnchor,
    broadcast_artifacts: ArtifactRegistry,
    broadcast_artifact_id: StableId,
    bindings: BTreeMap<(StableId, StableId), PlasticityDynamicSignalBindingV1>,
    observed_at: u64,
    expires_at: u64,
}

impl PlasticityDynamicOwnerEvidenceResolverV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        objective_digest: Digest32,
        ndu_subject_digest: Digest32,
        ndu_owner_id: StableId,
        neuron_owner_id: StableId,
        ndu_journal: Arc<RwLock<NduProjectionJournalV1>>,
        modulator_values: Vec<FixedQ32>,
        neuron_journal: Arc<Mutex<SparseJournal>>,
        acknowledged_neuron_anchor: JournalAnchor,
        broadcast_artifacts: ArtifactRegistry,
        broadcast_artifact_id: StableId,
        bindings: Vec<PlasticityDynamicSignalBindingV1>,
        observed_at: u64,
        expires_at: u64,
    ) -> Result<Self, PlasticityOwnerEvidenceErrorV1> {
        if objective_digest.is_zero()
            || ndu_subject_digest.is_zero()
            || observed_at > expires_at
            || acknowledged_neuron_anchor.sequence == 0
            || acknowledged_neuron_anchor.checkpoint_digest.is_zero()
            || modulator_values.is_empty()
            || modulator_values.len() > 8
            || modulator_values.iter().any(|value| {
                *value < FixedQ32::from_raw(-FixedQ32::ONE.raw()) || *value > FixedQ32::ONE
            })
        {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
        }

        let mut binding_map = BTreeMap::new();
        for binding in bindings {
            if binding.modulator_weights.len() != modulator_values.len()
                || fixed_l1(&binding.modulator_weights)? > i128::from(FixedQ32::ONE.raw())
            {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
            let key = (binding.layer_id.clone(), binding.parameter_id.clone());
            if binding_map.insert(key, binding).is_some() {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
        if binding_map.is_empty() {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
        }

        {
            let journal = neuron_journal
                .lock()
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?;
            let checkpoint = journal
                .current()
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
                .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
            if checkpoint.digest() != acknowledged_neuron_anchor.checkpoint_digest {
                return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
            }
            let width = checkpoint.eligibility_q24().len();
            if binding_map.values().any(|binding| {
                usize::try_from(binding.eligibility_index)
                    .map_or(true, |index| index >= width)
            }) {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }

        let modulator_digest =
            plasticity_modulator_digest_v1(objective_digest, ndu_subject_digest, &modulator_values)?;
        let ndu_prefix = {
            let journal = ndu_journal
                .read()
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?;
            if journal.selected_projection_digest(objective_digest, ndu_subject_digest)
                != Some(modulator_digest)
                || journal.entries().last().is_none()
            {
                return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
            }
            journal
                .entries()
                .iter()
                .map(|entry| entry.entry_digest)
                .collect::<Vec<_>>()
        };

        let broadcast_digest =
            plasticity_modulator_broadcast_digest_v1(binding_map.values())?;
        let manifest = broadcast_artifacts
            .manifest(&broadcast_artifact_id)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        if !broadcast_artifacts.is_eligible(&broadcast_artifact_id)
            || manifest.kind != ArtifactKind::Policy
            || manifest.objective_digest != objective_digest
            || manifest.content_digest != broadcast_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }

        Ok(Self {
            objective_digest,
            ndu_subject_digest,
            ndu_owner_id,
            neuron_owner_id,
            ndu_journal,
            ndu_prefix,
            modulator_values,
            neuron_journal,
            acknowledged_neuron_anchor,
            broadcast_artifacts,
            broadcast_artifact_id,
            bindings: binding_map,
            observed_at,
            expires_at,
        })
    }

    fn current_modulator(
        &self,
    ) -> Result<(Digest32, Digest32), PlasticityOwnerEvidenceErrorV1> {
        let digest = plasticity_modulator_digest_v1(
            self.objective_digest,
            self.ndu_subject_digest,
            &self.modulator_values,
        )?;
        let journal = self
            .ndu_journal
            .read()
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?;
        if journal.entries().len() < self.ndu_prefix.len()
            || !journal
                .entries()
                .iter()
                .zip(&self.ndu_prefix)
                .all(|(entry, expected)| entry.entry_digest == *expected)
            || journal.selected_projection_digest(self.objective_digest, self.ndu_subject_digest)
                != Some(digest)
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let head = journal
            .entries()
            .last()
            .map(|entry| entry.entry_digest)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        Ok((digest, head))
    }

    fn current_eligibility(
        &self,
    ) -> Result<(Digest32, Digest32, Vec<i64>), PlasticityOwnerEvidenceErrorV1> {
        let journal = self
            .neuron_journal
            .lock()
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?;
        let checkpoint = journal
            .current()
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        if checkpoint.digest().is_zero()
            || !journal
                .contains_anchor(self.acknowledged_neuron_anchor)
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let digest = plasticity_eligibility_digest_v1(checkpoint)?;
        Ok((
            digest,
            checkpoint.digest(),
            checkpoint.eligibility_q24().to_vec(),
        ))
    }

    fn broadcast(
        &self,
        artifact_registry_head_digest: Digest32,
    ) -> Result<(Digest32, StableId, Digest32), PlasticityOwnerEvidenceErrorV1> {
        let head = self.broadcast_artifacts.snapshot().head_digest;
        if head.is_zero() || head != artifact_registry_head_digest {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let manifest = self
            .broadcast_artifacts
            .manifest(&self.broadcast_artifact_id)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        if !self.broadcast_artifacts.is_eligible(&self.broadcast_artifact_id)
            || manifest.kind != ArtifactKind::Policy
            || manifest.objective_digest != self.objective_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let expected = plasticity_modulator_broadcast_digest_v1(self.bindings.values())?;
        if manifest.content_digest != expected {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok((
            expected,
            manifest.producer_id.clone(),
            artifact_manifest_receipt_digest(manifest),
        ))
    }

    fn resolve_parameter_signal(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        let layer = query
            .layer_id
            .as_ref()
            .ok_or(PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
        let parameter = query
            .parameter_id
            .as_ref()
            .ok_or(PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
        let binding = self
            .bindings
            .get(&(layer.clone(), parameter.clone()))
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        let (modulator_digest, _) = self.current_modulator()?;
        let (eligibility_digest, checkpoint_digest, eligibility_q24) =
            self.current_eligibility()?;
        let (broadcast_digest, _, _) = self.broadcast(query.artifact_registry_head_digest)?;
        let index = usize::try_from(binding.eligibility_index)
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
        let eligibility = q24_to_q32(
            *eligibility_q24
                .get(index)
                .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?,
        )?;
        let modulator = weighted_modulator(&binding.modulator_weights, &self.modulator_values)?;

        let learning_rate = query
            .signal_learning_rate
            .ok_or(PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
        let lower_bound = query
            .signal_lower_bound
            .ok_or(PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
        let upper_bound = query
            .signal_upper_bound
            .ok_or(PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
        if query.signal_eligibility != Some(eligibility)
            || query.signal_modulator != Some(modulator)
            || lower_bound > upper_bound
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let expected = plasticity_parameter_signal_digest_v1(
            layer,
            parameter,
            eligibility,
            modulator,
            learning_rate,
            lower_bound,
            upper_bound,
            eligibility_digest,
            modulator_digest,
            broadcast_digest,
        )?;
        if expected != query.evidence_digest {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(receipt_from_query(
            query,
            self.neuron_owner_id.clone(),
            checkpoint_digest,
            expected,
            self.observed_at,
            self.expires_at,
        ))
    }
}

impl PlasticityOwnerEvidenceResolverV1 for PlasticityDynamicOwnerEvidenceResolverV1 {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        if query.objective_digest != self.objective_digest {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        match query.kind {
            PlasticityOwnerEvidenceKindV1::Modulator => {
                let (digest, head) = self.current_modulator()?;
                if query.evidence_digest != digest {
                    return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
                }
                Ok(receipt_from_query(
                    query,
                    self.ndu_owner_id.clone(),
                    head,
                    head,
                    self.observed_at,
                    self.expires_at,
                ))
            }
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast => {
                let (digest, owner_id, receipt_digest) =
                    self.broadcast(query.artifact_registry_head_digest)?;
                if query.evidence_digest != digest {
                    return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
                }
                Ok(receipt_from_query(
                    query,
                    owner_id,
                    query.artifact_registry_head_digest,
                    receipt_digest,
                    self.observed_at,
                    self.expires_at,
                ))
            }
            PlasticityOwnerEvidenceKindV1::Eligibility => {
                let (digest, checkpoint_digest, _) = self.current_eligibility()?;
                if query.evidence_digest != digest {
                    return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
                }
                Ok(receipt_from_query(
                    query,
                    self.neuron_owner_id.clone(),
                    checkpoint_digest,
                    digest,
                    self.observed_at,
                    self.expires_at,
                ))
            }
            PlasticityOwnerEvidenceKindV1::ParameterSignal => {
                self.resolve_parameter_signal(query)
            }
            _ => Err(PlasticityOwnerEvidenceErrorV1::Unavailable),
        }
    }
}

pub fn plasticity_modulator_digest_v1(
    objective_digest: Digest32,
    subject_digest: Digest32,
    values: &[FixedQ32],
) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
    if objective_digest.is_zero()
        || subject_digest.is_zero()
        || values.is_empty()
        || values.len() > 8
    {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    let mut bytes = b"hepta.utility.ndu.plasticity-modulator.v1\0".to_vec();
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(subject_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(values.len())
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?
            .to_be_bytes(),
    );
    for value in values {
        if *value < FixedQ32::from_raw(-FixedQ32::ONE.raw()) || *value > FixedQ32::ONE {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
        }
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn plasticity_modulator_broadcast_digest_v1<'a>(
    bindings: impl IntoIterator<Item = &'a PlasticityDynamicSignalBindingV1>,
) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
    let mut bindings = bindings.into_iter().cloned().collect::<Vec<_>>();
    if bindings.is_empty() {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    bindings.sort_by(|left, right| {
        left.layer_id
            .cmp(&right.layer_id)
            .then_with(|| left.parameter_id.cmp(&right.parameter_id))
    });
    let mut bytes = b"hepta.neuron.modulator-broadcast.v1\0".to_vec();
    for binding in bindings {
        push_id_checked(&mut bytes, &binding.layer_id)?;
        push_id_checked(&mut bytes, &binding.parameter_id)?;
        bytes.extend_from_slice(&binding.eligibility_index.to_be_bytes());
        bytes.extend_from_slice(
            &u32::try_from(binding.modulator_weights.len())
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?
                .to_be_bytes(),
        );
        for weight in binding.modulator_weights {
            bytes.extend_from_slice(&weight.raw().to_be_bytes());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn plasticity_eligibility_digest_v1(
    checkpoint: &SparseCheckpoint,
) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
    if checkpoint.digest().is_zero() || checkpoint.eligibility_q24().is_empty() {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    let mut bytes = b"hepta.neuron.eligibility.v1\0".to_vec();
    bytes.extend_from_slice(checkpoint.digest().as_array());
    bytes.extend_from_slice(
        &u32::try_from(checkpoint.eligibility_q24().len())
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?
            .to_be_bytes(),
    );
    for value in checkpoint.eligibility_q24() {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[allow(clippy::too_many_arguments)]
pub fn plasticity_parameter_signal_digest_v1(
    layer_id: &StableId,
    parameter_id: &StableId,
    eligibility: FixedQ32,
    modulator: FixedQ32,
    learning_rate: FixedQ32,
    lower_bound: FixedQ32,
    upper_bound: FixedQ32,
    eligibility_digest: Digest32,
    modulator_digest: Digest32,
    broadcast_digest: Digest32,
) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
    if eligibility_digest.is_zero()
        || modulator_digest.is_zero()
        || broadcast_digest.is_zero()
        || lower_bound > upper_bound
    {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    let mut bytes = b"hepta.neuron.parameter-plasticity-signal.v1\0".to_vec();
    push_id_checked(&mut bytes, layer_id)?;
    push_id_checked(&mut bytes, parameter_id)?;
    for value in [eligibility, modulator, learning_rate, lower_bound, upper_bound] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    for digest in [eligibility_digest, modulator_digest, broadcast_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn weighted_modulator(
    weights: &[FixedQ32],
    values: &[FixedQ32],
) -> Result<FixedQ32, PlasticityOwnerEvidenceErrorV1> {
    if weights.len() != values.len() {
        return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
    }
    weights
        .iter()
        .zip(values)
        .try_fold(FixedQ32::ZERO, |sum, (weight, value)| {
            let product = weight
                .checked_mul(*value)
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
            sum.checked_add(product)
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)
        })
}

fn fixed_l1(values: &[FixedQ32]) -> Result<i128, PlasticityOwnerEvidenceErrorV1> {
    values.iter().try_fold(0_i128, |sum, value| {
        sum.checked_add(i128::from(value.raw()).abs())
            .ok_or(PlasticityOwnerEvidenceErrorV1::InvalidReceipt)
    })
}

fn q24_to_q32(value: i64) -> Result<FixedQ32, PlasticityOwnerEvidenceErrorV1> {
    value
        .checked_mul(1_i64 << 8)
        .map(FixedQ32::from_raw)
        .ok_or(PlasticityOwnerEvidenceErrorV1::InvalidReceipt)
}

fn push_id_checked(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
    bytes.extend_from_slice(
        &u32::try_from(value.as_str().len())
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_str().as_bytes());
    Ok(())
}

fn receipt_from_query(
    query: &PlasticityOwnerEvidenceQueryV1,
    owner_id: StableId,
    owner_store_head_digest: Digest32,
    owner_receipt_digest: Digest32,
    observed_at: u64,
    expires_at: u64,
) -> VerifiedPlasticityOwnerEvidenceV1 {
    VerifiedPlasticityOwnerEvidenceV1 {
        kind: query.kind,
        evidence_digest: query.evidence_digest,
        owner_id,
        owner_store_head_digest,
        owner_receipt_digest,
        objective_digest: query.objective_digest,
        selected_artifact_digest: query.selected_artifact_digest,
        artifact_registry_head_digest: query.artifact_registry_head_digest,
        qualification_evidence_head_digest: query.qualification_evidence_head_digest,
        window: query.window.clone(),
        dataset_digest: query.dataset_digest,
        baseline_generation: query.baseline_generation,
        layer_id: query.layer_id.clone(),
        parameter_id: query.parameter_id.clone(),
        signal_eligibility: query.signal_eligibility,
        signal_modulator: query.signal_modulator,
        signal_learning_rate: query.signal_learning_rate,
        signal_lower_bound: query.signal_lower_bound,
        signal_upper_bound: query.signal_upper_bound,
        observed_at,
        expires_at,
    }
}

fn artifact_manifest_receipt_digest(manifest: &ArtifactManifest) -> Digest32 {
    let mut bytes = b"hepta.agentd.plasticity-artifact-owner-receipt.v1\0".to_vec();
    push_id(&mut bytes, &manifest.artifact_id);
    bytes.push(match manifest.kind {
        ArtifactKind::Prompt => 0,
        ArtifactKind::Policy => 1,
        ArtifactKind::Model => 2,
        ArtifactKind::Workflow => 3,
        ArtifactKind::Skill => 4,
        ArtifactKind::Parameters => 5,
        ArtifactKind::Topology => 6,
        ArtifactKind::Code => 7,
        ArtifactKind::ExternalAdapter => 8,
    });
    bytes.extend_from_slice(&manifest.generation.get().to_be_bytes());
    match &manifest.predecessor_id {
        Some(value) => {
            bytes.push(1);
            push_id(&mut bytes, value);
        }
        None => bytes.push(0),
    }
    for digest in [
        manifest.content_digest,
        manifest.objective_digest,
        manifest.support_digest,
        manifest.compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &manifest.producer_id);
    bytes.extend_from_slice(&manifest.encoded_size_bytes.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_artifacts::{ArtifactEvent, ArtifactManifest};
    use codex_hepta_learning_ledger::{
        AuthenticatedPrincipalV1, DatasetFreezeRequestV1, freeze_dataset_receipt_v3,
    };
    use codex_hepta_plasticity::ProposalWindowV2;
    use codex_hepta_types::Generation;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    struct UnavailableDynamic;
    impl PlasticityOwnerEvidenceResolverV1 for UnavailableDynamic {
        fn resolve(
            &self,
            _query: &PlasticityOwnerEvidenceQueryV1,
        ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
            Err(PlasticityOwnerEvidenceErrorV1::Unavailable)
        }
    }

    fn policy_manifest(
        artifact_id: &str,
        producer: &str,
        content: Digest32,
        objective: Digest32,
    ) -> ArtifactManifest {
        ArtifactManifest {
            artifact_id: id(artifact_id),
            kind: ArtifactKind::Policy,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: content,
            objective_digest: objective,
            support_digest: digest(&format!("{artifact_id}:support")),
            producer_id: id(producer),
            compatibility_digest: digest(&format!("{artifact_id}:compatibility")),
            encoded_size_bytes: 32,
        }
    }

    fn fixture() -> (
        ConcretePlasticityOwnerEvidenceResolverV1,
        Digest32,
        Digest32,
        Digest32,
    ) {
        let objective = digest("objective");
        let ledger_head = digest("ledger-head");
        let producer = AuthenticatedPrincipalV1 {
            principal_id: id("owner:dataset"),
            credential_chain_digest: digest("dataset:credential"),
            signing_key_digest: digest("dataset:key"),
            scope_digest: digest("dataset:scope"),
            authority_epoch: 1,
            authenticated_at: 10,
            expires_at: 100,
        };
        let dataset = freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("dataset:snapshot"),
                producer,
                ledger_head_digest: ledger_head,
                objective_digest: objective,
                eligible_frontier: 7,
                outcome_watermark: 7,
                correction_cut_digest: digest("dataset:correction"),
                revocation_cut_digest: digest("dataset:revocation"),
                inclusion_policy_digest: digest("dataset:policy"),
                source_record_digests: vec![digest("dataset:record")],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            50,
        )
        .expect("dataset receipt");
        let dataset_digest = dataset.snapshot.dataset_digest;

        let update_digest = digest("update-rule");
        let mutation_digest = digest("mutation-policy");
        let mut artifacts = ArtifactRegistry::new();
        for (event_id, manifest) in [
            (
                "event:update-rule",
                policy_manifest(
                    "policy:update-rule",
                    "owner:update-rule",
                    update_digest,
                    objective,
                ),
            ),
            (
                "event:mutation-policy",
                policy_manifest(
                    "policy:mutation-policy",
                    "owner:mutation-policy",
                    mutation_digest,
                    objective,
                ),
            ),
        ] {
            artifacts
                .append(ArtifactEvent::Register {
                    event_id: id(event_id),
                    manifest,
                })
                .expect("artifact append");
        }
        let artifact_head = artifacts.snapshot().head_digest;
        let resolver = ConcretePlasticityOwnerEvidenceResolverV1::new(
            dataset,
            artifacts,
            40,
            60,
            vec![
                PlasticityArtifactOwnerBindingV1 {
                    kind: PlasticityOwnerEvidenceKindV1::UpdateRule,
                    artifact_id: id("policy:update-rule"),
                },
                PlasticityArtifactOwnerBindingV1 {
                    kind: PlasticityOwnerEvidenceKindV1::MutationPolicy,
                    artifact_id: id("policy:mutation-policy"),
                },
            ],
            Box::new(UnavailableDynamic),
        )
        .expect("resolver");
        (resolver, artifact_head, ledger_head, dataset_digest)
    }

    fn query(
        kind: PlasticityOwnerEvidenceKindV1,
        evidence_digest: Digest32,
        artifact_head: Digest32,
        ledger_head: Digest32,
        dataset_digest: Digest32,
    ) -> PlasticityOwnerEvidenceQueryV1 {
        PlasticityOwnerEvidenceQueryV1 {
            kind,
            evidence_digest,
            objective_digest: digest("objective"),
            selected_artifact_digest: digest("selected-artifact"),
            artifact_registry_head_digest: artifact_head,
            qualification_evidence_head_digest: ledger_head,
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: digest("window"),
            },
            dataset_digest,
            baseline_generation: Generation::new(1).expect("generation"),
            layer_id: None,
            parameter_id: None,
            signal_eligibility: None,
            signal_modulator: None,
            signal_learning_rate: None,
            signal_lower_bound: None,
            signal_upper_bound: None,
            now: 50,
        }
    }

    #[test]
    fn concrete_dataset_and_policy_adapters_bind_live_frontiers() {
        let (resolver, artifact_head, ledger_head, dataset_digest) = fixture();

        let dataset = resolver
            .resolve(&query(
                PlasticityOwnerEvidenceKindV1::Dataset,
                dataset_digest,
                artifact_head,
                ledger_head,
                dataset_digest,
            ))
            .expect("dataset owner");
        assert_eq!(dataset.owner_id, id("owner:dataset"));
        assert_eq!(dataset.owner_store_head_digest, ledger_head);

        let update = resolver
            .resolve(&query(
                PlasticityOwnerEvidenceKindV1::UpdateRule,
                digest("update-rule"),
                artifact_head,
                ledger_head,
                dataset_digest,
            ))
            .expect("update owner");
        assert_eq!(update.owner_id, id("owner:update-rule"));
        assert_eq!(update.owner_store_head_digest, artifact_head);

        let mutation = resolver
            .resolve(&query(
                PlasticityOwnerEvidenceKindV1::MutationPolicy,
                digest("mutation-policy"),
                artifact_head,
                ledger_head,
                dataset_digest,
            ))
            .expect("mutation owner");
        assert_eq!(mutation.owner_id, id("owner:mutation-policy"));
    }

    #[test]
    fn concrete_adapters_reject_rollback_frontiers_and_missing_dynamic_owner() {
        let (resolver, artifact_head, ledger_head, dataset_digest) = fixture();

        let mut stale_dataset = query(
            PlasticityOwnerEvidenceKindV1::Dataset,
            dataset_digest,
            artifact_head,
            ledger_head,
            dataset_digest,
        );
        stale_dataset.qualification_evidence_head_digest = digest("rolled-back-ledger");
        assert_eq!(
            resolver.resolve(&stale_dataset),
            Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
        );

        let mut stale_policy = query(
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            digest("update-rule"),
            artifact_head,
            ledger_head,
            dataset_digest,
        );
        stale_policy.artifact_registry_head_digest = digest("rolled-back-artifacts");
        assert_eq!(
            resolver.resolve(&stale_policy),
            Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
        );

        assert_eq!(
            resolver.resolve(&query(
                PlasticityOwnerEvidenceKindV1::Modulator,
                digest("modulator"),
                artifact_head,
                ledger_head,
                dataset_digest,
            )),
            Err(PlasticityOwnerEvidenceErrorV1::Unavailable)
        );
    }
}

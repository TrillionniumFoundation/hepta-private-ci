//! Durable-boundary owner for one Plasticity candidate artifact.
//!
//! The Plasticity adapter produces a proposal only.  This module is the next
//! owner in the chain: it materializes the exact candidate bytes in the
//! create-only CAS, appends the candidate manifest under a registry-head
//! fence, and records independent retain/quarantine/rollback dispositions.
//! It deliberately does not select, activate, or route a candidate.  A
//! retained candidate remains in the registry's `Candidate` state until an
//! independently authenticated selector records activation elsewhere.

use std::error::Error;
use std::fmt;
use std::path::Path;

use codex_hepta_cell_roles::PlasticityCandidateQualificationReceiptV1;
use codex_hepta_cell_roles::RoleMetricDecisionDispositionV1;
use codex_hepta_cell_roles::RoleMetricDecisionReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactCasOwnerV1;
use crate::ArtifactEvent;
use crate::ArtifactManifest;
use crate::ArtifactRegistry;
use crate::ArtifactRegistryError;
use crate::ProductionOwnerError;
use crate::StateChange;

pub const PLASTICITY_CANDIDATE_OWNER_SCHEMA_V1: &str =
    "hepta.learning.plasticity-candidate-owner.v1";

/// Lifecycle of a materialized Plasticity candidate.  `Retained` means that
/// an independent evaluator accepted the evidence for continued eligibility;
/// it is intentionally not an activation or promotion state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityCandidatePhaseV1 {
    Prepared,
    Materialized,
    Retained,
    Quarantined,
    RolledBack,
}

impl PlasticityCandidatePhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::Materialized => 1,
            Self::Retained => 2,
            Self::Quarantined => 3,
            Self::RolledBack => 4,
        }
    }
}

/// Receipt emitted after candidate bytes and the candidate registry event are
/// both durable.  The CAS receipt carries the writer signature; this receipt
/// binds that signed write to the candidate manifest and fenced predecessor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityCandidateMaterializationReceiptV1 {
    pub schema: &'static str,
    pub operation_id: StableId,
    pub candidate_id: StableId,
    pub predecessor_id: StableId,
    pub predecessor_registry_head_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub manifest_digest: Digest32,
    pub artifact_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub write_receipt_digest: Digest32,
    pub phase: PlasticityCandidatePhaseV1,
    pub receipt_digest: Digest32,
}

impl PlasticityCandidateMaterializationReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::from(self.schema.as_bytes());
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.candidate_id);
        push_id(&mut bytes, &self.predecessor_id);
        for digest in [
            self.predecessor_registry_head_digest,
            self.registry_head_digest,
            self.manifest_digest,
            self.artifact_digest,
            self.write_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.encoded_size_bytes.to_be_bytes());
        bytes.push(self.phase.tag());
        Digest32::of_bytes(&bytes)
    }

    fn validate(&self) -> Result<(), PlasticityCandidateOwnerErrorV1> {
        if self.schema != PLASTICITY_CANDIDATE_OWNER_SCHEMA_V1
            || self.receipt_digest != self.content_digest()
            || self.phase != PlasticityCandidatePhaseV1::Materialized
        {
            return Err(PlasticityCandidateOwnerErrorV1::ReceiptBinding);
        }
        for (label, digest) in [
            (
                "predecessor registry head",
                self.predecessor_registry_head_digest,
            ),
            ("registry head", self.registry_head_digest),
            ("manifest", self.manifest_digest),
            ("artifact", self.artifact_digest),
            ("write receipt", self.write_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(PlasticityCandidateOwnerErrorV1::EmptyDigest(label));
            }
        }
        if self.operation_id.as_str().is_empty()
            || self.candidate_id.as_str().is_empty()
            || self.predecessor_id.as_str().is_empty()
            || self.encoded_size_bytes == 0
        {
            return Err(PlasticityCandidateOwnerErrorV1::ReceiptBinding);
        }
        Ok(())
    }
}

/// Receipt for an independent evaluator disposition.  Retain changes only
/// this owner phase; quarantine appends a durable registry event.  Neither
/// operation activates a route or changes the selected artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityCandidateDispositionReceiptV1 {
    pub schema: &'static str,
    pub operation_id: StableId,
    pub candidate_id: StableId,
    pub predecessor_id: StableId,
    pub evaluator_id: StableId,
    pub producer_id: StableId,
    pub candidate_artifact_digest: Digest32,
    pub evidence_digest: Digest32,
    pub predecessor_registry_head_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub disposition: PlasticityCandidatePhaseV1,
    pub receipt_digest: Digest32,
}

impl PlasticityCandidateDispositionReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::from(self.schema.as_bytes());
        for id in [
            &self.operation_id,
            &self.candidate_id,
            &self.predecessor_id,
            &self.evaluator_id,
            &self.producer_id,
        ] {
            push_id(&mut bytes, id);
        }
        for digest in [
            self.candidate_artifact_digest,
            self.evidence_digest,
            self.predecessor_registry_head_digest,
            self.registry_head_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(self.disposition.tag());
        Digest32::of_bytes(&bytes)
    }

    fn validate(&self) -> Result<(), PlasticityCandidateOwnerErrorV1> {
        if self.schema != PLASTICITY_CANDIDATE_OWNER_SCHEMA_V1
            || self.receipt_digest != self.content_digest()
            || !matches!(
                self.disposition,
                PlasticityCandidatePhaseV1::Retained | PlasticityCandidatePhaseV1::Quarantined
            )
            || self.evaluator_id == self.producer_id
        {
            return Err(PlasticityCandidateOwnerErrorV1::ReceiptBinding);
        }
        for (label, digest) in [
            ("candidate artifact", self.candidate_artifact_digest),
            ("evidence", self.evidence_digest),
            (
                "predecessor registry head",
                self.predecessor_registry_head_digest,
            ),
            ("registry head", self.registry_head_digest),
        ] {
            if digest.is_zero() {
                return Err(PlasticityCandidateOwnerErrorV1::EmptyDigest(label));
            }
        }
        Ok(())
    }
}

/// Receipt proving that the immutable predecessor remains the rollback target
/// after a quarantined candidate is removed from eligibility.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityCandidateRollbackReceiptV1 {
    pub schema: &'static str,
    pub operation_id: StableId,
    pub candidate_id: StableId,
    pub predecessor_id: StableId,
    pub quarantined_registry_head_digest: Digest32,
    pub rollback_predecessor_registry_head_digest: Digest32,
    pub rollback_verified: bool,
    pub receipt_digest: Digest32,
}

impl PlasticityCandidateRollbackReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::from(self.schema.as_bytes());
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.candidate_id);
        push_id(&mut bytes, &self.predecessor_id);
        bytes.extend_from_slice(self.quarantined_registry_head_digest.as_array());
        bytes.extend_from_slice(self.rollback_predecessor_registry_head_digest.as_array());
        bytes.push(u8::from(self.rollback_verified));
        Digest32::of_bytes(&bytes)
    }

    fn validate(&self) -> Result<(), PlasticityCandidateOwnerErrorV1> {
        if self.schema != PLASTICITY_CANDIDATE_OWNER_SCHEMA_V1
            || self.receipt_digest != self.content_digest()
            || !self.rollback_verified
            || self.operation_id.as_str().is_empty()
            || self.candidate_id.as_str().is_empty()
            || self.predecessor_id.as_str().is_empty()
            || self.quarantined_registry_head_digest.is_zero()
            || self.rollback_predecessor_registry_head_digest.is_zero()
        {
            return Err(PlasticityCandidateOwnerErrorV1::ReceiptBinding);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityCandidateOwnerErrorV1 {
    Registry(ArtifactRegistryError),
    Production(ProductionOwnerError),
    InvalidManifest,
    RegistryHeadMismatch,
    InvalidPhase(PlasticityCandidatePhaseV1),
    EmptyDigest(&'static str),
    ProducerMismatch,
    EvaluatorIsProducer,
    EvaluatorMismatch,
    CandidateUnavailable,
    QualificationBinding,
    MetricDecisionBinding,
    MetricDecisionNotPass,
    ReceiptBinding,
}

impl fmt::Display for PlasticityCandidateOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PlasticityCandidateOwnerErrorV1 {}

impl From<ArtifactRegistryError> for PlasticityCandidateOwnerErrorV1 {
    fn from(error: ArtifactRegistryError) -> Self {
        Self::Registry(error)
    }
}

impl From<ProductionOwnerError> for PlasticityCandidateOwnerErrorV1 {
    fn from(error: ProductionOwnerError) -> Self {
        Self::Production(error)
    }
}

/// Candidate-specific owner that joins CAS materialization and registry
/// lifecycle under one expected-head fence.
#[derive(Clone, Debug)]
pub struct PlasticityCandidateOwnerV1 {
    operation_id: StableId,
    producer_id: StableId,
    evaluator_id: StableId,
    manifest: ArtifactManifest,
    predecessor_registry_head_digest: Digest32,
    phase: PlasticityCandidatePhaseV1,
    materialization: Option<PlasticityCandidateMaterializationReceiptV1>,
    disposition: Option<PlasticityCandidateDispositionReceiptV1>,
    rollback: Option<PlasticityCandidateRollbackReceiptV1>,
}

impl PlasticityCandidateOwnerV1 {
    pub fn begin(
        operation_id: StableId,
        producer_id: StableId,
        evaluator_id: StableId,
        manifest: ArtifactManifest,
        predecessor_registry_head_digest: Digest32,
    ) -> Result<Self, PlasticityCandidateOwnerErrorV1> {
        if operation_id.as_str().is_empty()
            || producer_id.as_str().is_empty()
            || evaluator_id.as_str().is_empty()
            || producer_id == evaluator_id
            || manifest.producer_id != producer_id
            || predecessor_registry_head_digest.is_zero()
            || manifest.predecessor_id.is_none()
            || manifest.content_digest.is_zero()
            || manifest.encoded_size_bytes == 0
        {
            return Err(if manifest.producer_id != producer_id {
                PlasticityCandidateOwnerErrorV1::ProducerMismatch
            } else {
                PlasticityCandidateOwnerErrorV1::InvalidManifest
            });
        }
        Ok(Self {
            operation_id,
            producer_id,
            evaluator_id,
            manifest,
            predecessor_registry_head_digest,
            phase: PlasticityCandidatePhaseV1::Prepared,
            materialization: None,
            disposition: None,
            rollback: None,
        })
    }

    #[must_use]
    pub const fn phase(&self) -> PlasticityCandidatePhaseV1 {
        self.phase
    }

    #[must_use]
    pub fn manifest(&self) -> &ArtifactManifest {
        &self.manifest
    }

    #[must_use]
    pub fn materialization(&self) -> Option<&PlasticityCandidateMaterializationReceiptV1> {
        self.materialization.as_ref()
    }

    /// Register and write the exact candidate bytes.  Registry mutation is
    /// staged on a clone, so a failed payload write leaves the caller's
    /// registry untouched. A successful write commits both the registry event
    /// and the signed CAS receipt to the owner state.
    #[allow(clippy::too_many_arguments)]
    pub fn materialize(
        &mut self,
        registry: &mut ArtifactRegistry,
        cas_owner: &ArtifactCasOwnerV1,
        root: impl AsRef<Path>,
        relative: impl AsRef<Path>,
        payload: &[u8],
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<PlasticityCandidateMaterializationReceiptV1, PlasticityCandidateOwnerErrorV1> {
        if self.phase != PlasticityCandidatePhaseV1::Prepared {
            return Err(PlasticityCandidateOwnerErrorV1::InvalidPhase(self.phase));
        }
        if registry.snapshot().head_digest != self.predecessor_registry_head_digest {
            return Err(PlasticityCandidateOwnerErrorV1::RegistryHeadMismatch);
        }
        let predecessor_id = self
            .manifest
            .predecessor_id
            .clone()
            .ok_or(PlasticityCandidateOwnerErrorV1::InvalidManifest)?;
        if registry.manifest(&predecessor_id).is_none() || !registry.is_eligible(&predecessor_id) {
            return Err(PlasticityCandidateOwnerErrorV1::CandidateUnavailable);
        }
        let mut staged = registry.clone();
        let event_id = StableId::new(format!(
            "{}:register:{}",
            self.operation_id.as_str(),
            self.manifest.artifact_id.as_str()
        ))
        .map_err(|_| PlasticityCandidateOwnerErrorV1::InvalidManifest)?;
        staged.append(ArtifactEvent::Register {
            event_id,
            manifest: self.manifest.clone(),
        })?;
        let write = cas_owner.write_candidate(
            self.operation_id.clone(),
            root,
            relative,
            &staged,
            &self.manifest.artifact_id,
            payload,
            host_evidence_digest,
            observer_evidence_digest,
        )?;
        if write.artifact_digest != self.manifest.content_digest
            || write.encoded_size_bytes != self.manifest.encoded_size_bytes
        {
            return Err(PlasticityCandidateOwnerErrorV1::ReceiptBinding);
        }
        let registry_head_digest = staged.snapshot().head_digest;
        let mut receipt = PlasticityCandidateMaterializationReceiptV1 {
            schema: PLASTICITY_CANDIDATE_OWNER_SCHEMA_V1,
            operation_id: self.operation_id.clone(),
            candidate_id: self.manifest.artifact_id.clone(),
            predecessor_id,
            predecessor_registry_head_digest: self.predecessor_registry_head_digest,
            registry_head_digest,
            manifest_digest: digest_manifest(&self.manifest),
            artifact_digest: self.manifest.content_digest,
            encoded_size_bytes: self.manifest.encoded_size_bytes,
            write_receipt_digest: write.content_digest(),
            phase: PlasticityCandidatePhaseV1::Materialized,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.validate()?;
        *registry = staged;
        self.materialization = Some(receipt.clone());
        self.phase = PlasticityCandidatePhaseV1::Materialized;
        Ok(receipt)
    }

    /// Retain the candidate after an independent evaluator has supplied a
    /// non-empty evidence digest. No registry event or activation is emitted.
    pub fn retain(
        &mut self,
        registry: &ArtifactRegistry,
        evaluator_id: StableId,
        evidence_digest: Digest32,
    ) -> Result<PlasticityCandidateDispositionReceiptV1, PlasticityCandidateOwnerErrorV1> {
        self.disposition(
            registry,
            evaluator_id,
            evidence_digest,
            PlasticityCandidatePhaseV1::Retained,
        )
    }

    /// Production retain path. The qualification receipt and the separately
    /// evaluated metric decision must agree on the candidate and metric
    /// receipt; only a policy `Pass` may keep the candidate eligible.
    pub fn retain_evaluated(
        &mut self,
        registry: &ArtifactRegistry,
        qualification: &PlasticityCandidateQualificationReceiptV1,
        decision: &RoleMetricDecisionReceiptV1,
    ) -> Result<PlasticityCandidateDispositionReceiptV1, PlasticityCandidateOwnerErrorV1> {
        self.validate_evaluation_binding(registry, qualification, decision, true)?;
        self.retain(
            registry,
            self.evaluator_id.clone(),
            qualification.qualification_digest,
        )
    }

    /// Quarantine the candidate with an append-only registry event. The
    /// predecessor remains untouched and is the only rollback target.
    pub fn quarantine(
        &mut self,
        registry: &mut ArtifactRegistry,
        evaluator_id: StableId,
        evidence_digest: Digest32,
    ) -> Result<PlasticityCandidateDispositionReceiptV1, PlasticityCandidateOwnerErrorV1> {
        self.validate_disposition_inputs(registry, &evaluator_id, evidence_digest)?;
        let mut staged = registry.clone();
        let event_id = StableId::new(format!(
            "{}:quarantine:{}",
            self.operation_id.as_str(),
            self.manifest.artifact_id.as_str()
        ))
        .map_err(|_| PlasticityCandidateOwnerErrorV1::ReceiptBinding)?;
        staged.append(ArtifactEvent::Quarantine(StateChange {
            event_id,
            artifact_id: self.manifest.artifact_id.clone(),
            evaluator_id: evaluator_id.clone(),
            reason_digest: evidence_digest,
        }))?;
        let receipt = self.make_disposition_receipt(
            evaluator_id,
            evidence_digest,
            PlasticityCandidatePhaseV1::Quarantined,
            staged.snapshot().head_digest,
        )?;
        *registry = staged;
        self.disposition = Some(receipt.clone());
        self.phase = PlasticityCandidatePhaseV1::Quarantined;
        Ok(receipt)
    }

    /// Production quarantine path. A failed or insufficient decision may be
    /// quarantined, while the same independent evidence binding is required
    /// before the registry is mutated.
    pub fn quarantine_evaluated(
        &mut self,
        registry: &mut ArtifactRegistry,
        qualification: &PlasticityCandidateQualificationReceiptV1,
        decision: &RoleMetricDecisionReceiptV1,
    ) -> Result<PlasticityCandidateDispositionReceiptV1, PlasticityCandidateOwnerErrorV1> {
        self.validate_evaluation_binding(registry, qualification, decision, false)?;
        self.quarantine(
            registry,
            self.evaluator_id.clone(),
            qualification.qualification_digest,
        )
    }

    pub fn rollback(
        &mut self,
        registry: &ArtifactRegistry,
    ) -> Result<PlasticityCandidateRollbackReceiptV1, PlasticityCandidateOwnerErrorV1> {
        if self.phase != PlasticityCandidatePhaseV1::Quarantined {
            return Err(PlasticityCandidateOwnerErrorV1::InvalidPhase(self.phase));
        }
        let predecessor_id = self
            .manifest
            .predecessor_id
            .clone()
            .ok_or(PlasticityCandidateOwnerErrorV1::InvalidManifest)?;
        if !registry.is_eligible(&predecessor_id)
            || registry.is_eligible(&self.manifest.artifact_id)
        {
            return Err(PlasticityCandidateOwnerErrorV1::CandidateUnavailable);
        }
        let mut receipt = PlasticityCandidateRollbackReceiptV1 {
            schema: PLASTICITY_CANDIDATE_OWNER_SCHEMA_V1,
            operation_id: self.operation_id.clone(),
            candidate_id: self.manifest.artifact_id.clone(),
            predecessor_id,
            quarantined_registry_head_digest: registry.snapshot().head_digest,
            rollback_predecessor_registry_head_digest: self.predecessor_registry_head_digest,
            rollback_verified: true,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.validate()?;
        self.rollback = Some(receipt.clone());
        self.phase = PlasticityCandidatePhaseV1::RolledBack;
        Ok(receipt)
    }

    fn disposition(
        &mut self,
        registry: &ArtifactRegistry,
        evaluator_id: StableId,
        evidence_digest: Digest32,
        disposition: PlasticityCandidatePhaseV1,
    ) -> Result<PlasticityCandidateDispositionReceiptV1, PlasticityCandidateOwnerErrorV1> {
        self.validate_disposition_inputs(registry, &evaluator_id, evidence_digest)?;
        let receipt = self.make_disposition_receipt(
            evaluator_id,
            evidence_digest,
            disposition,
            registry.snapshot().head_digest,
        )?;
        self.disposition = Some(receipt.clone());
        self.phase = disposition;
        Ok(receipt)
    }

    fn validate_disposition_inputs(
        &self,
        registry: &ArtifactRegistry,
        evaluator_id: &StableId,
        evidence_digest: Digest32,
    ) -> Result<(), PlasticityCandidateOwnerErrorV1> {
        if evaluator_id == &self.producer_id {
            return Err(PlasticityCandidateOwnerErrorV1::EvaluatorIsProducer);
        }
        if evaluator_id != &self.evaluator_id {
            return Err(PlasticityCandidateOwnerErrorV1::EvaluatorMismatch);
        }
        if !matches!(
            self.phase,
            PlasticityCandidatePhaseV1::Materialized | PlasticityCandidatePhaseV1::Retained
        ) {
            return Err(PlasticityCandidateOwnerErrorV1::InvalidPhase(self.phase));
        }
        if evidence_digest.is_zero()
            || registry.manifest(&self.manifest.artifact_id) != Some(&self.manifest)
            || !registry.is_eligible(&self.manifest.artifact_id)
        {
            return Err(PlasticityCandidateOwnerErrorV1::CandidateUnavailable);
        }
        Ok(())
    }

    fn make_disposition_receipt(
        &self,
        evaluator_id: StableId,
        evidence_digest: Digest32,
        disposition: PlasticityCandidatePhaseV1,
        registry_head_digest: Digest32,
    ) -> Result<PlasticityCandidateDispositionReceiptV1, PlasticityCandidateOwnerErrorV1> {
        let mut receipt = PlasticityCandidateDispositionReceiptV1 {
            schema: PLASTICITY_CANDIDATE_OWNER_SCHEMA_V1,
            operation_id: self.operation_id.clone(),
            candidate_id: self.manifest.artifact_id.clone(),
            predecessor_id: self
                .manifest
                .predecessor_id
                .clone()
                .ok_or(PlasticityCandidateOwnerErrorV1::InvalidManifest)?,
            evaluator_id,
            producer_id: self.producer_id.clone(),
            candidate_artifact_digest: self.manifest.content_digest,
            evidence_digest,
            predecessor_registry_head_digest: self.predecessor_registry_head_digest,
            registry_head_digest,
            disposition,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.validate()?;
        Ok(receipt)
    }

    fn validate_evaluation_binding(
        &self,
        registry: &ArtifactRegistry,
        qualification: &PlasticityCandidateQualificationReceiptV1,
        decision: &RoleMetricDecisionReceiptV1,
        require_pass: bool,
    ) -> Result<(), PlasticityCandidateOwnerErrorV1> {
        codex_hepta_cell_roles::verify_plasticity_candidate_qualification_v1(qualification)
            .map_err(|_| PlasticityCandidateOwnerErrorV1::QualificationBinding)?;
        if qualification.candidate_id != self.manifest.artifact_id
            || qualification.candidate_snapshot_digest != self.manifest.content_digest
            || qualification.evaluator_id != self.evaluator_id
            || qualification.candidate_artifact_receipt_digest.is_zero()
        {
            return Err(PlasticityCandidateOwnerErrorV1::QualificationBinding);
        }
        let predecessor_id = self
            .manifest
            .predecessor_id
            .as_ref()
            .ok_or(PlasticityCandidateOwnerErrorV1::InvalidManifest)?;
        let predecessor = registry
            .manifest(predecessor_id)
            .ok_or(PlasticityCandidateOwnerErrorV1::CandidateUnavailable)?;
        if qualification.rollback_predecessor_digest != predecessor.content_digest {
            return Err(PlasticityCandidateOwnerErrorV1::QualificationBinding);
        }
        if decision.metric_receipt_digest != qualification.metric_receipt_digest
            || decision.profile_digest != qualification.metric_profile_digest
            || decision.generation != qualification.candidate_generation
            || decision.role != codex_hepta_types::CellRoleV1::Plasticity
            || decision.authority.grants_any()
        {
            return Err(PlasticityCandidateOwnerErrorV1::MetricDecisionBinding);
        }
        if require_pass && decision.disposition != RoleMetricDecisionDispositionV1::Pass {
            return Err(PlasticityCandidateOwnerErrorV1::MetricDecisionNotPass);
        }
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn digest_manifest(value: &ArtifactManifest) -> Digest32 {
    let mut bytes = b"hepta.learning.plasticity-manifest.v1".to_vec();
    push_id(&mut bytes, &value.artifact_id);
    bytes.push(value.kind.tag());
    bytes.extend_from_slice(&value.generation.get().to_be_bytes());
    match &value.predecessor_id {
        Some(predecessor) => {
            bytes.push(1);
            push_id(&mut bytes, predecessor);
        }
        None => bytes.push(0),
    }
    for digest in [
        value.content_digest,
        value.objective_digest,
        value.support_digest,
        value.compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &value.producer_id);
    bytes.extend_from_slice(&value.encoded_size_bytes.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "plasticity_owner_tests.rs"]
mod tests;

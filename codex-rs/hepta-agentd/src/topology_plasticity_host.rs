//! Agentd host composition for governed topology plasticity.
//!
//! The host recomputes artifact/learning frontiers immediately before admission,
//! owns a rollback-domain-independent topology registry anchor/fence, and withholds
//! success until that anchor is durably committed. It never applies topology.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_intelligence::{
    TopologyAdmissionEvidenceV1, TopologyPlasticityProductErrorV1,
    TopologyPlasticityProductReceiptV1, TopologyPlasticityProductRequestV1,
    propose_authenticated_topology_plasticity_v1,
};
use codex_hepta_learning_artifacts::{ArtifactKind, ArtifactRegistry};
use codex_hepta_learning_ledger::{DurableLedger, DurableLedgerError, LearningEvidenceVerifierV1};
use codex_hepta_plasticity::{
    DurableTopologyProposalRegistryV1, DurableTopologyRegistryAnchorV1,
    DurableTopologyRegistryErrorV1,
};
use codex_hepta_types::{Digest32, Generation, StableId};

use crate::plasticity_anchor_journal::{
    AdaptiveAnchorJournalErrorV1, AdaptiveAnchorJournalV1, AdaptiveAnchorV1,
};

const ANCHOR_MAGIC: [u8; 8] = *b"HPTTANC2";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdTopologyWriterStateV1 {
    Healthy,
    AppendPendingAnchor,
    Poisoned,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdTopologyHostErrorV1 {
    AnchorBusy,
    AnchorNotRegular,
    AnchorCorrupt,
    AnchorScopeMismatch,
    AnchorFenceOverflow,
    AnchorIo(std::io::ErrorKind),
    MissingAnchor,
    ArtifactMissing,
    ArtifactIneligible,
    ArtifactBinding,
    Ledger(DurableLedgerError),
    Registry(DurableTopologyRegistryErrorV1),
    Product(TopologyPlasticityProductErrorV1),
    AdmissionDrift,
    AnchorPersistenceFailed,
    Poisoned,
}

impl fmt::Display for AgentdTopologyHostErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdTopologyHostErrorV1 {}
impl From<DurableLedgerError> for AgentdTopologyHostErrorV1 {
    fn from(value: DurableLedgerError) -> Self {
        Self::Ledger(value)
    }
}
impl From<DurableTopologyRegistryErrorV1> for AgentdTopologyHostErrorV1 {
    fn from(value: DurableTopologyRegistryErrorV1) -> Self {
        Self::Registry(value)
    }
}
impl From<TopologyPlasticityProductErrorV1> for AgentdTopologyHostErrorV1 {
    fn from(value: TopologyPlasticityProductErrorV1) -> Self {
        Self::Product(value)
    }
}

pub struct AgentdTopologyAnchorStoreV1 {
    journal: AdaptiveAnchorJournalV1,
}

impl From<AdaptiveAnchorJournalErrorV1> for AgentdTopologyHostErrorV1 {
    fn from(value: AdaptiveAnchorJournalErrorV1) -> Self {
        match value {
            AdaptiveAnchorJournalErrorV1::Busy => Self::AnchorBusy,
            AdaptiveAnchorJournalErrorV1::NotRegular => Self::AnchorNotRegular,
            AdaptiveAnchorJournalErrorV1::ScopeMismatch => Self::AnchorScopeMismatch,
            AdaptiveAnchorJournalErrorV1::FenceOverflow => Self::AnchorFenceOverflow,
            AdaptiveAnchorJournalErrorV1::Io(kind) => Self::AnchorIo(kind),
            AdaptiveAnchorJournalErrorV1::InvalidScope
            | AdaptiveAnchorJournalErrorV1::Corrupt
            | AdaptiveAnchorJournalErrorV1::GenerationPending
            | AdaptiveAnchorJournalErrorV1::Capacity => Self::AnchorCorrupt,
        }
    }
}

impl AgentdTopologyAnchorStoreV1 {
    pub fn open(file: File, scope: Digest32) -> Result<Self, AgentdTopologyHostErrorV1> {
        Ok(Self {
            journal: AdaptiveAnchorJournalV1::open(file, scope, ANCHOR_MAGIC)?,
        })
    }

    pub fn issue_next_fence(&mut self) -> Result<u64, AgentdTopologyHostErrorV1> {
        self.journal.issue_new_registry_fence().map_err(Into::into)
    }

    pub const fn fence(&self) -> u64 {
        self.journal.state().writer_fence
    }

    pub fn anchor(&self) -> Option<DurableTopologyRegistryAnchorV1> {
        self.journal
            .state()
            .anchor
            .map(|anchor| DurableTopologyRegistryAnchorV1 {
                sequence: anchor.sequence,
                frame_digest: anchor.frame_digest,
            })
    }

    pub fn previous_anchor(&self) -> Option<DurableTopologyRegistryAnchorV1> {
        self.journal
            .state()
            .previous_anchor
            .map(|anchor| DurableTopologyRegistryAnchorV1 {
                sequence: anchor.sequence,
                frame_digest: anchor.frame_digest,
            })
    }

    pub fn persist_anchor(
        &mut self,
        scope: Digest32,
        fence: u64,
        anchor: DurableTopologyRegistryAnchorV1,
    ) -> Result<(), AgentdTopologyHostErrorV1> {
        self.journal
            .persist_anchor(
                scope,
                fence,
                AdaptiveAnchorV1 {
                    sequence: anchor.sequence,
                    frame_digest: anchor.frame_digest,
                },
            )
            .map_err(Into::into)
    }
}

pub struct AgentdTopologyWriterV1 {
    registry: DurableTopologyProposalRegistryV1,
    scope: Digest32,
    fence: u64,
    state: AgentdTopologyWriterStateV1,
}

impl AgentdTopologyWriterV1 {
    pub const fn state(&self) -> AgentdTopologyWriterStateV1 {
        self.state
    }
    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableTopologyRegistryAnchorV1>, AgentdTopologyHostErrorV1> {
        if self.state != AgentdTopologyWriterStateV1::Healthy {
            return Err(AgentdTopologyHostErrorV1::Poisoned);
        }
        self.registry.current_anchor().map_err(Into::into)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdTopologyAdmissionInputV1 {
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: codex_hepta_plasticity::ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub generation_digest: Digest32,
    pub evaluation_receipt_digest: Digest32,
}

pub fn resolve_agentd_topology_admission_v1(
    input: &AgentdTopologyAdmissionInputV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
) -> Result<TopologyAdmissionEvidenceV1, AgentdTopologyHostErrorV1> {
    let manifest = artifacts
        .manifest(&input.baseline_id)
        .ok_or(AgentdTopologyHostErrorV1::ArtifactMissing)?;
    if !artifacts.is_eligible(&input.baseline_id) {
        return Err(AgentdTopologyHostErrorV1::ArtifactIneligible);
    }
    if !matches!(manifest.kind, ArtifactKind::Topology | ArtifactKind::Model)
        || manifest.content_digest != input.selected_artifact_digest
        || manifest.objective_digest != input.objective_digest
        || manifest.generation != input.baseline_generation
        || input.baseline_generation.next() != Ok(input.candidate_generation)
    {
        return Err(AgentdTopologyHostErrorV1::ArtifactBinding);
    }
    let artifact_registry_head_digest = artifacts.snapshot().head_digest;
    let ledger_head_digest = ledger.snapshot()?.head_digest;
    if artifact_registry_head_digest.is_zero()
        || ledger_head_digest.is_zero()
        || input.generation_digest.is_zero()
        || input.evaluation_receipt_digest.is_zero()
    {
        return Err(AgentdTopologyHostErrorV1::ArtifactBinding);
    }
    Ok(TopologyAdmissionEvidenceV1 {
        baseline_id: input.baseline_id.clone(),
        objective_digest: input.objective_digest,
        selected_artifact_digest: input.selected_artifact_digest,
        artifact_registry_head_digest,
        qualification_evidence_head_digest: ledger_head_digest,
        window: input.window.clone(),
        baseline_generation: input.baseline_generation,
        candidate_generation: input.candidate_generation,
        generation_digest: input.generation_digest,
        evaluation_receipt_digest: input.evaluation_receipt_digest,
    })
}

pub fn propose_agentd_topology_plasticity_v1(
    mut request: TopologyPlasticityProductRequestV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AgentdTopologyWriterV1,
    anchor_store: &mut AgentdTopologyAnchorStoreV1,
    now: u64,
) -> Result<TopologyPlasticityProductReceiptV1, AgentdTopologyHostErrorV1> {
    if writer.state != AgentdTopologyWriterStateV1::Healthy {
        return Err(AgentdTopologyHostErrorV1::Poisoned);
    }
    let resolved = resolve_agentd_topology_admission_v1(
        &AgentdTopologyAdmissionInputV1 {
            baseline_id: request.admission.baseline_id.clone(),
            objective_digest: request.admission.objective_digest,
            selected_artifact_digest: request.selected_artifact_digest,
            window: request.window.clone(),
            baseline_generation: request.baseline_generation,
            candidate_generation: request.candidate_generation,
            generation_digest: request.admission.generation_digest,
            evaluation_receipt_digest: request.admission.evaluation_receipt_digest,
        },
        artifacts,
        ledger,
    )?;
    if resolved != request.admission {
        return Err(AgentdTopologyHostErrorV1::AdmissionDrift);
    }
    request.admission = resolved;

    writer.state = AgentdTopologyWriterStateV1::AppendPendingAnchor;
    let receipt = match propose_authenticated_topology_plasticity_v1(
        request,
        verifier,
        &mut writer.registry,
        now,
    ) {
        Ok(receipt) => receipt,
        Err(error) => {
            writer.state = if matches!(
                error,
                TopologyPlasticityProductErrorV1::Registry(
                    DurableTopologyRegistryErrorV1::Corrupt
                        | DurableTopologyRegistryErrorV1::Indeterminate
                        | DurableTopologyRegistryErrorV1::Poisoned
                        | DurableTopologyRegistryErrorV1::Io(_)
                ) | TopologyPlasticityProductErrorV1::MissingAnchor
            ) {
                AgentdTopologyWriterStateV1::Poisoned
            } else {
                AgentdTopologyWriterStateV1::Healthy
            };
            return Err(AgentdTopologyHostErrorV1::Product(error));
        }
    };
    if anchor_store
        .persist_anchor(writer.scope, writer.fence, receipt.next_registry_anchor)
        .is_err()
    {
        writer.state = AgentdTopologyWriterStateV1::Poisoned;
        return Err(AgentdTopologyHostErrorV1::AnchorPersistenceFailed);
    }
    writer.state = AgentdTopologyWriterStateV1::Healthy;
    Ok(receipt)
}

pub fn bootstrap_agentd_topology_writer_v1(
    registry_file: File,
    anchor_file: File,
    scope: Digest32,
    maximum_records: usize,
) -> Result<(AgentdTopologyWriterV1, AgentdTopologyAnchorStoreV1), AgentdTopologyHostErrorV1> {
    let mut anchor_store = AgentdTopologyAnchorStoreV1::open(anchor_file, scope)?;
    if anchor_store.anchor().is_some() || anchor_store.fence() != 0 {
        return Err(AgentdTopologyHostErrorV1::AnchorCorrupt);
    }
    let fence = anchor_store.issue_next_fence()?;
    let registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
        registry_file,
        scope,
        fence,
        maximum_records,
    )?;
    Ok((
        AgentdTopologyWriterV1 {
            registry,
            scope,
            fence,
            state: AgentdTopologyWriterStateV1::Healthy,
        },
        anchor_store,
    ))
}

pub fn rollover_agentd_topology_writer_v1(
    registry_file: File,
    anchor_file: File,
    registry_scope_digest: Digest32,
    maximum_records: usize,
    expected_previous_anchor: DurableTopologyRegistryAnchorV1,
) -> Result<(AgentdTopologyWriterV1, AgentdTopologyAnchorStoreV1), AgentdTopologyHostErrorV1> {
    let mut anchor_store = AgentdTopologyAnchorStoreV1::open(anchor_file, registry_scope_digest)?;
    if anchor_store.anchor() != Some(expected_previous_anchor) {
        return Err(AgentdTopologyHostErrorV1::AnchorCorrupt);
    }
    let fence = anchor_store.issue_next_fence()?;
    let registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
        registry_file,
        registry_scope_digest,
        fence,
        maximum_records,
    )?;
    Ok((
        AgentdTopologyWriterV1 {
            registry,
            scope: registry_scope_digest,
            fence,
            state: AgentdTopologyWriterStateV1::Healthy,
        },
        anchor_store,
    ))
}

pub fn resume_agentd_topology_writer_v1(
    registry_file: File,
    anchor_file: File,
    registry_scope_digest: Digest32,
    maximum_records: usize,
) -> Result<(AgentdTopologyWriterV1, AgentdTopologyAnchorStoreV1), AgentdTopologyHostErrorV1> {
    let anchor_store = AgentdTopologyAnchorStoreV1::open(anchor_file, registry_scope_digest)?;
    if anchor_store.fence() == 0 || anchor_store.anchor().is_some() {
        return Err(AgentdTopologyHostErrorV1::AnchorCorrupt);
    }
    let fence = anchor_store.fence();
    let registry = DurableTopologyProposalRegistryV1::resume_unacknowledged_bootstrap(
        registry_file,
        registry_scope_digest,
        fence,
        maximum_records,
    )?;
    Ok((
        AgentdTopologyWriterV1 {
            registry,
            scope: registry_scope_digest,
            fence,
            state: AgentdTopologyWriterStateV1::Healthy,
        },
        anchor_store,
    ))
}

pub fn reopen_agentd_topology_writer_v1(
    registry_file: File,
    anchor_file: File,
    scope: Digest32,
    maximum_records: usize,
) -> Result<(AgentdTopologyWriterV1, AgentdTopologyAnchorStoreV1), AgentdTopologyHostErrorV1> {
    let anchor_store = AgentdTopologyAnchorStoreV1::open(anchor_file, scope)?;
    let anchor = anchor_store
        .anchor()
        .ok_or(AgentdTopologyHostErrorV1::MissingAnchor)?;
    let fence = anchor_store.fence();
    if fence == 0 {
        return Err(AgentdTopologyHostErrorV1::AnchorCorrupt);
    }
    let registry = DurableTopologyProposalRegistryV1::reopen_anchored(
        registry_file,
        scope,
        fence,
        maximum_records,
        anchor,
    )?;
    Ok((
        AgentdTopologyWriterV1 {
            registry,
            scope,
            fence,
            state: AgentdTopologyWriterStateV1::Healthy,
        },
        anchor_store,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempfile;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[test]
    fn topology_anchor_store_preserves_fence_and_anchor() {
        let file = tempfile().expect("file");
        let scope = digest(b"topology-scope");
        let mut store = AgentdTopologyAnchorStoreV1::open(file.try_clone().expect("clone"), scope)
            .expect("open");
        let fence = store.issue_next_fence().expect("fence");
        assert_eq!(fence, 1);
        let anchor = DurableTopologyRegistryAnchorV1 {
            sequence: 1,
            frame_digest: digest(b"frame"),
        };
        store.persist_anchor(scope, fence, anchor).expect("persist");
        drop(store);
        let reopened = AgentdTopologyAnchorStoreV1::open(file, scope).expect("reopen");
        assert_eq!(reopened.fence(), 1);
        assert_eq!(reopened.anchor(), Some(anchor));
    }
}

use crate::{
    ContractError, CrossModalBinding, Digest32, EpisodeId, EventId, MAX_BINDINGS,
    MAX_MODALITY_SPANS, MAX_PROVENANCE, MemoryScope, ModalityKind, ModalitySpanRef, TimeInterval,
    ppm, validate_keys, validate_text,
};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProvenanceRef {
    pub source_id: String,
    pub source_revision: u64,
    pub source_sha256: Digest32,
    pub observed_at_unix_ms: i64,
}

impl ProvenanceRef {
    fn validate(&self) -> Result<(), ContractError> {
        validate_text(&self.source_id, 256, "source id")?;
        if self.source_revision == 0 {
            return Err(ContractError::Invalid("source revision must be non-zero"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryLifecycle {
    Active,
    Superseded { by_event_id: EventId },
    Tombstoned { reason_sha256: Digest32 },
}

impl MemoryLifecycle {
    fn validate_for(&self, event_id: EventId) -> Result<(), ContractError> {
        match self {
            Self::Active | Self::Tombstoned { .. } => Ok(()),
            Self::Superseded { by_event_id } if *by_event_id != 0 && *by_event_id != event_id => {
                Ok(())
            }
            Self::Superseded { .. } => Err(ContractError::Invalid(
                "superseding event id must be distinct and non-zero",
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryEvent {
    pub event_id: EventId,
    pub episode_id: EpisodeId,
    pub scope: MemoryScope,
    pub observed_interval: TimeInterval,
    pub modality_spans: Vec<ModalitySpanRef>,
    pub cross_modal_bindings: Vec<CrossModalBinding>,
    pub semantic_keys: BTreeSet<String>,
    pub provenance: Vec<ProvenanceRef>,
    pub objective_digest: Digest32,
    pub ndu_state_digest: Digest32,
    pub behavior_propensity_ppm: Option<u32>,
    pub lifecycle: MemoryLifecycle,
}

impl MemoryEvent {
    pub fn validate(&self) -> Result<(), ContractError> {
        if self.event_id == 0 || self.episode_id == 0 {
            return Err(ContractError::Invalid(
                "event and episode ids must be non-zero",
            ));
        }
        self.scope.validate()?;
        self.observed_interval.validate()?;
        self.lifecycle.validate_for(self.event_id)?;
        if self.modality_spans.is_empty() || self.modality_spans.len() > MAX_MODALITY_SPANS {
            return Err(ContractError::BoundExceeded("event modality spans"));
        }
        if self.cross_modal_bindings.len() > MAX_BINDINGS {
            return Err(ContractError::BoundExceeded("event bindings"));
        }
        validate_keys(&self.semantic_keys)?;
        if self.provenance.is_empty() || self.provenance.len() > MAX_PROVENANCE {
            return Err(ContractError::BoundExceeded("event provenance"));
        }
        if let Some(value) = self.behavior_propensity_ppm {
            if value == 0 {
                return Err(ContractError::Invalid(
                    "behavior propensity must be positive when present",
                ));
            }
            ppm(value, "behavior propensity")?;
        }
        let mut spans = BTreeMap::new();
        for span in &self.modality_spans {
            span.validate()?;
            if span.privacy_class != self.scope.privacy_class() {
                return Err(ContractError::Conflict(
                    "span privacy class does not match event scope",
                ));
            }
            if spans.insert(span.span_id, span).is_some() {
                return Err(ContractError::Conflict("duplicate span id"));
            }
        }
        let mut binding_ids = BTreeSet::new();
        for binding in &self.cross_modal_bindings {
            if !binding_ids.insert(binding.binding_id) {
                return Err(ContractError::Conflict("duplicate binding id"));
            }
            binding.validate_against(self.event_id, &spans)?;
        }
        let mut sources = BTreeSet::new();
        for provenance in &self.provenance {
            provenance.validate()?;
            if !sources.insert((
                provenance.source_id.as_str(),
                provenance.source_revision,
                provenance.source_sha256.as_str(),
            )) {
                return Err(ContractError::Conflict("duplicate provenance"));
            }
        }
        Ok(())
    }

    pub(crate) fn is_readable(
        &self,
        principal: &crate::PrincipalScope,
        now_unix_ms: i64,
        revoked_sources: &BTreeSet<Digest32>,
    ) -> bool {
        matches!(self.lifecycle, MemoryLifecycle::Active)
            && self.scope.permits(principal)
            && self.observed_interval.contains(now_unix_ms)
            && self
                .provenance
                .iter()
                .all(|source| !revoked_sources.contains(&source.source_sha256))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KernelEventView {
    pub event_id: EventId,
    pub modalities: BTreeSet<ModalityKind>,
    pub source_sha256: BTreeSet<Digest32>,
    pub objective_digest: Digest32,
    pub ndu_state_digest: Digest32,
}

impl TryFrom<&MemoryEvent> for KernelEventView {
    type Error = ContractError;

    fn try_from(value: &MemoryEvent) -> Result<Self, Self::Error> {
        value.validate()?;
        Ok(Self {
            event_id: value.event_id,
            modalities: value
                .modality_spans
                .iter()
                .map(|span| span.modality)
                .collect(),
            source_sha256: value
                .provenance
                .iter()
                .map(|source| source.source_sha256.clone())
                .collect(),
            objective_digest: value.objective_digest.clone(),
            ndu_state_digest: value.ndu_state_digest.clone(),
        })
    }
}

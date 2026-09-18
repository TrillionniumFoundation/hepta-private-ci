use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::CanonicalContractV1;
use super::CanonicalDigestV1;
use super::ContractErrorV1;
use super::CrossModalBindingV1;
use super::EpisodeIdV1;
use super::EventIdV1;
use super::MAX_BINDINGS;
use super::MAX_MODALITY_SPANS;
use super::MAX_PROVENANCE;
use super::MemoryScopeV1;
use super::ModalityKindV1;
use super::ModalitySpanRefV1;
use super::TimeIntervalV1;
use super::validate_nonzero;
use super::validate_semantic_keys;
use super::validate_text;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ProvenanceRefV1 {
    source_id: String,
    source_revision: u64,
    source_sha256: CanonicalDigestV1,
    observed_at_unix_ms: i64,
}

impl ProvenanceRefV1 {
    pub fn try_new(
        source_id: impl Into<String>,
        source_revision: u64,
        source_sha256: CanonicalDigestV1,
        observed_at_unix_ms: i64,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            source_id: source_id.into(),
            source_revision,
            source_sha256,
            observed_at_unix_ms,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_text(&self.source_id, 256, "source id")?;
        validate_nonzero(self.source_revision, "source revision must be non-zero")
    }

    #[must_use]
    pub fn source_id(&self) -> &str {
        &self.source_id
    }

    #[must_use]
    pub const fn source_revision(&self) -> u64 {
        self.source_revision
    }

    #[must_use]
    pub const fn source_sha256(&self) -> &CanonicalDigestV1 {
        &self.source_sha256
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum MemoryLifecycleV1 {
    Active,
    Superseded { by_event_id: EventIdV1 },
    Tombstoned { reason_sha256: CanonicalDigestV1 },
}

impl MemoryLifecycleV1 {
    fn validate_for(&self, event_id: EventIdV1) -> Result<(), ContractErrorV1> {
        match self {
            Self::Active | Self::Tombstoned { .. } => Ok(()),
            Self::Superseded { by_event_id } if *by_event_id != 0 && *by_event_id != event_id => {
                Ok(())
            }
            Self::Superseded { .. } => Err(ContractErrorV1::Invalid(
                "superseding event id must be distinct and non-zero",
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct MemoryEventV1 {
    event_id: EventIdV1,
    episode_id: EpisodeIdV1,
    scope: MemoryScopeV1,
    observed_interval: TimeIntervalV1,
    modality_spans: Vec<ModalitySpanRefV1>,
    cross_modal_bindings: Vec<CrossModalBindingV1>,
    semantic_keys: BTreeSet<String>,
    provenance: Vec<ProvenanceRefV1>,
    objective_digest: CanonicalDigestV1,
    ndu_state_digest: CanonicalDigestV1,
    behavior_propensity_ppm: Option<u32>,
    lifecycle: MemoryLifecycleV1,
}

impl MemoryEventV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        event_id: EventIdV1,
        episode_id: EpisodeIdV1,
        scope: MemoryScopeV1,
        observed_interval: TimeIntervalV1,
        modality_spans: Vec<ModalitySpanRefV1>,
        cross_modal_bindings: Vec<CrossModalBindingV1>,
        semantic_keys: BTreeSet<String>,
        provenance: Vec<ProvenanceRefV1>,
        objective_digest: CanonicalDigestV1,
        ndu_state_digest: CanonicalDigestV1,
        behavior_propensity_ppm: Option<u32>,
        lifecycle: MemoryLifecycleV1,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            event_id,
            episode_id,
            scope,
            observed_interval,
            modality_spans,
            cross_modal_bindings,
            semantic_keys,
            provenance,
            objective_digest,
            ndu_state_digest,
            behavior_propensity_ppm,
            lifecycle,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.event_id, "event id must be non-zero")?;
        validate_nonzero(self.episode_id, "episode id must be non-zero")?;
        self.scope.validate()?;
        self.observed_interval.validate()?;
        self.lifecycle.validate_for(self.event_id)?;
        if self.modality_spans.is_empty() || self.modality_spans.len() > MAX_MODALITY_SPANS {
            return Err(ContractErrorV1::BoundExceeded("event modality spans"));
        }
        if self.cross_modal_bindings.len() > MAX_BINDINGS {
            return Err(ContractErrorV1::BoundExceeded("event bindings"));
        }
        validate_semantic_keys(&self.semantic_keys)?;
        if self.provenance.is_empty() || self.provenance.len() > MAX_PROVENANCE {
            return Err(ContractErrorV1::BoundExceeded("event provenance"));
        }
        if let Some(value) = self.behavior_propensity_ppm {
            if value == 0 || value > super::PPM as u32 {
                return Err(ContractErrorV1::Invalid(
                    "behavior propensity must be within (0, 1_000_000]",
                ));
            }
        }

        let mut spans = BTreeMap::new();
        for span in &self.modality_spans {
            span.validate()?;
            if span.privacy_class() != self.scope.privacy_class() {
                return Err(ContractErrorV1::Conflict(
                    "span privacy class does not match event scope",
                ));
            }
            if spans.insert(span.span_id(), span).is_some() {
                return Err(ContractErrorV1::Conflict("duplicate span id"));
            }
        }

        let mut binding_ids = BTreeSet::new();
        for binding in &self.cross_modal_bindings {
            let encoded = super::canonical_json_bytes(binding)
                .map_err(|_| ContractErrorV1::Invalid("binding canonical encoding"))?;
            let binding_id_key = codex_hepta_types::Digest32::of_bytes(&encoded);
            if !binding_ids.insert(binding_id_key) {
                return Err(ContractErrorV1::Conflict("duplicate binding"));
            }
            binding.validate_against(self.event_id, &spans)?;
        }

        let mut sources = BTreeSet::new();
        for provenance in &self.provenance {
            provenance.validate()?;
            if !sources.insert((
                provenance.source_id().to_owned(),
                provenance.source_revision(),
                provenance.source_sha256().to_string(),
            )) {
                return Err(ContractErrorV1::Conflict("duplicate provenance"));
            }
        }
        Ok(())
    }

    #[must_use]
    pub const fn event_id(&self) -> EventIdV1 {
        self.event_id
    }

    #[must_use]
    pub const fn episode_id(&self) -> EpisodeIdV1 {
        self.episode_id
    }

    #[must_use]
    pub fn modality_spans(&self) -> &[ModalitySpanRefV1] {
        &self.modality_spans
    }

    #[must_use]
    pub fn semantic_keys(&self) -> &BTreeSet<String> {
        &self.semantic_keys
    }

    #[must_use]
    pub fn provenance(&self) -> &[ProvenanceRefV1] {
        &self.provenance
    }

    #[must_use]
    pub const fn objective_digest(&self) -> &CanonicalDigestV1 {
        &self.objective_digest
    }

    #[must_use]
    pub const fn ndu_state_digest(&self) -> &CanonicalDigestV1 {
        &self.ndu_state_digest
    }
}

impl CanonicalContractV1 for MemoryEventV1 {
    const SCHEMA_ID: &'static str = "MemoryEventV1";
    const MAX_ENCODED_BYTES: usize = 262_144;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KernelEventViewV1 {
    pub event_id: EventIdV1,
    pub modalities: BTreeSet<ModalityKindV1>,
    pub source_sha256: BTreeSet<CanonicalDigestV1>,
    pub objective_digest: CanonicalDigestV1,
    pub ndu_state_digest: CanonicalDigestV1,
}

impl TryFrom<&MemoryEventV1> for KernelEventViewV1 {
    type Error = ContractErrorV1;

    fn try_from(value: &MemoryEventV1) -> Result<Self, Self::Error> {
        value.validate()?;
        Ok(Self {
            event_id: value.event_id,
            modalities: value
                .modality_spans
                .iter()
                .map(ModalitySpanRefV1::modality)
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

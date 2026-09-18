use super::*;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProvenanceRefV1 {
    pub source_id: String,
    #[serde(with = "super::exact_u64")]
    pub source_revision: u64,
    pub source_sha256: Sha256DigestV1,
    #[serde(with = "super::exact_i64")]
    pub observed_at_unix_ms: i64,
}

impl ProvenanceRefV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        validate_text(&self.source_id, 256, "source id")?;
        if self.source_revision == 0 {
            return Err(HnmfContractError::Invalid("source revision must be non-zero"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryVerificationStateV1 {
    Unverified,
    Verified,
    Contradicted,
    Revoked,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RetentionPolicyV1 {
    #[serde(with = "super::exact_i64_option")]
    pub expires_unix_ms: Option<i64>,
    pub legal_hold: bool,
    pub session_only: bool,
}

impl RetentionPolicyV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.legal_hold && self.session_only {
            return Err(HnmfContractError::Conflict(
                "legal-hold memory cannot be session-only",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", rename_all_fields = "camelCase", deny_unknown_fields)]
pub enum MemoryLifecycleV1 {
    Active,
    Superseded {
        #[serde(with = "super::exact_u64")]
        by_event_id: EventIdV1,
    },
    Correction {
        #[serde(with = "super::exact_u64")]
        corrects_event_id: EventIdV1,
    },
    Tombstoned { reason_sha256: Sha256DigestV1 },
}

impl MemoryLifecycleV1 {
    fn validate_for(&self, event_id: EventIdV1) -> Result<(), HnmfContractError> {
        match self {
            Self::Active | Self::Tombstoned { .. } => Ok(()),
            Self::Superseded { by_event_id }
                if *by_event_id != 0 && *by_event_id != event_id => Ok(()),
            Self::Correction { corrects_event_id }
                if *corrects_event_id != 0 && *corrects_event_id != event_id => Ok(()),
            Self::Superseded { .. } => Err(HnmfContractError::Invalid(
                "superseding event id must be distinct and non-zero",
            )),
            Self::Correction { .. } => Err(HnmfContractError::Invalid(
                "correction event id must be distinct and non-zero",
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryEventV1 {
    #[serde(with = "super::exact_u64")]
    pub event_id: EventIdV1,
    #[serde(with = "super::exact_u64")]
    pub episode_id: EpisodeIdV1,
    pub scope: MemoryScopeV1,
    pub observed_interval: TimeIntervalV1,
    pub modality_spans: Vec<ModalitySpanRefV1>,
    pub cross_modal_bindings: Vec<CrossModalBindingV1>,
    pub semantic_keys: Vec<String>,
    pub provenance: Vec<ProvenanceRefV1>,
    pub verification: MemoryVerificationStateV1,
    pub retention_policy: RetentionPolicyV1,
    pub objective_digest: Sha256DigestV1,
    pub ndu_state_digest: Sha256DigestV1,
    #[serde(with = "super::exact_u64_vec")]
    pub causal_parent_event_ids: Vec<EventIdV1>,
    #[serde(with = "super::exact_u64_vec")]
    pub temporal_neighbor_event_ids: Vec<EventIdV1>,
    pub behavior_propensity_ppm: Option<u32>,
    pub lifecycle: MemoryLifecycleV1,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for MemoryEventV1 {
    const SCHEMA_ID: &'static str = "MemoryEventV1";
    const MAX_ENCODED_BYTES: usize = 262_144;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.event_id == 0 || self.episode_id == 0 {
            return Err(HnmfContractError::Invalid(
                "event and episode ids must be non-zero",
            ));
        }
        self.scope.validate()?;
        self.observed_interval.validate()?;
        self.lifecycle.validate_for(self.event_id)?;
        self.retention_policy.validate()?;
        if self.modality_spans.is_empty() || self.modality_spans.len() > MAX_MODALITY_SPANS {
            return Err(HnmfContractError::BoundExceeded("event modality spans"));
        }
        if self.cross_modal_bindings.len() > MAX_BINDINGS {
            return Err(HnmfContractError::BoundExceeded("event bindings"));
        }
        validate_sorted_unique_text(&self.semantic_keys, MAX_SEMANTIC_KEYS, "semantic keys")?;
        if self.provenance.is_empty() || self.provenance.len() > MAX_PROVENANCE {
            return Err(HnmfContractError::BoundExceeded("event provenance"));
        }
        validate_sorted_unique_u64_bounded(&self.causal_parent_event_ids, MAX_EVENT_REFS, "causal parents")?;
        validate_sorted_unique_u64_bounded(&self.temporal_neighbor_event_ids, MAX_EVENT_REFS, "temporal neighbors")?;
        if self.causal_parent_event_ids.contains(&self.event_id)
            || self.temporal_neighbor_event_ids.contains(&self.event_id)
        {
            return Err(HnmfContractError::Conflict("event cannot reference itself"));
        }
        if let Some(value) = self.behavior_propensity_ppm {
            if value == 0 {
                return Err(HnmfContractError::Invalid(
                    "behavior propensity must be positive when present",
                ));
            }
            ppm(value, "behavior propensity")?;
        }
        let mut spans = BTreeMap::new();
        for span in &self.modality_spans {
            span.validate()?;
            if span.privacy_class != self.scope.privacy_class() {
                return Err(HnmfContractError::Conflict(
                    "span privacy class does not match event scope",
                ));
            }
            if spans.insert(span.span_id, span).is_some() {
                return Err(HnmfContractError::Conflict("duplicate span id"));
            }
        }
        let mut binding_ids = BTreeSet::new();
        for binding in &self.cross_modal_bindings {
            if !binding_ids.insert(binding.binding_id) {
                return Err(HnmfContractError::Conflict("duplicate binding id"));
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
                return Err(HnmfContractError::Conflict("duplicate provenance"));
            }
        }
        self.authority.validate()
    }
}

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::CanonicalJsonV1;
use super::EventIdV1;
use super::EpisodeIdV1;
use super::HnmfContractError;
use super::MAX_BINDINGS;
use super::MAX_MODALITY_SPANS;
use super::MAX_PROVENANCE;
use super::MAX_SEMANTIC_KEYS;
use super::PrivacyClassV1;
use super::SpanIdV1;
use super::ValidateHnmfV1;
use super::ppm;
use super::validate_keys;
use super::validate_text;
use super::{CrossModalBindingV1, ModalitySpanRefV1};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum MemoryScopeV1 {
    #[non_exhaustive]
    AgentPrivate { agent_id: String },
    #[non_exhaustive]
    WorkspacePrivate {
        agent_id: String,
        #[serde(with = "super::wire::digest")]
        workspace_sha256: Digest32,
    },
}

impl MemoryScopeV1 {
    pub fn agent_private(agent_id: impl Into<String>) -> Result<Self, HnmfContractError> {
        let value = Self::AgentPrivate {
            agent_id: agent_id.into(),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn workspace_private(
        agent_id: impl Into<String>,
        workspace_sha256: Digest32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self::WorkspacePrivate {
            agent_id: agent_id.into(),
            workspace_sha256,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn privacy_class(&self) -> PrivacyClassV1 {
        match self {
            Self::AgentPrivate { .. } => PrivacyClassV1::AgentPrivate,
            Self::WorkspacePrivate { .. } => PrivacyClassV1::WorkspacePrivate,
        }
    }
}

impl ValidateHnmfV1 for MemoryScopeV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        match self {
            Self::AgentPrivate { agent_id } => validate_text(agent_id, 128, "scope agent id"),
            Self::WorkspacePrivate {
                agent_id,
                workspace_sha256,
            } => {
                validate_text(agent_id, 128, "scope agent id")?;
                if workspace_sha256.is_zero() {
                    return Err(HnmfContractError::Invalid(
                        "workspace digest must be non-zero",
                    ));
                }
                Ok(())
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TimeIntervalV1 {
    start_unix_ms: i64,
    end_unix_ms: Option<i64>,
}

impl TimeIntervalV1 {
    pub fn try_new(
        start_unix_ms: i64,
        end_unix_ms: Option<i64>,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            start_unix_ms,
            end_unix_ms,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn start_unix_ms(self) -> i64 {
        self.start_unix_ms
    }
}

impl ValidateHnmfV1 for TimeIntervalV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self
            .end_unix_ms
            .is_some_and(|end| end <= self.start_unix_ms)
        {
            return Err(HnmfContractError::Invalid(
                "time interval end must be greater than start",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProvenanceRefV1 {
    source_id: String,
    source_revision: u64,
    #[serde(with = "super::wire::digest")]
    source_sha256: Digest32,
    observed_at_unix_ms: i64,
}

impl ProvenanceRefV1 {
    pub fn try_new(
        source_id: impl Into<String>,
        source_revision: u64,
        source_sha256: Digest32,
        observed_at_unix_ms: i64,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            source_id: source_id.into(),
            source_revision,
            source_sha256,
            observed_at_unix_ms,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn source_id(&self) -> &str {
        &self.source_id
    }

    pub const fn source_revision(&self) -> u64 {
        self.source_revision
    }

    pub const fn source_sha256(&self) -> Digest32 {
        self.source_sha256
    }
}

impl ValidateHnmfV1 for ProvenanceRefV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        validate_text(&self.source_id, 256, "source id")?;
        if self.source_revision == 0 || self.source_sha256.is_zero() {
            return Err(HnmfContractError::Invalid(
                "source revision and digest must be non-zero",
            ));
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
    #[serde(with = "super::wire::digest")]
    policy_digest: Digest32,
    retain_until_unix_ms: Option<i64>,
    legal_hold: bool,
}

impl RetentionPolicyV1 {
    pub fn try_new(
        policy_digest: Digest32,
        retain_until_unix_ms: Option<i64>,
        legal_hold: bool,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            policy_digest,
            retain_until_unix_ms,
            legal_hold,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for RetentionPolicyV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.policy_digest.is_zero() {
            return Err(HnmfContractError::Invalid(
                "retention policy digest must be non-zero",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum MemoryLifecycleV1 {
    Active,
    #[non_exhaustive]
    Superseded { by_event_id: EventIdV1 },
    #[non_exhaustive]
    Tombstoned {
        #[serde(with = "super::wire::digest")]
        reason_sha256: Digest32,
    },
}

impl MemoryLifecycleV1 {
    pub fn superseded(
        event_id: EventIdV1,
        by_event_id: EventIdV1,
    ) -> Result<Self, HnmfContractError> {
        let value = Self::Superseded { by_event_id };
        value.validate_for(event_id)?;
        Ok(value)
    }

    pub fn tombstoned(reason_sha256: Digest32) -> Result<Self, HnmfContractError> {
        let value = Self::Tombstoned { reason_sha256 };
        value.validate_for(0)?;
        Ok(value)
    }

    fn validate_for(&self, event_id: EventIdV1) -> Result<(), HnmfContractError> {
        match self {
            Self::Active => Ok(()),
            Self::Superseded { by_event_id } if *by_event_id != 0 && *by_event_id != event_id => {
                Ok(())
            }
            Self::Superseded { .. } => Err(HnmfContractError::Invalid(
                "superseding event id must be distinct and non-zero",
            )),
            Self::Tombstoned { reason_sha256 } if !reason_sha256.is_zero() => Ok(()),
            Self::Tombstoned { .. } => Err(HnmfContractError::Invalid(
                "tombstone reason digest must be non-zero",
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryEventV1 {
    event_id: EventIdV1,
    episode_id: EpisodeIdV1,
    scope: MemoryScopeV1,
    observed_interval: TimeIntervalV1,
    modality_spans: Vec<ModalitySpanRefV1>,
    cross_modal_bindings: Vec<CrossModalBindingV1>,
    semantic_keys: BTreeSet<String>,
    provenance: Vec<ProvenanceRefV1>,
    verification: MemoryVerificationStateV1,
    retention_policy: RetentionPolicyV1,
    #[serde(with = "super::wire::digest")]
    objective_digest: Digest32,
    #[serde(with = "super::wire::digest")]
    ndu_state_digest: Digest32,
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
        verification: MemoryVerificationStateV1,
        retention_policy: RetentionPolicyV1,
        objective_digest: Digest32,
        ndu_state_digest: Digest32,
        behavior_propensity_ppm: Option<u32>,
        lifecycle: MemoryLifecycleV1,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            event_id,
            episode_id,
            scope,
            observed_interval,
            modality_spans,
            cross_modal_bindings,
            semantic_keys,
            provenance,
            verification,
            retention_policy,
            objective_digest,
            ndu_state_digest,
            behavior_propensity_ppm,
            lifecycle,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn event_id(&self) -> EventIdV1 {
        self.event_id
    }

    pub const fn episode_id(&self) -> EpisodeIdV1 {
        self.episode_id
    }

    pub fn modality_spans(&self) -> &[ModalitySpanRefV1] {
        &self.modality_spans
    }

    pub fn provenance(&self) -> &[ProvenanceRefV1] {
        &self.provenance
    }
}

impl ValidateHnmfV1 for MemoryEventV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.event_id == 0 || self.episode_id == 0 {
            return Err(HnmfContractError::Invalid(
                "event and episode ids must be non-zero",
            ));
        }
        self.scope.validate()?;
        self.observed_interval.validate()?;
        self.retention_policy.validate()?;
        self.lifecycle.validate_for(self.event_id)?;
        if self.modality_spans.is_empty() || self.modality_spans.len() > MAX_MODALITY_SPANS {
            return Err(HnmfContractError::BoundExceeded("event modality spans"));
        }
        if self.cross_modal_bindings.len() > MAX_BINDINGS {
            return Err(HnmfContractError::BoundExceeded("event bindings"));
        }
        validate_keys(&self.semantic_keys, MAX_SEMANTIC_KEYS, "event semantic keys")?;
        if self.provenance.is_empty() || self.provenance.len() > MAX_PROVENANCE {
            return Err(HnmfContractError::BoundExceeded("event provenance"));
        }
        if self.objective_digest.is_zero() || self.ndu_state_digest.is_zero() {
            return Err(HnmfContractError::Invalid(
                "objective and NDU digests must be non-zero",
            ));
        }
        if let Some(value) = self.behavior_propensity_ppm {
            if value == 0 {
                return Err(HnmfContractError::Invalid(
                    "behavior propensity must be positive when present",
                ));
            }
            ppm(value, "behavior propensity")?;
        }
        if matches!(self.verification, MemoryVerificationStateV1::Revoked)
            && !matches!(self.lifecycle, MemoryLifecycleV1::Tombstoned { .. })
        {
            return Err(HnmfContractError::Conflict(
                "revoked event must be tombstoned",
            ));
        }
        if self
            .retention_policy
            .retain_until_unix_ms
            .is_some_and(|end| end <= self.observed_interval.start_unix_ms())
            && !self.retention_policy.legal_hold
        {
            return Err(HnmfContractError::Invalid(
                "retention end must be after event start unless legal hold applies",
            ));
        }
        let mut spans: BTreeMap<SpanIdV1, &ModalitySpanRefV1> = BTreeMap::new();
        for span in &self.modality_spans {
            span.validate()?;
            if span.privacy_class() != self.scope.privacy_class() {
                return Err(HnmfContractError::Conflict(
                    "span privacy class does not match event scope",
                ));
            }
            if spans.insert(span.span_id(), span).is_some() {
                return Err(HnmfContractError::Conflict("duplicate span id"));
            }
        }
        let mut binding_ids = BTreeSet::new();
        for binding in &self.cross_modal_bindings {
            if !binding_ids.insert(binding.binding_id()) {
                return Err(HnmfContractError::Conflict("duplicate binding id"));
            }
            binding.validate_against(self.event_id, &spans)?;
        }
        let mut sources = BTreeSet::new();
        for provenance in &self.provenance {
            provenance.validate()?;
            if !sources.insert((
                provenance.source_id(),
                provenance.source_revision(),
                provenance.source_sha256(),
            )) {
                return Err(HnmfContractError::Conflict("duplicate provenance"));
            }
        }
        Ok(())
    }
}

impl CanonicalJsonV1 for MemoryEventV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.memory-event.v1";
    const MAX_ENCODED_BYTES: usize = 262_144;
}

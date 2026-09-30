//! Canonical evidence result values without opening or linking a durable store.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::fmt;

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct EvidenceId(String);

impl EvidenceId {
    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        StableId::new(value.clone()).map_err(|error| error.to_string())?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for EvidenceId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        Self::parse(String::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}

impl fmt::Display for EvidenceId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClaimClassV1 {
    ExactSource,
    SyntheticMerge,
    MandatoryTests,
    Fixture,
    Hardware,
    Causal,
    Longitudinal,
    SecurityResource,
    ProviderEffect,
    IndependentDecision,
    Conformance,
    AlgorithmFault,
    Runtime,
    Outbox,
    Reconciliation,
    Unlearning,
    OperatorAcceptance,
    RegistrySnapshot,
}

impl EvidenceClaimClassV1 {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ExactSource => "exact_source",
            Self::SyntheticMerge => "synthetic_merge",
            Self::MandatoryTests => "mandatory_tests",
            Self::Fixture => "fixture",
            Self::Hardware => "hardware",
            Self::Causal => "causal",
            Self::Longitudinal => "longitudinal",
            Self::SecurityResource => "security_resource",
            Self::ProviderEffect => "provider_effect",
            Self::IndependentDecision => "independent_decision",
            Self::Conformance => "conformance",
            Self::AlgorithmFault => "algorithm_fault",
            Self::Runtime => "runtime",
            Self::Outbox => "outbox",
            Self::Reconciliation => "reconciliation",
            Self::Unlearning => "unlearning",
            Self::OperatorAcceptance => "operator_acceptance",
            Self::RegistrySnapshot => "registry_snapshot",
        }
    }

    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "exact_source" => Ok(Self::ExactSource),
            "synthetic_merge" => Ok(Self::SyntheticMerge),
            "mandatory_tests" => Ok(Self::MandatoryTests),
            "fixture" => Ok(Self::Fixture),
            "hardware" => Ok(Self::Hardware),
            "causal" => Ok(Self::Causal),
            "longitudinal" => Ok(Self::Longitudinal),
            "security_resource" => Ok(Self::SecurityResource),
            "provider_effect" => Ok(Self::ProviderEffect),
            "independent_decision" => Ok(Self::IndependentDecision),
            "conformance" => Ok(Self::Conformance),
            "algorithm_fault" => Ok(Self::AlgorithmFault),
            "runtime" => Ok(Self::Runtime),
            "outbox" => Ok(Self::Outbox),
            "reconciliation" => Ok(Self::Reconciliation),
            "unlearning" => Ok(Self::Unlearning),
            "operator_acceptance" => Ok(Self::OperatorAcceptance),
            "registry_snapshot" => Ok(Self::RegistrySnapshot),
            _ => Err("unknown qualification evidence claim class".to_string()),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceReceiptKindV1 {
    Evidence,
    Correction,
    Revocation,
}

impl EvidenceReceiptKindV1 {
    #[cfg(feature = "runtime")]
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Evidence => "evidence",
            Self::Correction => "correction",
            Self::Revocation => "revocation",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceIssuerRoleV1 {
    Generator,
    Evaluator,
    Reviewer,
    Architecture,
    Durability,
    Learning,
    Security,
    Operator,
    Documentation,
    TerminalObserver,
    ProductWriter,
    Selector,
    Loader,
}

impl EvidenceIssuerRoleV1 {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Generator => "generator",
            Self::Evaluator => "evaluator",
            Self::Reviewer => "reviewer",
            Self::Architecture => "architecture",
            Self::Durability => "durability",
            Self::Learning => "learning",
            Self::Security => "security",
            Self::Operator => "operator",
            Self::Documentation => "documentation",
            Self::TerminalObserver => "terminal_observer",
            Self::ProductWriter => "product_writer",
            Self::Selector => "selector",
            Self::Loader => "loader",
        }
    }

    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "generator" => Ok(Self::Generator),
            "evaluator" => Ok(Self::Evaluator),
            "reviewer" => Ok(Self::Reviewer),
            "architecture" => Ok(Self::Architecture),
            "durability" => Ok(Self::Durability),
            "learning" => Ok(Self::Learning),
            "security" => Ok(Self::Security),
            "operator" => Ok(Self::Operator),
            "documentation" => Ok(Self::Documentation),
            "terminal_observer" => Ok(Self::TerminalObserver),
            "product_writer" => Ok(Self::ProductWriter),
            "selector" => Ok(Self::Selector),
            "loader" => Ok(Self::Loader),
            _ => Err("unknown qualification evidence issuer role".to_string()),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceReferenceV1 {
    pub evidence_id: EvidenceId,
    pub claim_class: EvidenceClaimClassV1,
    pub receipt_kind: EvidenceReceiptKindV1,
    pub issuer_role: EvidenceIssuerRoleV1,
    pub issuer_principal_id: String,
    pub payload_sha256: Sha256Digest,
    pub envelope_sha256: Sha256Digest,
    pub predecessor_evidence_id: Option<EvidenceId>,
    pub target_evidence_id: Option<EvidenceId>,
    pub observed_unix_ms: u64,
    pub expires_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum EvidenceDispositionV1 {
    Supported {
        evidence: Vec<EvidenceReferenceV1>,
    },
    Missing,
    Expired {
        evidence: Vec<EvidenceReferenceV1>,
    },
    Conflicting {
        evidence: Vec<EvidenceReferenceV1>,
        reason: String,
    },
}

#[cfg(test)]
#[path = "qualification_types_tests.rs"]
mod tests;

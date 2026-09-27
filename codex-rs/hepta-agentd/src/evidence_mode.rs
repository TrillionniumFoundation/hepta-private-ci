use std::path::PathBuf;
use std::sync::OnceLock;

use codex_hepta_types::StableId;

use crate::AgentdError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvidenceRuntimeMode {
    Development,
    Production,
}

impl EvidenceRuntimeMode {
    pub fn parse(value: &str) -> Result<Self, AgentdError> {
        match value {
            "development" => Ok(Self::Development),
            "production" => Ok(Self::Production),
            _ => Err(AgentdError::Invalid(
                "--evidence-mode must be development or production".to_string(),
            )),
        }
    }

    #[must_use]
    pub const fn is_production(self) -> bool {
        matches!(self, Self::Production)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceProductionAdmissionFiles {
    pub backend_identity_file: PathBuf,
    pub build_identity_file: PathBuf,
    pub qualification_status_file: PathBuf,
    pub backup_publication_file: PathBuf,
    pub local_rollback_domain_id: String,
}

impl EvidenceProductionAdmissionFiles {
    fn validate(&self) -> Result<(), AgentdError> {
        StableId::new(self.local_rollback_domain_id.clone()).map_err(|error| {
            AgentdError::Invalid(format!(
                "invalid kernel.evidence local rollback-domain id: {error}"
            ))
        })?;
        for (label, path) in [
            ("backend identity", &self.backend_identity_file),
            ("build identity", &self.build_identity_file),
            ("qualification status", &self.qualification_status_file),
            ("backup publication", &self.backup_publication_file),
        ] {
            if !path.is_absolute() {
                return Err(AgentdError::Invalid(format!(
                    "kernel.evidence production {label} file must use an absolute path"
                )));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceRuntimePolicy {
    pub mode: EvidenceRuntimeMode,
    pub production: Option<EvidenceProductionAdmissionFiles>,
}

impl EvidenceRuntimePolicy {
    #[must_use]
    pub const fn development() -> Self {
        Self {
            mode: EvidenceRuntimeMode::Development,
            production: None,
        }
    }

    pub fn production(
        files: EvidenceProductionAdmissionFiles,
    ) -> Result<Self, AgentdError> {
        files.validate()?;
        Ok(Self {
            mode: EvidenceRuntimeMode::Production,
            production: Some(files),
        })
    }

    /// Validate runtime capabilities, not merely the syntax of supplied files.
    ///
    /// The current product has no live external frontier transport or durable
    /// append/publication fence. Local JSON assertions cannot substitute for
    /// those capabilities, even when signed and placed outside Agent home.
    /// Keep production unavailable until that product path exists and is
    /// qualified. There is deliberately no environment or boolean override.
    pub fn validate_startup(&self) -> Result<(), AgentdError> {
        self.validate()?;
        if self.mode.is_production() {
            return Err(AgentdError::Invalid(
                "kernel.evidence production unavailable: live authenticated frontier backend \
                 and durable append/publication fence are not installed; admission files \
                 alone cannot prove external freshness or durability"
                    .to_string(),
            ));
        }
        Ok(())
    }

    pub fn validate(&self) -> Result<(), AgentdError> {
        match (self.mode, self.production.as_ref()) {
            (EvidenceRuntimeMode::Development, None) => Ok(()),
            (EvidenceRuntimeMode::Production, Some(files)) => files.validate(),
            (EvidenceRuntimeMode::Development, Some(_)) => Err(AgentdError::Invalid(
                "kernel.evidence production files cannot be supplied in development mode"
                    .to_string(),
            )),
            (EvidenceRuntimeMode::Production, None) => Err(AgentdError::Invalid(
                "kernel.evidence production mode requires external admission files".to_string(),
            )),
        }
    }
}

static EVIDENCE_RUNTIME_POLICY: OnceLock<EvidenceRuntimePolicy> = OnceLock::new();

/// Set the one-process Agentd evidence policy exactly once. A caller cannot
/// replace a production policy with development after startup validation.
pub fn configure_evidence_runtime_policy(
    policy: EvidenceRuntimePolicy,
) -> Result<(), AgentdError> {
    policy.validate_startup()?;
    EVIDENCE_RUNTIME_POLICY.set(policy).map_err(|_| {
        AgentdError::Invalid("kernel.evidence runtime policy is already configured".to_string())
    })
}

pub(crate) fn evidence_runtime_policy() -> EvidenceRuntimePolicy {
    EVIDENCE_RUNTIME_POLICY
        .get()
        .cloned()
        .unwrap_or_else(EvidenceRuntimePolicy::development)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn production_requires_all_external_admission_files() {
        let policy = EvidenceRuntimePolicy {
            mode: EvidenceRuntimeMode::Production,
            production: None,
        };
        assert!(policy.validate().is_err());
    }

    #[test]
    fn development_rejects_hidden_production_inputs() {
        let policy = EvidenceRuntimePolicy {
            mode: EvidenceRuntimeMode::Development,
            production: Some(EvidenceProductionAdmissionFiles {
                backend_identity_file: PathBuf::from("/external/backend.json"),
                build_identity_file: PathBuf::from("/external/build.json"),
                qualification_status_file: PathBuf::from("/external/status.json"),
                backup_publication_file: PathBuf::from("/external/backup.json"),
                local_rollback_domain_id: "rollback:local-evidence".to_string(),
            }),
        };
        assert!(policy.validate().is_err());
    }
}

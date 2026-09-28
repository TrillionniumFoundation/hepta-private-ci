//! Public capability classification for the three inference.worker surfaces.
//!
//! These values are claim ceilings. They do not turn source presence or a
//! passing repository test into deployment, promotion or release authority.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkerProfile {
    HostedAppServerWorker,
    LocalModelWorker,
    LegacyReceiptBoundary,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProfileReadiness {
    /// Repository production candidate; target-host qualification, independent
    /// acceptance, activation and release remain separate external gates.
    ProductionCandidate,
    /// Opt-in source surface that must not be used as production evidence.
    ExperimentalNonProduction,
    /// Pure validation/receipt boundary; it never proves provider execution.
    ValidationOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProfileStatus {
    pub profile: WorkerProfile,
    pub readiness: ProfileReadiness,
    pub feature: Option<&'static str>,
    pub provider_execution_claim: bool,
    pub local_weights_claim: bool,
}

pub const HOSTED_APP_SERVER_STATUS: ProfileStatus = ProfileStatus {
    profile: WorkerProfile::HostedAppServerWorker,
    readiness: ProfileReadiness::ProductionCandidate,
    feature: None,
    provider_execution_claim: true,
    local_weights_claim: false,
};

pub const LOCAL_MODEL_STATUS: ProfileStatus = ProfileStatus {
    profile: WorkerProfile::LocalModelWorker,
    readiness: ProfileReadiness::ExperimentalNonProduction,
    feature: Some("local-model-experimental"),
    provider_execution_claim: false,
    local_weights_claim: false,
};

pub const LEGACY_RECEIPT_STATUS: ProfileStatus = ProfileStatus {
    profile: WorkerProfile::LegacyReceiptBoundary,
    readiness: ProfileReadiness::ValidationOnly,
    feature: None,
    provider_execution_claim: false,
    local_weights_claim: false,
};

pub const PROFILE_STATUSES: [ProfileStatus; 3] = [
    HOSTED_APP_SERVER_STATUS,
    LOCAL_MODEL_STATUS,
    LEGACY_RECEIPT_STATUS,
];

#[must_use]
pub const fn profile_status(profile: WorkerProfile) -> ProfileStatus {
    match profile {
        WorkerProfile::HostedAppServerWorker => HOSTED_APP_SERVER_STATUS,
        WorkerProfile::LocalModelWorker => LOCAL_MODEL_STATUS,
        WorkerProfile::LegacyReceiptBoundary => LEGACY_RECEIPT_STATUS,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_model_never_claims_production_or_physical_weights() {
        let status = profile_status(WorkerProfile::LocalModelWorker);
        assert_eq!(status.readiness, ProfileReadiness::ExperimentalNonProduction);
        assert_eq!(status.feature, Some("local-model-experimental"));
        assert!(!status.provider_execution_claim);
        assert!(!status.local_weights_claim);
    }

    #[test]
    fn legacy_boundary_is_validation_only() {
        let status = profile_status(WorkerProfile::LegacyReceiptBoundary);
        assert_eq!(status.readiness, ProfileReadiness::ValidationOnly);
        assert!(!status.provider_execution_claim);
    }
}

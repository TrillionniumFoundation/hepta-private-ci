//! Public capability and maturity declarations for inference.worker.
//!
//! These declarations are intentionally conservative. Source presence, unit
//! tests or a validation receipt cannot upgrade a profile into production
//! execution evidence.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkerProfile {
    HostedAppServerWorker,
    LocalModelWorker,
    LegacyReceiptBoundary,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProfileMaturity {
    ProductionCandidate,
    ExperimentalNonProduction,
    ValidationOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProfileStatus {
    pub profile: WorkerProfile,
    pub maturity: ProfileMaturity,
    pub feature: Option<&'static str>,
    pub exported_by_default: bool,
    pub may_supply_product_execution_evidence: bool,
}

pub const HOSTED_APP_SERVER_WORKER: ProfileStatus = ProfileStatus {
    profile: WorkerProfile::HostedAppServerWorker,
    maturity: ProfileMaturity::ProductionCandidate,
    feature: None,
    exported_by_default: true,
    may_supply_product_execution_evidence: true,
};

pub const LOCAL_MODEL_WORKER: ProfileStatus = ProfileStatus {
    profile: WorkerProfile::LocalModelWorker,
    maturity: ProfileMaturity::ExperimentalNonProduction,
    feature: Some("experimental-local-model"),
    exported_by_default: false,
    may_supply_product_execution_evidence: false,
};

pub const LEGACY_RECEIPT_BOUNDARY: ProfileStatus = ProfileStatus {
    profile: WorkerProfile::LegacyReceiptBoundary,
    maturity: ProfileMaturity::ValidationOnly,
    feature: None,
    exported_by_default: true,
    may_supply_product_execution_evidence: false,
};

pub const ALL_PROFILE_STATUSES: [ProfileStatus; 3] = [
    HOSTED_APP_SERVER_WORKER,
    LOCAL_MODEL_WORKER,
    LEGACY_RECEIPT_BOUNDARY,
];

#[must_use]
pub const fn status(profile: WorkerProfile) -> ProfileStatus {
    match profile {
        WorkerProfile::HostedAppServerWorker => HOSTED_APP_SERVER_WORKER,
        WorkerProfile::LocalModelWorker => LOCAL_MODEL_WORKER,
        WorkerProfile::LegacyReceiptBoundary => LEGACY_RECEIPT_BOUNDARY,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_hosted_profile_can_supply_product_execution_evidence() {
        let admitted = ALL_PROFILE_STATUSES
            .iter()
            .filter(|status| status.may_supply_product_execution_evidence)
            .map(|status| status.profile)
            .collect::<Vec<_>>();
        assert_eq!(admitted, vec![WorkerProfile::HostedAppServerWorker]);
    }

    #[test]
    fn local_model_profile_is_feature_gated_and_nonproduction() {
        assert_eq!(
            LOCAL_MODEL_WORKER.maturity,
            ProfileMaturity::ExperimentalNonProduction
        );
        assert_eq!(LOCAL_MODEL_WORKER.feature, Some("experimental-local-model"));
        assert!(!LOCAL_MODEL_WORKER.exported_by_default);
        assert!(!LOCAL_MODEL_WORKER.may_supply_product_execution_evidence);
    }

    #[test]
    fn legacy_receipt_boundary_is_validation_only() {
        assert_eq!(
            LEGACY_RECEIPT_BOUNDARY.maturity,
            ProfileMaturity::ValidationOnly
        );
        assert!(!LEGACY_RECEIPT_BOUNDARY.may_supply_product_execution_evidence);
    }
}

//! Public capability boundary for `inference.worker`.
//!
//! A profile status is a source claim only. It does not grant runtime,
//! deployment, promotion, independent acceptance, or release authority.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkerProfile {
    HostedAppServer,
    LocalModel,
    LegacyReceipt,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProfileMaturity {
    /// Source candidate with a real named provider path and durable no-replay
    /// semantics. Target-host and independent acceptance remain external gates.
    ProductionCandidate,
    /// Compiles only when the explicit Cargo feature is selected and must not
    /// be treated as production evidence.
    Experimental,
    /// Pure validation/receipt logic. It does not execute a provider.
    ValidationOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProfileStatus {
    pub profile: WorkerProfile,
    pub maturity: ProfileMaturity,
    pub cargo_feature: Option<&'static str>,
    pub executes_provider: bool,
    pub production_implementation: bool,
}

pub const PROFILE_STATUS: [ProfileStatus; 3] = [
    ProfileStatus {
        profile: WorkerProfile::HostedAppServer,
        maturity: ProfileMaturity::ProductionCandidate,
        cargo_feature: None,
        executes_provider: true,
        production_implementation: false,
    },
    ProfileStatus {
        profile: WorkerProfile::LocalModel,
        maturity: ProfileMaturity::Experimental,
        cargo_feature: Some("experimental-local-model"),
        executes_provider: true,
        production_implementation: false,
    },
    ProfileStatus {
        profile: WorkerProfile::LegacyReceipt,
        maturity: ProfileMaturity::ValidationOnly,
        cargo_feature: None,
        executes_provider: false,
        production_implementation: false,
    },
];

#[must_use]
pub const fn status(profile: WorkerProfile) -> ProfileStatus {
    match profile {
        WorkerProfile::HostedAppServer => PROFILE_STATUS[0],
        WorkerProfile::LocalModel => PROFILE_STATUS[1],
        WorkerProfile::LegacyReceipt => PROFILE_STATUS[2],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_status_does_not_overclaim_any_profile() {
        assert_eq!(
            status(WorkerProfile::HostedAppServer).maturity,
            ProfileMaturity::ProductionCandidate
        );
        assert_eq!(
            status(WorkerProfile::LocalModel).cargo_feature,
            Some("experimental-local-model")
        );
        assert!(
            !PROFILE_STATUS
                .iter()
                .any(|entry| entry.production_implementation)
        );
        assert!(!status(WorkerProfile::LegacyReceipt).executes_provider);
    }
}

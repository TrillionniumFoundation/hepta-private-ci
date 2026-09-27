//! Profile classification is descriptive, never runtime or release authority.

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

impl WorkerProfile {
    pub const fn maturity(self) -> ProfileMaturity {
        match self {
            Self::HostedAppServerWorker => ProfileMaturity::ProductionCandidate,
            Self::LocalModelWorker => ProfileMaturity::ExperimentalNonProduction,
            Self::LegacyReceiptBoundary => ProfileMaturity::ValidationOnly,
        }
    }

    pub const fn compiled(self) -> bool {
        match self {
            Self::HostedAppServerWorker | Self::LegacyReceiptBoundary => true,
            Self::LocalModelWorker => cfg!(feature = "experimental-local-worker"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn experimental_feature_never_promotes_profile_maturity() {
        assert_eq!(
            WorkerProfile::LocalModelWorker.maturity(),
            ProfileMaturity::ExperimentalNonProduction
        );
        assert_eq!(
            WorkerProfile::LocalModelWorker.compiled(),
            cfg!(feature = "experimental-local-worker")
        );
        assert_eq!(
            WorkerProfile::LegacyReceiptBoundary.maturity(),
            ProfileMaturity::ValidationOnly
        );
    }
}

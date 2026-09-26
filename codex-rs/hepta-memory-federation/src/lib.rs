//! Scoped, fail-closed cognitive federation verification.

#![forbid(unsafe_code)]

mod v2;

#[cfg(feature = "legacy-v1")]
#[deprecated(
    since = "0.0.0",
    note = "V1 is compatibility-only; product code must use the canonical V2 surface"
)]
pub mod legacy_v1;

pub use v2::FederatedCompletenessV2;
pub use v2::FederatedCoverageV2;
pub use v2::FederatedEvidenceItemV2;
pub use v2::FederatedFailureCoverageV2;
pub use v2::FederatedLeaseV2;
pub use v2::FederatedQueryV2;
pub use v2::FederatedResultV2;
pub use v2::FederatedValidityV2;
pub use v2::FederationAttemptControlV2;
pub use v2::FederationAuthorityFuture;
pub use v2::FederationAuthorityObservationV2;
pub use v2::FederationAuthorityStateV2;
pub use v2::FederationAuthorityV2;
pub use v2::FederationCancellationReceiptV2;
pub use v2::FederationCancellationRequestV2;
pub use v2::FederationStopFuture;
pub use v2::FederationStopReasonV2;
pub use v2::FederationTransportFuture;
pub use v2::FederationTransportOutcomeV2;
pub use v2::FederationTransportResultV2;
pub use v2::FederationTransportV2;
pub use v2::FederationV2Error;
pub use v2::MAX_FEDERATED_RESULTS_V2;
pub use v2::RemoteFederatedResponseV2;
pub use v2::execute_once;
pub use v2::observe_cancellation;

#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::Error;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedReadLease;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedReadReceipt;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedReadRequest;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedStatus;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::RemoteObservation;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::observe;

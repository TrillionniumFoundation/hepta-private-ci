//! Canonical wire registrations for Shared Experience V2 contracts.
//!
//! Kept separate from `wire.rs` so the shared-experience contract family can be
//! compiled, tested, and reviewed as an explicit extension without weakening the
//! canonical envelope implementation.

use crate::hnmf::HnmfContractError;
use crate::shared_experience::SharedExperiencePublicationV2;
use crate::shared_experience::SharedExperienceRevocationReceiptV2;
use crate::shared_experience::SharedExperienceSnapshotV2;
use crate::shared_experience::SharedExperienceUseReceiptV2;
use crate::wire::CognitiveContractV1;

macro_rules! impl_shared_contract {
    ($type:ty, $contract:literal, $schema:literal, $maximum:expr, $validate:expr) => {
        impl CognitiveContractV1 for $type {
            const CONTRACT_ID: &'static str = $contract;
            const SCHEMA_ID: &'static str = $schema;
            const MAX_ENCODED_BYTES: usize = $maximum;

            fn validate_contract(&self) -> Result<(), HnmfContractError> {
                ($validate)(self)
            }
        }
    };
}

impl_shared_contract!(
    SharedExperiencePublicationV2,
    "SharedExperiencePublicationV2",
    "hepta.shared-experience.publication.v2",
    262_144,
    SharedExperiencePublicationV2::validate
);
impl_shared_contract!(
    SharedExperienceSnapshotV2,
    "SharedExperienceSnapshotV2",
    "hepta.shared-experience.snapshot.v2",
    1_048_576,
    SharedExperienceSnapshotV2::validate
);
impl_shared_contract!(
    SharedExperienceUseReceiptV2,
    "SharedExperienceUseReceiptV2",
    "hepta.shared-experience.use-receipt.v2",
    65_536,
    SharedExperienceUseReceiptV2::validate
);
impl_shared_contract!(
    SharedExperienceRevocationReceiptV2,
    "SharedExperienceRevocationReceiptV2",
    "hepta.shared-experience.revocation-receipt.v2",
    1_048_576,
    SharedExperienceRevocationReceiptV2::validate
);

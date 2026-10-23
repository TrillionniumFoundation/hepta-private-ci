//! Additive verifier for the full provenance joined to a signed V1 projection.

use std::fs::File;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerVerifierV1;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryHeadRequirementV1;
use crate::RegistrySnapshotReceipt;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

impl ArtifactOwnerVerifierV1 {
    /// Authenticate CURRENT and join every complete admission to its immutable
    /// manifest digest in the signed registry. The withdrawal frontier must be
    /// independently authenticated by the deployment's dataset authority or
    /// recovered from the owner's signed state-publication checkpoints; it must
    /// not be reconstructed as a trust anchor from a suspect snapshot.
    ///
    /// This enforces all parents, dataset inputs and expiry at `requirement.now`.
    /// Missing sidecars require exact backfill or a new explicitly admitted
    /// compatibility consumer; they never imply dataset independence.
    pub fn verify_current_registry_view_with_admission_closure(
        &self,
        snapshot_file: File,
        snapshot_receipt: RegistrySnapshotReceipt,
        signed_head: &SignedCurrentArtifactHeadV1,
        requirement: &RegistryHeadRequirementV1,
        admissions: Vec<WithdrawalBoundArtifactAdmissionV3>,
        withdrawals: &DatasetWithdrawalRegistry,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        if withdrawals.scope_digest() != Some(signed_head.withdrawal_scope_digest) {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        self.verify_current_registry_view(
            snapshot_file,
            snapshot_receipt,
            signed_head,
            requirement,
        )?
        .with_admission_closure(admissions, withdrawals, requirement.now)
        .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)
    }
}

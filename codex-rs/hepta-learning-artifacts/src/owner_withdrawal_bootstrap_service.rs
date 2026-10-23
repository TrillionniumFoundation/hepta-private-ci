//! Signed withdrawal bootstrap before the first artifact publication.
use super::*;
use crate::ArtifactWithdrawalBootstrapReceiptV1;
use crate::LearningArtifactWithdrawalBootstrapRequestV1;
impl LearningArtifactOwnerService {
    pub fn publish_withdrawal_bootstrap(
        &mut self,
        request: LearningArtifactWithdrawalBootstrapRequestV1,
        now: u64,
    ) -> Result<ArtifactWithdrawalBootstrapReceiptV1, LearningArtifactOwnerServiceError> {
        if let Some(operation) = &self.recovery_required {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                operation.clone(),
            ));
        }
        if request.binding != self.storage_binding {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let result =
            self.host
                .publish_bootstrap_withdrawal(&request, &self.withdrawal_registry, now);
        match self
            .host
            .recover_bootstrap_withdrawals(self.withdrawal_registry.clone(), self.storage_binding)
        {
            Ok(frontier) => self.withdrawal_registry = frontier,
            Err(error) => {
                self.recovery_required = Some(request.operation_id);
                return Err(error.into());
            }
        }
        result.map_err(Into::into)
    }
}

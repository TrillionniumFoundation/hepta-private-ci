//! A sealed admission from the original Root publication, not policy data.

use super::*;
use crate::authority_host_service::generation_publication::RootPreparedPublicationGrantV1;

impl DeploymentFinalUseIssuer {
    pub(crate) fn issue_original_publication_final_use(
        &self,
        admitted: RootPreparedPublicationGrantV1<'_>,
    ) -> io::Result<Option<SignedFinalUseGrant>> {
        let (binding, registration, proof, expiry) = admitted.into_original_parts();
        self.issue_registered_final_use(&binding, registration, proof, expiry)
    }
}

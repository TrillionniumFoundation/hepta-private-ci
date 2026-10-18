//! sqlite runtime ingress implementation.

use super::*;

impl SqliteBaoProductRuntimeV1 {
    pub async fn consume_kv_v2_with_authbus<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        read: BaoApprovedReadV1<'_>,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let started = Instant::now();
        let result = self
            .host
            .consume_kv_v2_with_authbus_sqlite(
                client,
                authbus,
                &self.owner,
                &self.config,
                read,
                evidence,
            )
            .await;
        self.host.record_forward_metric(started, &result);
        result
    }
}

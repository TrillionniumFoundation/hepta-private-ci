//! provider final use dispatch implementation.

use super::*;

impl BaoClient {
    /// Crate-private typed final-delivery gate used by the registered host.
    /// Provider I/O and secret validation complete first, then kernel authority
    /// is revalidated and this gate executes at the final consumer boundary.
    pub(crate) async fn consume_kv_v2_guarded<E>(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        prepare_delivery: impl FnOnce(&BaoSecretReceipt) -> Result<(), E>,
        consumer: impl FnOnce(&[u8], &BaoSecretReceipt) -> Result<(), E>,
    ) -> Result<Result<BaoSecretReceipt, E>, BaoClientError> {
        match self
            .consume_kv_v2_guarded_async(
                authority,
                grant,
                request,
                |receipt| std::future::ready(prepare_delivery(receipt)),
                consumer,
            )
            .await?
        {
            Ok(receipt) => Ok(Ok(receipt)),
            Err(BaoGuardedDeliveryError::Preparation(error))
            | Err(BaoGuardedDeliveryError::Consumer(error)) => Ok(Err(error)),
        }
    }

    /// Async durable preparation variant used by the SQLite product owner. The
    /// preparation future completes before the final live-authority check and
    /// before any secret byte enters the registered consumer.
    pub(crate) async fn consume_kv_v2_guarded_async<
        PreparationError,
        ConsumerError,
        Prepare,
        PrepareFuture,
    >(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        prepare_delivery: Prepare,
        consumer: impl FnOnce(&[u8], &BaoSecretReceipt) -> Result<(), ConsumerError>,
    ) -> Result<
        Result<BaoSecretReceipt, BaoGuardedDeliveryError<PreparationError, ConsumerError>>,
        BaoClientError,
    >
    where
        Prepare: FnOnce(&BaoSecretReceipt) -> PrepareFuture,
        PrepareFuture: Future<Output = Result<(), PreparationError>>,
    {
        let binding = self.binding(request)?;
        let mut url = self.origin.clone();
        {
            let mut parts = url
                .path_segments_mut()
                .map_err(|_| BaoClientError::InvalidRequest)?;
            parts.clear().push("v1");
            for part in request.mount.split('/') {
                parts.push(part);
            }
            parts.push("data");
            for part in request.path.split('/') {
                parts.push(part);
            }
        }
        url.query_pairs_mut()
            .append_pair("version", &request.version.to_string());
        let mut token = HeaderValue::from_str(&self.token.0)
            .map_err(|_| BaoClientError::InvalidConfiguration)?;
        token.set_sensitive(true);
        let mut network_request = self
            .client
            .get(url)
            .header("X-Vault-Token", token)
            .header("Accept", "application/json");
        if !request.namespace.is_empty() {
            network_request = network_request.header("X-Vault-Namespace", &request.namespace);
        }
        let verified =
            claim_final_use(authority, grant, &binding).map_err(BaoClientError::Authority)?;
        #[cfg(all(test, unix))]
        crate::saga_crash::cut("provider_response.before");
        let mut response = network_request.send().await.map_err(transport_error)?;
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                return Err(BaoClientError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => return Err(BaoClientError::NotFound),
            _ => return Err(BaoClientError::ProviderUnavailable),
        }
        if response
            .content_length()
            .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
        {
            return Err(BaoClientError::ResponseTooLarge);
        }
        // Allocate the bounded buffer before plaintext arrives. Growing a Vec
        // can leave earlier secret-bearing allocations unzeroized even when
        // the final allocation is wrapped in Zeroizing.
        let mut body = Zeroizing::new(Vec::with_capacity(MAX_RESPONSE_BYTES));
        while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
            if chunk.len() > MAX_RESPONSE_BYTES - body.len() {
                return Err(BaoClientError::ResponseTooLarge);
            }
            body.extend_from_slice(&chunk);
        }
        let decoded: KvResponse =
            serde_json::from_slice(&body).map_err(|_| BaoClientError::InvalidResponse)?;
        if decoded.data.metadata.version != request.version {
            return Err(BaoClientError::VersionMismatch);
        }
        let secret = decoded
            .data
            .data
            .get(&request.field)
            .ok_or(BaoClientError::InvalidResponse)?;
        let digest = Digest32::of_bytes(secret.as_bytes()).into_array();
        if digest != request.expected_secret_sha256 {
            return Err(BaoClientError::SecretDigestMismatch);
        }
        let receipt = BaoSecretReceipt {
            request_sha256: binding.request_sha256,
            response_sha256: Digest32::of_bytes(&body).into_array(),
            secret_sha256: digest,
            version: request.version,
            secret_bytes: secret.len(),
        };
        #[cfg(all(test, unix))]
        crate::saga_crash::cut("provider_response.after");
        #[cfg(all(test, unix))]
        crate::saga_crash::cut("delivery_preparation.before");
        if let Err(error) = prepare_delivery(&receipt).await {
            return Ok(Err(BaoGuardedDeliveryError::Preparation(error)));
        }
        #[cfg(all(test, unix))]
        crate::saga_crash::cut("delivery_preparation.after");
        // Durable delivery preparation happens before the final authority check.
        match deliver_final_use(authority, verified, &binding, || {
            #[cfg(all(test, unix))]
            crate::saga_crash::cut("consumer_entry.before");
            let result = consumer(secret.as_bytes(), &receipt);
            #[cfg(all(test, unix))]
            crate::saga_crash::cut("consumer_entry.after");
            result
        })
        .map_err(BaoClientError::Authority)?
        {
            Ok(()) => Ok(Ok(receipt)),
            Err(error) => Ok(Err(BaoGuardedDeliveryError::Consumer(error))),
        }
    }
}

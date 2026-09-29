use super::*;

impl BaoClient {
    /// Claim a kernel permit, fetch exactly one version, then deliver only to
    /// the supplied trusted in-process consumer under a live revocation fence.
    /// No automatic retry occurs. The consumer must not reenter the authority.
    pub async fn consume_kv_v2(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoSecretReceipt, BaoClientError> {
        match self
            .consume_kv_v2_guarded(authority, grant, request, consumer)
            .await?
        {
            Ok(receipt) => Ok(receipt),
            Err(()) => Err(BaoClientError::ConsumerIndeterminate),
        }
    }

    /// Crate-private typed final-delivery gate used by the registered host.
    /// Provider I/O and secret validation complete first, then kernel authority
    /// is revalidated and this gate executes at the final consumer boundary.
    pub(crate) async fn consume_kv_v2_guarded<E>(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        consumer: impl FnOnce(&[u8]) -> Result<(), E>,
    ) -> Result<Result<BaoSecretReceipt, E>, BaoClientError> {
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
        let mut body = Zeroizing::new(Vec::new());
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
        match deliver_final_use(authority, verified, &binding, || {
            consumer(secret.as_bytes())
        })
        .map_err(BaoClientError::Authority)?
        {
            Ok(()) => Ok(Ok(receipt)),
            Err(error) => Ok(Err(error)),
        }
    }
}


#[derive(Deserialize)]
struct KvResponse {
    data: KvPayload,
}
#[derive(Deserialize)]
struct KvPayload {
    data: BTreeMap<String, Zeroizing<String>>,
    metadata: KvMetadata,
}
#[derive(Deserialize)]
struct KvMetadata {
    version: u64,
}

fn transport_error(error: HttpError) -> BaoClientError {
    if error.is_timeout() {
        BaoClientError::TimedOut
    } else {
        BaoClientError::TransportUnavailable
    }
}


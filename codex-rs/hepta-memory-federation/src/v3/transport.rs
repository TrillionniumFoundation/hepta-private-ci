#[derive(Clone, Debug)]
pub struct FederationCancellationTokenV3 {
    cancelled: Arc<AtomicBool>,
    notify: Arc<tokio::sync::Notify>,
}

impl Default for FederationCancellationTokenV3 {
    fn default() -> Self {
        Self {
            cancelled: Arc::new(AtomicBool::new(false)),
            notify: Arc::new(tokio::sync::Notify::new()),
        }
    }
}

impl FederationCancellationTokenV3 {
    pub fn cancel(&self) {
        if !self.cancelled.swap(true, Ordering::AcqRel) {
            self.notify.notify_waiters();
        }
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    pub async fn cancelled(&self) {
        if self.is_cancelled() {
            return;
        }
        let notified = self.notify.notified();
        if self.is_cancelled() {
            return;
        }
        notified.await;
    }
}

pub trait FederationTransportV3: Send + Sync {
    fn send_once<'a>(
        &'a self,
        attempt: FederatedAttemptV3,
        cancellation: FederationCancellationTokenV3,
    ) -> BoxFuture<'a, Result<FederationTransportResultV3, FederationV3Error>>;
}

#[derive(Clone, Debug)]
pub struct PinnedHttpsFederationTransportV3 {
    path: &'static str,
    maximum_response_bytes: usize,
}

impl Default for PinnedHttpsFederationTransportV3 {
    fn default() -> Self {
        Self {
            path: FEDERATION_QUERY_PATH_V3,
            maximum_response_bytes: MAX_FEDERATION_RESPONSE_BYTES_V3,
        }
    }
}

impl FederationTransportV3 for PinnedHttpsFederationTransportV3 {
    fn send_once<'a>(
        &'a self,
        attempt: FederatedAttemptV3,
        cancellation: FederationCancellationTokenV3,
    ) -> BoxFuture<'a, Result<FederationTransportResultV3, FederationV3Error>> {
        async move {
            if cancellation.is_cancelled() {
                return Ok(FederationTransportResultV3::NonTerminal(
                    FederationTransportOutcomeV3::Cancelled,
                ));
            }
            let now = system_now_unix_ms()?;
            if now >= attempt.query.deadline_unix_ms {
                return Ok(FederationTransportResultV3::NonTerminal(
                    FederationTransportOutcomeV3::TimedOut,
                ));
            }
            let remaining = attempt.query.deadline_unix_ms - now;
            let client = HttpClientBuilder::build_pinned_https_direct(
                &attempt.enrollment.ca_pem,
                Duration::from_millis(remaining),
            )
            .map_err(|_| FederationV3Error::InvalidPeerEnrollment)?;
            let origin = Url::parse(&attempt.enrollment.endpoint)
                .map_err(|_| FederationV3Error::InvalidPeerEnrollment)?;
            let url = origin
                .join(self.path)
                .map_err(|_| FederationV3Error::InvalidPeerEnrollment)?;
            let wire = FederationWireRequestV3::from_attempt(&attempt);
            let mut response = client
                .post(url)
                .header("Accept", "application/json")
                .json(&wire)
                .send()
                .await
                .map_err(transport_error)?;
            if cancellation.is_cancelled() {
                return Ok(FederationTransportResultV3::NonTerminal(
                    FederationTransportOutcomeV3::Cancelled,
                ));
            }
            match response.status().as_u16() {
                200 => {}
                408 | 504 => {
                    return Ok(FederationTransportResultV3::NonTerminal(
                        FederationTransportOutcomeV3::TimedOut,
                    ));
                }
                429 | 502 | 503 => {
                    return Ok(FederationTransportResultV3::NonTerminal(
                        FederationTransportOutcomeV3::Unavailable,
                    ));
                }
                401 | 403 => return Err(FederationV3Error::TransportRejected),
                _ => return Err(FederationV3Error::InvalidRemoteEnvelope),
            }
            if response
                .content_length()
                .is_some_and(|value| value > self.maximum_response_bytes as u64)
            {
                return Err(FederationV3Error::ResponseTooLarge);
            }
            let mut body = Vec::new();
            while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
                if cancellation.is_cancelled() {
                    return Ok(FederationTransportResultV3::NonTerminal(
                        FederationTransportOutcomeV3::Cancelled,
                    ));
                }
                if chunk.len() > self.maximum_response_bytes.saturating_sub(body.len()) {
                    return Err(FederationV3Error::ResponseTooLarge);
                }
                body.extend_from_slice(&chunk);
            }
            let wire: RemoteFederatedEnvelopeWireV3 = serde_json::from_slice(&body)
                .map_err(|_| FederationV3Error::InvalidRemoteEnvelope)?;
            Ok(FederationTransportResultV3::Terminal(wire.try_into_domain()?))
        }
        .boxed()
    }
}

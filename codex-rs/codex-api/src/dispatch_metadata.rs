use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;

use crate::encoded_body_observer::EncodedRequestBodyObserver;

/// Shared witness that a prepared request reached its transport invocation.
///
/// `false` proves the host may classify an aborted attempt as not dispatched.
/// `true` is deliberately conservative: it means the transport was invoked,
/// not that bytes reached a remote peer, so an unobserved outcome is
/// indeterminate rather than safely retryable.
#[derive(Clone, Default)]
pub struct RequestDispatchMetadata {
    transport_invoked: Arc<AtomicBool>,
    expected_headers: Arc<Vec<(HeaderName, Option<HeaderValue>)>>,
    final_request_observer: Arc<OnceLock<Arc<dyn EncodedRequestBodyObserver>>>,
    final_request_observation_required: Arc<AtomicBool>,
}

impl RequestDispatchMetadata {
    pub fn new() -> Self {
        Self::default()
    }

    /// Creates a dispatch witness that also guards host-admitted header state.
    ///
    /// Validation runs after authentication has produced the authoritative
    /// request and before transport invocation. Values are retained only in
    /// memory and are never logged or serialized by this type.
    pub fn new_with_expected_headers(
        expected_headers: Vec<(HeaderName, Option<HeaderValue>)>,
    ) -> Self {
        Self {
            transport_invoked: Arc::new(AtomicBool::new(false)),
            expected_headers: Arc::new(expected_headers),
            final_request_observer: Arc::new(OnceLock::new()),
            final_request_observation_required: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn transport_invoked(&self) -> bool {
        self.transport_invoked.load(Ordering::Acquire)
    }

    /// Marks this physical attempt as requiring an exact-body observation.
    ///
    /// The send path fails closed when this bit is set but no observer is
    /// installed. The bit is monotonic for all shared clones.
    pub fn require_final_request_observation(&self) {
        self.final_request_observation_required
            .store(true, Ordering::Release);
    }

    /// Installs the single final-use observer for the exact encoded body.
    ///
    /// All clones share the same once-cell. A second installation is rejected
    /// so no later policy layer can replace the observer admitted for this
    /// physical attempt.
    pub fn install_final_request_observer(
        &self,
        observer: Arc<dyn EncodedRequestBodyObserver>,
    ) -> Result<(), String> {
        self.final_request_observer.set(observer).map_err(|_| {
            "final request observer was already installed for this provider attempt".to_owned()
        })
    }

    pub(crate) fn final_request_observer(
        &self,
    ) -> Result<Option<Arc<dyn EncodedRequestBodyObserver>>, String> {
        let observer = self.final_request_observer.get().cloned();
        if observer.is_none()
            && self
                .final_request_observation_required
                .load(Ordering::Acquire)
        {
            return Err(
                "final request observation was required but no observer was installed".to_owned(),
            );
        }
        Ok(observer)
    }

    pub(crate) fn validate_headers(&self, headers: &HeaderMap) -> Result<(), String> {
        for (name, expected) in self.expected_headers.iter() {
            let mut actual = headers.get_all(name).iter();
            let matches = match expected {
                Some(expected) => actual.next() == Some(expected) && actual.next().is_none(),
                None => actual.next().is_none(),
            };
            if !matches {
                return Err(format!(
                    "request header state changed after provider policy admission: {name}"
                ));
            }
        }
        Ok(())
    }

    pub(crate) fn mark_transport_invoked(&self) {
        self.transport_invoked.store(true, Ordering::Release);
    }
}

#[cfg(test)]
mod tests {
    use std::fmt;
    use std::sync::Arc;

    use futures::future::BoxFuture;
    use http::HeaderMap;
    use http::HeaderName;
    use http::HeaderValue;

    use crate::encoded_body_observer::EncodedRequestBodyObserver;

    use super::RequestDispatchMetadata;

    const ROUTING_HINT: HeaderName = HeaderName::from_static("x-codex-routing-hint");

    struct TestObserver;

    impl fmt::Debug for TestObserver {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("TestObserver")
        }
    }

    impl EncodedRequestBodyObserver for TestObserver {
        fn observe_encoded_body<'a>(
            &'a self,
            _body: &'a [u8],
        ) -> BoxFuture<'a, Result<(), String>> {
            Box::pin(std::future::ready(Ok(())))
        }
    }

    #[test]
    fn exact_expected_header_state_is_accepted() {
        let metadata = RequestDispatchMetadata::new_with_expected_headers(vec![(
            ROUTING_HINT,
            Some(HeaderValue::from_static("host-hint")),
        )]);
        let mut headers = HeaderMap::new();
        headers.insert(ROUTING_HINT, HeaderValue::from_static("host-hint"));

        metadata
            .validate_headers(&headers)
            .expect("exact admitted header should remain valid");
    }

    #[test]
    fn absent_overridden_and_duplicate_header_states_are_rejected() {
        let expected_present = RequestDispatchMetadata::new_with_expected_headers(vec![(
            ROUTING_HINT,
            Some(HeaderValue::from_static("host-hint")),
        )]);
        assert!(
            expected_present
                .validate_headers(&HeaderMap::new())
                .is_err()
        );

        let mut overridden = HeaderMap::new();
        overridden.insert(ROUTING_HINT, HeaderValue::from_static("auth-hint"));
        assert!(expected_present.validate_headers(&overridden).is_err());

        let expected_absent =
            RequestDispatchMetadata::new_with_expected_headers(vec![(ROUTING_HINT, None)]);
        assert!(expected_absent.validate_headers(&overridden).is_err());

        let mut duplicate = HeaderMap::new();
        duplicate.append(ROUTING_HINT, HeaderValue::from_static("host-hint"));
        duplicate.append(ROUTING_HINT, HeaderValue::from_static("host-hint"));
        assert!(expected_present.validate_headers(&duplicate).is_err());
    }

    #[test]
    fn final_request_observer_is_shared_and_single_assignment() {
        let metadata = RequestDispatchMetadata::new();
        let clone = metadata.clone();
        metadata
            .install_final_request_observer(Arc::new(TestObserver))
            .expect("first observer installation");
        assert!(clone.final_request_observer().expect("observer state").is_some());
        assert!(
            clone
                .install_final_request_observer(Arc::new(TestObserver))
                .is_err()
        );
    }
}

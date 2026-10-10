use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;

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
        }
    }

    pub fn transport_invoked(&self) -> bool {
        self.transport_invoked.load(Ordering::Acquire)
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
    use http::HeaderMap;
    use http::HeaderName;
    use http::HeaderValue;

    use super::RequestDispatchMetadata;

    const ROUTING_HINT: HeaderName = HeaderName::from_static("x-codex-routing-hint");

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
}

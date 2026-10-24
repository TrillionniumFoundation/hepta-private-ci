#![allow(
    clippy::expect_used,
    reason = "controlled diagnostic fixtures fail loudly"
)]

use super::*;
use crate::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use http::HeaderMap;
use http::HeaderValue;
use http::StatusCode;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

const SECRET: &str = "DO_NOT_RETAIN_URL_AUTH_HEADER_OR_BODY";

#[test]
fn http_diagnostic_retains_only_numeric_status_and_static_category() {
    let mut headers = HeaderMap::new();
    headers.insert("authorization", HeaderValue::from_static(SECRET));
    let error = ApiError::Transport(TransportError::Http {
        status: StatusCode::TOO_MANY_REQUESTS,
        url: Some(format!("https://{SECRET}/responses")),
        headers: Some(headers),
        body: Some(SECRET.into()),
    });
    let safe = ResponsesFailure::from_api(ResponsesFailureStage::Request, &error);
    assert_eq!(safe.category, ResponsesFailureCategory::TransportHttp);
    assert_eq!(safe.http_status, Some(429));
    assert_eq!(safe.to_string(), "request:transport_http (HTTP 429)");
    assert!(!format!("{safe:?} {safe}").contains(SECRET));
    assert!(!format!("{safe:?} {safe}").contains("https://"));
}

#[test]
fn all_upstream_message_fields_are_discarded_without_displaying_the_error() {
    for error in [
        ApiError::Api {
            status: StatusCode::BAD_REQUEST,
            message: SECRET.into(),
        },
        ApiError::Stream(SECRET.into()),
        ApiError::Retryable {
            message: SECRET.into(),
            delay: Some(std::time::Duration::from_secs(2)),
        },
        ApiError::RateLimit(SECRET.into()),
        ApiError::InvalidRequest {
            message: SECRET.into(),
        },
        ApiError::CyberPolicy {
            message: SECRET.into(),
        },
        ApiError::MisalignmentPolicyViolation {
            message: SECRET.into(),
        },
        ApiError::Transport(TransportError::Network(SECRET.into())),
        ApiError::Transport(TransportError::Build(SECRET.into())),
    ] {
        let safe = ResponsesFailure::from_api(ResponsesFailureStage::Stream, &error);
        let loop_error = Error::Responses(safe);
        assert!(!format!("{loop_error:?} {loop_error}").contains(SECRET));
        assert_eq!(safe.stage, ResponsesFailureStage::Stream);
    }
}

struct Turn {
    frame: Frame,
    writes: usize,
}

impl TurnOwner for Turn {
    async fn load(&mut self, _: &TurnBinding) -> Result<Frame> {
        Ok(self.frame.clone())
    }

    async fn commit(&mut self, _: &Frame, _: Transition) -> Result<Frame> {
        self.writes += 1;
        Err(Error::Owner("unexpected diagnostic cursor write".into()))
    }
}

struct Inference {
    failure: ResponsesFailure,
    opens: usize,
    cancels: usize,
}

impl InferenceOwner for Inference {
    async fn open_or_reconcile(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
    ) -> Result<ModelSession> {
        self.opens += 1;
        Err(Error::Responses(self.failure))
    }

    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancels += 1;
        Ok(StopObservation::Unresolved)
    }
}

#[derive(Default)]
struct Effects {
    calls: usize,
    cancels: usize,
}

impl EffectOwner for Effects {
    async fn execute_or_observe(
        &mut self,
        _: &TurnBinding,
        _: Digest32,
        _: &ToolCall,
    ) -> Result<EffectObservation> {
        self.calls += 1;
        Ok(EffectObservation::Unresolved)
    }

    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancels += 1;
        Ok(StopObservation::Unresolved)
    }
}

#[tokio::test]
async fn typed_provider_failure_preserves_original_owner_error_recovery_behavior() {
    let id = |value: &str| StableId::new(value).expect("controlled ID");
    let binding = TurnBinding {
        run_id: id("diagnostic-run"),
        turn_id: id("diagnostic-turn"),
        generation: Generation::new(1).expect("generation"),
        admission_digest: Digest32::of_bytes(b"controlled admission"),
        deadline_unix_ms: u64::MAX,
    };
    let initial = Frame {
        binding: binding.clone(),
        revision: 0,
        round: 0,
        consumed_tokens: 0,
        phase: Phase::Model(ModelRequest {
            request_id: id("diagnostic-request"),
            payload: "diagnostic input".into(),
            context_digest: Digest32::of_bytes(b"diagnostic input"),
            input_tokens: 1,
            maximum_provider_input_tokens: 8,
            maximum_output_tokens: 8,
        }),
    };
    let failure = ResponsesFailure {
        stage: ResponsesFailureStage::Request,
        category: ResponsesFailureCategory::TransportHttp,
        http_status: Some(503),
    };
    let mut turn = Turn {
        frame: initial.clone(),
        writes: 0,
    };
    let mut inference = Inference {
        failure,
        opens: 0,
        cancels: 0,
    };
    let mut effects = Effects::default();
    let result = run(
        &mut turn,
        &mut inference,
        &mut effects,
        &binding,
        &Limits::default(),
        &CancellationToken::new(),
    )
    .await;
    assert!(
        matches!(&result, Err(Error::Responses(observed)) if *observed == failure),
        "{result:?}"
    );
    assert_eq!(turn.frame, initial);
    assert_eq!(turn.writes, 0);
    assert_eq!(inference.opens, 1);
    assert_eq!(inference.cancels, 0);
    assert_eq!(effects.calls, 0);
    assert_eq!(effects.cancels, 0);
}

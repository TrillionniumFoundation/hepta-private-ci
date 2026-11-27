use anyhow::Result;
use codex_client::HttpClientBuilder;
use codex_client::Request;
use codex_client::RetryOn;
use codex_client::RetryPolicy;
use codex_client::TransportError;
use codex_client::run_with_retry;
use http::HeaderMap;
use http::HeaderValue;
use http::Method;
use http::StatusCode;
use pretty_assertions::assert_eq;
use std::cell::RefCell;
use std::rc::Rc;
use std::time::Duration;

fn policy(bits: u8) -> RetryOn {
    RetryOn {
        retry_429: bits & 1 != 0,
        retry_5xx: bits & 2 != 0,
        retry_transport: bits & 4 != 0,
    }
}

fn http_error(status: u16) -> Result<TransportError> {
    let mut headers = HeaderMap::new();
    headers.insert("x-original-error", HeaderValue::from_static("retained"));
    Ok(TransportError::Http {
        status: StatusCode::from_u16(status)?,
        url: Some("https://example.invalid/original".to_owned()),
        headers: Some(headers),
        body: Some("original é中 error".to_owned()),
    })
}

#[test]
fn literal_http_policy_matrix_preserves_status_edges_and_u64_limits() -> Result<()> {
    let never = [false; 8];
    let rate = [false, true, false, true, false, true, false, true];
    let server = [false, false, true, true, false, false, true, true];
    let rows = [
        (100, never),
        (200, never),
        (299, never),
        (400, never),
        (428, never),
        (429, rate),
        (430, never),
        (499, never),
        (500, server),
        (503, server),
        (599, server),
        (600, never),
        (999, never),
    ];
    let limits = [
        (0, 0, false),
        (0, 1, true),
        (1, 1, false),
        (1, 2, true),
        (u64::MAX - 1, u64::MAX, true),
        (u64::MAX, u64::MAX, false),
        (u64::MAX, 0, false),
    ];
    for (status, expected) in rows {
        let error = http_error(status)?;
        for bits in 0..8_u8 {
            let retry = policy(bits);
            for (attempt, max_attempts, remains) in limits {
                assert_eq!(
                    retry.should_retry(&error, attempt, max_attempts),
                    remains && expected[usize::from(bits)],
                    "status {status}, policy {bits}, attempt {attempt}, limit {max_attempts}"
                );
            }
        }
    }
    Ok(())
}

#[test]
fn every_transport_error_variant_obeys_only_its_original_policy() -> Result<()> {
    // A malformed certificate constructs a real opaque HttpError locally.
    // Its inner classification is intentionally irrelevant to Connection.
    let connection = match HttpClientBuilder::build_pinned_https_direct(
        b"not a PEM certificate",
        Duration::ZERO,
    ) {
        Ok(_) => panic!("the malformed certificate fixture unexpectedly built a client"),
        Err(error) => TransportError::Connection(error),
    };
    let transport = [false, false, false, false, true, true, true, true];
    let never = [false; 8];
    let rows = [
        (TransportError::Timeout, transport),
        (connection, transport),
        (TransportError::Network("é中".to_owned()), transport),
        (TransportError::Build("opaque".to_owned()), never),
        (TransportError::RetryLimit, never),
    ];
    for (error, expected) in rows {
        for bits in 0..8_u8 {
            let retry = policy(bits);
            assert_eq!(
                retry.should_retry(&error, /*attempt*/ 0, /*max_attempts*/ 1),
                expected[usize::from(bits)]
            );
            assert!(!retry.should_retry(&error, u64::MAX, u64::MAX));
        }
    }
    Ok(())
}

#[tokio::test]
async fn retries_preserve_request_and_operation_order_then_stop_on_success() -> Result<()> {
    let events = Rc::new(RefCell::new(Vec::new()));
    let make_events = Rc::clone(&events);
    let op_events = Rc::clone(&events);
    let retry_policy = RetryPolicy {
        max_attempts: 5,
        base_delay: Duration::ZERO,
        retry_on: policy(/*bits*/ 4),
    };
    let output = run_with_retry(
        retry_policy,
        move || {
            make_events.borrow_mut().push("make".to_owned());
            Request::new(Method::POST, "https://example.invalid/provider".to_owned())
        },
        move |request, attempt| {
            op_events.borrow_mut().push(format!("op:{attempt}"));
            async move {
                assert_eq!(request.method, Method::POST);
                assert_eq!(request.url, "https://example.invalid/provider");
                if attempt < 2 {
                    Err(TransportError::Network(format!("retry:{attempt}")))
                } else {
                    Ok("original response".to_owned())
                }
            }
        },
    )
    .await?;
    assert_eq!(output, "original response");
    assert_eq!(
        *events.borrow(),
        ["make", "op:0", "make", "op:1", "make", "op:2"]
    );
    Ok(())
}

#[tokio::test]
async fn inclusive_limit_returns_last_original_error_without_an_extra_request() {
    let attempts = Rc::new(RefCell::new(Vec::new()));
    let observed = Rc::clone(&attempts);
    let result = run_with_retry(
        RetryPolicy {
            max_attempts: 3,
            base_delay: Duration::ZERO,
            retry_on: policy(/*bits*/ 4),
        },
        || Request::new(Method::GET, "https://example.invalid/provider".to_owned()),
        move |_request, attempt| {
            observed.borrow_mut().push(attempt);
            async move { Err::<(), _>(TransportError::Network(format!("last:{attempt}"))) }
        },
    )
    .await;
    assert_eq!(*attempts.borrow(), [0, 1, 2, 3]);
    match result {
        Err(TransportError::Network(message)) => assert_eq!(message, "last:3"),
        other => panic!("expected the last original network error, got {other:?}"),
    }
}

#[tokio::test]
async fn zero_limit_and_nonretryable_error_preserve_opaque_allocation() -> Result<()> {
    for maximum in [0, u64::MAX] {
        let body = "é".repeat(1_048_577);
        let allocation = body.as_ptr();
        let error = Rc::new(RefCell::new(Some(TransportError::Http {
            status: StatusCode::BAD_REQUEST,
            url: Some("https://example.invalid/original".to_owned()),
            headers: None,
            body: Some(body),
        })));
        let result = run_with_retry(
            RetryPolicy {
                max_attempts: maximum,
                base_delay: Duration::ZERO,
                retry_on: policy(/*bits*/ 7),
            },
            || Request::new(Method::GET, "https://example.invalid/provider".to_owned()),
            move |_request, attempt| {
                assert_eq!(attempt, 0);
                let next = match error.borrow_mut().take() {
                    Some(error) => error,
                    None => panic!("a nonretryable error created a second request"),
                };
                async move { Err::<(), _>(next) }
            },
        )
        .await;
        match result {
            Err(TransportError::Http {
                status,
                url,
                headers,
                body: Some(body),
            }) => {
                assert_eq!(
                    (status, url, headers, body.len(), body.as_ptr()),
                    (
                        StatusCode::BAD_REQUEST,
                        Some("https://example.invalid/original".to_owned()),
                        None,
                        2_097_154,
                        allocation
                    )
                );
            }
            other => panic!("expected the original opaque HTTP error, got {other:?}"),
        }
    }
    Ok(())
}

#[tokio::test]
async fn dropping_a_pending_attempt_does_not_construct_a_retry() {
    let events = Rc::new(RefCell::new(Vec::new()));
    let make_events = Rc::clone(&events);
    let op_events = Rc::clone(&events);
    let future = run_with_retry(
        RetryPolicy {
            max_attempts: u64::MAX,
            base_delay: Duration::ZERO,
            retry_on: policy(/*bits*/ 7),
        },
        move || {
            make_events.borrow_mut().push("make");
            Request::new(Method::GET, "https://example.invalid/provider".to_owned())
        },
        move |_request, attempt| {
            assert_eq!(attempt, 0);
            op_events.borrow_mut().push("pending");
            std::future::pending::<Result<(), TransportError>>()
        },
    );
    let mut task = tokio_test::task::spawn(future);
    assert!(task.poll().is_pending());
    drop(task);
    assert_eq!(*events.borrow(), ["make", "pending"]);
}

#[tokio::test(start_paused = true)]
async fn dropping_during_backoff_does_not_construct_a_retry() {
    let events = Rc::new(RefCell::new(Vec::new()));
    let make_events = Rc::clone(&events);
    let op_events = Rc::clone(&events);
    let future = run_with_retry(
        RetryPolicy {
            max_attempts: 3,
            base_delay: Duration::from_secs(60),
            retry_on: policy(/*bits*/ 4),
        },
        move || {
            make_events.borrow_mut().push("make".to_owned());
            Request::new(Method::GET, "https://example.invalid/provider".to_owned())
        },
        move |_request, attempt| {
            op_events.borrow_mut().push(format!("op:{attempt}"));
            async { Err::<(), _>(TransportError::Network("first attempt".to_owned())) }
        },
    );
    let mut task = tokio_test::task::spawn(future);
    assert!(task.poll().is_pending());
    assert_eq!(*events.borrow(), ["make", "op:0"]);

    // The unchanged first backoff is 60 seconds with 0.9..1.1 jitter.
    // A point below its minimum must still be within the pending sleep.
    tokio::time::advance(Duration::from_secs(53)).await;
    assert!(task.poll().is_pending());
    assert_eq!(*events.borrow(), ["make", "op:0"]);

    drop(task);
    tokio::time::advance(Duration::from_secs(120)).await;
    assert_eq!(*events.borrow(), ["make", "op:0"]);
}

use super::*;

async fn required_lease(
    host: crate::ProviderRequestEnforcementHost,
) -> (
    TempDir,
    Arc<HeptaEvidenceStore>,
    codex_hepta_contracts::ProviderInvocationIntent,
    Box<dyn codex_extension_api::ModelProviderAttemptLease>,
) {
    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let mut state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    state.provider_request_required = true;
    state.provider_request_host = Some(host);
    let (session, thread, turn) = stores();
    let digests = digests(b"endpoint");
    let invocation = input(
        &session,
        &thread,
        &turn,
        "encoded-attempt",
        "encoded-binding",
        &digests,
    );
    let intent = provider_intent(&invocation).expect("intent");
    let ModelProviderPolicyDecision::Allow { lease } =
        state.begin_provider(invocation).await.expect("begin")
    else {
        panic!("first attempt")
    };
    (temp, evidence, intent, lease)
}

#[tokio::test]
async fn required_encoded_request_rejects_missing_host_without_shadow_fallback() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let mut state = GovernanceState::enabled(GovernanceMode::Shadow, Ok(evidence.clone()));
    state.provider_request_required = true;
    let (session, thread, turn) = stores();
    let digests = digests(b"endpoint");
    let decision = state
        .begin_provider(input(
            &session,
            &thread,
            &turn,
            "missing-host",
            "missing-host-binding",
            &digests,
        ))
        .await
        .expect("typed decision");
    assert!(
        matches!(decision, ModelProviderPolicyDecision::Block { ref reason_code, .. }
        if reason_code == "hepta_provider_request_host_required")
    );
    assert_eq!(
        evidence
            .pending_provider_attempt_count()
            .await
            .expect("pending"),
        0
    );
}

#[tokio::test]
async fn required_encoded_request_cannot_complete_without_binding() {
    let (_temp, evidence, expected, lease) =
        required_lease(crate::ProviderRequestEnforcementHost::from_fn(|_, _, _| {
            Box::pin(async { Ok(()) })
        }))
        .await;
    assert!(lease.finish(completed()).await.is_err());
    let stored = evidence
        .get_provider_attempt(&expected.attempt_id)
        .await
        .expect("read")
        .expect("attempt")
        .receipt
        .expect("original attempt settled once");
    assert!(matches!(
        stored.receipt.terminal,
        StoredTerminal::Indeterminate { .. }
    ));
}

#[tokio::test]
async fn required_encoded_request_persists_exact_body_with_original_attempt_on_cold_read() {
    let observed = Arc::new(std::sync::Mutex::new(None));
    let capture = observed.clone();
    let (temp, evidence, intent, mut lease) = required_lease(
        crate::ProviderRequestEnforcementHost::from_fn(move |intent, digest, bytes| {
            *capture.lock().expect("capture") = Some((intent, digest, bytes));
            Box::pin(async { Ok(()) })
        }),
    )
    .await;
    let raw_body = b"entire compiled request bytes";
    let body = api_digest(raw_body);
    let bytes = u64::try_from(raw_body.len()).expect("length");
    assert!(lease.encoded_body_required());
    lease
        .bind_encoded_body_v1(body.clone(), bytes)
        .await
        .expect("bind");
    for digest in [body.clone(), api_digest(b"different body")] {
        assert!(lease.bind_encoded_body_v1(digest, bytes).await.is_err());
    }
    lease.finish(completed()).await.expect("complete");
    assert_eq!(
        *observed.lock().expect("capture"),
        Some((intent.clone(), body.clone(), bytes))
    );
    evidence.as_ref().clone().close().await;
    let cold = HeptaEvidenceStore::open_existing_read_only(&sqlite_config(&temp))
        .await
        .expect("cold open");
    assert_eq!(
        cold.get_provider_encoded_request_v1(&intent)
            .await
            .expect("cold binding"),
        Some((Sha256Digest::parse(body.as_str()).expect("digest"), bytes))
    );
    assert!(matches!(
        cold.get_provider_attempt(&intent.attempt_id)
            .await
            .expect("read")
            .expect("attempt")
            .receipt
            .expect("receipt")
            .receipt
            .terminal,
        StoredTerminal::Completed { .. }
    ));
}

#[tokio::test]
async fn required_encoded_request_unavailable_host_never_persists_body_or_completes() {
    let (_temp, evidence, intent, mut lease) =
        required_lease(crate::ProviderRequestEnforcementHost::unavailable()).await;
    let raw_body = b"body";
    let bytes = u64::try_from(raw_body.len()).expect("length");
    let error = lease
        .bind_encoded_body_v1(api_digest(raw_body), bytes)
        .await
        .expect_err("unavailable");
    assert_eq!(
        error.reason_code(),
        "hepta_provider_request_host_unavailable"
    );
    assert!(
        evidence
            .get_provider_encoded_request_v1(&intent)
            .await
            .expect("binding")
            .is_none()
    );
    assert!(lease.finish(completed()).await.is_err());
    assert!(matches!(
        evidence
            .get_provider_attempt(&intent.attempt_id)
            .await
            .expect("read")
            .expect("attempt")
            .receipt
            .expect("original receipt")
            .receipt
            .terminal,
        StoredTerminal::Indeterminate { .. }
    ));
}

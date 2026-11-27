//! Dispatch, in-flight body and local socket controls for owner-grant revocation.

use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn future_created_before_revocation_never_dispatches_and_ordinary_http_is_unchanged() {
    let original = Arc::new(RecordingClient::default());
    let revocation = OAuthAuthorizationRevocation::default();
    let wrapped = with_revocable_oauth_authorization_origins(
        original.clone(),
        "http://localhost:8181/mcp",
        OAuthAuthorizationOrigins::new(vec!["http://localhost:8383".to_string()]).unwrap(),
        revocation.clone(),
    )
    .unwrap();
    let decorated: Arc<dyn HttpClient> =
        Arc::new(crate::http_client_redirect::SameOriginRedirectHttpClient::new(wrapped.clone()));
    let observed = decorated
        .restricted_request_cancellation()
        .expect("decorator preserves owner cancellation");
    let request_before_revocation = wrapped.http_request_stream_restricted(request());
    let decorated_before_revocation = decorated.http_request_stream_restricted(request());
    revocation.revoke();
    assert!(observed.is_cancelled());
    revocation.revoke();
    for result in [
        request_before_revocation.await,
        decorated_before_revocation.await,
    ] {
        assert!(matches!(result,
            Err(ExecServerError::HttpRequest(message)) if message.contains("authorization was revoked")));
    }
    assert!(original.restricted.lock().unwrap().is_empty());
    let _ = wrapped.http_request(request().request).await;
    let _ = wrapped.http_request_stream_once(request().request).await;
    assert_eq!(original.ordinary.load(Ordering::SeqCst), 1);
    assert_eq!(original.once.load(Ordering::SeqCst), 1);
}

struct PendingRestrictedClient {
    calls: AtomicUsize,
    started: tokio::sync::Notify,
    dropped: Arc<std::sync::atomic::AtomicBool>,
}

struct PendingDrop(Arc<std::sync::atomic::AtomicBool>);

impl Drop for PendingDrop {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

impl HttpClient for PendingRestrictedClient {
    fn http_request_stream_restricted(
        &self,
        _params: HttpRequestRestrictedParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            let _drop = PendingDrop(Arc::clone(&self.dropped));
            self.started.notify_one();
            std::future::pending().await
        })
    }

    fn http_request(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "unexpected ordinary request".to_string(),
            ))
        })
    }

    fn http_request_stream(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        Box::pin(async {
            Err(ExecServerError::HttpRequest(
                "unexpected ordinary stream".to_string(),
            ))
        })
    }
}

#[tokio::test]
async fn revocation_drops_the_original_pending_request_without_redispatch() -> anyhow::Result<()> {
    let original = Arc::new(PendingRestrictedClient {
        calls: AtomicUsize::new(0),
        started: tokio::sync::Notify::new(),
        dropped: Arc::new(std::sync::atomic::AtomicBool::new(false)),
    });
    let revocation = OAuthAuthorizationRevocation::default();
    let wrapped = with_revocable_oauth_authorization_origins(
        original.clone(),
        "http://localhost:8181/mcp",
        OAuthAuthorizationOrigins::new(vec!["http://localhost:8383".to_string()])?,
        revocation.clone(),
    )?;
    let task = tokio::spawn(async move {
        wrapped
            .http_request_stream_restricted(request())
            .await
            .map(|_| ())
    });
    tokio::time::timeout(Duration::from_secs(1), original.started.notified()).await?;
    revocation.revoke();
    let result = tokio::time::timeout(Duration::from_secs(1), task).await??;
    assert!(matches!(result, Err(ExecServerError::HttpRequest(message))
        if message.contains("authorization was revoked")));
    assert!(original.dropped.load(Ordering::SeqCst));
    assert_eq!(original.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn revocation_cancels_oauth_response_body_and_closes_its_original_socket()
-> anyhow::Result<()> {
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;

    let resource = MockServer::start().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let authorization_origin = format!("http://{}", listener.local_addr()?);
    Mock::given(method("GET"))
        .and(path("/.well-known/oauth-protected-resource/mcp"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "resource": format!("{}/mcp", resource.uri()),
            "authorization_servers": [authorization_origin.clone()]
        })))
        .expect(1)
        .mount(&resource)
        .await;
    let body_started = Arc::new(tokio::sync::Notify::new());
    let notify = Arc::clone(&body_started);
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut request = Vec::new();
        while !request.ends_with(b"\r\n\r\n") {
            anyhow::ensure!(request.len() < 8192, "fixture request headers exceed bound");
            let mut byte = [0_u8; 1];
            anyhow::ensure!(
                socket.read(&mut byte).await? == 1,
                "fixture request ended early"
            );
            request.push(byte[0]);
        }
        socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 512\r\n\r\n{\"issuer\":").await?;
        socket.flush().await?;
        notify.notify_one();
        let mut byte = [0_u8; 1];
        let end = tokio::time::timeout(Duration::from_secs(1), socket.read(&mut byte)).await?;
        match end {
            Ok(0) => Ok::<_, anyhow::Error>(()),
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::ConnectionReset | std::io::ErrorKind::ConnectionAborted
                ) =>
            {
                Ok(())
            }
            other => {
                anyhow::bail!("original OAuth socket did not close after revocation: {other:?}")
            }
        }
    });
    let revocation = OAuthAuthorizationRevocation::default();
    let resource_url = format!("{}/mcp", resource.uri());
    let route = Arc::new(RouteAwareHttpClient::new(HttpClientFactory::new(
        OutboundProxyPolicy::ReqwestDefault,
    )));
    let client = with_revocable_oauth_authorization_origins(
        route,
        &resource_url,
        OAuthAuthorizationOrigins::new(vec![authorization_origin.clone()])?,
        revocation.clone(),
    )?;
    let adapter = Arc::new(OAuthHttpClientAdapter::new(
        client,
        HeaderMap::new(),
        &resource_url,
    ));
    let manager = AuthorizationManager::new_with_oauth_http_client(resource_url, adapter).await?;
    let operation = manager.resolve_metadata();
    tokio::pin!(operation);
    tokio::select! {
        result = &mut operation => anyhow::bail!("metadata completed before body revocation: {result:?}"),
        ready = tokio::time::timeout(Duration::from_secs(1), body_started.notified()) => { ready?; }
    }
    revocation.revoke();
    let result = tokio::time::timeout(Duration::from_secs(1), operation).await?;
    assert!(matches!(result,
        Err(AuthError::DiscoveryRequestFailed { url, source })
            if url.as_str() == format!("{authorization_origin}/.well-known/oauth-authorization-server")
                && matches!(source.downcast_ref::<ExecServerError>(),
                    Some(ExecServerError::HttpRequest(message)) if message.contains("authorization was revoked"))
    ));
    server.await??;
    Ok(())
}

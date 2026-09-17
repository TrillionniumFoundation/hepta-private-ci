use std::str::FromStr;

use ed25519_dalek::Verifier;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type HttpsTestError = Box<dyn std::error::Error + Send + Sync>;

async fn federation_tls_peer(
    issuer_key: ed25519_dalek::VerifyingKey,
    peer_signing_key: SigningKey,
) -> Result<
    (
        String,
        String,
        tokio::task::JoinHandle<Result<FederationWireRequestV3, HttpsTestError>>,
    ),
    HttpsTestError,
> {
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()])?;
    let ca_pem = certified.cert.pem();
    let config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::aws_lc_rs::default_provider(),
    ))
    .with_safe_default_protocol_versions()?
    .with_no_client_auth()
    .with_single_cert(
        vec![certified.cert.der().clone()],
        rustls::pki_types::PrivatePkcs8KeyDer::from(certified.signing_key.serialize_der()).into(),
    )?;
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let endpoint = format!("https://localhost:{}/", listener.local_addr()?.port());
    let task = tokio::spawn(async move {
        let (socket, _) = listener.accept().await?;
        let mut stream = TlsAcceptor::from(Arc::new(config)).accept(socket).await?;
        let mut request = Vec::new();
        while !request.ends_with(b"\r\n\r\n") && request.len() < 32 * 1024 {
            request.push(stream.read_u8().await?);
        }
        let headers = std::str::from_utf8(&request)?;
        if !headers.starts_with("POST /v1/memory/federation/query HTTP/1.1\r\n") {
            return Err("unexpected federation request path".into());
        }
        let content_length = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| usize::from_str(value.trim()).ok())
                    .flatten()
            })
            .ok_or("missing content-length")?;
        if content_length > 64 * 1024 {
            return Err("request exceeded test bound".into());
        }
        let mut body = vec![0; content_length];
        stream.read_exact(&mut body).await?;
        let wire: FederationWireRequestV3 = serde_json::from_slice(&body)?;
        if wire.schema_version != 3 {
            return Err("unexpected schema".into());
        }
        let signing_bytes = wire.signed_grant.grant.signing_bytes()?;
        let signature = Signature::from_slice(&wire.signed_grant.signature)?;
        issuer_key.verify(&signing_bytes, &signature)?;
        if wire.signed_grant.grant.binding.request_sha256 != wire.query_binding_sha256
            || wire.signed_grant.grant.binding.scope_sha256 != wire.scope_sha256
            || wire.signed_grant.grant.binding.payload_sha256 != wire.query_sha256
            || wire.signed_grant.grant.binding.subject_id != wire.principal_id
            || wire.signed_grant.grant.binding.destination_id != wire.peer_id
            || wire.signed_grant.grant.authority_epoch != wire.authority_epoch
        {
            return Err("signed capability did not bind the wire request".into());
        }
        let now = system_now();
        let mut response = RemoteFederatedEnvelopeV3 {
            query_id: id(&wire.query_id),
            peer_id: id(&wire.peer_id),
            principal_id: id(&wire.principal_id),
            scope_digest: Digest32::from_array(wire.scope_sha256),
            purpose_digest: Digest32::from_array(wire.purpose_sha256),
            generation_vector_digest: Digest32::from_array(wire.generation_vector_sha256),
            query_binding_digest: Digest32::from_array(wire.query_binding_sha256),
            request_nonce_digest: Digest32::from_array(wire.request_nonce_sha256),
            authority_epoch: wire.authority_epoch,
            grant_id: wire.signed_grant.grant.grant_id.clone(),
            response_nonce_digest: digest("real-tls-response-nonce"),
            key_id: "peer-key:tls".to_owned(),
            observed_frontier: 23,
            expires_unix_ms: now + 4_000,
            items: vec![item("remote-owner", "remote-record", 1)],
            completeness: FederatedCompletenessV2::Complete,
            terminal_observed: true,
            payload_digest: Digest32::ZERO,
            signature: Vec::new(),
        };
        response.payload_digest = response.compute_payload_digest();
        response.signature = peer_signing_key
            .sign(&response.signature_message())
            .to_bytes()
            .to_vec();
        let response_body = serde_json::to_vec(&RemoteFederatedEnvelopeWireV3::from_domain(&response))?;
        let response_headers = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            response_body.len()
        );
        stream.write_all(response_headers.as_bytes()).await?;
        stream.write_all(&response_body).await?;
        Ok::<_, HttpsTestError>(wire)
    });
    Ok((endpoint, ca_pem, task))
}

#[tokio::test]
async fn real_pinned_https_peer_verifies_capability_and_returns_signed_evidence() {
    let fixture = authority_fixture();
    let peer_key = SigningKey::from_bytes(&[63; 32]);
    let now = system_now();
    let (endpoint, ca_pem, server) = federation_tls_peer(
        fixture.issuer.verifying_key(),
        peer_key.clone(),
    )
    .await
    .expect("TLS peer");
    let enrollment = FederatedPeerEnrollmentV3 {
        peer_id: id("peer:tls"),
        endpoint,
        ca_pem: ca_pem.into_bytes(),
        key_id: "peer-key:tls".to_owned(),
        verifying_key: peer_key.verifying_key().to_bytes(),
        enrollment_epoch: 1,
        expires_unix_ms: now + 10_000,
        revoked: false,
    };
    let registry = FederationPeerRegistryV3::new(vec![enrollment], now).expect("registry");
    let spec = spec("query:real-tls", now + 5_000, 8);
    let permit = permit(
        &spec,
        &fixture.issuer,
        "peer:tls",
        "nonce:real-tls",
        "grant:real-tls",
        79,
    );
    let client = ProductionFederationClientV3::new_pinned_https(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry,
        32,
    )
    .expect("production client");
    let result = client
        .query(FederatedReadPlanV3 {
            spec,
            peers: vec![permit],
            maximum_concurrency: 1,
        })
        .await
        .expect("real TLS query");
    assert_eq!(result.completeness, FederatedCompletenessV2::Complete);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
    assert_eq!(result.items.len(), 1);
    assert_eq!(result.coverage.completed_peers, 1);
    assert!(!result.authority.grants_any());
    let observed = server.await.expect("server join").expect("server result");
    assert_eq!(observed.peer_id, "peer:tls");
    assert_eq!(observed.signed_grant.grant.grant_id, "grant:real-tls");
}

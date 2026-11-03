//! Isolated canonical PQ issuer, signed clock and durable frontier services.
//! Test keys and temporary local services are not deployment qualification.

use super::*;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::UnixPqTrustEndpointConfig;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::frontier_service;
use crate::authority_trust_unix::tests::key;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use std::os::unix::fs::PermissionsExt;

const NOW_MS: u64 = 1_700_000_000_000;

pub(crate) struct IndependentPqIssuer {
    finish: tokio::sync::oneshot::Sender<()>,
    server: tokio::task::JoinHandle<Result<()>>,
}

impl IndependentPqIssuer {
    pub(crate) async fn finish(self) -> Result<()> {
        let _ = self.finish.send(());
        self.server.await?
    }
}

pub(crate) async fn independent_test_authorizer_v2(
    root: &Path,
    count: usize,
) -> Result<(UnixFinalUseAuthorizer, IndependentPqIssuer)> {
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let initial = FinalUseFrontier::for_initial_head_with_profile(
        &head,
        FinalUseAuthenticationProfile::MlDsa65V2,
    )?;
    let clock = TestService::start(root, "clock.sock", /*seed*/ 80, |request, signer| {
        signed(request, PqTrustOutcomeV2::Clock { unix_ms: NOW_MS }, signer)
    });
    let frontier = frontier_service(root, initial);
    let socket = root.join("pq-issuer.sock");
    let listener = tokio::net::UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))?;
    let (issuer, issuer_key) = key(/*seed*/ 82);
    let (feed, feed_key) = key(/*seed*/ 83);
    let config = serde_json::json!({
        "authentication_profile": "ml_dsa65_v2",
        "issuer_socket": socket,
        "issuer_uid": rustix::process::geteuid().as_raw(),
        "signer_id": "authority-owner",
        "issuer_keys": [issuer_key],
        "authority_state_dir": root.join("pq-state"),
        "head": head,
        "issuer_timeout_ms": 2_000,
        "revocation_distributor_id": "feed",
        "revocation_keys": [feed_key],
        "external_clock": endpoint(&clock.config),
        "external_frontier": endpoint(&frontier.config),
    });
    let config_path = root.join("pq-config.json");
    std::fs::write(&config_path, serde_json::to_vec(&config)?)?;
    std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o600))?;
    // Exercise the same explicit configuration route used by ordinary consumers.
    let authorizer = UnixFinalUseAuthorizer::open(&config_path)?;
    let (finish, finished) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        // Clock/frontier remain alive through the consumer's final entry check.
        let services = (clock, frontier);
        for index in 0..count {
            let (mut stream, _) = listener.accept().await?;
            let mut length = [0; 4];
            stream.read_exact(&mut length).await?;
            let length = usize::try_from(u32::from_be_bytes(length))?;
            if length == 0 || length > MAX_REQUEST_BYTES {
                return Err("unbounded PQ issuer request".into());
            }
            let mut request = vec![0; length];
            stream.read_exact(&mut request).await?;
            let request: PqIssuerRequestV2 = serde_json::from_slice(&request)?;
            if request.schema_version != 2 || request.operation != AUTHORITY_PORT_OPERATION {
                return Err("canonical PQ issuer requires exact V2 port selection".into());
            }
            let grant = FinalUseGrant {
                schema_version: 2,
                signer_id: "authority-owner".into(),
                authority_epoch: 1,
                grant_id: format!("pq-grant-{index}"),
                nonce: request.challenge,
                binding: request.binding,
                not_before_unix_ms: NOW_MS - 1_000,
                expires_at_unix_ms: NOW_MS + 60_000,
            };
            let signature = issuer.sign_exact_message(&grant.signing_bytes()?)?.to_vec();
            let update = FinalUseRevocationUpdate::new_pq(
                "feed".into(),
                head.clone(),
                /*issued_at_unix_ms*/ NOW_MS - 1_000,
                /*expires_at_unix_ms*/ NOW_MS + 60_000,
            );
            let signature_revocations = feed.sign_exact_message(&update.signing_bytes()?)?.to_vec();
            let response = PqIssuerResponseV2 {
                schema_version: 2,
                challenge: request.challenge,
                revocations: SignedFinalUseRevocationUpdate {
                    update,
                    signature: signature_revocations,
                },
                grant: Some(SignedFinalUseGrant { grant, signature }),
                denial_reason: None,
            };
            let bytes = serde_json::to_vec(&response)?;
            if bytes.len() > MAX_RESPONSE_BYTES {
                return Err("canonical PQ response exceeds the original port bound".into());
            }
            stream
                .write_all(&u32::try_from(bytes.len())?.to_be_bytes())
                .await?;
            stream.write_all(&bytes).await?;
        }
        let _ = finished.await;
        drop(services);
        Ok(())
    });
    Ok((authorizer, IndependentPqIssuer { finish, server }))
}

fn endpoint(config: &UnixPqTrustEndpointConfig) -> serde_json::Value {
    serde_json::json!({
        "socket_path": config.socket_path,
        "peer_uid": config.peer_uid,
        "service_id": config.service_id,
        "key_generation": config.key_generation,
        "public_key_id": config.public_key_id,
        "public_key_spki": config.public_key_spki,
        "timeout_ms": config.timeout_ms,
    })
}

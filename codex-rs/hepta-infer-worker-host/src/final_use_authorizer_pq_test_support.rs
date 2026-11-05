//! Isolated canonical PQ issuer, signed clock and durable frontier services.
//! Test keys and temporary local services are not deployment qualification.

use super::*;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::UnixPqTrustEndpointConfig;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::frontier_service_with_lifetime;
use crate::authority_trust_unix::tests::key;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const NOW_MS: u64 = 1_700_000_000_000;

pub(crate) struct IndependentPqIssuer {
    finish: Option<tokio::sync::oneshot::Sender<()>>,
    server: Option<tokio::task::JoinHandle<Result<()>>>,
    services: Option<(TestService, TestService)>,
    last_grant: Arc<Mutex<Option<SignedFinalUseGrant>>>,
}

impl IndependentPqIssuer {
    pub(crate) async fn finish(mut self) -> Result<()> {
        self.finish_owned().await
    }

    pub(crate) async fn finish_owned(&mut self) -> Result<()> {
        if let Some(finish) = self.finish.take() {
            let _ = finish.send(());
        }
        let Some(server) = self.server.as_mut() else {
            return Ok(());
        };
        let result = match timeout(Duration::from_secs(20), server).await {
            Ok(result) => {
                self.server.take();
                result.map_err(Into::into).and_then(std::convert::identity)
            }
            Err(_) => {
                self.abort_and_join().await?;
                Err("PQ test issuer did not finish within 20 seconds".into())
            }
        };
        drop(self.services.take());
        result
    }

    pub(crate) async fn abort_and_join(&mut self) -> Result<()> {
        self.finish.take();
        let result = if let Some(server) = self.server.take() {
            server.abort();
            match server.await {
                Ok(result) => result,
                Err(error) if error.is_cancelled() => Ok(()),
                Err(error) => Err(error.into()),
            }
        } else {
            Ok(())
        };
        drop(self.services.take());
        result
    }
}

impl Drop for IndependentPqIssuer {
    fn drop(&mut self) {
        if let Some(server) = &self.server {
            server.abort();
        }
        // TestService joins its thread and propagates service errors on drop.
        drop(self.services.take());
    }
}

pub(crate) async fn independent_test_authorizer_v2(
    root: &Path,
    count: usize,
) -> Result<(UnixFinalUseAuthorizer, IndependentPqIssuer)> {
    start(
        root,
        count,
        || Ok(NOW_MS),
        /*authority_epoch*/ 1,
        Duration::from_secs(30),
    )
    .await
}

/// Original ordinary inputs use this advancing clock for their 900-second lease.
pub(crate) async fn independent_ordinary_test_authorizer_v2(
    root: &Path,
    count: usize,
) -> Result<(UnixFinalUseAuthorizer, IndependentPqIssuer)> {
    let unix_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let started = Instant::now();
    let time = move || {
        unix_ms
            .checked_add(u64::try_from(started.elapsed().as_millis())?)
            .ok_or_else(|| "PQ test clock overflow".into())
    };
    start(
        root,
        count,
        time,
        /*authority_epoch*/ 9,
        Duration::from_secs(900),
    )
    .await
}

/// Advance the real signed clock only after the original model load settles.
/// This is a test-time trigger, never an authorization or completion receipt.
pub(crate) async fn independent_ordinary_test_authorizer_v2_after_load(
    root: &Path,
    count: usize,
    journal: PathBuf,
    late_ms: u64,
) -> Result<(UnixFinalUseAuthorizer, IndependentPqIssuer)> {
    let unix_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let started = Instant::now();
    let time = move || {
        let now = unix_ms
            .checked_add(u64::try_from(started.elapsed().as_millis())?)
            .ok_or("PQ test clock overflow")?;
        let original = match std::fs::read_to_string(&journal) {
            Ok(original) => original,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(now),
            Err(error) => return Err(error.into()),
        };
        // The original journal's settled event carries observed=true and the
        // Completed state at fields 9 and 10. Do not invent a second load or
        // reopen the live writer. The test separately checks its retained
        // original load measurements and completed control identifiers.
        let loaded = original.split_inclusive('\n').any(|record| {
            let Some(line) = record.strip_suffix('\n') else {
                return false;
            };
            let fields: Vec<_> = line.split('|').collect();
            fields.len() == 15
                && fields.first() == Some(&"settle")
                && fields.get(9) == Some(&"1")
                && fields.get(10) == Some(&"completed")
                && fields.get(11) != Some(&"none")
                && fields.get(1) == fields.get(14)
        });
        Ok(if loaded { now.max(late_ms) } else { now })
    };
    start(
        root,
        count,
        time,
        /*authority_epoch*/ 9,
        Duration::from_secs(900),
    )
    .await
}

async fn start(
    root: &Path,
    count: usize,
    time: impl Fn() -> Result<u64> + Clone + Send + 'static,
    authority_epoch: u64,
    lifetime: Duration,
) -> Result<(UnixFinalUseAuthorizer, IndependentPqIssuer)> {
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    let head = FinalUseRevocations {
        authority_epoch,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let initial = FinalUseFrontier::for_initial_head_with_profile(
        &head,
        FinalUseAuthenticationProfile::MlDsa65V2,
    )?;
    let clock_time = time.clone();
    let clock = TestService::start_with_lifetime(
        root,
        "clock.sock",
        /*seed*/ 80,
        lifetime,
        move |request, signer| {
            let unix_ms = clock_time()?;
            signed(request, PqTrustOutcomeV2::Clock { unix_ms }, signer)
        },
    )?;
    let frontier = frontier_service_with_lifetime(root, initial, lifetime)?;
    let socket = root.join("pq-issuer.sock");
    let listener = tokio::net::UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))?;
    let (issuer, issuer_key) = key(/*seed*/ 82)?;
    let (feed, feed_key) = key(/*seed*/ 83)?;
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
    let last_grant = Arc::new(Mutex::new(None));
    let issued = Arc::clone(&last_grant);
    let run = async move {
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
            let now = time()?;
            let expires = now
                .checked_add(60_000)
                .ok_or("PQ test grant expiry overflow")?;
            let grant = FinalUseGrant {
                schema_version: 2,
                signer_id: "authority-owner".into(),
                authority_epoch,
                grant_id: format!("pq-grant-{index}"),
                nonce: request.challenge,
                binding: request.binding,
                not_before_unix_ms: now.saturating_sub(1_000),
                expires_at_unix_ms: expires,
            };
            let signature = issuer.sign_exact_message(&grant.signing_bytes()?)?.to_vec();
            let update = FinalUseRevocationUpdate::new_pq(
                "feed".into(),
                head.clone(),
                /*issued_at_unix_ms*/ now.saturating_sub(1_000),
                /*expires_at_unix_ms*/ expires,
            );
            let signature_revocations = feed.sign_exact_message(&update.signing_bytes()?)?.to_vec();
            let grant = SignedFinalUseGrant { grant, signature };
            *issued
                .lock()
                .map_err(|_| "PQ test grant capture poisoned")? = Some(grant.clone());
            let response = PqIssuerResponseV2 {
                schema_version: 2,
                challenge: request.challenge,
                revocations: SignedFinalUseRevocationUpdate {
                    update,
                    signature: signature_revocations,
                },
                grant: Some(grant),
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
        // No extra grants after the expected claims; trust services stay owned
        // by the handle through the consumer's final entry and explicit cleanup.
        drop(listener);
        let _ = finished.await;
        Ok::<(), Box<dyn StdError + Send + Sync>>(())
    };
    let server = tokio::spawn(async move {
        timeout(lifetime, run)
            .await
            .map_err(|_| "PQ test issuer exceeded its bounded service lifetime")?
    });
    Ok((
        authorizer,
        IndependentPqIssuer {
            finish: Some(finish),
            server: Some(server),
            services: Some((clock, frontier)),
            last_grant,
        },
    ))
}

#[path = "final_use_authorizer_pq_test_support_tests.rs"]
mod tests;

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

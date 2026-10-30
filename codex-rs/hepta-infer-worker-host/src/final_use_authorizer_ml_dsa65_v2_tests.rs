use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FINAL_USE_ML_DSA65_V2_CONTEXT;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_contracts::encode_ml_dsa65_final_use_signature_v2;
use ml_dsa::Keypair;
use ml_dsa::MlDsa65;
use ml_dsa::SigningKey;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::net::UnixListener;

struct Frontier(Mutex<FinalUseFrontier>);
impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, _owner: &str) -> std::result::Result<FinalUseFrontier, AuthorityTrustError> {
        self.0
            .lock()
            .map(|head| *head)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
    fn compare_and_set(
        &self,
        _owner: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> std::result::Result<(), AuthorityTrustError> {
        let mut head = self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if *head != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *head = *next;
        Ok(())
    }
}

pub(crate) async fn independent_test_authorizer_v2(
    root: &Path,
    count: usize,
) -> Result<(UnixFinalUseAuthorizer, tokio::task::JoinHandle<Result<()>>)> {
    test_authorizer_with_reply(root, count, IssuerReply::MlDsaV2).await
}

enum IssuerReply {
    MlDsaV2,
    LegacyPort,
    ClassicalGrant,
}

async fn test_authorizer_with_reply(
    root: &Path,
    count: usize,
    reply: IssuerReply,
) -> Result<(UnixFinalUseAuthorizer, tokio::task::JoinHandle<Result<()>>)> {
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    let socket = root.join("pq-issuer.sock");
    let listener = UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))?;
    let key = SigningKey::<MlDsa65>::from_seed(&[43; 32].into());
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let frontier = Arc::new(Frontier(Mutex::new(FinalUseFrontier::for_initial_head(
        &head,
    )?)));
    let config = serde_json::json!({
        "schema_version":2,"issuer_socket":socket,"issuer_uid":rustix::process::geteuid().as_raw(),
        "signer_id":"authority-owner","issuer_keys":[{"key_id":"issuer-pq","verifying_key":key.verifying_key().encode().to_vec(),"not_before_authority_epoch":9,"not_after_authority_epoch":9}],
        "authority_state_dir":root.join("pq-state"),"authority_epoch":9,"revocation_revision":1,
        "revoked_grant_ids":[],"issuer_timeout_ms":2_000,
    });
    let config_path = root.join("pq-config.json");
    std::fs::write(&config_path, serde_json::to_vec(&config)?)?;
    std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o600))?;
    // A product configuration must explicitly select the new constructor.
    if UnixFinalUseAuthorizer::open(&config_path).is_ok() {
        return Err("legacy configuration accepted the PQ profile".into());
    }
    let authorizer = UnixFinalUseAuthorizer::open_ml_dsa65_v2(
        &config_path,
        Arc::new(SystemAuthorityClock),
        frontier,
    )?;
    let server = tokio::spawn(async move {
        for nonce in 1..=count {
            let (mut stream, _) = listener.accept().await?;
            let mut length = [0; 4];
            stream.read_exact(&mut length).await?;
            let length = usize::try_from(u32::from_be_bytes(length))?;
            if length == 0 || length > MAX_REQUEST_BYTES {
                return Err("unbounded PQ issuer request".into());
            }
            let mut request = vec![0; length];
            stream.read_exact(&mut request).await?;
            let request: IssuerRequest = serde_json::from_slice(&request)?;
            if request.schema_version != 2 || request.operation != AUTHORITY_PORT_OPERATION {
                return Err("PQ issuer requires exact V2 port selection".into());
            }
            let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
            let grant = FinalUseGrant {
                schema_version: 2,
                signer_id: "authority-owner".into(),
                authority_epoch: 9,
                grant_id: format!("pq-grant-{nonce}"),
                nonce: [u8::try_from(nonce)?; 32],
                binding: request.binding,
                not_before_unix_ms: now.saturating_sub(1000),
                expires_at_unix_ms: now.checked_add(60_000).ok_or("expiry overflow")?,
            };
            let signature = key.expanded_key().sign_deterministic(
                &grant.ml_dsa65_v2_signing_bytes("issuer-pq")?,
                FINAL_USE_ML_DSA65_V2_CONTEXT,
            )?;
            let mut grant = SignedFinalUseGrant {
                grant,
                signature: encode_ml_dsa65_final_use_signature_v2(
                    "issuer-pq",
                    &signature.encode(),
                )?,
            };
            if matches!(reply, IssuerReply::ClassicalGrant) {
                use ed25519_dalek::Signer;
                grant.grant.schema_version = 1;
                grant.signature = ed25519_dalek::SigningKey::from_bytes(&[44; 32])
                    .sign(&grant.grant.signing_bytes()?)
                    .to_bytes()
                    .to_vec();
            }
            if serde_json::to_vec(&grant)?.len()
                > crate::final_use_grant_courier::MAX_SIGNED_GRANT_FILE_BYTES
            {
                return Err("PQ signature exceeds the original grant courier bound".into());
            }
            let response_schema = if matches!(reply, IssuerReply::LegacyPort) {
                1
            } else {
                2
            };
            let response = IssuerResponse {
                schema_version: response_schema,
                revocations: head.clone(),
                grant: Some(grant),
                denial_reason: None,
            };
            let response = serde_json::to_vec(&response)?;
            if response.len() > MAX_RESPONSE_BYTES {
                return Err("PQ signature exceeds the original Unix response bound".into());
            }
            stream
                .write_all(&u32::try_from(response.len())?.to_be_bytes())
                .await?;
            stream.write_all(&response).await?;
            stream.flush().await?;
        }
        Ok(())
    });
    Ok((authorizer, server))
}

#[tokio::test]
async fn protected_v2_configuration_real_issuer_and_unix_claim_reach_original_use_entry()
-> Result<()> {
    let root = tempfile::tempdir()?;
    let (authorizer, server) = independent_test_authorizer_v2(root.path(), 1).await?;
    let expected = FinalUseBinding {
        subject_id: "agent".into(),
        destination_id: "runtime.codex.turn_start".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let token = authorizer.claim(expected.clone()).await?;
    let entered = token.enter(&expected)?;
    if !entered.matches(&expected) || entered.witness_sha256() == [0; 32] {
        return Err("PQ claim did not enter the original exact use boundary".into());
    }
    server.await??;
    Ok(())
}

#[tokio::test]
async fn pq_unix_profile_refuses_legacy_port_and_real_classical_grant_without_claiming()
-> Result<()> {
    for reply in [IssuerReply::LegacyPort, IssuerReply::ClassicalGrant] {
        let root = tempfile::tempdir()?;
        let (authorizer, server) = test_authorizer_with_reply(root.path(), 1, reply).await?;
        let expected = FinalUseBinding {
            subject_id: "agent".into(),
            destination_id: "runtime.codex.turn_start".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        };
        if authorizer.claim(expected).await.is_ok()
            || authorizer.authority.capacity()?.used_nonces != 0
        {
            return Err(
                "PQ profile accepted a cross-profile response or consumed its nonce".into(),
            );
        }
        server.await??;
    }
    Ok(())
}

#[tokio::test]
async fn pq_external_signature_file_courier_uses_the_same_owner_and_cannot_replay() -> Result<()> {
    use crate::final_use_grant_courier::SignedFinalUseGrantCourier;
    use codex_hepta_agentd::AgentdFinalUseGrantProvider;
    let root = tempfile::tempdir()?;
    let (authorizer, server) = independent_test_authorizer_v2(root.path(), 1).await?;
    let expected = FinalUseBinding {
        subject_id: "agent".into(),
        destination_id: "runtime.codex.turn_start".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let signed = authorizer
        .request_grant(&expected)
        .await?
        .grant
        .ok_or("issuer did not issue grant")?;
    let file = root.path().join("external-grant.json");
    std::fs::write(&file, serde_json::to_vec(&signed)?)?;
    std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600))?;
    let courier = SignedFinalUseGrantCourier::open(
        &file,
        rustix::process::geteuid().as_raw(),
        authorizer.authority.clone(),
        &expected,
    )?;
    let delivered = courier.signed_grant(&expected)?;
    let entered = authorizer
        .authority
        .claim(&delivered, &expected)?
        .enter(&expected)?;
    if !entered.matches(&expected) || courier.signed_grant(&expected).is_ok() {
        return Err("PQ courier bypassed the original exact-use or nonce boundary".into());
    }
    server.await??;
    Ok(())
}

#[test]
fn maximum_pq_signature_carrier_and_grant_fit_original_transport_limits() -> Result<()> {
    // 'z' also forces three decimal digits in each JSON signature-frame byte.
    let identifier = "z".repeat(128);
    let grant = SignedFinalUseGrant {
        grant: FinalUseGrant {
            schema_version: 2,
            signer_id: identifier.clone(),
            authority_epoch: u64::MAX,
            grant_id: identifier.clone(),
            nonce: [255; 32],
            binding: FinalUseBinding {
                subject_id: identifier.clone(),
                destination_id: identifier.clone(),
                request_sha256: [255; 32],
                scope_sha256: [255; 32],
                payload_sha256: [255; 32],
            },
            not_before_unix_ms: u64::MAX - 1,
            expires_at_unix_ms: u64::MAX,
        },
        signature: encode_ml_dsa65_final_use_signature_v2(&identifier, &[255; 3_309])?,
    };
    if serde_json::to_vec(&grant)?.len()
        > crate::final_use_grant_courier::MAX_SIGNED_GRANT_FILE_BYTES
    {
        return Err("maximum PQ grant does not fit the original 16 KiB courier frame".into());
    }
    let response = IssuerResponse {
        schema_version: 2,
        revocations: FinalUseRevocations {
            authority_epoch: u64::MAX,
            revision: u64::MAX,
            revoked_grant_ids: BTreeSet::new(),
        },
        grant: Some(grant),
        denial_reason: None,
    };
    if serde_json::to_vec(&response)?.len() > MAX_RESPONSE_BYTES {
        return Err("maximum PQ signature does not fit the original Unix response frame".into());
    }
    Ok(())
}

#[test]
fn v2_configuration_rejects_unknown_schema_and_classical_key_before_opening_an_owner() -> Result<()>
{
    let root = tempfile::tempdir()?;
    let key = SigningKey::<MlDsa65>::from_seed(&[43; 32].into());
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    for (schema, public_key) in [(3, key.verifying_key().encode().to_vec()), (2, vec![7; 32])] {
        let path = root.path().join(format!("forbidden-{schema}"));
        let config = FinalUseMlDsa65AuthorizerConfigV2 {
            schema_version: schema,
            issuer_socket: root.path().join("issuer.sock"),
            issuer_uid: rustix::process::geteuid().as_raw(),
            signer_id: "owner".into(),
            issuer_keys: vec![FinalUseMlDsa65IssuerTrustKeyV2 {
                key_id: "issuer-pq".into(),
                verifying_key: public_key,
                not_before_authority_epoch: 9,
                not_after_authority_epoch: 9,
            }],
            authority_state_dir: path.clone(),
            authority_epoch: 9,
            revocation_revision: 1,
            revoked_grant_ids: BTreeSet::new(),
            issuer_timeout_ms: 1000,
        };
        let frontier = Arc::new(Frontier(Mutex::new(FinalUseFrontier::for_initial_head(
            &head,
        )?)));
        if UnixFinalUseAuthorizer::from_ml_dsa65_v2_config(
            config,
            Arc::new(SystemAuthorityClock),
            frontier,
        )
        .is_ok()
            || path.exists()
        {
            return Err("cross-profile configuration opened an owner".into());
        }
    }
    Ok(())
}

#[test]
fn v2_configuration_refuses_fifo_without_waiting_for_a_writer() -> Result<()> {
    const CHILD_PATH: &str = "HEPTA_TEST_V2_FINAL_USE_FIFO_PATH";
    const TEST_NAME: &str = "final_use_authorizer::ml_dsa65_v2::tests::v2_configuration_refuses_fifo_without_waiting_for_a_writer";
    const REFUSED: &str = "V2 final-use FIFO configuration refused before owner open";

    if let Some(path) = std::env::var_os(CHILD_PATH) {
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let frontier = Arc::new(Frontier(Mutex::new(FinalUseFrontier::for_initial_head(
            &head,
        )?)));
        return match UnixFinalUseAuthorizer::open_ml_dsa65_v2(
            &PathBuf::from(path),
            Arc::new(SystemAuthorityClock),
            frontier,
        ) {
            Err(error)
                if error.to_string()
                    == "final-use authority config must be a protected root/owner regular file" =>
            {
                println!("{REFUSED}");
                Ok(())
            }
            Err(error) => Err(format!("unexpected FIFO configuration refusal: {error}").into()),
            Ok(_) => Err("FIFO configuration opened a final-use owner".into()),
        };
    }

    let root = tempfile::tempdir()?;
    let fifo = root.path().join("pq-config.fifo");
    let created = std::process::Command::new("mkfifo")
        .args(["-m", "600"])
        .arg(&fifo)
        .status()?;
    assert!(created.success());
    assert!(std::fs::symlink_metadata(&fifo)?.file_type().is_fifo());

    // Isolate the actual constructor so the blocking-open regression can be
    // terminated and reaped without leaving a blocked thread in the test host.
    let mut child = std::process::Command::new(std::env::current_exe()?)
        .args(["--exact", TEST_NAME, "--nocapture"])
        .env(CHILD_PATH, &fifo)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()?;
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    let mut completed = false;
    let poll_error = loop {
        match child.try_wait() {
            Ok(Some(_)) => {
                completed = true;
                break None;
            }
            Ok(None) if std::time::Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(10));
            }
            Ok(None) => break None,
            Err(error) => break Some(error.to_string()),
        }
    };
    let kill_error = if completed {
        None
    } else {
        child.kill().err().map(|error| error.to_string())
    };
    let output = child.wait_with_output()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        completed
            && output.status.success()
            && stdout.contains(REFUSED)
            && stdout.contains("1 passed; 0 failed"),
        "FIFO configuration must be refused without a writer; completed={completed}, poll_error={poll_error:?}, kill_error={kill_error:?}, status={}; stdout={stdout}; stderr={stderr}",
        output.status,
    );
    Ok(())
}

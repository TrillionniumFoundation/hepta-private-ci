use super::*;
use codex_hepta_contracts::FinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeSet;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::net::UnixListener;

type Result<T> = anyhow::Result<T>;

struct Fixture {
    _root: tempfile::TempDir,
    listener: UnixListener,
    client: AgentdUnixFinalUseGrantProvider,
    authority: FinalUseAuthority,
    key: SigningKey,
    binding: FinalUseBinding,
}

impl Fixture {
    fn new(timeout: Duration) -> Result<Self> {
        let root = tempfile::tempdir()?;
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
        let socket = root.path().join("issuer.sock");
        let listener = UnixListener::bind(&socket)?;
        std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))?;
        let key = SigningKey::from_bytes(&[81; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &root.path().join("authority"),
            "existing-issuer".to_owned(),
            key.verifying_key().to_bytes(),
            head(),
        )?;
        let client = AgentdUnixFinalUseGrantProvider::new(
            socket.clone(),
            std::fs::metadata(&socket)?.uid(),
            timeout,
            authority.clone(),
        )?;
        Ok(Self {
            _root: root,
            listener,
            client,
            authority,
            key,
            binding: FinalUseBinding {
                subject_id: "existing-agent".to_owned(),
                destination_id: "native-runtime".to_owned(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
        })
    }

    fn response(&self) -> Result<Value> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "existing-issuer".to_owned(),
            authority_epoch: 7,
            grant_id: "original-effect".to_owned(),
            nonce: [19; 32],
            binding: self.binding.clone(),
            not_before_unix_ms: now.saturating_sub(1000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = self.key.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        Ok(json!({ "schema_version":1, "revocations":head(),
            "grant":SignedFinalUseGrant { grant, signature }, "denial_reason":null }))
    }
}

fn head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    }
}

async fn reply(listener: &UnixListener, response: Value) -> Result<Value> {
    let (mut stream, _) = listener.accept().await?;
    let length = stream.read_u32().await? as usize;
    anyhow::ensure!(length <= MAX_REQUEST_BYTES, "unbounded issuer request");
    let mut request = vec![0; length];
    stream.read_exact(&mut request).await?;
    let response = serde_json::to_vec(&response)?;
    stream.write_u32(response.len() as u32).await?;
    stream.write_all(&response).await?;
    Ok(serde_json::from_slice(&request)?)
}

#[tokio::test]
async fn requests_original_binding_without_consuming_writer_nonce() -> Result<()> {
    let fixture = Fixture::new(Duration::from_secs(1))?;
    let response = fixture.response()?;
    let (grant, request) = tokio::join!(
        fixture.client.signed_grant(&fixture.binding),
        reply(&fixture.listener, response)
    );
    let grant = grant?;
    assert_eq!(
        request?,
        json!({ "schema_version":1, "operation":OPERATION, "binding":fixture.binding })
    );
    assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    let token = fixture.authority.claim(&grant, &fixture.binding)?;
    assert!(token.enter(&fixture.binding)?.matches(&fixture.binding));
    assert_eq!(fixture.authority.capacity()?.used_nonces, 1);
    assert!(fixture.authority.claim(&grant, &fixture.binding).is_err());
    Ok(())
}

#[tokio::test]
async fn rejects_changed_binding_and_conflicting_response_without_claim() -> Result<()> {
    for kind in ["binding", "both", "denied"] {
        let fixture = Fixture::new(Duration::from_secs(1))?;
        let mut response = fixture.response()?;
        match kind {
            "binding" => {
                response["grant"]["grant"]["binding"]["destination_id"] = json!("different-runtime")
            }
            "both" => response["denial_reason"] = json!("revoked"),
            "denied" => {
                response["grant"] = Value::Null;
                response["denial_reason"] = json!("revoked");
            }
            _ => unreachable!(),
        }
        let (result, server) = tokio::join!(
            fixture.client.signed_grant(&fixture.binding),
            reply(&fixture.listener, response)
        );
        assert!(result.is_err());
        server?;
        assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    }
    Ok(())
}

#[tokio::test]
async fn issuer_timeout_does_not_block_owner_or_claim_a_nonce() -> Result<()> {
    let fixture = Fixture::new(Duration::from_millis(30))?;
    let (connected, mut ready) = tokio::sync::oneshot::channel();
    let request = fixture.client.signed_grant(&fixture.binding);
    let server = async {
        let (stream, _) = fixture.listener.accept().await?;
        connected
            .send(())
            .map_err(|_| anyhow::anyhow!("request vanished"))?;
        std::future::pending::<()>().await;
        drop(stream);
        Ok::<(), anyhow::Error>(())
    };
    tokio::pin!(server);
    tokio::pin!(request);
    tokio::select! {
        result = &mut server => result?,
        result = &mut request => {
            assert!(ready.try_recv().is_ok(), "the issuer must have received the original request");
            assert!(result.is_err());
            assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
        }
    }
    Ok(())
}

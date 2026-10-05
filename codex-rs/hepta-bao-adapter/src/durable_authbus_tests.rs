//! Real composed entry rejection, before evidence, quota mutation or networking.
use super::*;
use crate::BAO_DURABLE_OPERATION_DESTINATION;
use crate::BaoDurableAuthBusAdmission;
use crate::BaoDurableAuthBusError;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_operations::DurableOperationIntentV1;
use codex_hepta_operations::DurableOperationStore;
use pretty_assertions::assert_eq;

struct NoEvidence;
impl BaoAuthBusEvidenceProvider for NoEvidence {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError> {
        panic!("rejected operation must not request trusted time")
    }
    fn settlement_evidence(
        &mut self,
        _: &QuotaReservation,
        _: SettlementStatus,
        _: u64,
        _: Digest32,
        _: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError> {
        panic!("rejected operation must not request settlement evidence")
    }
}

#[tokio::test]
async fn composed_bao_rejects_binding_drift_and_stale_handle_before_activity()
-> Result<(), TestError> {
    // No accept task consumes connections: any attempted provider connection
    // remains queued and the nonblocking accept below detects it directly.
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    listener.set_nonblocking(true)?;
    let certificate = rcgen::generate_simple_self_signed(vec!["localhost".into()])?;
    let client = BaoClient::new(
        &format!("https://localhost:{}/", listener.local_addr()?.port()),
        certificate.cert.pem().as_bytes(),
        BaoToken::new("fixture-only".into())?,
        Duration::from_secs(2),
    )?;
    let request = read_request();
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let (_database, _checkpoint, authbus, _evidence, admission) =
        authbus_host(&client, &request, now).await?;
    let quota_before = authbus.read().quota_snapshot(&admission.quota_key).await?;
    let admission = BaoDurableAuthBusAdmission {
        policy_revision: admission.policy_revision,
        quota_key: admission.quota_key,
        expected_quota_revision: admission.expected_quota_revision,
        amount: admission.amount,
        expires_at_ms: admission.expires_at_ms,
    };
    let operations_root = tempfile::tempdir()?;
    let operations =
        DurableOperationStore::open(&operations_root.path().join("operations.sqlite")).await?;
    let intent = DurableOperationIntentV1 {
        scope_id: StableId::new("scope:bao-composed")?,
        operation_id: StableId::new("operation:bao-composed")?,
        expected_predecessor: None,
        destination: StableId::new(BAO_DURABLE_OPERATION_DESTINATION)?,
        payload_digest: client.durable_operation_payload_digest(&request)?,
        owner_generation: Generation::new(1)?,
    };
    operations.prepare_intent(&intent).await?;
    let handle = operations
        .claim_authbus_operation(
            &intent.scope_id,
            &intent.operation_id,
            &intent.destination,
            intent.payload_digest,
            &StableId::new("worker:bao-composed")?,
            Generation::new(1)?,
            Duration::from_secs(30),
        )
        .await?
        .expect("owner issues exact handle");
    let (authority, provider_grant, _authority_root) = grant(&client, &request)?;
    let mut owner_grant = provider_grant.clone();
    owner_grant.grant.grant_id = "operation-owner-entry".into();
    owner_grant.grant.nonce = [29; 32];
    owner_grant.grant.binding = intent.final_use_binding();
    owner_grant.signature = SigningKey::from_bytes(&[71; 32])
        .sign(&owner_grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let entered = operations
        .enter_authbus_operation(&authority, &owner_grant, handle)
        .await?;
    operations
        .validate_entered_authbus_operation(&entered)
        .await?;

    let mut changed = request.clone();
    changed.path = "provider/different-token".into();
    let result = client
        .consume_kv_v2_with_durable_authbus_operation(
            &operations,
            &entered,
            authbus.execution(),
            &admission,
            &authority,
            &provider_grant,
            &changed,
            &mut NoEvidence,
            |_| panic!("rejected binding cannot deliver"),
        )
        .await;
    assert!(matches!(
        result,
        Err(BaoDurableAuthBusError::InvalidOperationBinding)
    ));
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    assert_eq!(
        authbus.read().quota_snapshot(&admission.quota_key).await?,
        quota_before
    );

    let recovered = operations
        .recover_entered_authbus_operation(
            &intent.scope_id,
            &intent.operation_id,
            Generation::new(2)?,
        )
        .await?;
    operations
        .validate_entered_authbus_operation(&recovered)
        .await?;
    let result = client
        .consume_kv_v2_with_durable_authbus_operation(
            &operations,
            &entered,
            authbus.execution(),
            &admission,
            &authority,
            &provider_grant,
            &request,
            &mut NoEvidence,
            |_| panic!("stale handle cannot deliver"),
        )
        .await;
    assert!(matches!(
        result,
        Err(BaoDurableAuthBusError::Operation(
            DurableOperationError::StaleGeneration | DurableOperationError::StaleLease
        ))
    ));
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    assert_eq!(
        authbus.read().quota_snapshot(&admission.quota_key).await?,
        quota_before
    );
    Ok(())
}

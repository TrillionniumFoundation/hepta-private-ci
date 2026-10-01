use super::*;
use crate::consumer_port::tests::Fixture;
use codex_hepta_contracts::FinalUseApproval;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::SystemAuthorityClock;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn prepared_sqlite_saga_requires_real_external_ack_and_preserves_original_result()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let mut consumer_process = fixture.spawn()?;
    let consumer = fixture.client()?;
    let secret = std::str::from_utf8(&fixture.credential)?;
    let (endpoint, ca, server_task) = server(200, body_for(2, secret), || async {})
        .await
        .map_err(|_| "provider fixture start failed")?;
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("prepared-saga-fixture-token".into())?,
        Duration::from_secs(3),
    )?;
    let mut request = read_request();
    request.consumer_id = fixture.config.consumer_id.clone();
    request.consumer_configuration_sha256 = Some(consumer.configuration_sha256());
    request.expected_secret_sha256 = fixture.config.credential_sha256;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let (_db, _checkpoint, authbus, mut evidence, admission) =
        authbus_host_with_lifetime(180_000, &client, &request, now)
            .await
            .map_err(|_| "AuthBus fixture initialization failed")?;
    let (authority, grant, _authority_root) =
        product_grant(&client, &request).map_err(|_| "grant fixture initialization failed")?;
    let approver = SigningKey::from_bytes(&[91; 32]);
    let distributor = SigningKey::from_bytes(&[92; 32]);
    let host = Arc::new(crate::BaoFinalUseHost::new(
        authority,
        FinalUseApprovalVerifier::new(
            "prepared-saga-approver".into(),
            approver.verifying_key().to_bytes(),
        )?,
        FinalUseRevocationFeedVerifier::new(
            "prepared-saga-revocation".into(),
            distributor.verifying_key().to_bytes(),
        )?,
        Arc::new(SystemAuthorityClock),
        [consumer.registration()?],
    )?);
    let update = FinalUseRevocationUpdate::new(
        "prepared-saga-revocation".into(),
        FinalUseRevocations {
            authority_epoch: 3,
            revision: 2,
            revoked_grant_ids: Default::default(),
        },
        now - 1000,
        now + 180_000,
    );
    let signature = distributor
        .sign(&update.signing_bytes()?)
        .to_bytes()
        .to_vec();
    host.apply_revocation_update(&SignedFinalUseRevocationUpdate { update, signature })?;
    let approval = FinalUseApproval::for_grant("prepared-saga-approver".into(), &grant.grant)?;
    let signature = approver
        .sign(&approval.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let approval = SignedFinalUseApproval {
        approval,
        signature,
    };
    // A prepared production profile cannot accidentally run through a legacy
    // callback engine. Both refuse before spending the grant or reading KV.
    assert!(matches!(
        host.consume_kv_v2(&client, &grant, &approval, &request)
            .await,
        Err(crate::BaoFinalUseHostError::InvalidConsumerConfiguration)
    ));
    let (_json_root, reference) =
        product_registry().map_err(|_| "reference owner initialization failed")?;
    let legacy_read = crate::BaoApprovedReadV1 {
        admission: &admission,
        grant: &grant,
        approval: &approval,
        request: &request,
    };
    assert!(matches!(
        host.consume_kv_v2_with_authbus(&client, &authbus, &reference, legacy_read, &mut evidence)
            .await,
        Err(crate::BaoProductHostError::ConsumerProfileRequired)
    ));
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let path = directory.path().join("product.sqlite");
    let owner = Arc::new(crate::SqliteBaoOwnerV1::open(&path, /*external_checkpoint*/ None).await?);
    let runtime = crate::SqliteBaoProductRuntimeV1::new(
        Arc::clone(&host),
        Arc::clone(&owner),
        Default::default(),
    )?;
    let _budget = consumer.begin_original_operation(
        admission.operation_id.as_str(),
        std::time::Instant::now() + Duration::from_secs(5),
    )?;
    let read = crate::BaoApprovedReadV1 {
        admission: &admission,
        grant: &grant,
        approval: &approval,
        request: &request,
    };
    let receipt = runtime
        .consume_kv_v2_with_authbus(&client, &authbus, read, &mut evidence)
        .await?;
    let original = owner
        .consumption_result(admission.operation_id.as_str())
        .await?;
    assert!(consumer.observe(
        admission.operation_id.as_str(),
        original.operation.semantic_sha256
    )?);
    let quota = authbus.quota_snapshot(&admission.quota_key).await?;
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 0, 1));
    tokio::time::timeout(Duration::from_secs(5), server_task)
        .await??
        .map_err(|_| "provider fixture exit failed")?;
    drop(runtime);
    owner.close().await;
    assert!(consumer_process.terminate()?.success());
    // Both provider and consumer have physically exited. An exact historical
    // call can succeed only from the immutable original terminal record.
    let owner = Arc::new(crate::SqliteBaoOwnerV1::open(&path, /*external_checkpoint*/ None).await?);
    let runtime =
        crate::SqliteBaoProductRuntimeV1::new(host, Arc::clone(&owner), Default::default())?;
    assert_eq!(
        runtime
            .consume_kv_v2_with_authbus(&client, &authbus, read, &mut evidence)
            .await?,
        receipt
    );
    assert_eq!(
        owner
            .consumption_result(admission.operation_id.as_str())
            .await?,
        original
    );
    owner.close().await;
    Ok(())
}

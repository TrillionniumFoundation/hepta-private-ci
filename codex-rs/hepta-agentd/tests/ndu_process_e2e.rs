//! Real normal-binary/UDS/local-disk qualification; no external clock or
//! off-host rollback oracle, trained artifact or learning-benefit claim.
#![cfg(unix)]
mod support;

use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_agent_protocol::NduCommittedEntryV1;
use codex_hepta_agent_protocol::NduControlRequestV1 as Request;
use codex_hepta_agent_protocol::NduControlResultV1 as Response;
use codex_hepta_agent_protocol::NduMutationOperationV1 as Operation;
use codex_hepta_agent_protocol::NduMutationV1 as Mutation;
use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdMethod;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_ndu::NduProjectionStoreError;
use codex_hepta_ndu::NduProjectionStoreV1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use support::fleet::FleetHarness;
use tokio::io::AsyncWriteExt;

fn digest(label: &str) -> [u8; 32] {
    *Digest32::of_bytes(label.as_bytes()).as_array()
}
fn now_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}
fn feed(path: &Path, signer: &SigningKey, revision: u64, revoked: BTreeSet<String>) -> Result<()> {
    let now = now_ms()?;
    let update = FinalUseRevocationUpdate::new(
        "ndu-feed".into(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision,
            revoked_grant_ids: revoked,
        },
        now.saturating_sub(1_000),
        now + 240_000,
    );
    let signature = signer.sign(&update.signing_bytes()?).to_bytes().to_vec();
    let bytes = serde_json::to_vec(&SignedFinalUseRevocationUpdate { update, signature })?;
    // The trusted feed publisher replaces atomically; readers never accept a
    // partially rewritten JSON document as a current authority view.
    let temporary = path.with_extension("tmp");
    std::fs::write(&temporary, bytes)?;
    std::fs::rename(temporary, path)?;
    Ok(())
}
fn mutation(
    label: &str,
    operation: Operation,
    projection: &str,
    predecessor: Option<&str>,
) -> Mutation {
    Mutation {
        operation,
        identity: digest(label),
        objective: digest("objective"),
        subject: digest("subject"),
        projection: digest(projection),
        expected_predecessor: predecessor.map(digest),
    }
}
async fn head(client: &AgentdClient) -> Result<[u8; 32]> {
    match client.ndu_control(Request::Context).await? {
        Response::Context { journal_head, .. } => Ok(journal_head),
        other => bail!("unexpected NDU context: {other:?}"),
    }
}
fn sign(
    binding: FinalUseBinding,
    key: &SigningKey,
    nonce: u8,
    grant_id: &str,
) -> Result<SignedFinalUseGrant> {
    let now = now_ms()?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "ndu-issuer".into(),
        authority_epoch: 1,
        grant_id: grant_id.into(),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = key.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}
async fn prepare(
    client: &AgentdClient,
    mutation: Mutation,
    key: &SigningKey,
    nonce: u8,
    grant_id: &str,
) -> Result<(Request, [u8; 32])> {
    let expected_head = head(client).await?;
    let binding = match client
        .ndu_control(Request::Prepare {
            mutation: mutation.clone(),
            expected_head,
        })
        .await?
    {
        Response::Prepared { binding, .. } => binding,
        other => bail!("unexpected NDU preparation: {other:?}"),
    };
    Ok((
        Request::Apply {
            mutation,
            expected_head,
            grant: sign(binding, key, nonce, grant_id)?,
        },
        expected_head,
    ))
}
async fn apply(
    client: &AgentdClient,
    mutation: Mutation,
    key: &SigningKey,
    nonce: u8,
) -> Result<NduCommittedEntryV1> {
    let (request, _) = prepare(client, mutation, key, nonce, &format!("grant-{nonce}")).await?;
    match client.ndu_control(request).await? {
        Response::Committed { entry } => Ok(entry),
        other => bail!("unexpected NDU commit: {other:?}"),
    }
}
async fn outcome(client: &AgentdClient, identity: [u8; 32]) -> Result<Option<NduCommittedEntryV1>> {
    match client.ndu_control(Request::Outcome { identity }).await? {
        Response::Outcome { entry } => Ok(entry),
        other => bail!("unexpected NDU outcome: {other:?}"),
    }
}

#[tokio::test]
async fn normal_agentd_ndu_mutation_lost_ack_revocation_and_process_recovery() -> Result<()> {
    let mut harness = FleetHarness::new()?;
    let agent = harness.register("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c79", "ndu-process")?;
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let store = root.join("store");
    let authority = root.join("authority");
    for path in [&store, &authority] {
        std::fs::create_dir(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    let issuer = SigningKey::from_bytes(&[93; 32]);
    let distributor = SigningKey::from_bytes(&[94; 32]);
    let feed_path = root.join("revocations.json");
    feed(&feed_path, &distributor, 1, BTreeSet::new())?;
    let descriptor = root.join("ndu.json");
    let bytes = serde_json::to_vec(&json!({
        "schema":"hepta.agentd.ndu-bootstrap.v1","trust_profile":"local-deterministic",
        "agent_id":agent.agent_id.as_str(),"store_root":store,"authority_directory":authority,
        "authority_signer":"ndu-issuer","authority_key":issuer.verifying_key().to_bytes(),
        "revocation_distributor":"ndu-feed","revocation_key":distributor.verifying_key().to_bytes(),
        "revocation_update_path":feed_path,
        "policy": {"profile_id":"ndu-product-v1","policy_id":"ndu-aggregate-v1",
            "axis_registry_digest":Digest32::from_array(digest("axes")).to_string(),
            "normalization_manifest_digest":Digest32::from_array(digest("normalization")).to_string(),
            "utility_axes":[{"id":"success","direction":"maximize","aggregation":"sum",
                "uncertainty_aggregation":"maximum","tolerance_raw":0}],
            "risk_axes":[{"id":"risk","maximum_raw":0,"aggregation":"maximum"}],
            "resource_axes":[{"id":"compute","maximum_raw":4294967296_i64,"aggregation":"sum"}],
            "required_organs":["planner"],"scalarization":null
        }
    }))?;
    std::fs::write(&descriptor, &bytes)?;
    harness.start_with_ndu_bootstrap_descriptor(
        &agent,
        &descriptor,
        &Digest32::of_bytes(&bytes).to_string(),
    )?;
    let (client, health) = harness.wait_ready(&agent, 1).await?;
    ensure!(
        matches!(
            NduProjectionStoreV1::open(&store),
            Err(NduProjectionStoreError::Busy)
        ),
        "second writer was admitted"
    );
    let first = apply(
        &client,
        mutation("append-a", Operation::AppendPreference, "a", None),
        &issuer,
        1,
    )
    .await?;
    ensure!(first.sequence == 1);

    let lost = mutation("append-b", Operation::AppendPreference, "b", None);
    let (request, _) = prepare(&client, lost.clone(), &issuer, 2, "grant-lost-ack").await?;
    let mut stream = codex_uds::UnixStream::connect(agent.layout.agentd_control_socket()).await?;
    let wire = AgentdRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 9_001,
        spawn_generation: 1,
        method: AgentdMethod::NduControl { request },
    };
    let mut frame = serde_json::to_vec(&wire)?;
    frame.push(b'\n');
    stream.write_all(&frame).await?;
    stream.shutdown().await?;
    drop(stream); // Intentionally discard the acknowledgement, never resend.
    let deadline = Instant::now() + Duration::from_secs(10);
    let recovered_lost = loop {
        if let Some(entry) = outcome(&client, lost.identity).await? {
            break entry;
        }
        ensure!(
            Instant::now() < deadline,
            "lost acknowledgement result was not queryable"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    };
    ensure!(recovered_lost.sequence == 2);
    apply(
        &client,
        mutation("select-a", Operation::Select, "a", None),
        &issuer,
        3,
    )
    .await?;
    let stale = mutation("stale-b", Operation::Select, "b", Some("a"));
    let (stale_request, _) = prepare(&client, stale.clone(), &issuer, 4, "grant-stale").await?;
    apply(
        &client,
        mutation("select-b", Operation::Select, "b", Some("a")),
        &issuer,
        5,
    )
    .await?;
    apply(
        &client,
        mutation("return-a", Operation::Select, "a", Some("b")),
        &issuer,
        6,
    )
    .await?;
    let before = head(&client).await?;
    ensure!(
        client.ndu_control(stale_request).await.is_err(),
        "ABA stale selection was accepted"
    );
    ensure!(head(&client).await? == before);
    ensure!(outcome(&client, stale.identity).await?.is_none());

    feed(
        &feed_path,
        &distributor,
        2,
        BTreeSet::from(["revoked-grant".to_string()]),
    )?;
    let denied = mutation("denied", Operation::AppendUtility, "denied", None);
    let (request, _) = prepare(&client, denied.clone(), &issuer, 7, "revoked-grant").await?;
    ensure!(
        client.ndu_control(request).await.is_err(),
        "live revoked grant was accepted"
    );
    ensure!(outcome(&client, denied.identity).await?.is_none());
    let revoked = apply(
        &client,
        mutation("revoke-a", Operation::Revoke, "a", None),
        &issuer,
        8,
    )
    .await?;
    match client
        .ndu_control(Request::Selection {
            objective: digest("objective"),
            subject: digest("subject"),
        })
        .await?
    {
        Response::Selection {
            projection: None, ..
        } => {}
        other => bail!("revoked selection remained active: {other:?}"),
    }

    harness.supervisor.kill(&agent.agent_id)?;
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        harness.supervisor.tick(Instant::now());
        if harness
            .supervisor
            .snapshot(&agent.agent_id)
            .is_some_and(|snapshot| !snapshot.active)
        {
            break;
        }
        ensure!(Instant::now() < deadline, "killed Agentd did not stop");
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    harness
        .supervisor
        .restart(&agent.agent_id, Instant::now())?;
    let (restarted, new_health) = harness.wait_new_spawn(&agent, 1).await?;
    ensure!(
        new_health.process_id != health.process_id,
        "process did not restart"
    );
    ensure!(outcome(&restarted, lost.identity).await? == Some(recovered_lost));
    ensure!(outcome(&restarted, revoked.identity).await? == Some(revoked));
    match restarted
        .ndu_control(Request::Selection {
            objective: digest("objective"),
            subject: digest("subject"),
        })
        .await?
    {
        Response::Selection {
            projection: None, ..
        } => {}
        other => bail!("restart resurrected revoked selection: {other:?}"),
    }
    ensure!(
        client.ndu_control(Request::Context).await.is_err(),
        "old generation client survived restart"
    );
    Ok(())
}

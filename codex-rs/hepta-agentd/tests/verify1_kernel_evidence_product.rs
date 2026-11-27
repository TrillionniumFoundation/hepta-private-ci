#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::KernelEvidenceAppendIngress;
use codex_hepta_agentd::KernelEvidenceCandidateV1;
use codex_hepta_agentd::KernelEvidenceQueryV1;
use codex_hepta_agentd::KernelEvidenceVerifyV1;
use codex_hepta_agentd::kernel_evidence_claims;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceCandidateV1;
use codex_hepta_evidence::EvidenceClaimClassV1;
use codex_hepta_evidence::EvidenceDispositionV1;
use codex_hepta_evidence::EvidenceId;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceReceiptKindV1;
use codex_hepta_evidence::EvidenceReferenceV1;
use codex_hepta_evidence::QualificationEvidenceEnvelopeV1;
use codex_hepta_evidence::Verify1FixtureGoal;
use codex_hepta_evidence::Verify1Record;
use codex_hepta_evidence::Verify1Scope;
use codex_hepta_evidence::Verify1Verdict;
use codex_hepta_evidence::check_verify1_sqlite;
use codex_hepta_evidence::parse_verify1_payload;
use codex_hepta_evidence::qualification_envelope_bytes;
use codex_hepta_evidence::verify1_receipt_payload;
use codex_state::SqliteConfig;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use sqlx::Connection;
use sqlx::SqliteConnection;

mod support;
use support::fleet::FleetHarness;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c44";
const ISSUER: &str = "issuer:verify1-fixture-checker";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_agentd_retains_checked_reports_with_current_trust_without_granting_effects()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "verify1-native-evidence")?;
    // Provider config only: this test makes no inference or model-efficacy claim.
    let provider = core_test_support::responses::start_mock_server().await;
    MockResponsesConfig::new(&provider.uri()).write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let key = SigningKey::from_bytes(&[71; 32]);
    let trust_file = agent.layout.home_root().join("verify1-evidence-trust.json");
    write_trust(&trust_file, &key, TrustState::Active)?;
    fleet.start_with_evidence_trust_file(&agent, &trust_file)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    ensure!(
        control
            .capabilities()
            .await?
            .capabilities
            .iter()
            .any(|item| item.id == "kernel.evidence" && item.major == 1),
        "kernel.evidence absent"
    );

    let fixture_path = agent.workspace.join("verify1.sqlite");
    let (mut fixture, goal, mut scope) = create_fixture(&fixture_path).await?;
    let receipt = check_verify1_sqlite(&fixture_path, &goal, &scope).await?;
    ensure!(
        receipt.verdict == Verify1Verdict::Proved,
        "ready fixture was not proved"
    );
    let envelope = QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        evidence_id: EvidenceId::parse("evidence:verify1:proved").map_err(anyhow::Error::msg)?,
        candidate: EvidenceCandidateV1 {
            candidate_id: "candidate:verify1:native-fixture".to_string(),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
        },
        claim_class: EvidenceClaimClassV1::Fixture,
        receipt_kind: EvidenceReceiptKindV1::Evidence,
        issuer_role: EvidenceIssuerRoleV1::TerminalObserver,
        payload: verify1_receipt_payload(&receipt).map_err(anyhow::Error::msg)?,
        predecessor_evidence_id: None,
        target_evidence_id: None,
        observed_unix_ms: now_ms()?,
        expires_unix_ms: None,
        asset_digests: vec![],
    };
    let expires = now_ms()?.saturating_add(120_000);
    let request = signed_request(&key, /*sequence*/ 1, expires, &envelope)?;
    ensure!(
        control.append_kernel_evidence(request.clone()).await? == envelope.evidence_id,
        "wrong append identity"
    );
    ensure!(
        control.append_kernel_evidence(request).await? == envelope.evidence_id,
        "exact replay was not idempotent"
    );
    let query = KernelEvidenceQueryV1 {
        candidate: wire_candidate(&envelope.candidate),
        claim_class: "fixture".to_string(),
    };
    let verify = KernelEvidenceVerifyV1 {
        candidate: wire_candidate(&envelope.candidate),
        claim_class: "fixture".to_string(),
        required_roles: vec!["terminal_observer".to_string()],
    };
    let reference = expected_reference(&envelope)?;
    ensure!(
        control.query_kernel_evidence(query.clone()).await? == vec![reference.clone()],
        "query did not bind retained canonical envelope"
    );
    ensure!(
        control.verify_kernel_evidence(verify.clone()).await?
            == EvidenceDispositionV1::Supported {
                evidence: vec![reference.clone()]
            },
        "checked report did not have chain support"
    );

    let mut changed = envelope.clone();
    changed.evidence_id =
        EvidenceId::parse("evidence:verify1:replay").map_err(anyhow::Error::msg)?;
    assert_server_rejected(
        control
            .append_kernel_evidence(signed_request(
                &key, /*sequence*/ 1, expires, &changed,
            )?)
            .await,
    )?;
    changed.evidence_id =
        EvidenceId::parse("evidence:verify1:expired").map_err(anyhow::Error::msg)?;
    assert_server_rejected(
        control
            .append_kernel_evidence(signed_request(
                &key,
                /*sequence*/ 50,
                now_ms()?.saturating_sub(1),
                &changed,
            )?)
            .await,
    )?;
    let mut tampered = signed_request(&key, /*sequence*/ 51, expires, &changed)?;
    changed.evidence_id =
        EvidenceId::parse("evidence:verify1:tampered").map_err(anyhow::Error::msg)?;
    tampered.envelope_json = String::from_utf8(qualification_envelope_bytes(&changed)?)?;
    assert_server_rejected(control.append_kernel_evidence(tampered).await)?;
    let mut wrong_tree = verify.clone();
    wrong_tree.candidate.source_tree = "c".repeat(40);
    ensure!(
        control.verify_kernel_evidence(wrong_tree).await? == EvidenceDispositionV1::Missing,
        "wrong source tree matched"
    );

    // A syntactically valid foreign 'proved' remains only a claim. Recompute the
    // actual state; no imported receipt is accepted by the checker API.
    let foreign = parse_verify1_payload(&envelope.payload).map_err(anyhow::Error::msg)?;
    ensure!(
        matches!(foreign,Verify1Record::VerificationReceipt(record) if record.verdict==Verify1Verdict::Proved),
        "foreign fixture report changed"
    );
    sqlx::query("UPDATE resources SET value=10 WHERE name='right'")
        .execute(&mut fixture)
        .await?;
    sqlx::query("UPDATE meta SET epoch=4")
        .execute(&mut fixture)
        .await?;
    scope.state_version = 4;
    let refuted = check_verify1_sqlite(&fixture_path, &goal, &scope).await?;
    ensure!(
        refuted.verdict == Verify1Verdict::Refuted,
        "foreign claim bypassed actual property checker"
    );
    let mut refuted_envelope = envelope.clone();
    refuted_envelope.evidence_id =
        EvidenceId::parse("evidence:verify1:refuted").map_err(anyhow::Error::msg)?;
    refuted_envelope.payload = verify1_receipt_payload(&refuted).map_err(anyhow::Error::msg)?;
    control
        .append_kernel_evidence(signed_request(
            &key,
            /*sequence*/ 2,
            expires,
            &refuted_envelope,
        )?)
        .await?;
    let refuted_reference = expected_reference(&refuted_envelope)?;
    let retained = vec![reference, refuted_reference];
    ensure!(
        control.query_kernel_evidence(query.clone()).await? == retained,
        "failed appends polluted query denominator"
    );
    ensure!(
        control.verify_kernel_evidence(verify.clone()).await?
            == EvidenceDispositionV1::Supported {
                evidence: retained.clone()
            },
        "refuted property report lost chain support"
    );
    // Supported authenticates retained evidence, including a refuted property.
    // It has not changed the fixture or created an acceptance record.
    let actual: (i64, i64) = sqlx::query_as(
        "SELECT value,(SELECT count(*) FROM accepted) FROM resources WHERE name='right'",
    )
    .fetch_one(&mut fixture)
    .await?;
    ensure!(
        actual == (10, 0),
        "evidence operation granted an effect or acceptance"
    );

    write_trust(&trust_file, &key, TrustState::Revoked)?;
    ensure!(
        matches!(
            control.verify_kernel_evidence(verify).await?,
            EvidenceDispositionV1::Conflicting { .. }
        ),
        "verifier ignored current trust revocation"
    );
    changed.evidence_id =
        EvidenceId::parse("evidence:verify1:revoked").map_err(anyhow::Error::msg)?;
    assert_server_rejected(
        control
            .append_kernel_evidence(signed_request(
                &key, /*sequence*/ 3, expires, &changed,
            )?)
            .await,
    )?;
    ensure!(
        control.query_kernel_evidence(query).await? == retained,
        "revoked writer changed retained evidence"
    );
    fixture.close().await?;
    Ok(())
}

async fn create_fixture(
    path: &Path,
) -> Result<(SqliteConnection, Verify1FixtureGoal, Verify1Scope)> {
    let config = SqliteConfig::from_sqlite_home(
        path.parent()
            .context("fixture parent missing")?
            .try_into()?,
    );
    let pool = config.open_durable_evidence_pool(path).await?;
    let mut db = pool.acquire().await?.detach();
    pool.close().await;
    sqlx::raw_sql("CREATE TABLE meta(epoch INTEGER NOT NULL,tick INTEGER NOT NULL);
        CREATE TABLE resources(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
        CREATE TABLE intents(operation_id TEXT PRIMARY KEY,request TEXT NOT NULL,tick INTEGER NOT NULL,finished INTEGER NOT NULL,ack INTEGER NOT NULL);
        CREATE TABLE readbacks(operation_id TEXT PRIMARY KEY,epoch INTEGER NOT NULL,evidence TEXT NOT NULL);
        CREATE TABLE journal(sequence INTEGER PRIMARY KEY,kind TEXT,payload TEXT);
        CREATE TABLE accepted(singleton INTEGER PRIMARY KEY CHECK(singleton=1),epoch INTEGER,goal TEXT,evidence TEXT);
        INSERT INTO meta VALUES(3,3); INSERT INTO resources VALUES('left',7),('right',9);
        INSERT INTO journal(kind,payload) VALUES('goal','{\"left\":7,\"right\":9,\"task_id\":\"task:native-agentd\"}');")
        .execute(&mut db).await?;
    let goal = Verify1FixtureGoal {
        task_id: "task:native-agentd".to_string(),
        left: 7,
        right: 9,
    };
    for tick in 1..=3 {
        sqlx::query("INSERT INTO intents VALUES(?,?,?,1,1)")
            .bind(format!("{}/step/{tick}", goal.task_id))
            .bind("a".repeat(64))
            .bind(tick)
            .execute(&mut db)
            .await?;
    }
    let scope = Verify1Scope {
        task_id: goal.task_id.clone(),
        attempt_id: "attempt:agentd".to_string(),
        subject_sha256: goal.subject_sha256()?.as_str().to_string(),
        state_version: 3,
        domain: "sqlite_two_field_engineering_fixture_v1".to_string(),
        event: "terminal_goal_value_error".to_string(),
        horizon_start: 4,
        horizon_end: 4,
    };
    Ok((db, goal, scope))
}

fn signed_request(
    key: &SigningKey,
    sequence: u64,
    expires_at_ms: u64,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<KernelEvidenceAppendIngress> {
    let message_id = format!("message:verify1:fixture:{sequence}");
    let claims = kernel_evidence_claims(
        ISSUER,
        /*key_epoch*/ 1,
        &message_id,
        sequence,
        expires_at_ms,
        envelope,
    )?;
    Ok(KernelEvidenceAppendIngress {
        issuer_id: ISSUER.to_string(),
        key_epoch: 1,
        message_id,
        sequence,
        expires_at_ms,
        signature_hex: hex(&key.sign(&claims.signing_bytes()).to_bytes()),
        envelope_json: String::from_utf8(qualification_envelope_bytes(envelope)?)?,
    })
}

fn expected_reference(envelope: &QualificationEvidenceEnvelopeV1) -> Result<EvidenceReferenceV1> {
    let bytes = qualification_envelope_bytes(envelope)?;
    let canonical: serde_json::Value = serde_json::from_slice(&bytes)?;
    Ok(EvidenceReferenceV1 {
        evidence_id: envelope.evidence_id.clone(),
        claim_class: envelope.claim_class,
        receipt_kind: envelope.receipt_kind,
        issuer_role: envelope.issuer_role,
        issuer_principal_id: ISSUER.to_string(),
        payload_sha256: Sha256Digest::for_bytes(&serde_json::to_vec(&canonical["payload"])?),
        envelope_sha256: Sha256Digest::for_bytes(&bytes),
        predecessor_evidence_id: None,
        target_evidence_id: None,
        observed_unix_ms: envelope.observed_unix_ms,
        expires_unix_ms: envelope.expires_unix_ms,
    })
}

fn wire_candidate(candidate: &EvidenceCandidateV1) -> KernelEvidenceCandidateV1 {
    KernelEvidenceCandidateV1 {
        candidate_id: candidate.candidate_id.clone(),
        source_commit: candidate.source_commit.clone(),
        source_tree: candidate.source_tree.clone(),
    }
}

fn assert_server_rejected(result: std::result::Result<EvidenceId, AgentdError>) -> Result<()> {
    let error = result
        .err()
        .context("negative case unexpectedly appended evidence")?;
    ensure!(
        matches!(&error,AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "failure outside Agentd rejection path: {error}"
    );
    Ok(())
}

enum TrustState {
    Active,
    Revoked,
}

fn write_trust(path: &Path, key: &SigningKey, state: TrustState) -> Result<()> {
    let registration = json!({"schema_version":1,"agent_id":AGENT_ID,"issuers":[{
        "issuer_id":ISSUER,"key_epoch":1,"public_key_hex":hex(key.verifying_key().as_bytes()),
        "revoked":matches!(state,TrustState::Revoked),"roles":["terminal_observer"]}]});
    let mut temporary =
        tempfile::NamedTempFile::new_in(path.parent().context("trust parent missing")?)?;
    temporary
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    serde_json::to_writer(temporary.as_file_mut(), &registration)?;
    temporary.as_file().sync_all()?;
    temporary.persist(path)?;
    Ok(())
}

fn now_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

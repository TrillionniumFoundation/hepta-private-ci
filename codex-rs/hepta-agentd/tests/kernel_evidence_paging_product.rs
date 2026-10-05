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
use codex_hepta_evidence::EvidenceCandidateV1;
use codex_hepta_evidence::EvidenceClaimClassV1;
use codex_hepta_evidence::EvidenceId;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceReceiptKindV1;
use codex_hepta_evidence::EvidenceVerificationStateV1;
use codex_hepta_evidence::QualificationEvidenceEnvelopeV1;
use codex_hepta_evidence::qualification_envelope_bytes;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

mod support;

use support::fleet::FleetHarness;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2d10";
const ARCHITECTURE_ISSUER: &str = "issuer:evidence-paging-architecture";

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn real_agentd_pages_evidence_and_returns_compact_profile_summary() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "kernel-evidence-paging-product")?;
    let model = core_test_support::responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;

    let key = SigningKey::from_bytes(&[71; 32]);
    let trust_file = agent.layout.home_root().join("evidence-trust.json");
    write_trust(&trust_file, &agent.agent_id.to_string(), &key)?;
    fleet.start_with_evidence_trust_file(&agent, &trust_file)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;

    let candidate = EvidenceCandidateV1 {
        candidate_id: "candidate:kernel-evidence-paging".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    };
    for sequence in 1..=3_u64 {
        let envelope = QualificationEvidenceEnvelopeV1 {
            schema_version: 1,
            evidence_id: EvidenceId::parse(format!("evidence:paging:{sequence}"))
                .expect("evidence id"),
            candidate: candidate.clone(),
            claim_class: EvidenceClaimClassV1::ExactSource,
            receipt_kind: EvidenceReceiptKindV1::Evidence,
            issuer_role: EvidenceIssuerRoleV1::Architecture,
            payload: json!({"sequence": sequence}),
            predecessor_evidence_id: None,
            target_evidence_id: None,
            observed_unix_ms: now_ms()?,
            expires_unix_ms: None,
            asset_digests: Vec::new(),
        };
        control
            .append_kernel_evidence(signed_request(&key, sequence, &envelope)?)
            .await?;
    }

    let first_request =
        KernelEvidenceQueryV1::paged(wire_candidate(&candidate), "exact_source", None, 2)
            .map_err(anyhow::Error::msg)?;
    ensure!(
        matches!(
            control.query_kernel_evidence(first_request.clone()).await,
            Err(AgentdError::Invalid(_))
        ),
        "legacy full-query client accepted the reserved page selector"
    );
    let first = control
        .query_kernel_evidence_page(first_request)
        .await
        .context("first evidence page")?;
    ensure!(
        first.evidence.len() == 2,
        "first page did not contain two rows"
    );
    let cursor = first.next_after_seq.context("first page had no cursor")?;
    let second = control
        .query_kernel_evidence_page(
            KernelEvidenceQueryV1::paged(
                wire_candidate(&candidate),
                "exact_source",
                Some(cursor),
                2,
            )
            .map_err(anyhow::Error::msg)?,
        )
        .await
        .context("second evidence page")?;
    ensure!(
        second.evidence.len() == 1,
        "second page did not contain one row"
    );
    ensure!(
        second.next_after_seq.is_none(),
        "last page returned another cursor"
    );
    ensure!(
        first.evidence[0].evidence_id.as_str() == "evidence:paging:1"
            && first.evidence[1].evidence_id.as_str() == "evidence:paging:2"
            && second.evidence[0].evidence_id.as_str() == "evidence:paging:3",
        "paged evidence order was not stable append-sequence order"
    );

    let profile_request =
        KernelEvidenceVerifyV1::profiled(wire_candidate(&candidate), "exact_source_architecture")
            .map_err(anyhow::Error::msg)?;
    ensure!(
        matches!(
            control
                .verify_kernel_evidence(profile_request.clone())
                .await,
            Err(AgentdError::Invalid(_))
        ),
        "legacy full verification client accepted the reserved profile selector"
    );
    let summary = control
        .verify_kernel_evidence_profile(profile_request)
        .await
        .context("compact verification summary")?;
    ensure!(
        summary.state == EvidenceVerificationStateV1::Supported,
        "owner profile did not support the authenticated exact-source evidence"
    );
    ensure!(
        summary.evidence_count == 3,
        "summary evidence count drifted"
    );
    ensure!(
        summary.evidence_set_sha256.is_some(),
        "supported summary omitted its canonical evidence-set digest"
    );
    Ok(())
}

fn signed_request(
    key: &SigningKey,
    sequence: u64,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<KernelEvidenceAppendIngress> {
    let message_id = format!("message:kernel-evidence-paging:{sequence}");
    let expires_at_ms = now_ms()?.saturating_add(120_000);
    let claims = kernel_evidence_claims(
        ARCHITECTURE_ISSUER,
        1,
        &message_id,
        sequence,
        expires_at_ms,
        envelope,
    )?;
    Ok(KernelEvidenceAppendIngress {
        issuer_id: ARCHITECTURE_ISSUER.to_string(),
        key_epoch: 1,
        message_id,
        sequence,
        expires_at_ms,
        signature_hex: hex(&key.sign(&claims.signing_bytes()).to_bytes()),
        envelope_json: String::from_utf8(qualification_envelope_bytes(envelope)?)?,
    })
}

fn write_trust(path: &Path, agent_id: &str, key: &SigningKey) -> Result<()> {
    let registration = json!({
        "schema_version": 1,
        "agent_id": agent_id,
        "issuers": [{
            "issuer_id": ARCHITECTURE_ISSUER,
            "key_epoch": 1,
            "public_key_hex": hex(key.verifying_key().as_bytes()),
            "revoked": false,
            "roles": ["architecture"]
        }]
    });
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

fn wire_candidate(candidate: &EvidenceCandidateV1) -> KernelEvidenceCandidateV1 {
    KernelEvidenceCandidateV1 {
        candidate_id: candidate.candidate_id.clone(),
        source_commit: candidate.source_commit.clone(),
        source_tree: candidate.source_tree.clone(),
    }
}

fn now_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

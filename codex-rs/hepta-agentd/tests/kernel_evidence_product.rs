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
use codex_hepta_evidence::EvidenceDispositionV1;
use codex_hepta_evidence::EvidenceId;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceReceiptKindV1;
use codex_hepta_evidence::IndependentDecisionReceiptV1;
use codex_hepta_evidence::IndependentDecisionRoleV1;
use codex_hepta_evidence::IndependentDecisionV1;
use codex_hepta_evidence::QualificationEvidenceEnvelopeV1;
use codex_hepta_evidence::evidence_set_digest;
use codex_hepta_evidence::qualification_envelope_bytes;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

mod support;

use support::fleet::FleetHarness;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c30";
const ARCHITECTURE_ISSUER: &str = "issuer:evidence-architecture";
const SECURITY_ISSUER: &str = "issuer:evidence-security";
const TERMINAL_ISSUER: &str = "issuer:evidence-terminal";

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn real_agentd_composes_authenticated_evidence_writer_query_verifier_and_terminal_observer()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "kernel-evidence-product")?;
    let model = core_test_support::responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;

    let architecture_key = SigningKey::from_bytes(&[31; 32]);
    let security_key = SigningKey::from_bytes(&[32; 32]);
    let terminal_key = SigningKey::from_bytes(&[33; 32]);
    let trust_file = agent.layout.home_root().join("evidence-trust.json");
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[
            TrustEntry {
                issuer_id: ARCHITECTURE_ISSUER,
                key: &architecture_key,
                revoked: false,
                roles: &["architecture"],
            },
            TrustEntry {
                issuer_id: SECURITY_ISSUER,
                key: &security_key,
                revoked: false,
                roles: &["security"],
            },
            TrustEntry {
                issuer_id: TERMINAL_ISSUER,
                key: &terminal_key,
                revoked: false,
                roles: &["terminal_observer"],
            },
        ],
    )?;

    fleet.start_with_evidence_trust_file(&agent, &trust_file)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let capabilities = control.capabilities().await?;
    ensure!(
        capabilities
            .capabilities
            .iter()
            .any(|capability| capability.id == "kernel.evidence" && capability.major == 1),
        "running Agentd did not advertise kernel.evidence"
    );

    let candidate = EvidenceCandidateV1 {
        candidate_id: "candidate:kernel-evidence-product".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    };
    let observed = now_ms()?;
    let exact = base_evidence(
        "evidence:product-exact-source",
        candidate.clone(),
        EvidenceClaimClassV1::ExactSource,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"exact_head": true, "tree_bound": true}),
    );
    let exact_request = signed_request(
        ARCHITECTURE_ISSUER,
        &architecture_key,
        /*sequence*/ 1,
        &exact,
    )?;
    ensure!(
        control.append_kernel_evidence(exact_request).await? == exact.evidence_id,
        "product append returned a different evidence id"
    );

    let exact_refs = control
        .query_kernel_evidence(KernelEvidenceQueryV1 {
            candidate: wire_candidate(&candidate),
            claim_class: EvidenceClaimClassV1::ExactSource.as_str().to_string(),
        })
        .await?;
    ensure!(exact_refs.len() == 1, "exact-source evidence was not queryable");
    ensure!(
        matches!(
            control
                .verify_kernel_evidence(KernelEvidenceVerifyV1 {
                    candidate: wire_candidate(&candidate),
                    claim_class: EvidenceClaimClassV1::ExactSource.as_str().to_string(),
                    required_roles: vec!["architecture".to_string()],
                    now_unix_ms: observed,
                })
                .await?,
            EvidenceDispositionV1::Supported { .. }
        ),
        "real Agentd verifier did not accept exact authenticated source evidence"
    );

    let source_set_digest = evidence_set_digest(&exact_refs)?;
    let decision_expiry = observed.saturating_add(60_000);
    let architecture_decision = independent_decision(
        "decision:product-architecture",
        &candidate,
        EvidenceIssuerRoleV1::Architecture,
        IndependentDecisionRoleV1::Architecture,
        ARCHITECTURE_ISSUER,
        &architecture_key,
        source_set_digest.clone(),
        observed,
        decision_expiry,
    );
    control
        .append_kernel_evidence(signed_request(
            ARCHITECTURE_ISSUER,
            &architecture_key,
            /*sequence*/ 2,
            &architecture_decision,
        )?)
        .await?;

    let security_decision = independent_decision(
        "decision:product-security",
        &candidate,
        EvidenceIssuerRoleV1::Security,
        IndependentDecisionRoleV1::Security,
        SECURITY_ISSUER,
        &security_key,
        source_set_digest,
        observed,
        decision_expiry,
    );
    control
        .append_kernel_evidence(signed_request(
            SECURITY_ISSUER,
            &security_key,
            /*sequence*/ 1,
            &security_decision,
        )?)
        .await?;

    ensure!(
        matches!(
            control
                .verify_kernel_evidence(KernelEvidenceVerifyV1 {
                    candidate: wire_candidate(&candidate),
                    claim_class: EvidenceClaimClassV1::IndependentDecision.as_str().to_string(),
                    required_roles: vec!["architecture".to_string(), "security".to_string()],
                    now_unix_ms: observed,
                })
                .await?,
            EvidenceDispositionV1::Supported { evidence } if evidence.len() == 2
        ),
        "independent Agentd decisions were not bound to distinct principals"
    );

    let terminal = base_evidence(
        "evidence:product-terminal-observer",
        candidate.clone(),
        EvidenceClaimClassV1::ProviderEffect,
        EvidenceIssuerRoleV1::TerminalObserver,
        observed,
        None,
        json!({
            "provider_operation_digest": Sha256Digest::for_bytes(b"provider-operation").as_str(),
            "terminal_state": "completed"
        }),
    );
    control
        .append_kernel_evidence(signed_request(
            TERMINAL_ISSUER,
            &terminal_key,
            /*sequence*/ 1,
            &terminal,
        )?)
        .await?;
    ensure!(
        control
            .query_kernel_evidence(KernelEvidenceQueryV1 {
                candidate: wire_candidate(&candidate),
                claim_class: EvidenceClaimClassV1::ProviderEffect.as_str().to_string(),
            })
            .await?
            .iter()
            .any(|reference| {
                reference.evidence_id == terminal.evidence_id
                    && reference.issuer_role == EvidenceIssuerRoleV1::TerminalObserver
            }),
        "terminal observer evidence was not persisted through the product path"
    );

    // Revocation is reloaded at the physical append boundary. A previously
    // trusted key cannot keep writing after the owner changes the registry.
    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[
            TrustEntry {
                issuer_id: ARCHITECTURE_ISSUER,
                key: &architecture_key,
                revoked: true,
                roles: &["architecture"],
            },
            TrustEntry {
                issuer_id: SECURITY_ISSUER,
                key: &security_key,
                revoked: false,
                roles: &["security"],
            },
            TrustEntry {
                issuer_id: TERMINAL_ISSUER,
                key: &terminal_key,
                revoked: false,
                roles: &["terminal_observer"],
            },
        ],
    )?;
    let after_revoke = base_evidence(
        "evidence:after-revoke",
        candidate,
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"must_not_commit": true}),
    );
    let rejection = control
        .append_kernel_evidence(signed_request(
            ARCHITECTURE_ISSUER,
            &architecture_key,
            /*sequence*/ 3,
            &after_revoke,
        )?)
        .await
        .err()
        .context("revoked evidence writer was accepted")?;
    ensure!(
        matches!(&rejection, AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "revoked writer failed outside the real server path: {rejection}"
    );
    Ok(())
}

fn base_evidence(
    id: &str,
    candidate: EvidenceCandidateV1,
    claim_class: EvidenceClaimClassV1,
    issuer_role: EvidenceIssuerRoleV1,
    observed_unix_ms: u64,
    expires_unix_ms: Option<u64>,
    payload: serde_json::Value,
) -> QualificationEvidenceEnvelopeV1 {
    QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        evidence_id: EvidenceId::parse(id).expect("evidence id"),
        candidate,
        claim_class,
        receipt_kind: EvidenceReceiptKindV1::Evidence,
        issuer_role,
        payload,
        predecessor_evidence_id: None,
        target_evidence_id: None,
        observed_unix_ms,
        expires_unix_ms,
        asset_digests: Vec::new(),
    }
}

#[allow(clippy::too_many_arguments)]
fn independent_decision(
    id: &str,
    candidate: &EvidenceCandidateV1,
    issuer_role: EvidenceIssuerRoleV1,
    role: IndependentDecisionRoleV1,
    issuer_id: &str,
    key: &SigningKey,
    evidence_set_digest: Sha256Digest,
    observed: u64,
    expires: u64,
) -> QualificationEvidenceEnvelopeV1 {
    let receipt = IndependentDecisionReceiptV1 {
        decision_id: id.to_string(),
        candidate_id: candidate.candidate_id.clone(),
        role,
        principal_id: issuer_id.to_string(),
        signing_identity_digest: Sha256Digest::for_bytes(key.verifying_key().as_bytes()),
        evidence_set_digest,
        decision: IndependentDecisionV1::Accept,
        conditions: Vec::new(),
        expires_unix_ms: expires,
    };
    base_evidence(
        id,
        candidate.clone(),
        EvidenceClaimClassV1::IndependentDecision,
        issuer_role,
        observed,
        Some(expires),
        serde_json::to_value(receipt).expect("decision payload"),
    )
}

fn signed_request(
    issuer_id: &str,
    key: &SigningKey,
    sequence: u64,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<KernelEvidenceAppendIngress> {
    let expires_at_ms = now_ms()?.saturating_add(120_000);
    let message_id = format!("message:kernel-evidence:{issuer_id}:{sequence}");
    let claims = kernel_evidence_claims(
        issuer_id,
        1,
        &message_id,
        sequence,
        expires_at_ms,
        envelope,
    )?;
    Ok(KernelEvidenceAppendIngress {
        issuer_id: issuer_id.to_string(),
        key_epoch: 1,
        message_id,
        sequence,
        expires_at_ms,
        signature_hex: hex(&key.sign(&claims.signing_bytes()).to_bytes()),
        envelope_json: String::from_utf8(qualification_envelope_bytes(envelope)?)?,
    })
}

fn wire_candidate(candidate: &EvidenceCandidateV1) -> KernelEvidenceCandidateV1 {
    KernelEvidenceCandidateV1 {
        candidate_id: candidate.candidate_id.clone(),
        source_commit: candidate.source_commit.clone(),
        source_tree: candidate.source_tree.clone(),
    }
}

struct TrustEntry<'a> {
    issuer_id: &'a str,
    key: &'a SigningKey,
    revoked: bool,
    roles: &'a [&'a str],
}

fn write_trust(
    path: &Path,
    agent_id: &str,
    entries: &[TrustEntry<'_>],
) -> Result<()> {
    let issuers = entries
        .iter()
        .map(|entry| {
            json!({
                "issuer_id": entry.issuer_id,
                "key_epoch": 1,
                "public_key_hex": hex(entry.key.verifying_key().as_bytes()),
                "revoked": entry.revoked,
                "roles": entry.roles,
            })
        })
        .collect::<Vec<_>>();
    let registration = json!({
        "schema_version": 1,
        "agent_id": agent_id,
        "issuers": issuers,
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

fn now_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

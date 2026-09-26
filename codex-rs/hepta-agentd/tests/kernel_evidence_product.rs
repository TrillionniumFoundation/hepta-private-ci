#![allow(clippy::expect_used)]
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
use codex_hepta_agentd::EvidenceRecoveryFrontierV1;
use codex_hepta_agentd::KernelEvidenceAppendIngress;
use codex_hepta_agentd::KernelEvidenceCandidateV1;
use codex_hepta_agentd::KernelEvidenceQueryV1;
use codex_hepta_agentd::KernelEvidenceVerifyV1;
use codex_hepta_agentd::evidence_recovery_frontier_signing_bytes;
use codex_hepta_agentd::kernel_evidence_claims;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceCandidateV1;
use codex_hepta_evidence::EvidenceClaimClassV1;
use codex_hepta_evidence::EvidenceDispositionV1;
use codex_hepta_evidence::EvidenceId;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceReceiptKindV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::IndependentDecisionReceiptV1;
use codex_hepta_evidence::IndependentDecisionRoleV1;
use codex_hepta_evidence::IndependentDecisionV1;
use codex_hepta_evidence::QualificationEvidenceEnvelopeV1;
use codex_hepta_evidence::evidence_set_digest;
use codex_hepta_evidence::qualification_envelope_bytes;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

mod support;

use support::fleet::FleetHarness;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c30";
const RECOVERY_OK_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c31";
const RECOVERY_OLD_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c32";
const RECOVERY_SIGNER: &str = "issuer:evidence-recovery-frontier";
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
    ensure!(
        exact_refs.len() == 1,
        "exact-source evidence was not queryable"
    );
    ensure!(
        matches!(
            control
                .verify_kernel_evidence(KernelEvidenceVerifyV1 {
                    candidate: wire_candidate(&candidate),
                    claim_class: EvidenceClaimClassV1::ExactSource.as_str().to_string(),
                    required_roles: vec!["architecture".to_string()],
                })
                .await?,
            EvidenceDispositionV1::Supported { .. }
        ),
        "real Agentd verifier did not accept exact authenticated source evidence"
    );

    let mut wrong_tree = candidate.clone();
    wrong_tree.source_tree = "c".repeat(40);
    ensure!(
        matches!(
            control
                .verify_kernel_evidence(KernelEvidenceVerifyV1 {
                    candidate: wire_candidate(&wrong_tree),
                    claim_class: EvidenceClaimClassV1::ExactSource.as_str().to_string(),
                    required_roles: vec!["architecture".to_string()],
                })
                .await?,
            EvidenceDispositionV1::Missing
        ),
        "wrong candidate tree satisfied exact-source evidence through Agentd"
    );

    let wrong_role = base_evidence(
        "evidence:product-wrong-role",
        candidate.clone(),
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Security,
        observed,
        None,
        json!({"must_not_commit": "wrong-role"}),
    );
    let wrong_role_rejection = control
        .append_kernel_evidence(signed_request(
            ARCHITECTURE_ISSUER,
            &architecture_key,
            /*sequence*/ 50,
            &wrong_role,
        )?)
        .await
        .err()
        .context("wrong-role evidence writer was accepted")?;
    ensure!(
        matches!(&wrong_role_rejection, AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "wrong-role writer failed outside the real server path: {wrong_role_rejection}"
    );

    let replayed = base_evidence(
        "evidence:product-replay",
        candidate.clone(),
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"must_not_commit": "replay"}),
    );
    let replay_rejection = control
        .append_kernel_evidence(signed_request(
            ARCHITECTURE_ISSUER,
            &architecture_key,
            /*sequence*/ 1,
            &replayed,
        )?)
        .await
        .err()
        .context("replayed evidence sequence was accepted")?;
    ensure!(
        matches!(&replay_rejection, AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "replay failed outside the real server path: {replay_rejection}"
    );

    let expired_ingress = base_evidence(
        "evidence:product-expired-ingress",
        candidate.clone(),
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"must_not_commit": "expired"}),
    );
    let expired_rejection = control
        .append_kernel_evidence(signed_request_with_expiry(
            ARCHITECTURE_ISSUER,
            &architecture_key,
            /*sequence*/ 51,
            now_ms()?.saturating_sub(1),
            &expired_ingress,
        )?)
        .await
        .err()
        .context("expired evidence ingress was accepted")?;
    ensure!(
        matches!(&expired_rejection, AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "expired ingress failed outside the real server path: {expired_rejection}"
    );

    let registry = base_evidence(
        "evidence:product-registry-snapshot",
        candidate.clone(),
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({
            "registry_digest": Sha256Digest::for_bytes(b"kernel-evidence-registry-v1").as_str()
        }),
    );
    control
        .append_kernel_evidence(signed_request(
            ARCHITECTURE_ISSUER,
            &architecture_key,
            /*sequence*/ 2,
            &registry,
        )?)
        .await?;

    let mandatory_tests = base_evidence(
        "evidence:product-mandatory-tests",
        candidate.clone(),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Security,
        observed,
        None,
        json!({
            "test_evidence_digest": Sha256Digest::for_bytes(b"kernel-evidence-tests-v1").as_str(),
            "passed": true
        }),
    );
    control
        .append_kernel_evidence(signed_request(
            SECURITY_ISSUER,
            &security_key,
            /*sequence*/ 1,
            &mandatory_tests,
        )?)
        .await?;

    let mut reviewed_evidence = exact_refs;
    reviewed_evidence.extend(
        control
            .query_kernel_evidence(KernelEvidenceQueryV1 {
                candidate: wire_candidate(&candidate),
                claim_class: EvidenceClaimClassV1::RegistrySnapshot.as_str().to_string(),
            })
            .await?,
    );
    reviewed_evidence.extend(
        control
            .query_kernel_evidence(KernelEvidenceQueryV1 {
                candidate: wire_candidate(&candidate),
                claim_class: EvidenceClaimClassV1::MandatoryTests.as_str().to_string(),
            })
            .await?,
    );
    let source_set_digest = evidence_set_digest(&reviewed_evidence)?;
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
            /*sequence*/ 3,
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
            /*sequence*/ 2,
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

    // Trust is reloaded both at append and positive-verification boundaries.
    // Rotating a key invalidates old evidence for positive claims and rejects
    // stale-key writes; a subsequent explicit revocation rejects the new key.
    let rotated_architecture_key = SigningKey::from_bytes(&[34; 32]);
    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[
            TrustEntry {
                issuer_id: ARCHITECTURE_ISSUER,
                key: &rotated_architecture_key,
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
    ensure!(
        matches!(
            control
                .verify_kernel_evidence(KernelEvidenceVerifyV1 {
                    candidate: wire_candidate(&candidate),
                    claim_class: EvidenceClaimClassV1::ExactSource.as_str().to_string(),
                    required_roles: vec!["architecture".to_string()],
                })
                .await?,
            EvidenceDispositionV1::Conflicting { .. }
        ),
        "key rotation did not invalidate stale positive evidence through Agentd"
    );

    let stale_key_attempt = base_evidence(
        "evidence:after-key-rotation",
        candidate.clone(),
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"must_not_commit": "stale-key"}),
    );
    let stale_key_rejection = control
        .append_kernel_evidence(signed_request(
            ARCHITECTURE_ISSUER,
            &architecture_key,
            /*sequence*/ 52,
            &stale_key_attempt,
        )?)
        .await
        .err()
        .context("stale evidence signing key was accepted")?;
    ensure!(
        matches!(&stale_key_rejection, AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "stale key failed outside the real server path: {stale_key_rejection}"
    );

    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[
            TrustEntry {
                issuer_id: ARCHITECTURE_ISSUER,
                key: &rotated_architecture_key,
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
        json!({"must_not_commit": "revoked"}),
    );
    let revoked_rejection = control
        .append_kernel_evidence(signed_request(
            ARCHITECTURE_ISSUER,
            &rotated_architecture_key,
            /*sequence*/ 53,
            &after_revoke,
        )?)
        .await
        .err()
        .context("revoked evidence writer was accepted")?;
    ensure!(
        matches!(&revoked_rejection, AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "revoked writer failed outside the real server path: {revoked_rejection}"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn signed_recovery_frontier_allows_exact_current_database() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(RECOVERY_OK_AGENT_ID, "kernel-evidence-recovery-ok")?;
    let model = core_test_support::responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;

    let architecture_key = SigningKey::from_bytes(&[61; 32]);
    let trust_file = agent.layout.home_root().join("evidence-trust.json");
    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[TrustEntry {
            issuer_id: ARCHITECTURE_ISSUER,
            key: &architecture_key,
            revoked: false,
            roles: &["architecture"],
        }],
    )?;

    let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
        agent.layout.home_root(),
    )?);
    let store = HeptaEvidenceStore::open(&sqlite).await?;
    let candidate = EvidenceCandidateV1 {
        candidate_id: "candidate:kernel-evidence-recovery-ok".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    };
    let envelope = base_evidence(
        "evidence:recovery-current",
        candidate.clone(),
        EvidenceClaimClassV1::ExactSource,
        EvidenceIssuerRoleV1::Architecture,
        now_ms()?,
        None,
        json!({"frontier": "current"}),
    );
    append_direct_evidence(&store, ARCHITECTURE_ISSUER, &architecture_key, 1, &envelope).await?;
    let snapshot = store.recovery_snapshot().await?;
    store.close().await;

    let external = tempfile::tempdir()?;
    let (frontier_file, frontier_trust_file) = write_recovery_frontier(
        external.path(),
        "store:kernel-evidence-recovery-ok",
        snapshot,
    )?;
    fleet.start_with_evidence_recovery(
        &agent,
        &trust_file,
        &frontier_file,
        &frontier_trust_file,
    )?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    ensure!(
        matches!(
            control
                .verify_kernel_evidence(KernelEvidenceVerifyV1 {
                    candidate: wire_candidate(&candidate),
                    claim_class: EvidenceClaimClassV1::ExactSource.as_str().to_string(),
                    required_roles: vec!["architecture".to_string()],
                })
                .await?,
            EvidenceDispositionV1::Supported { .. }
        ),
        "signed recovery frontier did not admit the exact current evidence database"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn signed_recovery_frontier_rejects_valid_older_database_image() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(RECOVERY_OLD_AGENT_ID, "kernel-evidence-recovery-old")?;
    let model = core_test_support::responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;

    let architecture_key = SigningKey::from_bytes(&[62; 32]);
    let trust_file = agent.layout.home_root().join("evidence-trust.json");
    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[TrustEntry {
            issuer_id: ARCHITECTURE_ISSUER,
            key: &architecture_key,
            revoked: false,
            roles: &["architecture"],
        }],
    )?;

    let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
        agent.layout.home_root(),
    )?);
    let old_store = HeptaEvidenceStore::open(&sqlite).await?;
    let database_path = old_store.path().to_path_buf();
    old_store.close().await;

    let external = tempfile::tempdir()?;
    let old_image = external.path().join("hepta-evidence-old.sqlite");
    std::fs::copy(&database_path, &old_image)?;

    let current_store = HeptaEvidenceStore::open(&sqlite).await?;
    let envelope = base_evidence(
        "evidence:recovery-newer",
        EvidenceCandidateV1 {
            candidate_id: "candidate:kernel-evidence-recovery-old".to_string(),
            source_commit: "c".repeat(40),
            source_tree: "d".repeat(40),
        },
        EvidenceClaimClassV1::ExactSource,
        EvidenceIssuerRoleV1::Architecture,
        now_ms()?,
        None,
        json!({"frontier": "newer"}),
    );
    append_direct_evidence(
        &current_store,
        ARCHITECTURE_ISSUER,
        &architecture_key,
        1,
        &envelope,
    )
    .await?;
    let current_snapshot = current_store.recovery_snapshot().await?;
    current_store.close().await;

    let (frontier_file, frontier_trust_file) = write_recovery_frontier(
        external.path(),
        "store:kernel-evidence-recovery-old",
        current_snapshot,
    )?;

    std::fs::copy(&old_image, &database_path)?;
    fleet.start_with_evidence_recovery(
        &agent,
        &trust_file,
        &frontier_file,
        &frontier_trust_file,
    )?;
    let failure = fleet
        .wait_ready(&agent, 1)
        .await
        .err()
        .context("older evidence database unexpectedly reached readiness")?;
    ensure!(
        format!("{failure:#}").contains("recovery_required"),
        "older database failed without the recovery-required oracle: {failure:#}"
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
    signed_request_with_expiry(
        issuer_id,
        key,
        sequence,
        now_ms()?.saturating_add(120_000),
        envelope,
    )
}

fn signed_request_with_expiry(
    issuer_id: &str,
    key: &SigningKey,
    sequence: u64,
    expires_at_ms: u64,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<KernelEvidenceAppendIngress> {
    let message_id = format!("message:kernel-evidence:{issuer_id}:{sequence}");
    let claims =
        kernel_evidence_claims(issuer_id, 1, &message_id, sequence, expires_at_ms, envelope)?;
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

async fn append_direct_evidence(
    store: &HeptaEvidenceStore,
    issuer_id: &str,
    key: &SigningKey,
    sequence: u64,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<()> {
    let claims = kernel_evidence_claims(
        issuer_id,
        1,
        &format!("message:recovery:{issuer_id}:{sequence}"),
        sequence,
        now_ms()?.saturating_add(120_000),
        envelope,
    )?;
    let message = SignedMessage {
        signature: key.sign(&claims.signing_bytes()).to_bytes(),
        claims,
    };
    let issuer = IssuerRegistration {
        issuer_id: StableId::new(issuer_id.to_string()).map_err(anyhow::Error::msg)?,
        key_epoch: Generation::new(1).map_err(anyhow::Error::msg)?,
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    store
        .qualification()
        .append_receipt(&issuer, &message, envelope)
        .await?;
    Ok(())
}

fn write_recovery_frontier(
    directory: &Path,
    store_id: &str,
    snapshot: codex_hepta_evidence::EvidenceRecoverySnapshotV1,
) -> Result<(std::path::PathBuf, std::path::PathBuf)> {
    let signer_key = SigningKey::from_bytes(&[63; 32]);
    let mut frontier = EvidenceRecoveryFrontierV1 {
        schema_version: 1,
        store_id: store_id.to_string(),
        frontier_generation: 1,
        snapshot,
        source_commit: "e".repeat(40),
        source_tree: "f".repeat(40),
        created_at_unix_ms: now_ms()?,
        signer_principal_id: RECOVERY_SIGNER.to_string(),
        signer_key_epoch: 1,
        signature_hex: "00".repeat(64),
    };
    frontier.signature_hex = hex(&signer_key
        .sign(&evidence_recovery_frontier_signing_bytes(&frontier)?)
        .to_bytes());

    let frontier_file = directory.join("evidence-recovery-frontier.json");
    write_private_json(&frontier_file, &frontier)?;
    let trust_file = directory.join("evidence-recovery-frontier-trust.json");
    write_private_json(
        &trust_file,
        &json!({
            "schemaVersion": 1,
            "signerPrincipalId": RECOVERY_SIGNER,
            "signerKeyEpoch": 1,
            "publicKeyHex": hex(signer_key.verifying_key().as_bytes()),
            "revoked": false
        }),
    )?;
    Ok((frontier_file, trust_file))
}

fn write_private_json<T: serde::Serialize>(path: &Path, value: &T) -> Result<()> {
    let mut temporary =
        tempfile::NamedTempFile::new_in(path.parent().context("JSON parent missing")?)?;
    temporary
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    serde_json::to_writer(temporary.as_file_mut(), value)?;
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

struct TrustEntry<'a> {
    issuer_id: &'a str,
    key: &'a SigningKey,
    revoked: bool,
    roles: &'a [&'a str],
}

fn write_trust(path: &Path, agent_id: &str, entries: &[TrustEntry<'_>]) -> Result<()> {
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

#[path = "support/evaluation_publication.rs"]
mod evaluation_publication;

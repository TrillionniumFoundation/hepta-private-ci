use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::AuthenticatedEvidenceIssuerV1;
use crate::EvidenceDisposition;
use crate::EvidenceError;
use crate::EvidenceId;
use crate::HeptaEvidenceStore;
use crate::QUALIFICATION_EVIDENCE_SCHEMA_VERSION;
use crate::QualificationCandidateV1;
use crate::QualificationClaimClassV1;
use crate::QualificationEvidenceDecisionV1;
use crate::QualificationEvidenceEnvelopeV1;
use crate::QualificationEvidenceRoleV1;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time after epoch")
            .as_millis(),
    )
    .expect("millis fit u64")
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn candidate() -> QualificationCandidateV1 {
    QualificationCandidateV1 {
        candidate_id: "candidate:kernel-evidence".to_string(),
        source_commit: "1".repeat(40),
        source_tree: "2".repeat(40),
    }
}

fn issuer(
    seed: u8,
    principal: &str,
    controller: &str,
    roles: Vec<QualificationEvidenceRoleV1>,
    now: u64,
) -> (SigningKey, AuthenticatedEvidenceIssuerV1) {
    let signing = SigningKey::from_bytes(&[seed; 32]);
    let verifying_key = signing.verifying_key().to_bytes();
    (
        signing,
        AuthenticatedEvidenceIssuerV1 {
            principal_id: principal.to_string(),
            controller_id: controller.to_string(),
            signing_identity_digest: Sha256Digest::for_bytes(&verifying_key),
            credential_chain_digest: Sha256Digest::for_bytes(
                format!("credential:{principal}:{controller}").as_bytes(),
            ),
            verifying_key,
            roles,
            authenticated_at_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 60_000,
            revoked_at_unix_ms: None,
        },
    )
}

fn receipt(
    signing: &SigningKey,
    issuer: &AuthenticatedEvidenceIssuerV1,
    id: &str,
    claim: QualificationClaimClassV1,
    role: QualificationEvidenceRoleV1,
    predecessor: Option<EvidenceId>,
    now: u64,
) -> QualificationEvidenceEnvelopeV1 {
    let mut envelope = QualificationEvidenceEnvelopeV1 {
        schema_version: QUALIFICATION_EVIDENCE_SCHEMA_VERSION,
        evidence_id: EvidenceId::parse(id).expect("evidence id"),
        candidate_id: candidate().candidate_id,
        source_commit: candidate().source_commit,
        source_tree: candidate().source_tree,
        claim_class: claim,
        protocol_id: claim.protocol_id().to_string(),
        issuer_principal_id: issuer.principal_id.clone(),
        issuer_controller_id: issuer.controller_id.clone(),
        issuer_role: role,
        signing_identity_digest: issuer.signing_identity_digest.clone(),
        credential_chain_digest: issuer.credential_chain_digest.clone(),
        verifying_key_hex: hex(&issuer.verifying_key),
        payload_digest: Sha256Digest::for_bytes(format!("payload:{id}").as_bytes()),
        evidence_set_digest: Sha256Digest::for_bytes(format!("evidence-set:{id}").as_bytes()),
        predecessor_evidence_id: predecessor,
        observed_unix_ms: now,
        expires_unix_ms: now + 30_000,
        revokes_evidence_id: None,
        supersedes_evidence_id: None,
        asset_digests: vec![Sha256Digest::for_bytes(format!("asset:{id}").as_bytes())],
        decision: QualificationEvidenceDecisionV1::Support,
        conditions: Vec::new(),
        detached_signature_hex: "0".repeat(128),
    };
    envelope.detached_signature_hex =
        hex(&signing.sign(&envelope.signing_bytes().expect("signing bytes")).to_bytes());
    envelope
}

#[tokio::test]
async fn target_api_appends_queries_verifies_and_survives_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let now = now_ms();
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open store");
    let (evaluation_key, evaluation_issuer) = issuer(
        11,
        "principal:evaluator",
        "controller:evaluator",
        vec![QualificationEvidenceRoleV1::Evaluator],
        now,
    );
    let evaluation = receipt(
        &evaluation_key,
        &evaluation_issuer,
        "evidence:evaluation",
        QualificationClaimClassV1::CandidateEvaluation,
        QualificationEvidenceRoleV1::Evaluator,
        None,
        now,
    );
    let (review_key, review_issuer) = issuer(
        12,
        "principal:reviewer",
        "controller:reviewer",
        vec![QualificationEvidenceRoleV1::Reviewer],
        now,
    );
    let review = receipt(
        &review_key,
        &review_issuer,
        "evidence:independent-review",
        QualificationClaimClassV1::IndependentDecision,
        QualificationEvidenceRoleV1::Reviewer,
        None,
        now,
    );

    assert_eq!(
        store
            .qualification()
            .append_receipt(&evaluation, &evaluation_issuer)
            .await
            .expect("append evaluation"),
        evaluation.evidence_id
    );
    assert_eq!(
        store
            .qualification()
            .append_receipt(&evaluation, &evaluation_issuer)
            .await
            .expect("exact replay is idempotent"),
        evaluation.evidence_id
    );
    store
        .qualification()
        .append_receipt(&review, &review_issuer)
        .await
        .expect("append review");

    let decisions = store
        .qualification()
        .query_claim(
            &candidate(),
            QualificationClaimClassV1::IndependentDecision,
        )
        .await
        .expect("query independent decisions");
    assert_eq!(decisions.len(), 1);
    assert_eq!(decisions[0].evidence_id, review.evidence_id);
    assert!(review.independent_decision_receipt().is_some());

    assert!(matches!(
        store
            .qualification()
            .verify_chain(
                &candidate(),
                &[
                    QualificationEvidenceRoleV1::Evaluator,
                    QualificationEvidenceRoleV1::Reviewer,
                ],
                now + 1,
            )
            .await
            .expect("verify chain"),
        EvidenceDisposition::Supported { evidence } if evidence.len() == 2
    ));

    drop(store);
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen qualification store");
    assert_eq!(
        reopened
            .qualification()
            .query_claim(&candidate(), QualificationClaimClassV1::CandidateEvaluation)
            .await
            .expect("query after reopen")
            .len(),
        1
    );
}

#[tokio::test]
async fn evid_01_same_controller_cannot_satisfy_independent_roles() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let now = now_ms();
    let (generator_key, generator) = issuer(
        21,
        "principal:generator",
        "controller:shared",
        vec![QualificationEvidenceRoleV1::Generator],
        now,
    );
    let (evaluator_key, evaluator) = issuer(
        22,
        "principal:evaluator",
        "controller:shared",
        vec![QualificationEvidenceRoleV1::Evaluator],
        now,
    );
    let generated = receipt(
        &generator_key,
        &generator,
        "evidence:generator",
        QualificationClaimClassV1::Conformance,
        QualificationEvidenceRoleV1::Generator,
        None,
        now,
    );
    let evaluated = receipt(
        &evaluator_key,
        &evaluator,
        "evidence:evaluator",
        QualificationClaimClassV1::CandidateEvaluation,
        QualificationEvidenceRoleV1::Evaluator,
        None,
        now,
    );
    store
        .qualification()
        .append_receipt(&generated, &generator)
        .await
        .expect("append generator");
    store
        .qualification()
        .append_receipt(&evaluated, &evaluator)
        .await
        .expect("append evaluator");

    assert!(matches!(
        store
            .qualification()
            .verify_chain(
                &candidate(),
                &[
                    QualificationEvidenceRoleV1::Generator,
                    QualificationEvidenceRoleV1::Evaluator,
                ],
                now + 1,
            )
            .await
            .expect("verify"),
        EvidenceDisposition::Conflicting { .. }
    ));
}

#[tokio::test]
async fn evid_02_different_tree_is_unavailable() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let now = now_ms();
    let (key, evaluator) = issuer(
        31,
        "principal:evaluator",
        "controller:evaluator",
        vec![QualificationEvidenceRoleV1::Evaluator],
        now,
    );
    let evaluation = receipt(
        &key,
        &evaluator,
        "evidence:tree-bound",
        QualificationClaimClassV1::CandidateEvaluation,
        QualificationEvidenceRoleV1::Evaluator,
        None,
        now,
    );
    store
        .qualification()
        .append_receipt(&evaluation, &evaluator)
        .await
        .expect("append");
    let mut other = candidate();
    other.source_tree = "3".repeat(40);

    assert!(matches!(
        store
            .qualification()
            .verify_chain(
                &other,
                &[QualificationEvidenceRoleV1::Evaluator],
                now + 1,
            )
            .await
            .expect("verify other tree"),
        EvidenceDisposition::Missing { .. }
    ));
}

#[tokio::test]
async fn evid_03_corrupted_payload_fails_integrity_on_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open");
    let now = now_ms();
    let (key, evaluator) = issuer(
        41,
        "principal:evaluator",
        "controller:evaluator",
        vec![QualificationEvidenceRoleV1::Evaluator],
        now,
    );
    let evaluation = receipt(
        &key,
        &evaluator,
        "evidence:corrupt-me",
        QualificationClaimClassV1::CandidateEvaluation,
        QualificationEvidenceRoleV1::Evaluator,
        None,
        now,
    );
    store
        .qualification()
        .append_receipt(&evaluation, &evaluator)
        .await
        .expect("append");
    let path = store.path().to_path_buf();
    drop(store);

    let raw = sqlite
        .open_durable_evidence_pool(&path)
        .await
        .expect("raw pool");
    sqlx::query("DROP TRIGGER qualification_evidence_no_update")
        .execute(&raw)
        .await
        .expect("drop trigger for corruption fixture");
    sqlx::query(
        "UPDATE qualification_evidence
         SET payload_json = replace(payload_json, 'candidate:kernel-evidence', 'candidate:tampered')",
    )
    .execute(&raw)
    .await
    .expect("corrupt payload");
    raw.close().await;

    assert!(matches!(
        HeptaEvidenceStore::open(&sqlite).await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[tokio::test]
async fn evid_04_claim_class_substitution_is_rejected_by_query() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let now = now_ms();
    let (key, evaluator) = issuer(
        51,
        "principal:evaluator",
        "controller:evaluator",
        vec![QualificationEvidenceRoleV1::Evaluator],
        now,
    );
    let evaluation = receipt(
        &key,
        &evaluator,
        "evidence:evaluation-only",
        QualificationClaimClassV1::Evaluation,
        QualificationEvidenceRoleV1::Evaluator,
        None,
        now,
    );
    store
        .qualification()
        .append_receipt(&evaluation, &evaluator)
        .await
        .expect("append");

    assert!(
        store
            .qualification()
            .query_claim(
                &candidate(),
                QualificationClaimClassV1::LongitudinalEvaluation,
            )
            .await
            .expect("query")
            .is_empty()
    );
}

#[tokio::test]
async fn changed_payload_under_reused_identity_conflicts() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let now = now_ms();
    let (key, evaluator) = issuer(
        61,
        "principal:evaluator",
        "controller:evaluator",
        vec![QualificationEvidenceRoleV1::Evaluator],
        now,
    );
    let original = receipt(
        &key,
        &evaluator,
        "evidence:stable-id",
        QualificationClaimClassV1::Evaluation,
        QualificationEvidenceRoleV1::Evaluator,
        None,
        now,
    );
    store
        .qualification()
        .append_receipt(&original, &evaluator)
        .await
        .expect("append");

    let mut changed = original.clone();
    changed.payload_digest = Sha256Digest::for_bytes(b"changed");
    changed.detached_signature_hex =
        hex(&key.sign(&changed.signing_bytes().expect("sign changed")).to_bytes());
    assert!(matches!(
        store
            .qualification()
            .append_receipt(&changed, &evaluator)
            .await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
}

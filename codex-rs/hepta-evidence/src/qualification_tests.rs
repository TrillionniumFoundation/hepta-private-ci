use std::collections::BTreeSet;
use std::fs;

use codex_hepta_contracts::IndependentDecisionReceiptV1;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::AppendDisposition;
use crate::AuthenticatedEvidenceIssuerV1;
use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceDispositionV1;
use crate::EvidenceIssuerCertificateV1;
use crate::EvidenceIssuerKeyRevocationV1;
use crate::EvidenceIssuerRevocationsV1;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceTrustRootV1;
use crate::HeptaEvidenceStore;
use crate::QualificationEvidenceEnvelopeV1;
use crate::SignedEvidenceIssuerCertificateV1;
use crate::SignedEvidenceIssuerKeyRevocationV1;
use crate::SignedQualificationEvidenceEnvelopeV1;
use crate::authenticate_evidence_issuer;

const NOW: u64 = 10_000;
const OBSERVED: u64 = 20_000;
const EXPIRES: u64 = 90_000;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn candidate() -> EvidenceCandidateV1 {
    EvidenceCandidateV1 {
        candidate_id: "candidate:kernel-evidence:exact".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    }
}

fn root_signing_key() -> SigningKey {
    SigningKey::from_bytes(&[7; 32])
}

fn authenticated_issuer(
    role: EvidenceIssuerRoleV1,
    principal: &str,
    key_id: &str,
    seed: u8,
) -> (SigningKey, AuthenticatedEvidenceIssuerV1) {
    let root_signing = root_signing_key();
    let root = EvidenceTrustRootV1::new(
        "root:kernel-evidence".to_string(),
        root_signing.verifying_key().to_bytes(),
    )
    .expect("trust root");
    let signing = SigningKey::from_bytes(&[seed; 32]);
    let certificate = EvidenceIssuerCertificateV1 {
        schema_version: 1,
        root_id: root.root_id().to_string(),
        principal_id: principal.to_string(),
        key_id: key_id.to_string(),
        role,
        verifying_key: signing.verifying_key().to_bytes(),
        not_before_unix_ms: 1_000,
        expires_unix_ms: 100_000,
    };
    let certificate_signature = root_signing
        .sign(&certificate.signing_bytes().expect("certificate bytes"))
        .to_bytes()
        .to_vec();
    let issuer = authenticate_evidence_issuer(
        &root,
        &EvidenceIssuerRevocationsV1 {
            root_id: root.root_id().to_string(),
            revision: 1,
            revoked_key_ids: BTreeSet::new(),
        },
        SignedEvidenceIssuerCertificateV1 {
            certificate,
            signature: certificate_signature,
        },
        NOW,
    )
    .expect("authenticated issuer");
    (signing, issuer)
}

fn envelope(
    receipt_id: &str,
    issuer: &AuthenticatedEvidenceIssuerV1,
    claim_class: EvidenceClaimClassV1,
    payload: Sha256Digest,
    expires: u64,
) -> QualificationEvidenceEnvelopeV1 {
    QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        receipt_id: receipt_id.to_string(),
        candidate: candidate(),
        claim_class,
        issuer_role: issuer.role(),
        issuer_principal: issuer.principal_id().to_string(),
        issuer_key_id: issuer.key_id().to_string(),
        payload_sha256: payload,
        predecessor_receipt_id: None,
        observed_unix_ms: OBSERVED,
        expires_unix_ms: expires,
        revokes_receipt_id: None,
        assets: Vec::new(),
    }
}

fn signed_envelope(
    signing: &SigningKey,
    envelope: QualificationEvidenceEnvelopeV1,
) -> SignedQualificationEvidenceEnvelopeV1 {
    let signature = signing
        .sign(&envelope.signing_bytes().expect("envelope bytes"))
        .to_bytes()
        .to_vec();
    SignedQualificationEvidenceEnvelopeV1 {
        envelope,
        signature,
    }
}

#[tokio::test]
async fn target_append_and_query_are_exact_candidate_and_claim_class_bound() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let (signing, issuer) = authenticated_issuer(
        EvidenceIssuerRoleV1::CiExecutor,
        "principal:ci-a",
        "key:ci-a",
        11,
    );
    let signed = signed_envelope(
        &signing,
        envelope(
            "qe:fixture:1",
            &issuer,
            EvidenceClaimClassV1::Fixture,
            Sha256Digest::for_bytes(b"fixture"),
            EXPIRES,
        ),
    );
    let first_id = store
        .append_receipt(&signed, &issuer)
        .await
        .expect("append");
    let replay_id = store
        .append_receipt(&signed, &issuer)
        .await
        .expect("replay");
    assert_eq!(first_id.as_str(), "qe:fixture:1");
    assert_eq!(replay_id, first_id);

    let fixture = store
        .query_claim(&candidate(), EvidenceClaimClassV1::Fixture)
        .await
        .expect("fixture query");
    assert_eq!(fixture.len(), 1);
    assert_eq!(fixture[0].receipt_id, "qe:fixture:1");
    assert!(
        store
            .query_claim(&candidate(), EvidenceClaimClassV1::Hardware)
            .await
            .expect("hardware query")
            .is_empty()
    );

    let mut other_tree = candidate();
    other_tree.source_tree = "c".repeat(40);
    assert!(
        store
            .query_claim(&other_tree, EvidenceClaimClassV1::Fixture)
            .await
            .expect("other tree")
            .is_empty()
    );
}

#[tokio::test]
async fn one_principal_cannot_satisfy_two_independent_roles() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let (eval_signing, evaluator) = authenticated_issuer(
        EvidenceIssuerRoleV1::IndependentEvaluator,
        "principal:shared",
        "key:evaluator",
        12,
    );
    let (arch_signing, architecture) = authenticated_issuer(
        EvidenceIssuerRoleV1::ArchitectureReviewer,
        "principal:shared",
        "key:architecture",
        13,
    );
    for (id, signing, issuer, payload) in [
        ("qe:eval:1", &eval_signing, &evaluator, b"eval".as_slice()),
        (
            "qe:arch:1",
            &arch_signing,
            &architecture,
            b"architecture".as_slice(),
        ),
    ] {
        let signed = signed_envelope(
            signing,
            envelope(
                id,
                issuer,
                EvidenceClaimClassV1::IndependentReview,
                Sha256Digest::for_bytes(payload),
                EXPIRES,
            ),
        );
        store
            .append_receipt(&signed, issuer)
            .await
            .expect("append role receipt");
    }

    let disposition = store
        .verify_chain(
            &candidate(),
            &[
                EvidenceIssuerRoleV1::IndependentEvaluator,
                EvidenceIssuerRoleV1::ArchitectureReviewer,
            ],
            30_000,
        )
        .await
        .expect("verify");
    assert!(matches!(
        disposition,
        EvidenceDispositionV1::Conflicting { reason_code, .. }
            if reason_code == "independent_roles_share_principal"
    ));
}

#[tokio::test]
async fn expired_candidate_evidence_is_not_supported() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let (signing, issuer) = authenticated_issuer(
        EvidenceIssuerRoleV1::IndependentEvaluator,
        "principal:eval-expired",
        "key:eval-expired",
        14,
    );
    let signed = signed_envelope(
        &signing,
        envelope(
            "qe:expired:1",
            &issuer,
            EvidenceClaimClassV1::IndependentReview,
            Sha256Digest::for_bytes(b"expired"),
            25_000,
        ),
    );
    store
        .append_receipt(&signed, &issuer)
        .await
        .expect("append expired receipt");

    let disposition = store
        .verify_chain(
            &candidate(),
            &[EvidenceIssuerRoleV1::IndependentEvaluator],
            30_000,
        )
        .await
        .expect("verify expired");
    assert!(matches!(
        disposition,
        EvidenceDispositionV1::Expired { receipt_ids }
            if receipt_ids == vec!["qe:expired:1".to_string()]
    ));
}

#[tokio::test]
async fn independent_decision_projection_binds_authenticated_signing_identity() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open");
    let (signing, issuer) = authenticated_issuer(
        EvidenceIssuerRoleV1::IndependentEvaluator,
        "principal:independent-a",
        "key:independent-a",
        15,
    );
    let decision = IndependentDecisionReceiptV1 {
        decision_id: "decision:kernel-evidence:1".to_string(),
        candidate_id: candidate().candidate_id,
        role: issuer.role().as_str().to_string(),
        principal_id: issuer.principal_id().to_string(),
        signing_identity_digest: issuer.signing_identity_digest(),
        evidence_set_digest: Sha256Digest::for_bytes(b"source-merge-security-evidence"),
        decision: "accept".to_string(),
        conditions: vec!["exact source and synthetic merge evidence current".to_string()],
        expires_unix_ms: 80_000,
    };
    let payload = decision.semantic_digest().expect("decision digest");
    let signed = signed_envelope(
        &signing,
        envelope(
            "qe:independent-decision:1",
            &issuer,
            EvidenceClaimClassV1::IndependentReview,
            payload,
            85_000,
        ),
    );
    assert_eq!(
        store
            .append_independent_decision_receipt(&signed, &issuer, &decision)
            .await
            .expect("append independent decision"),
        AppendDisposition::Inserted
    );
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite).await.expect("reopen");
    let refs = reopened
        .query_claim(&candidate(), EvidenceClaimClassV1::IndependentReview)
        .await
        .expect("query independent review");
    assert_eq!(refs.len(), 1);
    assert_eq!(refs[0].issuer_principal, "principal:independent-a");
}

#[tokio::test]
async fn durable_key_revocation_invalidates_previous_independent_evidence() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let (eval_signing, evaluator) = authenticated_issuer(
        EvidenceIssuerRoleV1::IndependentEvaluator,
        "principal:eval-revoked",
        "key:eval-revoked",
        16,
    );
    let eval_receipt = signed_envelope(
        &eval_signing,
        envelope(
            "qe:eval-revoked:1",
            &evaluator,
            EvidenceClaimClassV1::IndependentReview,
            Sha256Digest::for_bytes(b"review"),
            EXPIRES,
        ),
    );
    store
        .append_receipt(&eval_receipt, &evaluator)
        .await
        .expect("append evaluator");

    let (security_signing, security) = authenticated_issuer(
        EvidenceIssuerRoleV1::SecurityReviewer,
        "principal:security-a",
        "key:security-a",
        17,
    );
    let revocation = EvidenceIssuerKeyRevocationV1 {
        schema_version: 1,
        revocation_id: "revocation:eval-key:1".to_string(),
        root_id: security.root_id().to_string(),
        key_id: evaluator.key_id().to_string(),
        observed_unix_ms: 25_000,
        reason_code: "key_compromised".to_string(),
    };
    let signed_revocation = SignedEvidenceIssuerKeyRevocationV1 {
        signature: security_signing
            .sign(&revocation.signing_bytes().expect("revocation bytes"))
            .to_bytes()
            .to_vec(),
        revocation,
    };
    store
        .append_issuer_key_revocation(&signed_revocation, &security)
        .await
        .expect("append revocation");

    let disposition = store
        .verify_chain(
            &candidate(),
            &[EvidenceIssuerRoleV1::IndependentEvaluator],
            30_000,
        )
        .await
        .expect("verify revoked");
    assert!(matches!(disposition, EvidenceDispositionV1::Missing { .. }));
}

#[tokio::test]
async fn corrupted_qualification_payload_fails_closed_after_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open");
    let (signing, issuer) = authenticated_issuer(
        EvidenceIssuerRoleV1::CiExecutor,
        "principal:ci-corrupt",
        "key:ci-corrupt",
        18,
    );
    let signed = signed_envelope(
        &signing,
        envelope(
            "qe:corrupt:1",
            &issuer,
            EvidenceClaimClassV1::SourceExecution,
            Sha256Digest::for_bytes(b"source-result"),
            EXPIRES,
        ),
    );
    store
        .append_receipt(&signed, &issuer)
        .await
        .expect("append receipt");

    sqlx::query("DROP TRIGGER qualification_evidence_no_update")
        .execute(&store.pool)
        .await
        .expect("drop immutable trigger for corruption fixture");
    sqlx::query(
        "UPDATE qualification_evidence
         SET payload_sha256 = ?
         WHERE receipt_id = ?",
    )
    .bind(Sha256Digest::for_bytes(b"corrupted").as_str())
    .bind("qe:corrupt:1")
    .execute(&store.pool)
    .await
    .expect("corrupt payload");
    sqlx::query(
        "CREATE TRIGGER IF NOT EXISTS qualification_evidence_no_update
         BEFORE UPDATE ON qualification_evidence
         BEGIN
             SELECT RAISE(ABORT, 'qualification evidence is immutable');
         END",
    )
    .execute(&store.pool)
    .await
    .expect("restore immutable trigger");
    store.pool.close().await;

    let error = HeptaEvidenceStore::open(&sqlite)
        .await
        .err()
        .expect("corruption must fail closed");
    assert!(matches!(error, crate::EvidenceError::Corrupt(_)));
}

#[tokio::test]
async fn external_checkpoint_rejects_complete_database_rollback() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open");
    let (signing, issuer) = authenticated_issuer(
        EvidenceIssuerRoleV1::CiExecutor,
        "principal:ci-checkpoint",
        "key:ci-checkpoint",
        19,
    );
    let first = signed_envelope(
        &signing,
        envelope(
            "qe:checkpoint:1",
            &issuer,
            EvidenceClaimClassV1::SourceExecution,
            Sha256Digest::for_bytes(b"first"),
            EXPIRES,
        ),
    );
    store
        .append_receipt(&first, &issuer)
        .await
        .expect("append first");
    store.pool.close().await;

    let db_path = temp.path().join("hepta_evidence_2.sqlite");
    let rollback_copy = temp.path().join("rollback.sqlite");
    fs::copy(&db_path, &rollback_copy).expect("copy rollback database");

    let store = HeptaEvidenceStore::open(&sqlite).await.expect("reopen");
    let second = signed_envelope(
        &signing,
        envelope(
            "qe:checkpoint:2",
            &issuer,
            EvidenceClaimClassV1::MergeExecution,
            Sha256Digest::for_bytes(b"second"),
            EXPIRES,
        ),
    );
    store
        .append_receipt(&second, &issuer)
        .await
        .expect("append second");
    let checkpoint = store
        .capture_external_checkpoint()
        .await
        .expect("capture checkpoint");
    store
        .verify_external_checkpoint(&checkpoint)
        .await
        .expect("current store verifies");
    store.pool.close().await;

    fs::copy(&rollback_copy, &db_path).expect("restore old database");
    for suffix in ["-wal", "-shm"] {
        let path = temp.path().join(format!("hepta_evidence_2.sqlite{suffix}"));
        let _ = fs::remove_file(path);
    }
    let error = HeptaEvidenceStore::open_with_external_checkpoint(&sqlite, &checkpoint)
        .await
        .err()
        .expect("rolled back database must fail the checkpoint");
    assert!(matches!(error, crate::EvidenceError::Corrupt(_)));
}

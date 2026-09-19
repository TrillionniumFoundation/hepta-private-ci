use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::AppendDisposition;
use crate::EvidenceCandidate;
use crate::EvidenceClaimClass;
use crate::EvidenceDispositionKind;
use crate::EvidenceError;
use crate::EvidenceIssuerProof;
use crate::EvidenceIssuerRegistration;
use crate::EvidenceReferenceState;
use crate::EvidenceTrustPolicy;
use crate::HeptaEvidenceStore;
use crate::IndependentDecision;
use crate::IndependentDecisionInput;
use crate::QualificationEvidenceEnvelope;
use crate::QUALIFICATION_EVIDENCE_SCHEMA_VERSION;

const NOW: u64 = 1_000_000;
const EXPIRES: u64 = 2_000_000;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn candidate() -> EvidenceCandidate {
    EvidenceCandidate {
        candidate_id: "candidate-a".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    }
}

fn signing_key(seed: u8) -> SigningKey {
    SigningKey::from_bytes(&[seed; 32])
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn registration(
    key: &SigningKey,
    principal: &str,
    roles: &[&str],
) -> EvidenceIssuerRegistration {
    EvidenceIssuerRegistration {
        principal_id: principal.to_string(),
        verifying_key_hex: hex(&key.verifying_key().to_bytes()),
        roles: roles.iter().map(|role| (*role).to_string()).collect(),
        not_before_ms: NOW - 100,
        expires_at_ms: EXPIRES,
    }
}

fn policy(registrations: Vec<EvidenceIssuerRegistration>) -> EvidenceTrustPolicy {
    EvidenceTrustPolicy {
        schema_version: 1,
        policy_id: "qualification-policy-v1".to_string(),
        revision: 1,
        registrations,
        revoked_signing_identity_sha256: Vec::new(),
    }
}

fn envelope(
    receipt_id: &str,
    role: &str,
    claim_class: EvidenceClaimClass,
    payload: &[u8],
) -> QualificationEvidenceEnvelope {
    QualificationEvidenceEnvelope {
        schema_version: QUALIFICATION_EVIDENCE_SCHEMA_VERSION,
        receipt_id: receipt_id.to_string(),
        candidate: candidate(),
        claim_class,
        issuer_role: role.to_string(),
        payload_sha256: Sha256Digest::for_bytes(payload),
        predecessor_receipt_id: None,
        revokes_receipt_id: None,
        revokes_issuer_key_sha256: None,
        observed_at_ms: NOW,
        expires_at_ms: Some(NOW + 10_000),
        asset_refs: Vec::new(),
    }
}

fn proof(key: &SigningKey, principal: &str, envelope: &QualificationEvidenceEnvelope) -> EvidenceIssuerProof {
    let signature = key.sign(&envelope.signing_bytes().expect("signing bytes"));
    EvidenceIssuerProof {
        principal_id: principal.to_string(),
        verifying_key_hex: hex(&key.verifying_key().to_bytes()),
        signature_hex: hex(&signature.to_bytes()),
        signed_at_ms: NOW,
    }
}

#[tokio::test]
async fn qualification_receipt_is_authenticated_idempotent_queryable_and_reopen_safe() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open evidence");
    let key = signing_key(1);
    let trust = policy(vec![registration(&key, "reviewer-a", &["evaluator"])]);
    let receipt = envelope(
        "receipt-a",
        "evaluator",
        EvidenceClaimClass::ExactSource,
        b"exact-source-pass",
    );
    let issuer = store
        .qualification()
        .authenticate_issuer(&trust, &receipt, &proof(&key, "reviewer-a", &receipt))
        .expect("authenticated issuer");

    assert_eq!(
        store
            .qualification()
            .append_receipt(&receipt, &issuer)
            .await
            .expect("append"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .qualification()
            .append_receipt(&receipt, &issuer)
            .await
            .expect("idempotent replay"),
        AppendDisposition::AlreadyPresent
    );

    let refs = store
        .qualification()
        .query_claim_at(&candidate(), EvidenceClaimClass::ExactSource, NOW)
        .await
        .expect("query");
    assert_eq!(refs.len(), 1);
    assert_eq!(refs[0].state, EvidenceReferenceState::Active);

    drop(store);
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen verifies hash chain and signature");
    let refs = reopened
        .qualification()
        .query_claim_at(&candidate(), EvidenceClaimClass::ExactSource, NOW)
        .await
        .expect("query reopened");
    assert_eq!(refs.len(), 1);
}

#[tokio::test]
async fn same_receipt_identity_with_changed_content_conflicts() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let key = signing_key(2);
    let trust = policy(vec![registration(&key, "reviewer-a", &["evaluator"])]);
    let first = envelope(
        "receipt-conflict",
        "evaluator",
        EvidenceClaimClass::ExactSource,
        b"one",
    );
    let first_issuer = trust
        .authenticate(&first, &proof(&key, "reviewer-a", &first))
        .expect("first issuer");
    store
        .qualification()
        .append_receipt(&first, &first_issuer)
        .await
        .expect("first append");

    let changed = envelope(
        "receipt-conflict",
        "evaluator",
        EvidenceClaimClass::ExactSource,
        b"two",
    );
    let changed_issuer = trust
        .authenticate(&changed, &proof(&key, "reviewer-a", &changed))
        .expect("changed issuer");
    assert!(matches!(
        store
            .qualification()
            .append_receipt(&changed, &changed_issuer)
            .await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
}

#[tokio::test]
async fn exact_candidate_tree_and_expiry_are_enforced() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let key = signing_key(3);
    let trust = policy(vec![registration(&key, "reviewer-a", &["evaluator"])]);
    let receipt = envelope(
        "receipt-expiry",
        "evaluator",
        EvidenceClaimClass::ExactSource,
        b"exact",
    );
    let issuer = trust
        .authenticate(&receipt, &proof(&key, "reviewer-a", &receipt))
        .expect("issuer");
    store
        .qualification()
        .append_receipt(&receipt, &issuer)
        .await
        .expect("append");

    let expired = store
        .qualification()
        .query_claim_at(
            &candidate(),
            EvidenceClaimClass::ExactSource,
            NOW + 10_000,
        )
        .await
        .expect("expired query");
    assert_eq!(expired[0].state, EvidenceReferenceState::Expired);

    let mut other_tree = candidate();
    other_tree.source_tree = "c".repeat(40);
    assert!(
        store
            .qualification()
            .query_claim_at(&other_tree, EvidenceClaimClass::ExactSource, NOW)
            .await
            .expect("other tree query")
            .is_empty()
    );
}

#[tokio::test]
async fn security_authority_revocation_is_immediate_and_persistent() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let evaluator = signing_key(4);
    let security = signing_key(5);
    let trust = policy(vec![
        registration(&evaluator, "reviewer-a", &["evaluator"]),
        registration(&security, "security-a", &["security-authority"]),
    ]);
    let target = envelope(
        "receipt-target",
        "evaluator",
        EvidenceClaimClass::ExactSource,
        b"target",
    );
    let target_issuer = trust
        .authenticate(&target, &proof(&evaluator, "reviewer-a", &target))
        .expect("target issuer");
    store
        .qualification()
        .append_receipt(&target, &target_issuer)
        .await
        .expect("target append");

    let mut revoke = envelope(
        "receipt-revoke",
        "security-authority",
        EvidenceClaimClass::Revocation,
        b"revoke-target",
    );
    revoke.expires_at_ms = None;
    revoke.revokes_receipt_id = Some(target.receipt_id.clone());
    let revoke_issuer = trust
        .authenticate(&revoke, &proof(&security, "security-a", &revoke))
        .expect("security issuer");
    store
        .qualification()
        .append_receipt(&revoke, &revoke_issuer)
        .await
        .expect("revoke");

    let refs = store
        .qualification()
        .query_claim_at(&candidate(), EvidenceClaimClass::ExactSource, NOW)
        .await
        .expect("query");
    assert_eq!(refs[0].state, EvidenceReferenceState::Revoked);
}

#[tokio::test]
async fn one_principal_cannot_satisfy_two_independent_roles() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let key = signing_key(6);
    let trust = policy(vec![registration(
        &key,
        "same-human",
        &["generator-review", "evaluator-review"],
    )]);

    for (id, role) in [
        ("receipt-generator", "generator-review"),
        ("receipt-evaluator", "evaluator-review"),
    ] {
        let row = envelope(id, role, EvidenceClaimClass::ExactSource, role.as_bytes());
        let issuer = trust
            .authenticate(&row, &proof(&key, "same-human", &row))
            .expect("issuer");
        store
            .qualification()
            .append_receipt(&row, &issuer)
            .await
            .expect("append");
    }

    let disposition = store
        .qualification()
        .verify_chain(
            &candidate(),
            &[
                "generator-review".to_string(),
                "evaluator-review".to_string(),
            ],
            NOW,
        )
        .await
        .expect("verify");
    assert_eq!(disposition.kind, EvidenceDispositionKind::Conflicting);
}

#[tokio::test]
async fn independent_decision_is_typed_signed_and_projected_atomically() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open evidence");
    let key = signing_key(7);
    let trust = policy(vec![registration(
        &key,
        "independent-reviewer",
        &["independent-review"],
    )]);
    let prepared = store
        .qualification()
        .prepare_independent_decision(
            IndependentDecisionInput {
                decision_id: "decision-a".to_string(),
                candidate: candidate(),
                role: "independent-review".to_string(),
                principal_id: "independent-reviewer".to_string(),
                evidence_set_digest: Sha256Digest::for_bytes(b"evidence-set"),
                decision: IndependentDecision::Accept,
                conditions: vec!["exact_candidate_only".to_string()],
                observed_at_ms: NOW,
                expires_at_ms: NOW + 20_000,
                predecessor_receipt_id: None,
            },
            &trust,
        )
        .expect("prepare");
    let signed = key.sign(&prepared.signing_bytes().expect("signing bytes"));
    let issuer_proof = EvidenceIssuerProof {
        principal_id: "independent-reviewer".to_string(),
        verifying_key_hex: hex(&key.verifying_key().to_bytes()),
        signature_hex: hex(&signed.to_bytes()),
        signed_at_ms: NOW,
    };
    assert_eq!(
        store
            .qualification()
            .append_prepared_independent_decision(&prepared, &trust, &issuer_proof)
            .await
            .expect("append typed decision"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .qualification()
            .get_independent_decision("decision-a")
            .await
            .expect("projection")
            .expect("decision"),
        prepared.receipt
    );

    drop(store);
    HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("typed projection survives and verifies after reopen");
}

#[tokio::test]
async fn external_checkpoint_detects_database_replacement_and_backward_frontier() {
    let first_temp = TempDir::new().expect("first temp");
    let first_store = HeptaEvidenceStore::open(&sqlite_config(&first_temp))
        .await
        .expect("first store");
    let checkpoint = first_store
        .qualification()
        .export_checkpoint()
        .await
        .expect("checkpoint");

    let second_temp = TempDir::new().expect("second temp");
    let second_store = HeptaEvidenceStore::open(&sqlite_config(&second_temp))
        .await
        .expect("second store");
    assert!(matches!(
        second_store
            .qualification()
            .verify_external_checkpoint(&checkpoint)
            .await,
        Err(EvidenceError::Corrupt(_))
    ));

    let mut future = checkpoint.clone();
    future.receipt_count = 1;
    future.max_seq = 1;
    future.chain_head_sha256 = Sha256Digest::for_bytes(b"future-frontier");
    assert!(matches!(
        first_store
            .qualification()
            .verify_external_checkpoint(&future)
            .await,
        Err(EvidenceError::Corrupt(_))
    ));
}

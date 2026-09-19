use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use tempfile::TempDir;

use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceDispositionV1;
use crate::EvidenceError;
use crate::EvidenceId;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceReceiptKindV1;
use crate::HeptaEvidenceStore;
use crate::IndependentDecisionReceiptV1;
use crate::IndependentDecisionRoleV1;
use crate::IndependentDecisionV1;
use crate::QualificationEvidenceEnvelopeV1;
use crate::VerifyChainRequestV1;
use crate::evidence_set_digest;
use crate::qualification_append_scope_digest;
use crate::qualification_subject;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("u64 millis")
}

fn candidate(tree: char) -> EvidenceCandidateV1 {
    EvidenceCandidateV1 {
        candidate_id: "candidate:kernel-evidence".to_string(),
        source_commit: "a".repeat(40),
        source_tree: tree.to_string().repeat(40),
    }
}

fn issuer(principal: &str, seed: u8) -> (IssuerRegistration, SigningKey) {
    let key = SigningKey::from_bytes(&[seed; 32]);
    (
        IssuerRegistration {
            issuer_id: StableId::new(principal).expect("principal"),
            key_epoch: Generation::new(1).expect("epoch"),
            verifying_key: key.verifying_key(),
            revoked: false,
        },
        key,
    )
}

fn evidence(
    id: &str,
    candidate: EvidenceCandidateV1,
    class: EvidenceClaimClassV1,
    role: EvidenceIssuerRoleV1,
    observed: u64,
    expires: Option<u64>,
    payload: serde_json::Value,
) -> QualificationEvidenceEnvelopeV1 {
    QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        evidence_id: EvidenceId::parse(id).expect("evidence id"),
        candidate,
        claim_class: class,
        receipt_kind: EvidenceReceiptKindV1::Evidence,
        issuer_role: role,
        payload,
        predecessor_evidence_id: None,
        target_evidence_id: None,
        observed_unix_ms: observed,
        expires_unix_ms: expires,
        asset_digests: Vec::new(),
    }
}

fn lineage(
    id: &str,
    predecessor: &str,
    target: &str,
    base: &QualificationEvidenceEnvelopeV1,
    kind: EvidenceReceiptKindV1,
    observed: u64,
) -> QualificationEvidenceEnvelopeV1 {
    QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        evidence_id: EvidenceId::parse(id).expect("evidence id"),
        candidate: base.candidate.clone(),
        claim_class: base.claim_class,
        receipt_kind: kind,
        issuer_role: base.issuer_role,
        payload: json!({"lineage": id}),
        predecessor_evidence_id: Some(EvidenceId::parse(predecessor).expect("predecessor")),
        target_evidence_id: Some(EvidenceId::parse(target).expect("target")),
        observed_unix_ms: observed,
        expires_unix_ms: None,
        asset_digests: Vec::new(),
    }
}

fn signed(
    envelope: &QualificationEvidenceEnvelopeV1,
    issuer: &IssuerRegistration,
    key: &SigningKey,
    sequence: u64,
    expires_at_ms: u64,
) -> SignedMessage {
    let bytes = crate::canonical::canonical_json(envelope).expect("canonical envelope");
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!(
            "evidence-message:{}:{sequence}",
            envelope.evidence_id
        ))
        .expect("message id"),
        subject_id: qualification_subject(&envelope.candidate, envelope.issuer_role)
            .expect("qualification subject"),
        scope_digest: qualification_append_scope_digest(),
        payload_digest: Digest32::of_bytes(&bytes),
        sequence,
        expires_at_ms,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    SignedMessage { claims, signature }
}

async fn append(
    store: &HeptaEvidenceStore,
    issuer: &IssuerRegistration,
    key: &SigningKey,
    envelope: &QualificationEvidenceEnvelopeV1,
    sequence: u64,
) -> Result<EvidenceId, EvidenceError> {
    let message = signed(
        envelope,
        issuer,
        key,
        sequence,
        now_ms().saturating_add(60_000),
    );
    store
        .qualification()
        .append_receipt(issuer, &message, envelope)
        .await
}

#[tokio::test]
async fn evid_01_one_principal_cannot_satisfy_generator_and_evaluator_independence() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let candidate = candidate('b');
    let observed = now_ms();
    let (same_principal, key) = issuer("principal:shared", 11);

    let generator = evidence(
        "evidence:generator",
        candidate.clone(),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Generator,
        observed,
        None,
        json!({"passed": true}),
    );
    append(&store, &same_principal, &key, &generator, 1)
        .await
        .expect("append generator");

    let evaluator = evidence(
        "evidence:evaluator",
        candidate.clone(),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Evaluator,
        observed,
        None,
        json!({"passed": true}),
    );
    append(&store, &same_principal, &key, &evaluator, 1)
        .await
        .expect("append evaluator");

    let disposition = store
        .qualification()
        .verify_chain(&VerifyChainRequestV1 {
            candidate,
            claim_class: EvidenceClaimClassV1::MandatoryTests,
            required_roles: vec![
                EvidenceIssuerRoleV1::Generator,
                EvidenceIssuerRoleV1::Evaluator,
            ],
            now_unix_ms: observed,
        })
        .await
        .expect("verify");
    assert!(matches!(
        disposition,
        EvidenceDispositionV1::Conflicting { .. }
    ));
}

#[tokio::test]
async fn evid_01_distinct_authenticated_principals_satisfy_independence() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let candidate = candidate('b');
    let observed = now_ms();
    let (generator_issuer, generator_key) = issuer("principal:generator", 12);
    let (evaluator_issuer, evaluator_key) = issuer("principal:evaluator", 13);
    let generator = evidence(
        "evidence:generator-distinct",
        candidate.clone(),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Generator,
        observed,
        None,
        json!({"passed": true}),
    );
    append(&store, &generator_issuer, &generator_key, &generator, 1)
        .await
        .expect("append generator");
    let evaluator = evidence(
        "evidence:evaluator-distinct",
        candidate.clone(),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Evaluator,
        observed,
        None,
        json!({"passed": true}),
    );
    append(&store, &evaluator_issuer, &evaluator_key, &evaluator, 1)
        .await
        .expect("append evaluator");

    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate,
                claim_class: EvidenceClaimClassV1::MandatoryTests,
                required_roles: vec![
                    EvidenceIssuerRoleV1::Generator,
                    EvidenceIssuerRoleV1::Evaluator,
                ],
                now_unix_ms: observed,
            })
            .await
            .expect("verify"),
        EvidenceDispositionV1::Supported { .. }
    ));
}

#[tokio::test]
async fn evid_02_wrong_tree_and_expired_candidate_are_unavailable() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let exact = candidate('b');
    let observed = now_ms();
    let expiry = observed.saturating_add(5_000);
    let (source_issuer, key) = issuer("principal:source", 14);
    let receipt = evidence(
        "evidence:exact-source",
        exact.clone(),
        EvidenceClaimClassV1::ExactSource,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        Some(expiry),
        json!({"source": "exact"}),
    );
    append(&store, &source_issuer, &key, &receipt, 1)
        .await
        .expect("append source evidence");

    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate: candidate('c'),
                claim_class: EvidenceClaimClassV1::ExactSource,
                required_roles: vec![EvidenceIssuerRoleV1::Architecture],
                now_unix_ms: observed,
            })
            .await
            .expect("wrong tree verify"),
        EvidenceDispositionV1::Missing
    ));
    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate: exact,
                claim_class: EvidenceClaimClassV1::ExactSource,
                required_roles: vec![EvidenceIssuerRoleV1::Architecture],
                now_unix_ms: expiry.saturating_add(1),
            })
            .await
            .expect("expired verify"),
        EvidenceDispositionV1::Expired { .. }
    ));
}

#[tokio::test]
async fn evid_03_corrupted_canonical_payload_fails_reopen() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open evidence");
    let observed = now_ms();
    let (source_issuer, key) = issuer("principal:integrity", 15);
    let receipt = evidence(
        "evidence:integrity",
        candidate('b'),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Durability,
        observed,
        None,
        json!({"passed": true}),
    );
    append(&store, &source_issuer, &key, &receipt, 1)
        .await
        .expect("append integrity evidence");

    let mut connection = store.pool.acquire().await.expect("connection");
    sqlx::query("DROP TRIGGER qualification_evidence_no_update")
        .execute(&mut *connection)
        .await
        .expect("drop trigger");
    sqlx::query(
        "UPDATE qualification_evidence
         SET envelope_json = replace(envelope_json, '\"passed\":true', '\"passed\":false')
         WHERE evidence_id = 'evidence:integrity'",
    )
    .execute(&mut *connection)
    .await
    .expect("corrupt envelope");
    sqlx::query(
        "CREATE TRIGGER qualification_evidence_no_update
         BEFORE UPDATE ON qualification_evidence
         BEGIN
             SELECT RAISE(ABORT, 'qualification evidence is immutable');
         END",
    )
    .execute(&mut *connection)
    .await
    .expect("restore trigger");
    drop(connection);
    store.pool.close().await;

    assert!(matches!(
        HeptaEvidenceStore::open(&sqlite).await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[tokio::test]
async fn evid_03_broken_predecessor_fails_reopen() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open evidence");
    let observed = now_ms();
    let (issuer, key) = issuer("principal:lineage", 16);
    let base = evidence(
        "evidence:lineage-base",
        candidate('b'),
        EvidenceClaimClassV1::Conformance,
        EvidenceIssuerRoleV1::Reviewer,
        observed,
        None,
        json!({"version": 1}),
    );
    append(&store, &issuer, &key, &base, 1)
        .await
        .expect("append base");
    let correction = lineage(
        "evidence:lineage-correction",
        base.evidence_id.as_str(),
        base.evidence_id.as_str(),
        &base,
        EvidenceReceiptKindV1::Correction,
        observed.saturating_add(1),
    );
    append(&store, &issuer, &key, &correction, 2)
        .await
        .expect("append correction");

    let mut connection = store.pool.acquire().await.expect("connection");
    sqlx::query("PRAGMA foreign_keys = OFF")
        .execute(&mut *connection)
        .await
        .expect("disable fk");
    sqlx::query("DROP TRIGGER qualification_evidence_no_update")
        .execute(&mut *connection)
        .await
        .expect("drop trigger");
    sqlx::query(
        "UPDATE qualification_evidence
         SET predecessor_evidence_id = 'evidence:missing'
         WHERE evidence_id = 'evidence:lineage-correction'",
    )
    .execute(&mut *connection)
    .await
    .expect("break predecessor");
    sqlx::query(
        "CREATE TRIGGER qualification_evidence_no_update
         BEFORE UPDATE ON qualification_evidence
         BEGIN
             SELECT RAISE(ABORT, 'qualification evidence is immutable');
         END",
    )
    .execute(&mut *connection)
    .await
    .expect("restore trigger");
    drop(connection);
    store.pool.close().await;

    assert!(matches!(
        HeptaEvidenceStore::open(&sqlite).await,
        Err(EvidenceError::Corrupt(_))
    ));
}

#[tokio::test]
async fn evid_04_fixture_cannot_satisfy_hardware_claim() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let candidate = candidate('b');
    let observed = now_ms();
    let (issuer, key) = issuer("principal:fixture", 17);
    let fixture = evidence(
        "evidence:fixture",
        candidate.clone(),
        EvidenceClaimClassV1::Fixture,
        EvidenceIssuerRoleV1::Evaluator,
        observed,
        None,
        json!({"environment": "fixture"}),
    );
    append(&store, &issuer, &key, &fixture, 1)
        .await
        .expect("append fixture");

    assert!(
        store
            .qualification()
            .query_claim(&candidate, EvidenceClaimClassV1::Hardware)
            .await
            .expect("hardware query")
            .is_empty()
    );
    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate,
                claim_class: EvidenceClaimClassV1::Hardware,
                required_roles: vec![EvidenceIssuerRoleV1::Evaluator],
                now_unix_ms: observed,
            })
            .await
            .expect("hardware verify"),
        EvidenceDispositionV1::Missing
    ));
}

#[tokio::test]
async fn independent_decision_binds_candidate_principal_key_role_and_evidence_set() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let candidate = candidate('b');
    let observed = now_ms();
    let expiry = observed.saturating_add(30_000);
    let (reviewer, key) = issuer("principal:architecture", 18);

    let source = evidence(
        "evidence:decision-source",
        candidate.clone(),
        EvidenceClaimClassV1::ExactSource,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"exact_head": true}),
    );
    append(&store, &reviewer, &key, &source, 1)
        .await
        .expect("source");
    let refs = store
        .qualification()
        .query_claim(&candidate, EvidenceClaimClassV1::ExactSource)
        .await
        .expect("query source");
    let set_digest = evidence_set_digest(&refs).expect("evidence set digest");
    let signing_digest =
        codex_hepta_contracts::Sha256Digest::for_bytes(reviewer.verifying_key.as_bytes());
    let decision_id = "decision:architecture";
    let decision = IndependentDecisionReceiptV1 {
        decision_id: decision_id.to_string(),
        candidate_id: candidate.candidate_id.clone(),
        role: IndependentDecisionRoleV1::Architecture,
        principal_id: reviewer.issuer_id.to_string(),
        signing_identity_digest: signing_digest,
        evidence_set_digest: set_digest,
        decision: IndependentDecisionV1::Accept,
        conditions: Vec::new(),
        expires_unix_ms: expiry,
    };
    let envelope = evidence(
        decision_id,
        candidate.clone(),
        EvidenceClaimClassV1::IndependentDecision,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        Some(expiry),
        serde_json::to_value(decision).expect("decision value"),
    );
    append(&store, &reviewer, &key, &envelope, 2)
        .await
        .expect("append independent decision");

    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate,
                claim_class: EvidenceClaimClassV1::IndependentDecision,
                required_roles: vec![EvidenceIssuerRoleV1::Architecture],
                now_unix_ms: observed,
            })
            .await
            .expect("verify decision"),
        EvidenceDispositionV1::Supported { .. }
    ));
}

#[tokio::test]
async fn independent_decision_becomes_conflicting_when_candidate_evidence_set_changes() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let candidate = candidate('b');
    let observed = now_ms();
    let expiry = observed.saturating_add(30_000);
    let (reviewer, key) = issuer("principal:stale-review", 22);

    let source = evidence(
        "evidence:stale-source",
        candidate.clone(),
        EvidenceClaimClassV1::ExactSource,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"exact_head": true}),
    );
    append(&store, &reviewer, &key, &source, 1)
        .await
        .expect("source");
    let refs = store
        .qualification()
        .query_claim(&candidate, EvidenceClaimClassV1::ExactSource)
        .await
        .expect("query source");
    let decision = IndependentDecisionReceiptV1 {
        decision_id: "decision:stale-review".to_string(),
        candidate_id: candidate.candidate_id.clone(),
        role: IndependentDecisionRoleV1::Architecture,
        principal_id: reviewer.issuer_id.to_string(),
        signing_identity_digest: codex_hepta_contracts::Sha256Digest::for_bytes(
            reviewer.verifying_key.as_bytes(),
        ),
        evidence_set_digest: evidence_set_digest(&refs).expect("set digest"),
        decision: IndependentDecisionV1::Accept,
        conditions: Vec::new(),
        expires_unix_ms: expiry,
    };
    let decision_envelope = evidence(
        "decision:stale-review",
        candidate.clone(),
        EvidenceClaimClassV1::IndependentDecision,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        Some(expiry),
        serde_json::to_value(decision).expect("decision value"),
    );
    append(&store, &reviewer, &key, &decision_envelope, 2)
        .await
        .expect("decision");

    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate: candidate.clone(),
                claim_class: EvidenceClaimClassV1::IndependentDecision,
                required_roles: vec![EvidenceIssuerRoleV1::Architecture],
                now_unix_ms: observed,
            })
            .await
            .expect("initial decision"),
        EvidenceDispositionV1::Supported { .. }
    ));

    let registry = evidence(
        "evidence:stale-registry-change",
        candidate.clone(),
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Architecture,
        observed,
        None,
        json!({"registry": "changed"}),
    );
    append(&store, &reviewer, &key, &registry, 3)
        .await
        .expect("registry evidence");

    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate,
                claim_class: EvidenceClaimClassV1::IndependentDecision,
                required_roles: vec![EvidenceIssuerRoleV1::Architecture],
                now_unix_ms: observed,
            })
            .await
            .expect("stale decision"),
        EvidenceDispositionV1::Conflicting { .. }
    ));
}

#[tokio::test]
async fn exact_authenticated_retry_is_idempotent_but_payload_drift_conflicts() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let observed = now_ms();
    let (issuer, key) = issuer("principal:idempotent", 19);
    let receipt = evidence(
        "evidence:idempotent",
        candidate('b'),
        EvidenceClaimClassV1::RegistrySnapshot,
        EvidenceIssuerRoleV1::Reviewer,
        observed,
        None,
        json!({"revision": 1}),
    );
    let message = signed(
        &receipt,
        &issuer,
        &key,
        1,
        observed.saturating_add(60_000),
    );
    let first = store
        .qualification()
        .append_receipt(&issuer, &message, &receipt)
        .await
        .expect("first append");
    let retry = store
        .qualification()
        .append_receipt(&issuer, &message, &receipt)
        .await
        .expect("exact retry");
    assert_eq!(first, retry);

    let mut changed = receipt.clone();
    changed.payload = json!({"revision": 2});
    let changed_message = signed(
        &changed,
        &issuer,
        &key,
        2,
        observed.saturating_add(60_000),
    );
    assert!(matches!(
        store
            .qualification()
            .append_receipt(&issuer, &changed_message, &changed)
            .await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
}

#[tokio::test]
async fn correction_and_revocation_are_append_only_and_non_resurrecting() {
    let temp = TempDir::new().expect("temp");
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open");
    let observed = now_ms();
    let (issuer, key) = issuer("principal:reviewer", 20);
    let base = evidence(
        "evidence:revocable",
        candidate('b'),
        EvidenceClaimClassV1::Conformance,
        EvidenceIssuerRoleV1::Reviewer,
        observed,
        None,
        json!({"version": 1}),
    );
    append(&store, &issuer, &key, &base, 1)
        .await
        .expect("base");
    let correction = lineage(
        "evidence:corrected",
        base.evidence_id.as_str(),
        base.evidence_id.as_str(),
        &base,
        EvidenceReceiptKindV1::Correction,
        observed.saturating_add(1),
    );
    append(&store, &issuer, &key, &correction, 2)
        .await
        .expect("correction");
    let revocation = lineage(
        "evidence:revoked",
        correction.evidence_id.as_str(),
        correction.evidence_id.as_str(),
        &correction,
        EvidenceReceiptKindV1::Revocation,
        observed.saturating_add(2),
    );
    append(&store, &issuer, &key, &revocation, 3)
        .await
        .expect("revocation");

    assert!(matches!(
        store
            .qualification()
            .verify_chain(&VerifyChainRequestV1 {
                candidate: base.candidate.clone(),
                claim_class: EvidenceClaimClassV1::Conformance,
                required_roles: vec![EvidenceIssuerRoleV1::Reviewer],
                now_unix_ms: observed.saturating_add(3),
            })
            .await
            .expect("verify revoked"),
        EvidenceDispositionV1::Missing
    ));
    store.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&sqlite).await.expect("reopen");
    assert_eq!(
        reopened
            .qualification()
            .query_claim(&base.candidate, EvidenceClaimClassV1::Conformance)
            .await
            .expect("query history")
            .len(),
        3
    );
}

#[tokio::test]
async fn replay_sequence_is_consumed_atomically_with_insert() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open evidence");
    let observed = now_ms();
    let (issuer, key) = issuer("principal:atomic", 21);
    let first = evidence(
        "evidence:atomic-one",
        candidate('b'),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Evaluator,
        observed,
        None,
        json!({"case": 1}),
    );
    append(&store, &issuer, &key, &first, 7)
        .await
        .expect("first sequence");

    let second = evidence(
        "evidence:atomic-two",
        candidate('b'),
        EvidenceClaimClassV1::MandatoryTests,
        EvidenceIssuerRoleV1::Evaluator,
        observed,
        None,
        json!({"case": 2}),
    );
    let replay = signed(
        &second,
        &issuer,
        &key,
        7,
        observed.saturating_add(60_000),
    );
    assert!(matches!(
        store
            .qualification()
            .append_receipt(&issuer, &replay, &second)
            .await,
        Err(EvidenceError::InvalidRecord(_))
    ));
    assert!(
        store
            .qualification()
            .query_claim(&second.candidate, second.claim_class)
            .await
            .expect("query")
            .iter()
            .all(|reference| reference.evidence_id != second.evidence_id)
    );
}

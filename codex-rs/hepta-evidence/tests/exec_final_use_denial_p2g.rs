#![cfg(unix)]
//! Test-only P2g: exact signed Final-use vs. original Evidence P2b denial.
//!
//! Never starts Codex Exec Server, never calls a physical provider, and never
//! upgrades a test Final-use grant into the original effect owner's authority.
//! System clock + local test issuer are deliberately NOT production trust.

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::exec_server_start_p2c::CODEX_EXEC_SERVER_P2C_DESTINATION;
use codex_hepta_contracts::exec_server_start_p2c::CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY;
use codex_hepta_contracts::exec_server_start_p2c::inspect_codex_exec_server_start_v1;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;
use codex_hepta_contracts::execution_contract_v1::ExecutionTargetV1;
use codex_hepta_evidence::EXECUTION_EFFECT_ENTRY_P2B_PERMITTED;
use codex_hepta_evidence::EvidenceError;
use codex_hepta_evidence::ExecutionEffectEntryDeniedV1;
use codex_hepta_evidence::ExecutionPreparationReadbackStatusV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use tempfile::TempDir;

const EXPECTED_INSPECTABLE: usize = 6;
const SIGNER: &str = "issuer:p2g-test-only";

#[derive(Deserialize)]
struct Case {
    id: String,
    raw: String,
    hepta_accepts: bool,
}

#[derive(Deserialize)]
struct Corpus {
    schema: u32,
    authority: String,
    operation_id: String,
    cases: Vec<Case>,
}

fn inspectable_cases() -> (String, Vec<Case>) {
    let corpus: Corpus = serde_json::from_str(include_str!(
        "../../../qualification/codex-exec-p2e/corpus.json"
    ))
    .expect("exact P2e corpus");
    assert_eq!(corpus.schema, 1);
    assert_eq!(corpus.authority, "DENY_ALL");
    assert_eq!(corpus.cases.len(), 50);
    let accepted: Vec<Case> = corpus
        .cases
        .into_iter()
        .filter(|case| case.hepta_accepts)
        .collect();
    assert_eq!(accepted.len(), EXPECTED_INSPECTABLE);
    (corpus.operation_id, accepted)
}

fn intent_for(operation_id: &str, raw: &[u8]) -> ExecutionIntentV1 {
    ExecutionIntentV1 {
        schema_version: 1,
        operation_id: operation_id.into(),
        subject_id: "agent:p2g".into(),
        scope_id: "scope:p2g".into(),
        destination_id: CODEX_EXEC_SERVER_P2C_DESTINATION.into(),
        target: ExecutionTargetV1::CodexExecServerProcess,
        generation: 3,
        fence: 4,
        authority_epoch: 5,
        payload_sha256: Sha256Digest::for_bytes(raw),
        payload_bytes: u32::try_from(raw.len()).expect("bounded frozen corpus"),
        deadline_unix_ms: 1_800_000_000_000,
        max_wall_ms: 2000,
    }
}

fn original_config(dir: &TempDir) -> SqliteConfig {
    let path = AbsolutePathBuf::try_from(dir.path().to_path_buf()).expect("private test path");
    SqliteConfig::new_for_testing(path)
}

fn trust_head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 5,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    }
}

fn open_test_authority(directory: &TempDir, issuer: &SigningKey) -> FinalUseAuthority {
    std::fs::set_permissions(
        directory.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("private test-only Final-use directory");
    FinalUseAuthority::open_state_dir(
        directory.path(),
        SIGNER.to_owned(),
        issuer.verifying_key().to_bytes(),
        trust_head(),
    )
    .expect("original Final-use authority with local test trust")
}

fn signed_test_grant(
    intent: &ExecutionIntentV1,
    issuer: &SigningKey,
    nonce: u8,
    grant_id: &str,
) -> SignedFinalUseGrant {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("test host epoch")
        .as_millis() as u64;
    let binding = intent
        .binding_proposal()
        .expect("valid original intent")
        .proposed_final_use_binding;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: SIGNER.to_owned(),
        authority_epoch: intent.authority_epoch,
        grant_id: grant_id.into(),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 120_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("valid original grant"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

async fn prepare_original(
    original: &TempDir,
    intent: &ExecutionIntentV1,
    raw: &[u8],
) -> (SqliteConfig, codex_hepta_contracts::ProviderEffectKey) {
    inspect_codex_exec_server_start_v1(intent, raw).expect("actual P2c inspector");
    let cfg = original_config(original);
    let writer = HeptaEvidenceStore::open(&cfg).await.expect("original Evidence owner");
    let prepared = writer
        .prepare_execution_intent_v1(intent, raw)
        .await
        .expect("original SQLite atomic prepare");
    assert_eq!(
        prepared.readback.status,
        ExecutionPreparationReadbackStatusV1::RecordedOnly
    );
    writer.close().await;
    (cfg, prepared.readback.provider_effect_key)
}

#[tokio::test]
async fn six_valid_signed_final_use_entries_never_bypass_original_physical_denial() {
    const {
        assert!(!CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY);
        assert!(!EXECUTION_EFFECT_ENTRY_P2B_PERMITTED);
    }
    let (operation, cases) = inspectable_cases();
    for (index, case) in cases.iter().enumerate() {
        let raw = case.raw.as_bytes();
        let intent = intent_for(&operation, raw);
        let binding = intent
            .binding_proposal()
            .expect("original binding")
            .proposed_final_use_binding;
        let evidence_home = TempDir::new().expect("Evidence home");
        let (cfg, key) = prepare_original(&evidence_home, &intent, raw).await;
        let issuer = SigningKey::from_bytes(&[53; 32]);
        let authority_home = TempDir::new().expect("independent test authority home");
        let authority = open_test_authority(&authority_home, &issuer);
        let signed = signed_test_grant(
            &intent,
            &issuer,
            u8::try_from(index + 1).expect("six entries"),
            &format!("grant:p2g:{}", case.id),
        );

        // This genuine, single-use signed entry is an opaque token only.
        // The actual original Evidence P2b gate has no grant-to-effect adapter.
        let token = authority
            .claim(&signed, &binding)
            .expect("valid test-only independent signature");
        let entered = authority
            .enter_verified_use(token, &binding)
            .expect("actual original final live-authority check");
        assert!(entered.matches(&binding));
        drop(entered);

        let reader = HeptaEvidenceStore::open_existing_read_only(&cfg)
            .await
            .expect("cold Evidence owner");
        let recovered = reader
            .recover_execution_preparation_by_key_v1(&key)
            .await
            .expect("original recovery")
            .expect("complete original intent");
        assert_eq!(recovered.intent, intent, "{}", case.id);
        let refusal = reader
            .audit_execution_effect_entry_denied_v1(&recovered.intent, raw)
            .await
            .expect("original P2b denial");
        assert_eq!(
            refusal.denied,
            ExecutionEffectEntryDeniedV1::IndependentFinalUseAndPhysicalOwnerUnavailable
        );
        assert_eq!(
            refusal.request_sha256,
            binding.request_sha256,
            "{}",
            case.id
        );
        assert!(matches!(
            authority.claim(&signed, &binding),
            Err(FinalUseError::AlreadyClaimed)
        ));
        reader.close().await;

        // Actual persisted nonce is still consumed across cold authority reopen.
        drop(authority);
        let restarted = open_test_authority(&authority_home, &issuer);
        assert!(matches!(
            restarted.claim(&signed, &binding),
            Err(FinalUseError::AlreadyClaimed)
        ));
    }
}

#[tokio::test]
async fn wrong_binding_and_forged_signature_fail_before_any_owner_effect() {
    let (operation, cases) = inspectable_cases();
    let raw = cases[0].raw.as_bytes();
    let intent = intent_for(&operation, raw);
    let binding = intent
        .binding_proposal()
        .expect("binding")
        .proposed_final_use_binding;
    let evidence_home = TempDir::new().expect("Evidence home");
    let (cfg, key) = prepare_original(&evidence_home, &intent, raw).await;
    let issuer = SigningKey::from_bytes(&[54; 32]);
    let authority_home = TempDir::new().expect("authority home");
    let authority = open_test_authority(&authority_home, &issuer);
    let signed = signed_test_grant(&intent, &issuer, 7, "grant:p2g:tamper");

    let mut foreign: FinalUseBinding = binding.clone();
    foreign.scope_sha256[0] ^= 0x01;
    assert!(matches!(
        authority.claim(&signed, &foreign),
        Err(FinalUseError::BindingMismatch)
    ));
    let mut forged = signed.clone();
    forged.grant.binding = foreign.clone();
    assert!(matches!(
        authority.claim(&forged, &foreign),
        Err(FinalUseError::InvalidSignature)
    ));

    let reader = HeptaEvidenceStore::open_existing_read_only(&cfg)
        .await
        .expect("cold read-only Evidence");
    let recovered = reader
        .recover_execution_preparation_by_key_v1(&key)
        .await
        .expect("read original")
        .expect("complete original");
    let mut changed_raw = raw.to_vec();
    changed_raw.push(b' ');
    assert!(matches!(
        reader
            .audit_execution_effect_entry_denied_v1(&recovered.intent, &changed_raw)
            .await,
        Err(EvidenceError::InvalidRecord(_))
    ));
    let stale = ExecutionIntentV1 {
        generation: intent.generation + 1,
        ..intent
    };
    assert!(matches!(
        reader.audit_execution_effect_entry_denied_v1(&stale, raw).await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    let refused = reader
        .audit_execution_effect_entry_denied_v1(&recovered.intent, raw)
        .await
        .expect("no grant-to-effect conversion");
    assert_eq!(
        refused.denied,
        ExecutionEffectEntryDeniedV1::IndependentFinalUseAndPhysicalOwnerUnavailable
    );
    reader.close().await;
}

#[tokio::test]
async fn revoked_after_claim_cannot_enter_even_in_test_only_authority() {
    let (operation, cases) = inspectable_cases();
    let raw = cases[0].raw.as_bytes();
    let intent = intent_for(&operation, raw);
    let binding = intent
        .binding_proposal()
        .expect("binding")
        .proposed_final_use_binding;
    let issuer = SigningKey::from_bytes(&[55; 32]);
    let authority_home = TempDir::new().expect("authority home");
    let authority = open_test_authority(&authority_home, &issuer);
    let signed = signed_test_grant(&intent, &issuer, 8, "grant:p2g:revoked");
    let token = authority
        .claim(&signed, &binding)
        .expect("valid test-only signed claim");
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: intent.authority_epoch,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        })
        .expect("actual original revocation mutation");
    assert!(matches!(
        authority.enter_verified_use(token, &binding),
        Err(FinalUseError::Revoked)
    ));
    let evidence_home = TempDir::new().expect("Evidence home");
    let (cfg, _) = prepare_original(&evidence_home, &intent, raw).await;
    let reader = HeptaEvidenceStore::open_existing_read_only(&cfg)
        .await
        .expect("read-only Evidence");
    let refused = reader
        .audit_execution_effect_entry_denied_v1(&intent, raw)
        .await
        .expect("original refusal after revocation");
    assert_eq!(
        refused.denied,
        ExecutionEffectEntryDeniedV1::IndependentFinalUseAndPhysicalOwnerUnavailable
    );
    reader.close().await;
}

#[tokio::test]
async fn even_signed_final_use_cannot_clear_original_indeterminate_quarantine() {
    let (operation, cases) = inspectable_cases();
    let raw = cases[0].raw.as_bytes();
    let intent = intent_for(&operation, raw);
    let binding = intent
        .binding_proposal()
        .expect("binding")
        .proposed_final_use_binding;
    let evidence_home = TempDir::new().expect("Evidence home");
    let cfg = original_config(&evidence_home);
    let writer = HeptaEvidenceStore::open(&cfg).await.expect("original owner");
    inspect_codex_exec_server_start_v1(&intent, raw).expect("P2c preflight");
    let original = writer
        .prepare_execution_intent_v1(&intent, raw)
        .await
        .expect("atomic original prepare");
    writer
        .mark_provider_effect_indeterminate(
            &original.readback.provider_effect_key,
            "p2g_authentic_grant_does_not_clear_uncertainty",
        )
        .await
        .expect("original quarantine");
    writer.close().await;

    let issuer = SigningKey::from_bytes(&[56; 32]);
    let authority_home = TempDir::new().expect("authority home");
    let authority = open_test_authority(&authority_home, &issuer);
    let signed = signed_test_grant(&intent, &issuer, 9, "grant:p2g:unknown");
    let token = authority
        .claim(&signed, &binding)
        .expect("signed test-only claim");
    let entered = authority
        .enter_verified_use(token, &binding)
        .expect("test-only verified entry without any physical effect");
    drop(entered);

    let reader = HeptaEvidenceStore::open_existing_read_only(&cfg)
        .await
        .expect("cold original owner");
    let recovered = reader
        .recover_execution_preparation_by_key_v1(&original.readback.provider_effect_key)
        .await
        .expect("original recovery")
        .expect("complete original intent");
    assert_eq!(
        recovered.readback.status,
        ExecutionPreparationReadbackStatusV1::OriginalOwnerReconciliationRequired
    );
    let refusal = reader
        .audit_execution_effect_entry_denied_v1(&recovered.intent, raw)
        .await
        .expect("original unknown-effect refusal");
    assert_eq!(
        refusal.denied,
        ExecutionEffectEntryDeniedV1::OriginalOwnerReconciliationRequired
    );
    reader.close().await;
}

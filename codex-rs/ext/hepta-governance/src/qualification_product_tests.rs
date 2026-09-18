use std::collections::BTreeSet;
use std::sync::Arc;

use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceCandidateV1;
use codex_hepta_evidence::EvidenceClaimClassV1;
use codex_hepta_evidence::EvidenceDispositionV1;
use codex_hepta_evidence::EvidenceIssuerAuthorityV1;
use codex_hepta_evidence::EvidenceIssuerCertificateV1;
use codex_hepta_evidence::EvidenceIssuerRevocationsV1;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceTrustRootV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::QualificationEvidenceEnvelopeV1;
use codex_hepta_evidence::SignedEvidenceIssuerCertificateV1;
use codex_hepta_evidence::SignedQualificationEvidenceEnvelopeV1;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::GovernanceState;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn candidate() -> EvidenceCandidateV1 {
    EvidenceCandidateV1 {
        candidate_id: "candidate:governance-product:1".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    }
}

fn issuer(
    state: &GovernanceState,
    root_signing: &SigningKey,
    role: EvidenceIssuerRoleV1,
    principal: &str,
    key_id: &str,
    seed: u8,
) -> (SigningKey, codex_hepta_evidence::AuthenticatedEvidenceIssuerV1) {
    let signing = SigningKey::from_bytes(&[seed; 32]);
    let certificate = EvidenceIssuerCertificateV1 {
        schema_version: 1,
        root_id: "root:governance-product".to_string(),
        principal_id: principal.to_string(),
        key_id: key_id.to_string(),
        role,
        verifying_key: signing.verifying_key().to_bytes(),
        not_before_unix_ms: 1_000,
        expires_unix_ms: 100_000,
    };
    let signed = SignedEvidenceIssuerCertificateV1 {
        signature: root_signing
            .sign(&certificate.signing_bytes().expect("certificate bytes"))
            .to_bytes()
            .to_vec(),
        certificate,
    };
    let authenticated = state
        .authenticate_qualification_issuer(signed, 10_000)
        .expect("authenticate issuer");
    (signing, authenticated)
}

fn signed_receipt(
    signing: &SigningKey,
    issuer: &codex_hepta_evidence::AuthenticatedEvidenceIssuerV1,
    receipt_id: &str,
    claim_class: EvidenceClaimClassV1,
    payload: &[u8],
) -> SignedQualificationEvidenceEnvelopeV1 {
    let envelope = QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        receipt_id: receipt_id.to_string(),
        candidate: candidate(),
        claim_class,
        issuer_role: issuer.role(),
        issuer_principal: issuer.principal_id().to_string(),
        issuer_key_id: issuer.key_id().to_string(),
        payload_sha256: Sha256Digest::for_bytes(payload),
        predecessor_receipt_id: None,
        observed_unix_ms: 20_000,
        expires_unix_ms: 90_000,
        revokes_receipt_id: None,
        assets: Vec::new(),
    };
    SignedQualificationEvidenceEnvelopeV1 {
        signature: signing
            .sign(&envelope.signing_bytes().expect("envelope bytes"))
            .to_bytes()
            .to_vec(),
        envelope,
    }
}

#[tokio::test]
async fn governance_product_host_without_pinned_authority_rejects_issuer_authentication() {
    let temp = TempDir::new().expect("temp dir");
    let store = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(store));
    let root_signing = SigningKey::from_bytes(&[30; 32]);
    let signing = SigningKey::from_bytes(&[29; 32]);
    let certificate = EvidenceIssuerCertificateV1 {
        schema_version: 1,
        root_id: "root:untrusted-request".to_string(),
        principal_id: "principal:request".to_string(),
        key_id: "key:request".to_string(),
        role: EvidenceIssuerRoleV1::CiExecutor,
        verifying_key: signing.verifying_key().to_bytes(),
        not_before_unix_ms: 1_000,
        expires_unix_ms: 100_000,
    };
    let signed = SignedEvidenceIssuerCertificateV1 {
        signature: root_signing
            .sign(&certificate.signing_bytes().expect("certificate bytes"))
            .to_bytes()
            .to_vec(),
        certificate,
    };
    let error = state
        .authenticate_qualification_issuer(signed, 10_000)
        .expect_err("request-supplied roots must not authenticate a product issuer");
    assert!(matches!(
        error,
        codex_hepta_evidence::EvidenceError::Unavailable(_)
    ));
}

#[tokio::test]
async fn governance_product_host_composes_authenticated_writer_reader_and_terminal_observer() {
    let temp = TempDir::new().expect("temp dir");
    let store = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let root_signing = SigningKey::from_bytes(&[31; 32]);
    let root = EvidenceTrustRootV1::new(
        "root:governance-product".to_string(),
        root_signing.verifying_key().to_bytes(),
    )
    .expect("root");
    let authority = Arc::new(
        EvidenceIssuerAuthorityV1::new(
            root,
            EvidenceIssuerRevocationsV1 {
                root_id: "root:governance-product".to_string(),
                revision: 1,
                revoked_key_ids: BTreeSet::new(),
            },
        )
        .expect("qualification authority"),
    );
    let state = GovernanceState::enabled_with_qualification_authority(
        GovernanceMode::Enforce,
        Ok(store.clone()),
        authority,
    );

    let (ci_signing, ci) = issuer(
        &state,
        &root_signing,
        EvidenceIssuerRoleV1::CiExecutor,
        "principal:product-ci",
        "key:product-ci",
        32,
    );
    let source = signed_receipt(
        &ci_signing,
        &ci,
        "qe:product-source:1",
        EvidenceClaimClassV1::SourceExecution,
        b"source passed",
    );
    let source_id = state
        .append_qualification_receipt(&source, &ci)
        .await
        .expect("append source");
    assert_eq!(source_id.as_str(), "qe:product-source:1");

    let (observer_signing, observer) = issuer(
        &state,
        &root_signing,
        EvidenceIssuerRoleV1::TerminalObserver,
        "principal:product-terminal",
        "key:product-terminal",
        33,
    );
    let terminal = signed_receipt(
        &observer_signing,
        &observer,
        "qe:product-terminal:1",
        EvidenceClaimClassV1::ProviderEffect,
        b"terminal observation",
    );
    state
        .append_qualification_receipt(&terminal, &observer)
        .await
        .expect("append terminal observer");

    let refs = state
        .query_qualification_claim(&candidate(), EvidenceClaimClassV1::ProviderEffect)
        .await
        .expect("query provider effect");
    assert_eq!(refs.len(), 1);
    assert_eq!(refs[0].issuer_role, EvidenceIssuerRoleV1::TerminalObserver);

    let disposition = state
        .verify_qualification_chain(
            &candidate(),
            &[
                EvidenceIssuerRoleV1::CiExecutor,
                EvidenceIssuerRoleV1::TerminalObserver,
            ],
            30_000,
        )
        .await
        .expect("verify product chain");
    assert!(matches!(disposition, EvidenceDispositionV1::Supported { .. }));

    let checkpoint = state
        .capture_evidence_external_checkpoint()
        .await
        .expect("capture checkpoint");
    state
        .verify_evidence_external_checkpoint(&checkpoint)
        .await
        .expect("verify checkpoint");

    let revoked_authority = Arc::new(
        EvidenceIssuerAuthorityV1::new(
            EvidenceTrustRootV1::new(
                "root:governance-product".to_string(),
                root_signing.verifying_key().to_bytes(),
            )
            .expect("root"),
            EvidenceIssuerRevocationsV1 {
                root_id: "root:governance-product".to_string(),
                revision: 2,
                revoked_key_ids: BTreeSet::from(["key:product-terminal".to_string()]),
            },
        )
        .expect("revoked qualification authority"),
    );
    let revoked_state = GovernanceState::enabled_with_qualification_authority(
        GovernanceMode::Enforce,
        Ok(store.clone()),
        revoked_authority,
    );
    let revoked_refs = revoked_state
        .query_qualification_claim(&candidate(), EvidenceClaimClassV1::ProviderEffect)
        .await
        .expect("query with current revocation head");
    assert_eq!(revoked_refs.len(), 1);
    assert!(revoked_refs[0].revoked);
    let revoked_disposition = revoked_state
        .verify_qualification_chain(
            &candidate(),
            &[EvidenceIssuerRoleV1::TerminalObserver],
            30_000,
        )
        .await
        .expect("verify with current revocation head");
    assert!(matches!(
        revoked_disposition,
        EvidenceDispositionV1::Missing { roles }
            if roles == vec![EvidenceIssuerRoleV1::TerminalObserver]
    ));

    let other_root_signing = SigningKey::from_bytes(&[34; 32]);
    let untrusted_state = GovernanceState::enabled_with_qualification_authority(
        GovernanceMode::Enforce,
        Ok(store),
        Arc::new(
            EvidenceIssuerAuthorityV1::new(
                EvidenceTrustRootV1::new(
                    "root:governance-product-other".to_string(),
                    other_root_signing.verifying_key().to_bytes(),
                )
                .expect("other root"),
                EvidenceIssuerRevocationsV1 {
                    root_id: "root:governance-product-other".to_string(),
                    revision: 1,
                    revoked_key_ids: BTreeSet::new(),
                },
            )
            .expect("other qualification authority"),
        ),
    );
    let trust_error = untrusted_state
        .query_qualification_claim(&candidate(), EvidenceClaimClassV1::SourceExecution)
        .await
        .expect_err("stored issuer certificates must chain to the pinned product root");
    assert!(matches!(
        trust_error,
        codex_hepta_evidence::EvidenceError::Corrupt(_)
    ));
}

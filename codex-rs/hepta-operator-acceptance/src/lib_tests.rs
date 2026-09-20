use pretty_assertions::assert_eq;

use super::*;
use crate::model::AcceptanceReceipt;
use crate::model::CandidateBinding;
use crate::model::FrozenProductBinding;
use crate::model::NonceClaim;
use crate::model::OracleBinding;
use crate::model::QualificationReceiptBinding;
use crate::receipt_store::persist_final_acceptance;
use crate::receipt_store::signature_binding;
use crate::receipt_store::validate_idempotent_replay;
use crate::receipt_store::validate_receipt;
use crate::test_support::private_tempdir;
use crate::trust::VerifiedSignature;

#[test]
fn exact_challenge_boundary_accepts_only_operator_acceptance() {
    let evidence = evidence();
    let operator = operator();
    let challenge = challenge(&evidence, &operator);
    validate_challenge(&challenge, &evidence, &operator).expect("exact boundary");

    let authority_mutations: [fn(&mut AuthorityBoundary); 7] = [
        |value| value.authority = true,
        |value| value.enforce = true,
        |value| value.operator_acceptance = false,
        |value| value.outbound = true,
        |value| value.promotion = true,
        |value| value.qualification_authority = true,
        |value| value.retirement = true,
    ];
    for mutation in authority_mutations {
        let mut changed = challenge.clone();
        mutation(&mut changed.authority);
        assert!(validate_challenge(&changed, &evidence, &operator).is_err());
    }

    let exclusion_mutations: [fn(&mut ExcludedGates); 6] = [
        |value| value.github_gate_run = true,
        |value| value.memory_gate_run = true,
        |value| value.proof_gate_run = true,
        |value| value.s2_gate_run = true,
        |value| value.s5_gate_run = true,
        |value| value.windows_gate_run = true,
    ];
    for mutation in exclusion_mutations {
        let mut changed = challenge.clone();
        mutation(&mut changed.excluded_gates);
        assert!(validate_challenge(&changed, &evidence, &operator).is_err());
    }

    let mut automatic = challenge.clone();
    automatic.automatic_transition = true;
    assert!(validate_challenge(&automatic, &evidence, &operator).is_err());

    let mut wrong_namespace = challenge;
    wrong_namespace.namespace = "hepta-operator-acceptance-v1".to_string();
    assert!(validate_challenge(&wrong_namespace, &evidence, &operator).is_err());
}

#[test]
fn validity_window_is_half_open_and_policy_bounded() {
    let evidence = evidence();
    let operator = operator();
    let challenge = challenge(&evidence, &operator);
    validate_time_window(&challenge, 100).expect("inclusive start");
    validate_time_window(&challenge, 199).expect("last valid second");
    assert!(validate_time_window(&challenge, 99).is_err());
    assert!(validate_time_window(&challenge, 200).is_err());

    let mut too_long = challenge;
    too_long.expires_at_unix_seconds = 1_001;
    assert!(validate_challenge(&too_long, &evidence, &operator).is_err());
}

#[test]
fn final_consumption_at_expiry_creates_no_claim_or_receipt() {
    let evidence = evidence();
    let operator = operator();
    let challenge = challenge(&evidence, &operator);
    let challenge_sha256 = sha256(&canonical_json(&challenge).unwrap());
    let temporary = private_tempdir("temporary final-consumption store");
    let root = temporary
        .path()
        .canonicalize()
        .expect("canonical test store");
    let claim_path = root.join(CLAIM_FILE);
    let receipt_path = root.join(RECEIPT_FILE);
    let result = persist_final_acceptance(
        &receipt_path,
        &claim_path,
        &challenge,
        &challenge_sha256,
        &operator,
        &verified_signature("d"),
        challenge.expires_at_unix_seconds,
    );
    assert!(result.is_err());
    assert!(!claim_path.exists());
    assert!(!receipt_path.exists());
}

#[test]
fn receipt_repeated_authority_must_match_exact_boundary() {
    let evidence = evidence();
    let operator = operator();
    let challenge = challenge(&evidence, &operator);
    let challenge_sha256 = sha256(&canonical_json(&challenge).unwrap());
    let signature = signature_binding(&operator, &verified_signature("d"));
    let receipt = AcceptanceReceipt {
        accepted_at_unix_seconds: 150,
        authority: AuthorityBoundary::evidence_acceptance_only(),
        challenge: challenge.clone(),
        challenge_sha256: challenge_sha256.clone(),
        schema: RECEIPT_SCHEMA.to_string(),
        schema_version: 1,
        signature: signature.clone(),
    };
    validate_receipt(&receipt, &challenge, &challenge_sha256, &signature)
        .expect("consistent receipt");
    let mutations: [fn(&mut AuthorityBoundary); 7] = [
        |value| value.authority = true,
        |value| value.enforce = true,
        |value| value.operator_acceptance = false,
        |value| value.outbound = true,
        |value| value.promotion = true,
        |value| value.qualification_authority = true,
        |value| value.retirement = true,
    ];
    for mutation in mutations {
        let mut changed = receipt.clone();
        mutation(&mut changed.authority);
        assert!(validate_receipt(&changed, &challenge, &challenge_sha256, &signature).is_err());
    }
    let nested_authority_mutations: [fn(&mut AuthorityBoundary); 7] = [
        |value| value.authority = true,
        |value| value.enforce = true,
        |value| value.operator_acceptance = false,
        |value| value.outbound = true,
        |value| value.promotion = true,
        |value| value.qualification_authority = true,
        |value| value.retirement = true,
    ];
    for mutation in nested_authority_mutations {
        let mut changed = receipt.clone();
        mutation(&mut changed.challenge.authority);
        assert!(validate_receipt(&changed, &challenge, &challenge_sha256, &signature).is_err());
    }
    let nested_exclusion_mutations: [fn(&mut ExcludedGates); 6] = [
        |value| value.github_gate_run = true,
        |value| value.memory_gate_run = true,
        |value| value.proof_gate_run = true,
        |value| value.s2_gate_run = true,
        |value| value.s5_gate_run = true,
        |value| value.windows_gate_run = true,
    ];
    for mutation in nested_exclusion_mutations {
        let mut changed = receipt.clone();
        mutation(&mut changed.challenge.excluded_gates);
        assert!(validate_receipt(&changed, &challenge, &challenge_sha256, &signature).is_err());
    }
    let mut nested_automatic = receipt;
    nested_automatic.challenge.automatic_transition = true;
    assert!(
        validate_receipt(&nested_automatic, &challenge, &challenge_sha256, &signature,).is_err()
    );
}

#[test]
fn unknown_or_noncanonical_stored_json_is_rejected() {
    let temporary = private_tempdir("temporary canonical store");
    let root = temporary
        .path()
        .canonicalize()
        .expect("canonical test store");
    let unknown = root.join("unknown.json");
    write_private_new(
        &unknown,
        br#"{"extra":true,"last_observed_unix_seconds":1,"schema":"hepta_operator_acceptance_time_watermark_v1","schema_version":1,"trust_policy_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#,
    )
    .unwrap();
    assert!(read_canonical::<TimeWatermark>(&unknown, "unknown test JSON").is_err());

    let noncanonical = root.join("noncanonical.json");
    write_private_new(
        &noncanonical,
        br#"{"schema":"hepta_operator_acceptance_time_watermark_v1","last_observed_unix_seconds":1,"schema_version":1,"trust_policy_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#,
    )
    .unwrap();
    assert!(read_canonical::<TimeWatermark>(&noncanonical, "noncanonical test JSON").is_err());
}

#[test]
fn durable_time_watermark_rejects_clock_rollback() {
    let temporary = private_tempdir("temporary sidecar");
    let sidecar = temporary.path().canonicalize().expect("canonical sidecar");
    let policy_sha256 = "a".repeat(64);
    advance_time_watermark(&sidecar, 100, &policy_sha256).expect("initial watermark");
    assert!(advance_time_watermark(&sidecar, 99, &policy_sha256).is_err());
    advance_time_watermark(&sidecar, 101, &policy_sha256).expect("forward watermark");
    let (stored, _) =
        read_canonical::<TimeWatermark>(&sidecar.join(WATERMARK_FILE), "test watermark")
            .expect("read watermark");
    assert_eq!(stored.last_observed_unix_seconds, 101);
}

#[test]
fn read_only_lock_never_creates_missing_state() {
    let temporary = private_tempdir("temporary read-only store");
    let root = temporary
        .path()
        .canonicalize()
        .expect("canonical test store");
    let lock_path = root.join(".operator-acceptance.lock");
    assert!(lock_existing_sidecar(&root).is_err());
    assert!(!lock_path.exists());

    drop(lock_sidecar(&root).expect("create ceremony lock"));
    drop(lock_existing_sidecar(&root).expect("open existing lock"));
    std::fs::remove_file(&lock_path).expect("remove test lock");
    assert!(lock_existing_sidecar(&root).is_err());
    assert!(!lock_path.exists());
}

#[test]
fn exact_replay_returns_same_receipt_and_conflicting_claim_fails() {
    let evidence = evidence();
    let operator = operator();
    let challenge = challenge(&evidence, &operator);
    let challenge_sha256 = sha256(&canonical_json(&challenge).unwrap());
    let signature_sha256 = "d".repeat(64);
    let signature = signature_binding(&operator, &verified_signature("d"));
    let receipt = AcceptanceReceipt {
        accepted_at_unix_seconds: 150,
        authority: AuthorityBoundary::evidence_acceptance_only(),
        challenge: challenge.clone(),
        challenge_sha256: challenge_sha256.clone(),
        schema: RECEIPT_SCHEMA.to_string(),
        schema_version: 1,
        signature,
    };
    let claim = NonceClaim {
        accepted_at_unix_seconds: 150,
        challenge_sha256: challenge_sha256.clone(),
        detached_signature_sha256: signature_sha256,
        nonce: challenge.nonce.clone(),
        schema: CLAIM_SCHEMA.to_string(),
        schema_version: 1,
    };
    let temporary = private_tempdir("temporary replay store");
    let root = temporary
        .path()
        .canonicalize()
        .expect("canonical replay store");
    let receipt_path = root.join(RECEIPT_FILE);
    let claim_path = root.join(CLAIM_FILE);
    write_private_new(&receipt_path, &canonical_json(&receipt).unwrap()).unwrap();
    write_private_new(&claim_path, &canonical_json(&claim).unwrap()).unwrap();
    let replay = validate_idempotent_replay(
        &receipt_path,
        &claim_path,
        &challenge,
        &challenge_sha256,
        &receipt.signature,
    )
    .expect("exact replay");
    assert_eq!(replay.challenge_sha256, challenge_sha256);

    assert!(
        validate_idempotent_replay(
            &receipt_path,
            &claim_path,
            &challenge,
            &replay.challenge_sha256,
            &signature_binding(&operator, &verified_signature("e")),
        )
        .is_err()
    );
}

fn operator() -> OperatorBinding {
    OperatorBinding {
        acceptance_store_root: "/acceptance-store".to_string(),
        allowed_signers_sha256: "a".repeat(64),
        key_fingerprint: "SHA256:abcdefghijklmnopqrstuvwx".to_string(),
        maximum_lifetime_seconds: 900,
        principal: "operator@example".to_string(),
        trust_policy_scope: TRUST_POLICY_SCOPE.to_string(),
        trust_policy_sha256: "b".repeat(64),
        trust_root_id: "operator-root".to_string(),
        trust_root_revision: 1,
    }
}

fn verified_signature(digit: &str) -> VerifiedSignature {
    VerifiedSignature {
        detached_signature_sha256: digit.repeat(64),
        detached_signature_sshsig_base64: "dGVzdC1zc2hzaWc=".to_string(),
    }
}

fn evidence() -> EvidenceBinding {
    EvidenceBinding {
        candidate: CandidateBinding {
            base: "base".to_string(),
            bundle_sha256: "1".repeat(64),
            head: "head".to_string(),
            tree: "tree".to_string(),
        },
        frozen_product: FrozenProductBinding {
            audit_manifest_entry_count: 6,
            audit_manifest_sha256: "2".repeat(64),
            audit_root: "/frozen-product".to_string(),
            binary_relative_path: "product".to_string(),
            binary_sha256: "3".repeat(64),
            binary_size_bytes: 42,
            platform: "test-platform".to_string(),
            source_commit: "source".to_string(),
            source_tree: "source-tree".to_string(),
        },
        oracle: OracleBinding {
            commit: "oracle".to_string(),
            corpus_sha256: "4".repeat(64),
            expected_normalized_receipt_sha256: "5".repeat(64),
            sample_id_sha256: "6".repeat(64),
            tree: "oracle-tree".to_string(),
        },
        qualification_receipt: QualificationReceiptBinding {
            candidate_bundle_sha256: "1".repeat(64),
            git_tree_manifest_sha256: "7".repeat(64),
            manifest_entry_count: 1_786,
            manifest_root_kind: "sha256_of_sha256sums_bytes".to_string(),
            manifest_sha256: "8".repeat(64),
            receipt_id: "qualification-test".to_string(),
            receipt_root: "/qualification".to_string(),
            runs: Vec::new(),
            soak_summary_sha256: "9".repeat(64),
            status_sha256: "a".repeat(64),
            tracked_content_manifest_sha256: "b".repeat(64),
        },
    }
}

fn challenge(evidence: &EvidenceBinding, operator: &OperatorBinding) -> AcceptanceChallenge {
    AcceptanceChallenge {
        automatic_transition: false,
        authority: AuthorityBoundary::evidence_acceptance_only(),
        candidate: evidence.candidate.clone(),
        decision: DECISION.to_string(),
        declaration: DECLARATION.to_string(),
        expires_at_unix_seconds: 200,
        excluded_gates: ExcludedGates::none_run(),
        frozen_product: evidence.frozen_product.clone(),
        issued_at_unix_seconds: 100,
        namespace: SSHSIG_NAMESPACE.to_string(),
        nonce: "1".repeat(64),
        not_before_unix_seconds: 100,
        operator: operator.clone(),
        oracle: evidence.oracle.clone(),
        qualification_receipt: evidence.qualification_receipt.clone(),
        schema: CHALLENGE_SCHEMA.to_string(),
        schema_version: 1,
        scope: ACCEPTANCE_SCOPE.to_string(),
        signature_algorithm: SIGNATURE_ALGORITHM.to_string(),
    }
}

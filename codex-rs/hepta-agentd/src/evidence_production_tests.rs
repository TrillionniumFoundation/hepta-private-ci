use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_evidence::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use codex_hepta_evidence::EvidenceRecoveryFrontierSignatureV2;
use codex_hepta_evidence::EvidenceRecoveryFrontierV2;
use codex_hepta_evidence::EvidenceRecoverySnapshotV1;
use codex_hepta_evidence::evidence_recovery_ledger_root_v2;
use serde_json::Map;
use serde_json::Value;
use serde_json::json;

use super::EvidenceBackupPublicationReceiptV1;
use super::qualification_receipt_set_sha256;
use super::validate_backup_publication;
use super::validate_qualification_receipts;

const QUALIFICATION_CHECKS: [&str; 5] = [
    "agentd-product-test",
    "docs",
    "evidence-tests",
    "implementation-maps",
    "lane-a-truth",
];

fn check_record(name: &str) -> Value {
    json!({
        "path": format!("{name}.json"),
        "present": true,
        "sha256": "c".repeat(64),
        "bytes": 128,
        "status": "passed",
        "exitCode": 0,
        "commandExitCode": 0,
        "log": {
            "path": format!("{name}.log"),
            "present": true,
            "sha256": "d".repeat(64),
            "bytes": 0
        },
        "error": null,
        "passed": true
    })
}

fn check_map() -> Map<String, Value> {
    QUALIFICATION_CHECKS
        .into_iter()
        .map(|name| (name.to_string(), check_record(name)))
        .collect()
}

fn receipt(kind: &str, commit: &str, tree: &str) -> Vec<u8> {
    let base = "1".repeat(40);
    let (flag, job, candidate) = if kind == "kernel_evidence_exact_source" {
        (
            "exactSourceQualified",
            "source-head",
            json!({
                "asOfCommit": commit,
                "asOfTree": tree,
                "sourceCommit": commit,
                "baseCommit": base,
                "testedCommit": commit,
                "parents": ["2".repeat(40)],
                "lane": "source-head",
                "dirty": false,
                "identityErrors": []
            }),
        )
    } else {
        (
            "mergeCandidateQualified",
            "merge-candidate",
            json!({
                "asOfCommit": "d".repeat(40),
                "asOfTree": "e".repeat(40),
                "sourceCommit": commit,
                "baseCommit": base,
                "testedCommit": "d".repeat(40),
                "parents": [base, commit],
                "lane": "base-merge",
                "dirty": false,
                "identityErrors": []
            }),
        )
    };
    let mut value = json!({
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "kind": kind,
        "qualified": true,
        "exactSourceQualified": false,
        "mergeCandidateQualified": false,
        "independentAcceptance": false,
        "externalFrontierActive": false,
        "backupRestoreDrilled": false,
        "canaryAccepted": false,
        "releaseApproved": false,
        "candidate": candidate,
        "workflow": {
            "repository": "example/repo",
            "workflow": "blocking-ci",
            "workflowRunId": "12345",
            "workflowRunAttempt": "1",
            "job": job,
            "event": "pull_request"
        },
        "checks": check_map(),
        "artifact": {
            "id": 9,
            "url": "https://github.com/example/repo/actions/runs/12345/artifacts/9",
            "sha256": "f".repeat(64)
        },
        "authority": {
            "selfIssuedReleaseAuthority": false,
            "note": "qualification only"
        }
    });
    value[flag] = json!(true);
    serde_json::to_vec(&value).expect("serialize qualification receipt")
}

fn frontier() -> EvidenceRecoveryFrontierV2 {
    let snapshot = EvidenceRecoverySnapshotV1 {
        schema_version: 1,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: Sha256Digest::for_bytes(b"migrations"),
        qualification_max_seq: 4,
        qualification_frontier_sha256: Sha256Digest::for_bytes(b"qualification"),
        authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
    };
    EvidenceRecoveryFrontierV2 {
        schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
        store_id: "store:kernel-evidence".to_string(),
        frontier_generation: 12,
        ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
        snapshot,
        issuer_trust_registry_sha256: Sha256Digest::for_bytes(b"issuer"),
        frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signers"),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend"),
        build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
        qualification_receipt_sha256: Sha256Digest::for_bytes(b"qualification-receipts"),
        backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: 1_900_000_000_000,
        signer_policy_generation: 3,
        signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
            signer_principal_id: "issuer:recovery".to_string(),
            signer_key_epoch: 1,
            signature_hex: "11".repeat(64),
        }],
    }
}

#[test]
fn exact_and_merge_receipts_must_bind_the_same_source_candidate() {
    let commit = "a".repeat(40);
    let tree = "b".repeat(40);
    let exact = receipt("kernel_evidence_exact_source", &commit, &tree);
    let merge = receipt("kernel_evidence_synthetic_merge", &commit, &tree);
    let identity = validate_qualification_receipts(&exact, &merge)
        .expect("valid source and merge receipts");
    assert_eq!(identity.source_commit, commit);
    assert_eq!(identity.source_tree, tree);

    let wrong_merge = receipt(
        "kernel_evidence_synthetic_merge",
        &"c".repeat(40),
        &tree,
    );
    assert!(validate_qualification_receipts(&exact, &wrong_merge).is_err());
}

#[test]
fn failed_dirty_or_unretained_qualification_receipts_are_rejected() {
    let commit = "a".repeat(40);
    let tree = "b".repeat(40);
    let exact = receipt("kernel_evidence_exact_source", &commit, &tree);
    let merge = receipt("kernel_evidence_synthetic_merge", &commit, &tree);

    let mut failed: Value = serde_json::from_slice(&exact).unwrap();
    failed["checks"]["docs"]["passed"] = json!(false);
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&failed).unwrap(),
            &merge,
        )
        .is_err()
    );

    let mut dirty: Value = serde_json::from_slice(&exact).unwrap();
    dirty["candidate"]["dirty"] = json!(true);
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&dirty).unwrap(),
            &merge,
        )
        .is_err()
    );

    let mut no_artifact: Value = serde_json::from_slice(&exact).unwrap();
    no_artifact["artifact"] = Value::Null;
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&no_artifact).unwrap(),
            &merge,
        )
        .is_err()
    );

    let mut self_promoted: Value = serde_json::from_slice(&exact).unwrap();
    self_promoted["releaseApproved"] = json!(true);
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&self_promoted).unwrap(),
            &merge,
        )
        .is_err()
    );
}

#[test]
fn qualification_receipts_require_the_closed_world_check_inventory() {
    let commit = "a".repeat(40);
    let tree = "b".repeat(40);
    let exact = receipt("kernel_evidence_exact_source", &commit, &tree);
    let merge = receipt("kernel_evidence_synthetic_merge", &commit, &tree);

    let mut missing: Value = serde_json::from_slice(&exact).unwrap();
    missing["checks"].as_object_mut().unwrap().remove("docs");
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&missing).unwrap(),
            &merge,
        )
        .is_err()
    );

    let mut extra: Value = serde_json::from_slice(&exact).unwrap();
    extra["checks"]["unreviewed-extra"] = check_record("unreviewed-extra");
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&extra).unwrap(),
            &merge,
        )
        .is_err()
    );

    let mut forged_shape: Value = serde_json::from_slice(&exact).unwrap();
    forged_shape["checks"]["docs"]["commandExitCode"] = json!(1);
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&forged_shape).unwrap(),
            &merge,
        )
        .is_err()
    );

    let mut no_log: Value = serde_json::from_slice(&exact).unwrap();
    no_log["checks"]["docs"]["log"] = Value::Null;
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&no_log).unwrap(),
            &merge,
        )
        .is_err()
    );
}

#[test]
fn qualification_receipts_must_share_one_workflow_identity() {
    let commit = "a".repeat(40);
    let tree = "b".repeat(40);
    let exact = receipt("kernel_evidence_exact_source", &commit, &tree);
    let merge = receipt("kernel_evidence_synthetic_merge", &commit, &tree);

    let mut other_run: Value = serde_json::from_slice(&merge).unwrap();
    other_run["workflow"]["workflowRunId"] = json!("12346");
    other_run["artifact"]["url"] =
        json!("https://github.com/example/repo/actions/runs/12346/artifacts/9");
    assert!(
        validate_qualification_receipts(
            &exact,
            &serde_json::to_vec(&other_run).unwrap(),
        )
        .is_err()
    );

    let mut other_attempt: Value = serde_json::from_slice(&merge).unwrap();
    other_attempt["workflow"]["workflowRunAttempt"] = json!("2");
    assert!(
        validate_qualification_receipts(
            &exact,
            &serde_json::to_vec(&other_attempt).unwrap(),
        )
        .is_err()
    );
}

#[test]
fn qualification_artifact_and_merge_parent_identity_are_exact() {
    let commit = "a".repeat(40);
    let tree = "b".repeat(40);
    let exact = receipt("kernel_evidence_exact_source", &commit, &tree);
    let merge = receipt("kernel_evidence_synthetic_merge", &commit, &tree);

    let mut wrong_url: Value = serde_json::from_slice(&exact).unwrap();
    wrong_url["artifact"]["url"] =
        json!("https://github.com/example/repo/actions/runs/12345/artifacts/10");
    assert!(
        validate_qualification_receipts(
            &serde_json::to_vec(&wrong_url).unwrap(),
            &merge,
        )
        .is_err()
    );

    let mut reversed: Value = serde_json::from_slice(&merge).unwrap();
    reversed["candidate"]["parents"] =
        json!([commit, "1".repeat(40)]);
    assert!(
        validate_qualification_receipts(
            &exact,
            &serde_json::to_vec(&reversed).unwrap(),
        )
        .is_err()
    );
}

#[test]
fn qualification_receipt_set_digest_is_ordered() {
    let exact = Sha256Digest::for_bytes(b"exact");
    let merge = Sha256Digest::for_bytes(b"merge");
    assert_ne!(
        qualification_receipt_set_sha256(&exact, &merge),
        qualification_receipt_set_sha256(&merge, &exact)
    );
}

#[test]
fn backup_publication_must_match_snapshot_backend_generation_and_durability() {
    let frontier = frontier();
    let now = 1_900_000_000_100;
    let snapshot = serde_json::to_vec(&frontier.snapshot).unwrap();
    let valid = EvidenceBackupPublicationReceiptV1 {
        schema_version: 1,
        store_id: frontier.store_id.clone(),
        frontier_generation: frontier.frontier_generation,
        snapshot_sha256: Sha256Digest::for_bytes(&snapshot),
        backend_identity_sha256: frontier.backend_identity_sha256.clone(),
        published_at_unix_ms: now - 10,
        durable_acknowledged: true,
    };
    validate_backup_publication(&valid, &frontier, now, 1_000)
        .expect("valid durable backup witness");

    let mut invalid = valid.clone();
    invalid.durable_acknowledged = false;
    assert!(validate_backup_publication(&invalid, &frontier, now, 1_000).is_err());

    invalid = valid;
    invalid.frontier_generation += 1;
    assert!(validate_backup_publication(&invalid, &frontier, now, 1_000).is_err());
}

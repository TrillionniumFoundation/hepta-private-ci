use super::*;
fn private_directory() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().expect("private directory")
}

fn record() -> AgentdSelfIterationRecordV1 {
    AgentdSelfIterationRecordV1 {
        candidate_id: "candidate.a".into(),
        frozen_digest: Digest32::of_bytes(b"frozen"),
        objective_digest: Digest32::of_bytes(b"objective"),
        base_generation: 7,
        successor_generation: 8,
        rollback_generation: 9,
        successor_configuration: Digest32::of_bytes(b"next"),
        successor_body: Digest32::of_bytes(b"next body"),
        rollback_configuration: Digest32::of_bytes(b"rollback"),
        rollback_body: Digest32::of_bytes(b"rollback body"),
        expires_at: 100,
        phase: AgentdSelfIterationPhaseV1::Frozen,
        evaluation_digest: None,
        selection_digest: None,
        canary_operation_digest: None,
        canary_checkpoint_digest: None,
        canary_observation: None,
        observer_digest: None,
    }
}

#[test]
fn journal_reopens_exact_intent_and_preserves_exclusive_ownership() {
    let directory = private_directory();
    let path = directory.path().join("iteration.json");
    let mut owner = IterationJournal::open(path.clone()).expect("owner");
    let mut expected = record();
    owner.persist(&expected).expect("freeze");
    expected.evaluation_digest = Some(Digest32::of_bytes(b"independent evaluation"));
    expected.phase = AgentdSelfIterationPhaseV1::Evaluated;
    owner.persist(&expected).expect("evaluation");
    expected.selection_digest = Some(Digest32::of_bytes(b"independent selection"));
    expected.phase = AgentdSelfIterationPhaseV1::Applying;
    owner.persist(&expected).expect("durable intent");
    assert!(IterationJournal::open(path.clone()).is_err());
    drop(owner);
    let recovered = IterationJournal::open(path).expect("recover");
    assert_eq!(recovered.record(), Some(&expected));
    assert!(recovered.unresolved_apply());
}

#[test]
fn unresolved_intent_cannot_be_replaced_or_rewound_and_corruption_is_rejected() {
    let directory = private_directory();
    let path = directory.path().join("iteration.json");
    let mut owner = IterationJournal::open(path.clone()).expect("owner");
    let mut expected = record();
    owner.persist(&expected).expect("freeze");
    expected.phase = AgentdSelfIterationPhaseV1::Evaluated;
    expected.evaluation_digest = Some(Digest32::of_bytes(b"evaluated"));
    owner.persist(&expected).expect("evaluation");
    let mut foreign = expected.clone();
    foreign.frozen_digest = Digest32::of_bytes(b"foreign");
    assert!(owner.persist(&foreign).is_err());
    assert!(owner.persist(&record()).is_err());
    drop(owner);
    let mut stored: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).expect("read")).expect("json");
    stored["record"]["phase"] = serde_json::json!("accepted");
    std::fs::write(&path, serde_json::to_vec(&stored).expect("encode")).expect("write");
    assert!(IterationJournal::open(path).is_err());
}

#[test]
fn accepted_label_with_valid_checksum_cannot_replace_missing_native_and_owner_proofs() {
    let directory = private_directory();
    let path = directory.path().join("iteration.json");
    let mut forged = record();
    forged.phase = AgentdSelfIterationPhaseV1::Accepted;
    let stored = StoredRecord {
        version: 1,
        checksum: checksum(&forged).expect("checksum"),
        record: forged,
    };
    std::fs::write(&path, serde_json::to_vec(&stored).expect("json")).expect("write");
    assert!(IterationJournal::open(path).is_err());
}

#[test]
fn failed_evaluation_reopens_terminal_and_admits_another_candidate_on_same_predecessor() {
    let directory = private_directory();
    let path = directory.path().join("iteration.json");
    let mut owner = IterationJournal::open(path.clone()).expect("owner");
    let mut rejected = record();
    owner.persist(&rejected).expect("freeze");
    rejected.evaluation_digest = Some(Digest32::of_bytes(b"original failed evaluation"));
    rejected.phase = AgentdSelfIterationPhaseV1::Rejected;
    owner
        .persist(&rejected)
        .expect("reject actual failed experiment");
    assert!(!owner.pending());
    assert!(!owner.unresolved_apply());
    drop(owner);
    let mut recovered = IterationJournal::open(path).expect("recover rejection");
    assert_eq!(recovered.record(), Some(&rejected));
    let mut next = record();
    next.candidate_id = "candidate.b".into();
    next.frozen_digest = Digest32::of_bytes(b"next frozen");
    assert_eq!(next.base_generation, rejected.base_generation);
    recovered
        .persist(&next)
        .expect("next experiment admitted immediately");
    assert!(recovered.pending());
}

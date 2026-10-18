#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;
use artifacts::*;
use std::cell::Cell;
use std::fs;
use std::path::PathBuf;

#[path = "learning_withdrawal_test_support.rs"]
mod support;
use support::*;

#[test]
fn ordinary_agent_cannot_run_root_withdrawal_or_advance_either_owner() {
    let directory = tempfile::tempdir().unwrap();
    let mut fixture = Fixture::new(directory.path().join("ordinary"));
    let before_source = fixture.writer.snapshot().unwrap();
    let before_artifacts = fixture.owner.registry().clone();
    let invoked = Cell::new(false);
    let error = withdraw_learning_dataset_v1(
        &mut fixture.writer,
        &mut fixture.owner,
        &fixture.intent,
        |_, _, _| {
            invoked.set(true);
            Err("must not reach publication".into())
        },
    )
    .unwrap_err();
    assert_eq!(
        error.phase,
        HostLearningWithdrawalPhaseV1::RejectedBeforeFence
    );
    assert!(error.detail.contains("original Root host"));
    assert_eq!(fixture.writer.snapshot().unwrap(), before_source);
    assert_eq!(
        fixture.owner.registry().records(),
        before_artifacts.records()
    );
    assert!(error.source_ack.is_none());
    assert!(error.withdrawal_frontier.is_none());
    assert!(!invoked.get());
}

fn require_delivery_denial(fixture: &Fixture, consumers: &mut [RevalidatingCandidate]) {
    let reader = fixture.reader();
    for consumer in consumers {
        let delivered = Cell::new(false);
        assert_eq!(
            consumer.with_current(reader.current_registry_view(fixture.now).unwrap(), |_| {
                delivered.set(true)
            }),
            Err(PinnedCandidateLoadError::Ineligible)
        );
        assert!(!delivered.get());
    }
}

/// Real Root custody, full durable source and witness, real artifact ACK and
/// original physical delivery gate. Keys/payloads are ONLY isolated fixtures.
#[test]
#[ignore = "Run explicitly as Root in isolated /var/lib fixture custody"]
fn root_withdrawal_retains_partial_facts_closes_delivery_and_cold_recovers_exact_source() {
    let root = PathBuf::from(format!(
        "/var/lib/hepta/native-withdrawal-owner-tests/{}-{}",
        std::process::id(),
        wall_clock_millis().unwrap()
    ));
    fs::create_dir_all(&root).unwrap();

    let mut denied = Fixture::new(root.join("denied"));
    denied.owner.publish_root_read_frontier(denied.now).unwrap();
    let frontier = fs::read(denied.config.root.join("READ-CURRENT")).unwrap();
    let source = denied.writer.snapshot().unwrap();
    denied.intent.evidence.role = ledger::LearningEvidenceRoleV1::Observer;
    let error = withdraw_with_clock(
        &mut denied.writer,
        &mut denied.owner,
        &denied.intent,
        |_, _, _| panic!("wrong role cannot reach publication"),
        || Ok(denied.now),
    )
    .unwrap_err();
    assert_eq!(
        error.phase,
        HostLearningWithdrawalPhaseV1::RejectedBeforeFence
    );
    assert_eq!(denied.writer.snapshot().unwrap(), source);
    assert_eq!(
        fs::read(denied.config.root.join("READ-CURRENT")).unwrap(),
        frontier
    );
    drop(denied);

    let mut expired = Fixture::new(root.join("expired"));
    expired
        .owner
        .publish_root_read_frontier(expired.now)
        .unwrap();
    let old_reader = expired.reader();
    let mut consumers = expired.consumers();
    let before = expired.writer.snapshot().unwrap();
    let mut calls = 0;
    let now = expired.now;
    let error = withdraw_with_clock(
        &mut expired.writer,
        &mut expired.owner,
        &expired.intent,
        |_, _, _| panic!("expired source cannot reach publication"),
        || {
            calls += 1;
            Ok(if calls >= 3 { now + 60_001 } else { now })
        },
    )
    .unwrap_err();
    assert_eq!(
        error.phase,
        HostLearningWithdrawalPhaseV1::SourceAppendUncertain
    );
    assert!(error.source_ack.is_none());
    assert!(error.publication_ack.is_none());
    assert!(error.withdrawal_frontier.is_some());
    assert_eq!(expired.writer.snapshot().unwrap(), before);
    assert!(old_reader.current_registry_view(now).is_err());
    require_delivery_denial(&expired, &mut consumers);
    drop(expired);

    let mut partial = Fixture::new(root.join("partial"));
    partial
        .owner
        .publish_root_read_frontier(partial.now)
        .unwrap();
    let reader = partial.reader();
    let original_current = reader.protected_current_head(partial.now).unwrap();
    let mut consumers = partial.consumers();
    let before = partial.writer.snapshot().unwrap().records().len();
    let error = withdraw_with_clock(
        &mut partial.writer,
        &mut partial.owner,
        &partial.intent,
        |_, _, _| Err("independent replacement signing unavailable".into()),
        || Ok(partial.now),
    )
    .unwrap_err();
    assert_eq!(
        error.phase,
        HostLearningWithdrawalPhaseV1::SourceAcknowledged
    );
    let source_ack = error.source_ack.clone().unwrap();
    assert_eq!(
        partial.writer.snapshot().unwrap().records().len(),
        before + 1
    );
    assert_eq!(
        partial
            .writer
            .witness_frontier()
            .unwrap()
            .anchor
            .chain_digest,
        source_ack.append.chain_digest
    );
    assert!(error.publication_request.is_none());
    assert!(error.publication_ack.is_none());
    assert_eq!(error.state_changes.len(), 2);
    assert!(reader.current_registry_view(partial.now).is_err());
    require_delivery_denial(&partial, &mut consumers);

    let Fixture {
        root: fixture_root,
        writer,
        owner,
        intent,
        mut config,
        trust,
        key,
        now,
    } = partial;
    config.required_current_head = Some(original_current);
    config.withdrawal_registry = error.withdrawal_frontier.unwrap();
    drop(owner);
    drop(writer);
    let mut writer = reopen_writer(&fixture_root, trust);
    let mut owner = LearningArtifactOwnerService::open(config.clone()).unwrap();
    let actual_request = std::cell::RefCell::new(None);
    let receipt = withdraw_with_clock(
        &mut writer,
        &mut owner,
        &intent,
        |owner, changes, now| {
            let mut clean = model("actual-clean-replacement", Digest32::ZERO, now);
            clean.provenance_mode = ProvenanceModeV1::DatasetIndependent;
            clean.source_dataset_digests.clear();
            let request = publication(
                owner,
                &key,
                "original-replacement-operation",
                clean,
                changes,
                now,
            );
            *actual_request.borrow_mut() = Some(request.clone());
            Ok(request)
        },
        || Ok(now),
    )
    .unwrap();
    assert_eq!(
        receipt.source.append.event_digest,
        source_ack.append.event_digest
    );
    assert_eq!(writer.snapshot().unwrap().records().len(), before + 1);
    assert_eq!(
        receipt.current_ineligible_artifacts,
        vec![id("child"), id("source")]
    );
    let request = actual_request.into_inner().unwrap();
    let status = owner.publication_status(&request).unwrap().unwrap().status;
    assert_eq!(status.phase, ArtifactPublicationPhaseV1::Acknowledged);
    assert_eq!(
        status.registry_head_digest,
        Some(receipt.publication.registry_head_digest)
    );
    assert_eq!(
        status.witness_digest,
        Some(receipt.publication.witness_digest)
    );
    assert_eq!(
        status.acknowledged_at,
        Some(receipt.publication.acknowledged_at)
    );
    assert!(!status.authority.grants_any());
    let reader = ReadOnlyArtifactCurrentOwnerV1::open(
        &config.root,
        config.trust.clone(),
        owner.withdrawal_registry().clone(),
        now,
    )
    .unwrap();
    for name in ["source", "child"] {
        assert_eq!(
            owner.registry().state(&id(name)),
            Some(ArtifactState::Revoked)
        );
        assert!(
            !reader
                .current_registry_view(now)
                .unwrap()
                .is_eligible(&id(name))
        );
    }
    assert!(
        reader
            .current_registry_view(now)
            .unwrap()
            .is_eligible(&id("actual-clean-replacement"))
    );
    // A completed transaction is reconciled from its exact checkpoint. A fresh
    // high-level invocation may not silently rebind to the successor CURRENT.
    assert!(
        withdraw_with_clock(
            &mut writer,
            &mut owner,
            &intent,
            |_, _, _| panic!("already changed head cannot start another publication"),
            || Ok(now)
        )
        .is_err()
    );
    let withdrawals = owner.withdrawal_registry().clone();
    drop(owner);
    config.required_current_head = Some(request.signed_current_head.clone());
    config.withdrawal_registry = withdrawals;
    let reopened = LearningArtifactOwnerService::open(config).unwrap();
    assert_eq!(
        reopened
            .publication_status(&request)
            .unwrap()
            .unwrap()
            .status,
        status
    );
    drop(reopened);
    drop(writer);
    fs::remove_dir_all(root).unwrap();
}

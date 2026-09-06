//! Cross-crate real-file qualification, NOT a production learner or efficacy trial.
//! Observer/evaluator identities here are fixtures, not authenticated principals.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;

use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::ArtifactStorageError;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::read_candidate_payload;
use codex_hepta_learning_artifacts::read_registry_snapshot;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::OutcomeFinality;
use codex_hepta_learning_ledger::OutcomeObservation;
use codex_hepta_learning_ledger::inspect_ledger;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

#[path = "support/durable_process.rs"]
mod process;

fn id(value: &str) -> StableId {
    let Ok(identifier) = StableId::new(value) else {
        panic!("fixture identifier must be valid");
    };
    identifier
}

fn create(path: &Path) -> File {
    let Ok(file) = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
    else {
        panic!("new fixture file must be created");
    };
    file
}

fn open_readonly(path: &Path) -> File {
    let Ok(file) = File::open(path) else {
        panic!("fixture file must be readable");
    };
    file
}

/// A bounded fixture learner using ONLY reopened training records. This is not
/// OPE, NDU training or a general cross-fit/statistical acceptance algorithm.
fn fit_binary_fixture(ledger: &LearningLedger) -> Vec<u8> {
    let records = ledger.active_records();
    let mut decisions = BTreeMap::new();
    let mut scores: BTreeMap<StableId, (u64, u64)> = BTreeMap::new();
    for record in &records {
        if let LedgerEvent::Decision(decision) = &record.event {
            decisions.insert(
                decision.episode_id.clone(),
                decision.selected_candidate_id.clone(),
            );
        }
    }
    for record in records {
        if let LedgerEvent::Outcome(outcome) = &record.event {
            assert_eq!(outcome.finality, OutcomeFinality::Terminal);
            let Some(action) = decisions.get(&outcome.episode_id) else {
                panic!("fixture outcome must match a decision");
            };
            let score = scores.entry(action.clone()).or_default();
            score.0 += u64::from(outcome.value == FixedQ32::ONE);
            score.1 += 1;
        }
    }
    // Fixture counts must match; this avoids pretending a success count is an
    // unbiased comparison between differently supported actions.
    let counts: Vec<_> = scores.values().map(|score| score.1).collect();
    assert!(!counts.is_empty());
    assert!(counts.iter().all(|count| *count == counts[0]));
    let Some((action, _)) = scores.iter().max_by_key(|(_, score)| score.0) else {
        panic!("fixture training must have a scored action");
    };
    action.as_str().as_bytes().to_vec()
}

/// Independent code path and disjoint held-out fixture. No training store or
/// generator-provided outcome enters this oracle; identity authentication is not
/// tested by a local fixture and real efficacy is not inferred from this score.
fn held_out_oracle(policy: &[u8]) -> u64 {
    [
        b"freshness-order".as_slice(),
        b"freshness-order".as_slice(),
        b"freshness-order".as_slice(),
    ]
    .iter()
    .map(|expected| u64::from(*expected == policy))
    .sum()
}

fn register(
    registry: &mut ArtifactRegistry,
    name: &str,
    predecessor: Option<&str>,
    bytes: &[u8],
    dataset: Digest32,
) {
    let Ok(generation) = Generation::new(if predecessor.is_some() { 2 } else { 1 }) else {
        panic!("fixture artifact generation must be valid");
    };
    let Ok(_) = registry.append(ArtifactEvent::Register {
        event_id: id(&format!("register-{name}")),
        manifest: ArtifactManifest {
            artifact_id: id(name),
            kind: ArtifactKind::Policy,
            generation,
            predecessor_id: predecessor.map(id),
            content_digest: Digest32::of_bytes(bytes),
            objective_digest: Digest32::of_bytes(b"read-only-retrieval-fixture"),
            support_digest: dataset,
            producer_id: id("fixture-generator"),
            compatibility_digest: Digest32::of_bytes(b"binary-policy-fixture-v1"),
            encoded_size_bytes: bytes.len() as u64,
        },
    }) else {
        panic!("fixture artifact must register successfully");
    };
}

#[test]
fn durable_experience_candidate_reopen_next_snapshot_and_revocation_safe_rollback() {
    let directory = tempfile::tempdir().unwrap();
    let journal_path = directory.path().join("episodes");
    let registry_path = directory.path().join("registry-generation-1");
    let revoked_path = directory.path().join("registry-generation-2");
    let baseline_path = directory.path().join("baseline-payload");
    let candidate_path = directory.path().join("candidate-payload");
    let binding = Digest32::of_bytes(b"explicitly-authorized-fixture-scope");
    let objective = Digest32::of_bytes(b"read-only-retrieval-fixture");
    let mut ledger =
        DurableLedger::create(create(&journal_path), binding, /*max_records*/ 32).unwrap();
    let mut head = Digest32::ZERO;
    let mut sequence = 0;
    for (index, action) in [
        "title-order",
        "freshness-order",
        "title-order",
        "freshness-order",
    ]
    .iter()
    .enumerate()
    {
        let episode = id(&format!("training-episode-{index}"));
        let decision = LedgerEvent::Decision(EpisodeDecision {
            record_id: id(&format!("decision-{index}")),
            episode_id: episode.clone(),
            objective_digest: objective,
            policy_id: id("fixture-behavior-policy"),
            candidate_ids: vec![id("abstain"), id("freshness-order"), id("title-order")],
            selected_candidate_id: id(action),
            selected_propensity: ProbabilityQ32::from_raw(1_u64 << 31).unwrap(),
            completeness: CandidateSetCompleteness::Complete,
            support_digest: Digest32::of_bytes(b"fixture-complete-legal-set"),
        });
        head = ledger.append(head, decision).unwrap().chain_digest;
        let observed = LedgerEvent::Outcome(OutcomeObservation {
            record_id: id(&format!("observation-{index}")),
            outcome_id: id(&format!("outcome-{index}")),
            episode_id: episode,
            observer_id: id("fixture-observer-not-policy"),
            value: if *action == "freshness-order" {
                FixedQ32::ONE
            } else {
                FixedQ32::ZERO
            },
            finality: OutcomeFinality::Terminal,
            support_digest: Digest32::of_bytes(b"fixture-observer-source"),
        });
        let receipt = ledger.append(head, observed).unwrap();
        head = receipt.chain_digest;
        sequence = receipt.sequence.get();
    }
    let before = ledger.snapshot().unwrap();
    drop(ledger);
    let journal_bytes = std::fs::read(&journal_path).unwrap();
    // The evaluator has only an OS read-only file, not the writer/recovery API.
    let inspected = inspect_ledger(
        open_readonly(&journal_path),
        binding,
        /*max_records*/ 32,
        LedgerAnchor {
            sequence,
            chain_digest: head,
        },
    )
    .unwrap();
    assert_eq!(inspected, before);
    let ledger = LearningLedger::from_snapshot(inspected).unwrap();
    // Train in a separate executable process against the acknowledged journal.
    let trained = process::run(process::Request::Train {
        journal: journal_path.clone(),
        binding: binding.to_string(),
        sequence,
        head: head.to_string(),
    });
    let learned = match trained.result {
        process::ResultValue::Trained {
            policy,
            ledger_head,
        } => {
            assert_eq!(ledger_head, head.to_string());
            policy.into_bytes()
        }
        other => panic!("expected training receipt, got {other:?}"),
    };
    assert_eq!(learned, b"freshness-order");
    let baseline = b"title-order";
    assert!(held_out_oracle(&learned) > held_out_oracle(baseline));
    assert_eq!(ledger.snapshot(), before);
    assert_eq!(std::fs::read(&journal_path).unwrap(), journal_bytes);

    // An acknowledged tail lost before the reader starts is refused in that
    // process. Inspection cannot downgrade its witness or repair the journal.
    let truncated_path = directory.path().join("truncated-episodes");
    let truncated_bytes = &journal_bytes[..journal_bytes.len() - 1];
    std::fs::write(&truncated_path, truncated_bytes).unwrap();
    process::assert_rejected(
        &process::run(process::Request::Train {
            journal: truncated_path.clone(),
            binding: binding.to_string(),
            sequence,
            head: head.to_string(),
        }),
        "AcknowledgedHistoryMissing",
    );
    assert_eq!(std::fs::read(&truncated_path).unwrap(), truncated_bytes);

    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "baseline",
        /*predecessor*/ None,
        baseline,
        Digest32::of_bytes(b"baseline-support"),
    );
    register(&mut registry, "candidate", Some("baseline"), &learned, head);
    write_candidate_payload(create(&baseline_path), &registry, &id("baseline"), baseline).unwrap();
    write_candidate_payload(
        create(&candidate_path),
        &registry,
        &id("candidate"),
        &learned,
    )
    .unwrap();
    let registry_receipt =
        write_registry_snapshot(create(&registry_path), &registry, binding).unwrap();
    let expected_registry = registry.snapshot();
    drop(registry);
    let mut registry =
        read_registry_snapshot(open_readonly(&registry_path), registry_receipt).unwrap();
    assert_eq!(registry.snapshot(), expected_registry);

    // Three real executable process generations consume exact fixture-selected
    // tuples. Both ranking policies order the same two legal supported facts.
    let baseline_request = process::LoadRequest::new(
        &registry_path,
        registry_receipt,
        &baseline_path,
        registry.manifest(&id("baseline")).unwrap(),
    );
    let candidate_request = process::LoadRequest::new(
        &registry_path,
        registry_receipt,
        &candidate_path,
        registry.manifest(&id("candidate")).unwrap(),
    );
    let old = process::load(&baseline_request, /*generation*/ 1);
    let next = process::load(&candidate_request, /*generation*/ 2);
    let rollback = process::load(&baseline_request, /*generation*/ 3);
    let old_behavior = process::assert_loaded(
        &old,
        &baseline_request,
        &["supported-alpha", "supported-beta"],
    );
    let next_behavior = process::assert_loaded(
        &next,
        &candidate_request,
        &["supported-beta", "supported-alpha"],
    );
    let rollback_behavior = process::assert_loaded(
        &rollback,
        &baseline_request,
        &["supported-alpha", "supported-beta"],
    );
    assert_ne!(old_behavior, next_behavior);
    assert_eq!(old_behavior, rollback_behavior);
    assert_eq!(old.generation, 1);
    assert_eq!(next.generation, 2);
    assert_eq!(rollback.generation, 3);

    // The current request tuple cannot mix an old compatibility profile or a
    // different objective with the selected checkpoint.
    let mut mixed = candidate_request.clone();
    mixed.objective = Digest32::of_bytes(b"different-objective").to_string();
    process::assert_rejected(&process::load(&mixed, /*generation*/ 4), "tuple_mismatch");
    mixed = candidate_request.clone();
    mixed.compatibility = Digest32::of_bytes(b"different-encoder").to_string();
    process::assert_rejected(&process::load(&mixed, /*generation*/ 5), "tuple_mismatch");
    let corrupt_path = directory.path().join("corrupt-candidate");
    std::fs::write(&corrupt_path, b"corrupt-policy").unwrap();
    let mut corrupt = candidate_request.clone();
    corrupt.payload = corrupt_path;
    process::assert_rejected(
        &process::load(&corrupt, /*generation*/ 6),
        "PayloadMismatch",
    );
    assert_eq!(std::fs::read(&journal_path).unwrap(), journal_bytes);
    assert_eq!(std::fs::read(&baseline_path).unwrap(), baseline);
    assert_eq!(std::fs::read(&candidate_path).unwrap(), learned);

    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke-candidate"),
            artifact_id: id("candidate"),
            evaluator_id: id("fixture-independent-evaluator"),
            reason_digest: Digest32::of_bytes(b"fixture-revocation"),
        }))
        .unwrap();
    let current_receipt =
        write_registry_snapshot(create(&revoked_path), &registry, binding).unwrap();
    drop(registry);
    let mut stale = candidate_request;
    stale.set_witness(current_receipt);
    process::assert_rejected(&process::load(&stale, /*generation*/ 7), "Corrupt");
    let mut revoked_candidate = stale.clone();
    revoked_candidate.registry = revoked_path.clone();
    process::assert_rejected(
        &process::load(&revoked_candidate, /*generation*/ 8),
        "Unavailable",
    );
    let mut current_baseline = baseline_request;
    current_baseline.registry = revoked_path.clone();
    current_baseline.set_witness(current_receipt);
    process::assert_loaded(
        &process::load(&current_baseline, /*generation*/ 9),
        &current_baseline,
        &["supported-alpha", "supported-beta"],
    );
    let mut current =
        read_registry_snapshot(open_readonly(&revoked_path), current_receipt).unwrap();
    assert_eq!(
        read_candidate_payload(open_readonly(&candidate_path), &current, &id("candidate")),
        Err(ArtifactStorageError::Unavailable)
    );
    assert_eq!(
        read_candidate_payload(open_readonly(&baseline_path), &current, &id("baseline")).unwrap(),
        baseline
    );
    current
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke-baseline"),
            artifact_id: id("baseline"),
            evaluator_id: id("fixture-independent-evaluator"),
            reason_digest: Digest32::of_bytes(b"fixture-predecessor-revocation"),
        }))
        .unwrap();
    assert_eq!(
        read_candidate_payload(open_readonly(&baseline_path), &current, &id("baseline")),
        Err(ArtifactStorageError::Unavailable)
    );
    let final_registry = directory.path().join("registry-generation-3");
    let final_receipt =
        write_registry_snapshot(create(&final_registry), &current, binding).unwrap();
    current_baseline.registry = final_registry;
    current_baseline.set_witness(final_receipt);
    process::assert_rejected(
        &process::load(&current_baseline, /*generation*/ 10),
        "Unavailable",
    );
    assert_eq!(std::fs::read(&journal_path).unwrap(), journal_bytes);
}

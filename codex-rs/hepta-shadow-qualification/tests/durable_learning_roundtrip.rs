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

#[expect(
    clippy::unwrap_used,
    reason = "fixture identifiers are deterministic literals and should fail at their construction site"
)]
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

#[expect(
    clippy::unwrap_used,
    reason = "fixture files are required preconditions and collisions must fail the test immediately"
)]
fn create(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap()
}

#[expect(
    clippy::unwrap_used,
    reason = "fixture files were created earlier in the same test and missing files must fail immediately"
)]
fn open_readonly(path: &Path) -> File {
    File::open(path).unwrap()
}

/// A bounded fixture learner using ONLY reopened training records. This is not
/// OPE, NDU training or a general cross-fit/statistical acceptance algorithm.
#[expect(
    clippy::unwrap_used,
    reason = "the fixture asserts complete decisions and a non-empty balanced score set before selection"
)]
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
            let action = decisions.get(&outcome.episode_id).unwrap();
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
    scores
        .iter()
        .max_by_key(|(_, score)| score.0)
        .unwrap()
        .0
        .as_str()
        .as_bytes()
        .to_vec()
}

/// Independent code path and disjoint held-out fixture. No training store or
/// generator-provided outcome enters this oracle; identity authentication is not
/// tested by a local fixture and real efficacy is not inferred from this score.
fn held_out_oracle(policy: &[u8]) -> u64 {
    [
        b"fresh".as_slice(),
        b"fresh".as_slice(),
        b"fresh".as_slice(),
    ]
    .iter()
    .map(|expected| u64::from(*expected == policy))
    .sum()
}

#[expect(
    clippy::unwrap_used,
    reason = "fixture generation and registration are deterministic setup and must fail at the first invalid invariant"
)]
fn register(
    registry: &mut ArtifactRegistry,
    name: &str,
    predecessor: Option<&str>,
    bytes: &[u8],
    dataset: Digest32,
) {
    registry
        .append(ArtifactEvent::Register {
            event_id: id(&format!("register-{name}")),
            manifest: ArtifactManifest {
                artifact_id: id(name),
                kind: ArtifactKind::Policy,
                generation: Generation::new(if predecessor.is_some() { 2 } else { 1 }).unwrap(),
                predecessor_id: predecessor.map(id),
                content_digest: Digest32::of_bytes(bytes),
                objective_digest: Digest32::of_bytes(b"read-only-retrieval-fixture"),
                support_digest: dataset,
                producer_id: id("fixture-generator"),
                compatibility_digest: Digest32::of_bytes(b"binary-policy-fixture-v1"),
                encoded_size_bytes: bytes.len() as u64,
            },
        })
        .unwrap();
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
    for (index, action) in ["stale", "fresh", "stale", "fresh"].iter().enumerate() {
        let episode = id(&format!("training-episode-{index}"));
        let decision = LedgerEvent::Decision(EpisodeDecision {
            record_id: id(&format!("decision-{index}")),
            episode_id: episode.clone(),
            objective_digest: objective,
            policy_id: id("fixture-behavior-policy"),
            candidate_ids: vec![id("abstain"), id("fresh"), id("stale")],
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
            value: if *action == "fresh" {
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
    let learned = fit_binary_fixture(&ledger);
    assert_eq!(learned, b"fresh");
    let baseline = b"stale";
    assert!(held_out_oracle(&learned) > held_out_oracle(baseline));
    assert_eq!(ledger.snapshot(), before);
    assert_eq!(std::fs::read(&journal_path).unwrap(), journal_bytes);

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

    // These are fixture-host run snapshots, not production selection receipts.
    let existing_run =
        read_candidate_payload(open_readonly(&baseline_path), &registry, &id("baseline")).unwrap();
    let next_run =
        read_candidate_payload(open_readonly(&candidate_path), &registry, &id("candidate"))
            .unwrap();
    assert_eq!(existing_run, b"stale");
    assert_eq!(next_run, b"fresh");
    assert_eq!(existing_run, baseline); // Current run is unchanged.
    let rollback =
        read_candidate_payload(open_readonly(&baseline_path), &registry, &id("baseline")).unwrap();
    assert_eq!(rollback, baseline); // Uses current registry, not an old backup.

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
    assert!(read_registry_snapshot(open_readonly(&registry_path), current_receipt).is_err());
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
}

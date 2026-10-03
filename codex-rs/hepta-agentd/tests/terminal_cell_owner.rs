#![allow(
    clippy::unwrap_used,
    reason = "integration assertions and fixture setup must fail the test immediately"
)]
#![cfg(feature = "server")]

use codex_hepta_agent_components::bellman_operator::*;

use codex_hepta_agent_components::learning_artifacts as artifacts;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agent_components::types::FixedQ32;

#[path = "support/terminal_cell_owner.rs"]
mod support;
use support::Fixture;
use support::NOW;
use support::TRUST_EXPIRES_AT;
use support::digest;
use support::id;
use support::outcome;
use support::sign;

#[path = "support/terminal_cell_model.rs"]
mod model_support;
use model_support::collect;
use model_support::freeze;
use model_support::persist_reload;
use model_support::profile;

#[test]
fn real_owner_decision_outcome_freeze_fit_registry_reload_and_withdrawal() {
    let fixture = Fixture::new();
    let mut owner = fixture.writer();
    collect(&mut owner, "initial-a", "read", 0);
    collect(&mut owner, "initial-stop", "abstain", 0);
    let initial = freeze(&owner, "dataset.initial");
    let frozen = freeze_terminal_cell_from_owner_v1(&owner, &initial, profile(1), NOW).unwrap();
    assert_eq!(frozen.sample_count(), 2);
    let trained = fit_terminal_cell_from_owner_v1(&owner, frozen.clone(), NOW).unwrap();
    assert!(matches!(
        fit_terminal_cell_from_owner_v1(&owner, frozen, TRUST_EXPIRES_AT),
        Err(TerminalCellError::TrustDistribution(
            LearningTrustDistributionError::DistributionWindow
        ))
    ));
    let mut registry = artifacts::ArtifactRegistry::new();
    let first = persist_reload(&fixture.root, &mut registry, &trained, None);
    for index in 0..5 {
        collect(
            &mut owner,
            &format!("learn-{index}-a"),
            "read",
            FixedQ32::ONE.raw(),
        );
        collect(&mut owner, &format!("learn-{index}-stop"), "abstain", 0);
    }
    let next = freeze(&owner, "dataset.next");
    assert_eq!(
        freeze_terminal_cell_from_owner_v1(&owner, &initial, profile(2), NOW)
            .unwrap()
            .sample_count(),
        2,
        "new observations do not silently enter the old immutable dataset"
    );
    let pending = freeze_terminal_cell_from_owner_v1(&owner, &next, profile(2), NOW).unwrap();
    let trained_next = fit_terminal_cell_from_owner_v1(&owner, pending.clone(), NOW).unwrap();
    let second = persist_reload(
        &fixture.root,
        &mut registry,
        &trained_next,
        Some(trained.artifact_id.clone()),
    );
    let sensor = id("single-approved-state");
    let read = id("read");
    let abstain = id("abstain");
    assert_eq!(
        first.predict(&sensor, &read).unwrap().value,
        FixedQ32::ZERO,
        "loaded predecessor was not mutated"
    );
    assert!(
        second.predict(&sensor, &read).unwrap().value
            > second.predict(&sensor, &abstain).unwrap().value
    );
    assert!(
        !second
            .predict(&sensor, &read)
            .unwrap()
            .authority
            .grants_any()
    );
    // Fresh independent observer episodes, not training targets supplied by fit.
    let evaluation = Fixture::new();
    let mut evaluator = evaluation.writer();
    collect(&mut evaluator, "held-out-a", "read", FixedQ32::ONE.raw());
    collect(&mut evaluator, "held-out-stop", "abstain", 0);
    let heldout = freeze(&evaluator, "dataset.heldout");
    let target = fit_terminal_cell_from_owner_v1(
        &evaluator,
        freeze_terminal_cell_from_owner_v1(&evaluator, &heldout, profile(3), NOW).unwrap(),
        NOW,
    )
    .unwrap();
    assert!(
        target
            .cells
            .iter()
            .find(|cell| cell.action_id == read)
            .unwrap()
            .mean_target
            > target
                .cells
                .iter()
                .find(|cell| cell.action_id == abstain)
                .unwrap()
                .mean_target
    );
    let squared_error = |model: &LoadedTabularOperatorV1| -> u128 {
        target
            .cells
            .iter()
            .map(|cell| {
                let estimate = model
                    .predict(&cell.sensor_id, &cell.action_id)
                    .unwrap()
                    .value
                    .raw();
                let delta = i128::from(estimate) - i128::from(cell.mean_target.raw());
                delta.unsigned_abs().pow(2)
            })
            .sum()
    };
    assert!(
        squared_error(&second) < squared_error(&first),
        "the independently frozen held-out observations must favor the trained candidate"
    );

    // A real authenticated correction invalidates the frozen training cut.
    let mut correction = outcome(
        "correction.record",
        "correction.result",
        Some("learn-0-a.result"),
        0,
    );
    correction.episode_id = id("learn-0-a.episode");
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&correction),
    );
    let head = owner.witness_frontier().unwrap().anchor.chain_digest;
    owner
        .append_outcome(head, correction, &signed, NOW)
        .unwrap();
    assert!(fit_terminal_cell_from_owner_v1(&owner, pending, NOW).is_err());
    registry
        .append(artifacts::ArtifactEvent::Revoke(artifacts::StateChange {
            event_id: id("revoke.contaminated-parent"),
            artifact_id: trained.artifact_id,
            evaluator_id: id("independent.dataset-owner"),
            reason_digest: digest("source-withdrawal"),
        }))
        .unwrap();
    assert!(
        !registry.is_eligible(&trained_next.artifact_id),
        "withdrawal propagates through candidate lineage"
    );
}

#[test]
#[ignore = "explicit local-host history/concurrent training profile, not an SLO"]
fn durable_owner_history_and_concurrent_training_profile() {
    use std::time::Instant;
    for (agents, pairs) in [(1, 32), (1, 128), (1, 512), (4, 128)] {
        let started = Instant::now();
        let reports = std::thread::scope(|scope| {
            let jobs=(0..agents).map(|agent| scope.spawn(move || {
                let fixture=Fixture::new();let mut writer=fixture.writer_with_limit(4096);
                let mut append_latencies=Vec::new();
                for index in 0..pairs {
                    let t=Instant::now();
                    collect(&mut writer,&format!("profile-{agent}-{index}"),if index%2==0 { "read" } else { "abstain" },if index%2==0 { FixedQ32::ONE.raw() } else { 0 });
                    append_latencies.push(t.elapsed().as_micros());
                }
                let t=Instant::now();
                let data=freeze(&writer,&format!("profile.dataset.{agent}"));
                let frozen=freeze_terminal_cell_from_owner_v1(&writer,&data,profile(1),NOW).unwrap();
                let trained=fit_terminal_cell_from_owner_v1(&writer,frozen,NOW).unwrap();
                let mut registry=artifacts::ArtifactRegistry::new();
                let loaded=persist_reload(&fixture.root,&mut registry,&trained,None);
                assert!(loaded.predict(&id("single-approved-state"),&id("read")).is_ok());
                let fit_and_reload_us=t.elapsed().as_micros();
                let cut=writer.witness_frontier().unwrap();drop(writer);
                let bytes=std::fs::metadata(fixture.root.join("ledger")).unwrap().len();
                let t=Instant::now();let recovered=fixture.recover_writer(4096,cut);let recovery_us=t.elapsed().as_micros();
                assert_eq!(recovered.witness_frontier().unwrap().anchor.sequence, (pairs*2) as u64);
                let t=Instant::now();assert_eq!(recovered.read_dataset_records(&data,NOW).unwrap().len(),pairs*2);let page_us=t.elapsed().as_micros();
                append_latencies.sort_unstable();
                format!("OWNER_HISTORY_PROFILE agents={agents} agent={agent} records={} ledger_bytes={bytes} decision_outcome_p50_us={} p95_us={} p99_us={} fit_registry_reload_us={fit_and_reload_us} full_recovery_us={recovery_us} indexed_dataset_read_us={page_us} recovery_profile=complete_authenticated_history not_cold_compaction=true",pairs*2,append_latencies[pairs/2],append_latencies[(pairs*95/100).min(pairs-1)],append_latencies[(pairs*99/100).min(pairs-1)])
            })).collect::<Vec<_>>();
            jobs.into_iter()
                .map(|job| job.join().unwrap())
                .collect::<Vec<_>>()
        });
        for report in reports {
            println!("{report}");
        }
        println!(
            "OWNER_HISTORY_GROUP agents={agents} records_per_owner={} elapsed_ms={}",
            pairs * 2,
            started.elapsed().as_millis()
        );
    }
}

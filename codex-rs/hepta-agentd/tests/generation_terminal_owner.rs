//! Real old generation records through the existing causal learning owners.
//! This fixture does not re-train the Python model, certify production trust,
//! or turn previously observed holdout rows into new scientific samples.

use std::fs::File;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_bellman_operator::*;
use codex_hepta_learning_artifacts as artifacts;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;

#[path = "support/generation_terminal_fixture.rs"]
mod support;
use support::Fixture;
use support::LocalTrust;
use support::digest;
use support::id;

#[test]
fn binary64_terminal_q32_rounds_half_grid_and_neighbors_consistently() {
    let half_grid = 3.0 * 2_f64.powi(/*n*/ -33);
    for (value, expected) in [
        (half_grid, 2),
        (-half_grid, -2),
        (5.0 * 2_f64.powi(/*n*/ -33), 2),
        (-5.0 * 2_f64.powi(/*n*/ -33), -2),
        (1.0, 1_i64 << 32),
        (-1.0, -(1_i64 << 32)),
        (0.0, 0),
        (f64::from_bits(half_grid.to_bits() - 1), 1),
        (f64::from_bits(half_grid.to_bits() + 1), 2),
    ] {
        assert_eq!((value * 4294967296.0).round_ties_even() as i64, expected);
    }
}

#[test]
#[ignore = "requires an explicitly pinned completed-run engineering fixture"]
fn real_generation_records_admit_freeze_fit_persist_reload_through_existing_owners() -> Result<()> {
    let fixture_path = PathBuf::from(
        std::env::var_os("HEPTA_TERMINAL_OWNER_FIXTURE")
            .context("prepare terminal_fixture.py first")?,
    );
    let expected: Digest32 = std::env::var("HEPTA_TERMINAL_OWNER_FIXTURE_SHA256")?.parse()?;
    let fixture = Fixture::load(&fixture_path, expected)?;
    let importer_path = std::env::current_exe()?;
    let importer_code = Digest32::of_bytes(&std::fs::read(&importer_path)?);
    let directory = tempfile::Builder::new()
        .prefix("terminal-owner-evidence-")
        .tempdir_in(fixture_path.parent().context("fixture parent")?)?
        .keep();
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let objective: Digest32 = fixture.objective_sha256.parse()?;
    let state: Digest32 = fixture.state_sha256.parse()?;
    let units: Digest32 = fixture.metric_sha256.parse()?;
    let binding = digest(&format!(
        "hepta.local-research-terminal-owner.v1:{expected}"
    ));
    let trust = LocalTrust::new(objective, binding, now)?;
    let mut owner = trust.writer(&directory, binding)?;
    let actions = fixture
        .policy_ids
        .iter()
        .map(|p| id(p))
        .collect::<Result<Vec<_>>>()?;
    // The native import grammar reserves abstain. Only the seven original
    // forced executions have outcomes; abstain is neither evaluated nor fit.
    let mut candidates = actions.clone();
    candidates.push(id("abstain")?);
    candidates.sort();
    let grammar = digest(
        &candidates
            .iter()
            .map(codex_hepta_types::StableId::as_str)
            .collect::<Vec<_>>()
            .join("\n"),
    );
    let mut imported = Vec::new();
    let mut last_decision = None;
    let mut last_outcome = None;

    for record in &fixture.records {
        let prefix = format!("old-v6:{}", record.policy);
        let support: Digest32 = record.row_receipt_sha256.parse()?;
        let request = ProductionDecisionV2 {
            record_id: id(&format!("{prefix}:decision"))?,
            episode_id: id(&format!("{prefix}:episode"))?,
            run_snapshot_digest: state,
            objective_digest: objective,
            policy_digest: digest(&format!("forced-old-execution:{}:{support}", record.policy)),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id(&record.policy)?,
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id(&format!("{prefix}:complete-macro-policies"))?,
                state_digest: state,
                generator_id: trust.principal(/*index*/ 0).principal_id,
                generator_code_digest: importer_code,
                grammar_digest: grammar,
                hard_filter_digest: digest(
                    "local-old-v6:seven-recorded-macro-policies-plus-reserved-abstain",
                ),
                truncation_digest: digest("local-old-v6:no-omitted-macro-policy"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 8,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: support,
        };
        let predecessor = owner.witness_frontier()?.anchor.chain_digest;
        let evidence = trust.sign(
            owner.verifier(),
            /*index*/ 0,
            &decision_signing_payload_v2(&request)?,
        )?;
        let decision = owner.append_decision(predecessor, request.clone(), &evidence, now)?;
        let observed = AuthenticatedOutcomeV1 {
            record_id: id(&format!("{prefix}:observed-record"))?,
            outcome_id: id(&format!("{prefix}:observed-outcome"))?,
            episode_id: request.episode_id.clone(),
            observer: trust.principal(/*index*/ 1),
            // These timestamps describe current verification/import of old
            // evidence. They are never backdated as original execution times.
            observed_at: Some(now),
            value: Some(FixedQ32::from_raw(record.value_q32)),
            unit_profile_digest: units,
            support_digest: support,
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: now,
                expected_delay_profile_digest: digest("local-read-of-already-completed-evidence"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(now),
            },
        };
        let evidence = trust.sign(
            owner.verifier(),
            /*index*/ 1,
            &outcome_signing_payload_v2(&observed),
        )?;
        let outcome =
            owner.append_outcome(decision.chain_digest, observed.clone(), &evidence, now)?;
        imported.push(serde_json::json!({
            "action": record.policy, "source_row_receipt": record.row_receipt_sha256,
            "value_q32": record.value_q32, "decision_chain": decision.chain_digest.to_string(),
            "outcome_chain": outcome.chain_digest.to_string(),
        }));
        last_decision = Some(request);
        last_outcome = Some(observed);
    }
    assert_eq!(owner.witness_frontier()?.anchor.sequence, 14);
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("local-old-v6:fixed-group-dataset")?,
        objective_digest: objective,
        inclusion_policy_digest: digest(
            "all-14-current-authenticated-records-of-fixed-seven-policy-group",
        ),
    };
    let evidence = trust.sign(
        owner.verifier(),
        /*index*/ 2,
        &dataset_freeze_signing_payload_v2(&owner.snapshot()?, &plan)?,
    )?;
    let dataset = owner.freeze_dataset(plan, &evidence, now)?;
    assert_eq!(dataset.snapshot.source_record_digests.len(), 14);
    assert_eq!(owner.read_dataset_records(&dataset, now)?.len(), 14);
    let profile = TerminalCellProfileV1 {
        artifact_id: id("local-old-v6:terminal-cell-model")?,
        producer_id: id("owner:learning.operator:local-research")?,
        generation: Generation::new(/*value*/ 1)?,
        sensor_id: id("old-v6:one-public-input-model-budget")?,
        objective_digest: objective,
        run_snapshot_digest: state,
        unit_profile_digest: units,
        action_ids: actions,
        minimum_samples_per_action: 1,
    };
    let supported = TerminalSupportedCellProfileV1 {
        cells: profile.clone(),
        candidate_ids: candidates.clone(),
    };
    let frozen = freeze_supported_terminal_cells_from_owner_v1(&owner, &dataset, supported, now)?;
    assert_eq!(frozen.sample_count(), 7);
    let trained = fit_terminal_cell_from_owner_v1(&owner, frozen.clone(), now)?;
    assert_eq!(trained.cells.len(), 7);
    assert!(!trained.authority.grants_any());
    for (cell, record) in trained.cells.iter().zip(&fixture.records) {
        assert_eq!(cell.action_id.as_str(), record.policy);
        assert_eq!(cell.sample_count, 1);
        assert_eq!(cell.mean_target, FixedQ32::from_raw(record.value_q32));
        assert_eq!(cell.minimum_target, cell.maximum_target);
    }

    // Use the existing create-only artifact store and independently retained
    // in-memory pin, then actually execute the loaded learned predictor.
    let payload = encode_tabular_payload_v1(&trained)?;
    let manifest = artifacts::ArtifactManifest {
        artifact_id: trained.artifact_id.clone(),
        kind: artifacts::ArtifactKind::Policy,
        generation: trained.generation,
        predecessor_id: None,
        content_digest: Digest32::of_bytes(&payload),
        objective_digest: objective,
        support_digest: dataset.snapshot.dataset_digest,
        producer_id: trained.producer_id.clone(),
        compatibility_digest: trained.training_profile_digest,
        encoded_size_bytes: payload.len() as u64,
    };
    let mut registry = artifacts::ArtifactRegistry::new();
    registry.append(artifacts::ArtifactEvent::Register {
        event_id: id("local-old-v6:artifact-register")?,
        manifest: manifest.clone(),
    })?;
    let payload_path = directory.join("candidate.bin");
    let registry_path = directory.join("artifact-registry.bin");
    artifacts::write_candidate_payload(
        artifacts::CreateOnlyArtifactFile::create(&payload_path)?,
        &registry,
        &manifest.artifact_id,
        &payload,
    )?;
    let registry_receipt = artifacts::write_registry_snapshot(
        artifacts::CreateOnlyArtifactFile::create(&registry_path)?,
        &registry,
        binding,
    )?;
    let pinned = artifacts::load_pinned_candidate(
        File::open(&registry_path)?,
        File::open(&payload_path)?,
        artifacts::PinnedCandidateSpec {
            registry_receipt,
            manifest,
        },
    )?;
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&payload),
        artifact_digest: trained.artifact_digest,
        objective_digest: objective,
        dataset_digest: trained.dataset_digest,
        sensor_core_digest: trained.sensor_core_digest,
        training_profile_digest: trained.training_profile_digest,
        generation: trained.generation,
    };
    let loaded = LoadedTabularOperatorV1::from_pinned_payload(pinned.bytes(), &pin)?;
    for record in &fixture.records {
        let predicted = loaded.predict(&profile.sensor_id, &id(&record.policy)?)?;
        assert_eq!(predicted.value.raw(), record.value_q32);
        assert!(predicted.learned && predicted.synthetic && !predicted.authority.grants_any());
    }
    assert!(loaded.predict(&profile.sensor_id, &id("abstain")?).is_err());

    // Meaningful fail-closed checks leave the factual imported ledger intact.
    let head = owner.witness_frontier()?;
    let mut wrong_units = profile.clone();
    wrong_units.unit_profile_digest = digest("not-the-registered-metric");
    assert!(
        freeze_supported_terminal_cells_from_owner_v1(
            &owner,
            &dataset,
            TerminalSupportedCellProfileV1 {
                cells: wrong_units,
                candidate_ids: candidates.clone()
            },
            now
        )
        .is_err()
    );
    let mut missing_action = profile;
    missing_action.action_ids.pop();
    assert!(
        freeze_supported_terminal_cells_from_owner_v1(
            &owner,
            &dataset,
            TerminalSupportedCellProfileV1 {
                cells: missing_action,
                candidate_ids: candidates
            },
            now
        )
        .is_err()
    );
    let mut tampered = fixture.records[0].clone();
    tampered.png[0] ^= 1;
    assert!(fixture.verify_record(&tampered).is_err());
    let observed = last_outcome.context("observed outcome")?;
    let wrong_role = trust.sign(
        owner.verifier(),
        /*index*/ 0,
        &outcome_signing_payload_v2(&observed),
    )?;
    assert!(
        owner
            .append_outcome(head.anchor.chain_digest, observed, &wrong_role, now)
            .is_err()
    );
    let mut changed = last_decision.context("decision")?;
    changed.support_digest = digest("changed-source-with-reused-decision-id");
    let changed_signature = trust.sign(
        owner.verifier(),
        /*index*/ 0,
        &decision_signing_payload_v2(&changed)?,
    )?;
    assert!(
        owner
            .append_decision(head.anchor.chain_digest, changed, &changed_signature, now)
            .is_err()
    );
    assert_eq!(owner.witness_frontier()?, head);
    let owner_snapshot = owner.snapshot()?;
    let trust_digest = owner.verifier().trust_digest();
    let distribution_digest = owner.trust_distribution_digest();
    drop(owner);
    let open = |name: &str| -> Result<File> {
        Ok(File::options()
            .read(true)
            .write(true)
            .open(directory.join(name))?)
    };
    let restored_ledger = DurableLedger::recover(
        open("ledger.bin")?,
        binding,
        /*max_records*/ 64,
        LedgerRecovery::Acknowledged(head.anchor),
    )?;
    let restored_witness = LedgerWitnessStore::recover(open("witness.bin")?, binding)?;
    let containing = File::open(&directory)?;
    let restored = LedgerWriter::from_durable(
        restored_ledger,
        restored_witness,
        trust.activated()?,
        &containing,
        &containing,
    )?;
    assert_eq!(restored.witness_frontier()?, head);
    assert_eq!(restored.snapshot()?, owner_snapshot);
    assert_eq!(
        fit_terminal_cell_from_owner_v1(&restored, frozen, now)?,
        trained
    );
    fixture.verify_sources()?;
    assert_eq!(
        Digest32::of_bytes(&std::fs::read(importer_path)?),
        importer_code
    );
    let report = serde_json::json!({
        "schema": "hepta.ndu-v6.local-terminal-owner-evidence.v1", "state": "completed",
        "scope": fixture.scope, "source_usage": fixture.source_usage, "source_commit": fixture.source_commit,
        "fixture_sha256": expected.to_string(), "source_pins": fixture.source_pins,
        "owner_import_executable_sha256": importer_code.to_string(),
        "import_macro_grammar": "seven actually forced original policies plus reserved, unobserved abstain",
        "admitted_candidate_count": 8, "fitted_action_count": 7,
        "unobserved_abstain_prediction": "unsupported; no fabricated eighth outcome",
        "import_verified_at_unix_seconds": now, "behavior": fixture.behavior,
        "state_sha256": state.to_string(), "objective_sha256": objective.to_string(),
        "metric_sha256": units.to_string(), "trust_digest": trust_digest.to_string(),
        "trust_distribution_digest": distribution_digest.to_string(),
        "trust_description": "Explicit local root and deterministic fixture keys; distinct role/controller identities only; not production authentication",
        "ledger_records": 14, "observed_terminal_samples": 7, "cells": 7,
        "dataset_digest": dataset.snapshot.dataset_digest.to_string(),
        "source_record_digests": dataset.snapshot.source_record_digests.iter().map(ToString::to_string).collect::<Vec<_>>(),
        "artifact_digest": trained.artifact_digest.to_string(), "payload_digest": pin.payload_digest.to_string(),
        "ledger_head": head.anchor.chain_digest.to_string(), "records": imported,
        "persisted_and_reloaded_predictor": true, "recovered_owner_fit_identical": true,
        "altered_raw_bytes_rejected": true, "wrong_unit_rejected": true, "incomplete_actions_rejected": true,
        "wrong_signer_role_rejected": true, "conflicting_record_identity_rejected": true,
        "source_files_unchanged": true, "python_gradient_training": false,
        "new_scientific_samples": 0, "production_authenticated": false, "authority": "deny_all",
    });
    let evidence_path = directory.join("evidence.json");
    std::fs::write(&evidence_path, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "TERMINAL_OWNER_EVIDENCE path={} sha256={}",
        evidence_path.display(),
        Digest32::of_bytes(&std::fs::read(&evidence_path)?)
    );
    Ok(())
}

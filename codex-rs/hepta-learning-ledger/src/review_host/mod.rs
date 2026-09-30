//! Local calibration review through production ledger admission.
//! Same-controller diagnostics refuse outcome admission. A separate fixed
//! custody evaluator runs its own measurements and signs only those outcomes.
//! Neither path issues qualification, selector approvals or activation leases.

mod events;
mod execution_service;
mod files;
mod generator_wire;
mod independent;
mod independent_trust;
mod native_generator;
mod observations;
mod trust;

use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use self::events::EventBindings;
use self::events::ExecutedPolicy;
use self::events::decision;
use self::events::outcome;
use self::files::Access;
use self::files::ReviewResult;
use self::files::create_private;
use self::files::mutable_file;
use self::files::read_root;
use self::files::root_directory;
use self::observations::ModelExecutionFile;
use self::observations::PinnedModel;
use self::observations::load_calibration;
use self::trust::LocalAuditTrust;
use crate::DatasetFreezePlanV2;
use crate::DurableLedger;
use crate::LearningEvidenceRoleV1;
use crate::LedgerRecovery;
use crate::LedgerWitnessStore;
use crate::LedgerWriter;
use crate::ProductionLedgerError;
use crate::dataset_freeze_signing_payload_v2;
use crate::decision_signing_payload_v2;
use crate::outcome_signing_payload_v2;

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum Operation {
    Initialize,
    Review,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    operation: Operation,
    trust_config_path: PathBuf,
    ledger_directory: PathBuf,
    witness_directory: PathBuf,
    calibration_pairs_path: PathBuf,
    calibration_pairs_digest: String,
    source_mapping_path: PathBuf,
    native_inputs_path: PathBuf,
    candidate_manifest_path: PathBuf,
    candidate_weights_path: PathBuf,
    candidate_observations_path: PathBuf,
    baseline_manifest_path: PathBuf,
    baseline_weights_path: PathBuf,
    baseline_observations_path: PathBuf,
    // An actual deployed qualified descriptor, when one exists. The offline
    // majority comparison is never substituted for the live predecessor.
    predecessor_descriptor_path: Option<PathBuf>,
    receipt_path: PathBuf,
}

/// Run one bounded root-custody review. Inputs and keys must already be installed
/// under protected directories. Initialization is explicit; missing durable
/// history or acknowledgement witnesses are never silently recreated.
pub fn run_local_calibration_review(request_path: &Path) -> ReviewResult<()> {
    let request_bytes = read_root(request_path, 16 * 1024, Access::Private)?;
    let request: Request = serde_json::from_slice(&request_bytes)?;
    if request.schema != "hepta.local-calibration-review-request.v1" {
        return Err("review request schema mismatch".into());
    }
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?;
    let trust = LocalAuditTrust::open(&request.trust_config_path, now)?;
    let ledger_directory = root_directory(&request.ledger_directory)?;
    let witness_directory = root_directory(&request.witness_directory)?;
    let ledger_path = request.ledger_directory.join("causal-ledger.bin");
    let witness_path = request.witness_directory.join("acknowledged-frontier.bin");
    let binding = Digest32::of_bytes(
        &[
            b"hepta.local-calibration-ledger.v1".as_slice(),
            trust.config_digest.as_array(),
            trust.objective.as_array(),
        ]
        .concat(),
    );
    if let Operation::Initialize = request.operation {
        if ledger_path.exists() || witness_path.exists() {
            return Err("review ledger installation already or partially exists".into());
        }
        let ledger = DurableLedger::create(create_private(&ledger_path, &[])?, binding, 4096)?;
        let witness = LedgerWitnessStore::create(create_private(&witness_path, &[])?, binding)?;
        let writer = LedgerWriter::from_durable(
            ledger,
            witness,
            trust.activated,
            &ledger_directory,
            &witness_directory,
        )?;
        println!(
            "{}",
            serde_json::json!({"schema":"hepta.local-calibration-review-initialization.v1", "ledger_head":writer.snapshot()?.head_digest.to_string(), "trust_distribution_digest":writer.trust_distribution_digest().to_string(), "qualified":false, "authority_grants_any":false})
        );
        return Ok(());
    }
    let predecessor_before = request
        .predecessor_descriptor_path
        .as_ref()
        .map(|path| {
            read_root(path, 64 * 1024, Access::Immutable).map(|bytes| Digest32::of_bytes(&bytes))
        })
        .transpose()?;
    let candidate_model = PinnedModel::open(
        &request.candidate_manifest_path,
        &request.candidate_weights_path,
    )?;
    let baseline_model = PinnedModel::open(
        &request.baseline_manifest_path,
        &request.baseline_weights_path,
    )?;
    let (calibration_digest, executions) = load_calibration(
        &request.calibration_pairs_path,
        &request.source_mapping_path,
        &request.native_inputs_path,
        ModelExecutionFile {
            model: &candidate_model,
            path: &request.candidate_observations_path,
        },
        ModelExecutionFile {
            model: &baseline_model,
            path: &request.baseline_observations_path,
        },
        now,
    )?;
    if calibration_digest != request.calibration_pairs_digest.parse::<Digest32>()? {
        return Err("original calibration source hash changed".into());
    }
    let mut audit_bytes = b"hepta.local-calibration-dual-execution.v1".to_vec();
    audit_bytes.extend_from_slice(trust.program_digest.as_array());
    for digest in [
        candidate_model.manifest,
        candidate_model.weights,
        baseline_model.manifest,
        baseline_model.weights,
        calibration_digest,
    ] {
        audit_bytes.extend_from_slice(digest.as_array());
    }
    for execution in &executions {
        audit_bytes.extend_from_slice(execution.candidate_support.as_array());
        audit_bytes.extend_from_slice(execution.baseline_support.as_array());
    }
    let audit_digest = Digest32::of_bytes(&audit_bytes);
    let witness = LedgerWitnessStore::recover(mutable_file(&witness_path)?, binding)?;
    let anchor = witness.frontier()?.anchor;
    let recovery = if anchor.sequence == 0 && anchor.chain_digest.is_zero() {
        LedgerRecovery::Unacknowledged
    } else {
        LedgerRecovery::Acknowledged(anchor)
    };
    let ledger = DurableLedger::recover(mutable_file(&ledger_path)?, binding, 4096, recovery)?;
    let mut writer = LedgerWriter::from_durable(
        ledger,
        witness,
        trust.activated.clone(),
        &ledger_directory,
        &witness_directory,
    )?;
    let snapshot = writer.snapshot()?;
    let ledger_before = snapshot.head_digest;
    let mut head = ledger_before;
    let mut sequence = snapshot
        .records()
        .last()
        .map_or(0, |record| record.sequence.get());
    let predecessors: BTreeMap<_, _> = snapshot
        .records()
        .iter()
        .map(|record| {
            (
                record.event.record_id().clone(),
                record.predecessor_chain_digest,
            )
        })
        .collect();
    // Retain the first real signing preparation time before any append, so an
    // exact retry can reconcile an unwitnessed event after process death.
    let signing_path = request
        .ledger_directory
        .join(format!("audit.{audit_digest}.issued.json"));
    let distribution = writer.trust_distribution_digest().to_string();
    let signing_time = if signing_path.exists() {
        let bytes = read_root(&signing_path, 1024, Access::Private)?;
        let stored: serde_json::Value = serde_json::from_slice(&bytes)?;
        let issued = stored["issued_at_ms"]
            .as_u64()
            .ok_or("signing preparation time missing")?;
        if stored["audit_digest"] != audit_digest.to_string()
            || stored["trust_distribution_digest"] != distribution
            || issued > now
        {
            return Err("stored signing preparation belongs to another audit or trust".into());
        }
        issued
    } else {
        let bytes = serde_json::to_vec(
            &serde_json::json!({"audit_digest":audit_digest.to_string(),"trust_distribution_digest":distribution,"issued_at_ms":now}),
        )?;
        create_private(&signing_path, &bytes)?;
        now
    };
    let bindings = EventBindings {
        objective: trust.objective,
        generator: trust.generator.clone(),
        observer: trust.observer.clone(),
        program_digest: trust.program_digest,
    };
    let mut rejected_outcomes = 0;
    let mut first_outcome_rejection = None;
    for (index, execution) in executions.iter().enumerate() {
        for (label, observation, selected, model, support) in [
            (
                "candidate",
                &execution.candidate,
                execution.candidate_class,
                &candidate_model,
                execution.candidate_support,
            ),
            (
                "baseline",
                &execution.baseline,
                execution.baseline_class,
                &baseline_model,
                execution.baseline_support,
            ),
        ] {
            let decision = decision(
                &bindings,
                audit_digest,
                index,
                ExecutedPolicy {
                    label,
                    observation,
                    selected,
                    model,
                    support,
                },
                execution.source_digest,
            )?;
            let signed = trust.sign(
                LearningEvidenceRoleV1::Generator,
                StableId::new(format!(
                    "calibration.generator.{audit_digest}.{label}.{index}"
                ))?,
                &decision_signing_payload_v2(&decision)?,
                signing_time,
                now,
            )?;
            let expected_predecessor = predecessors
                .get(&decision.record_id)
                .copied()
                .unwrap_or(head);
            let append =
                writer.append_decision(expected_predecessor, decision.clone(), &signed, now)?;
            if append.sequence.get() > sequence {
                sequence = append.sequence.get();
                head = append.chain_digest;
            }
            let outcome = outcome(
                &bindings,
                &decision,
                observation,
                selected == execution.gold_class,
                support,
            )?;
            let signed = trust.sign(
                LearningEvidenceRoleV1::Observer,
                StableId::new(format!(
                    "calibration.observer.{audit_digest}.{label}.{index}"
                ))?,
                &outcome_signing_payload_v2(&outcome),
                signing_time,
                now,
            )?;
            match writer.append_outcome(head, outcome, &signed, now) {
                // All local roles have the same actual machine-root controller.
                // Valid signatures cannot make these independent observations.
                Err(ProductionLedgerError::Binding("generator/observer independence")) => {
                    rejected_outcomes += 1;
                    first_outcome_rejection.get_or_insert("generator/observer independence");
                }
                Err(error) => return Err(error.into()),
                Ok(_) => {
                    return Err(
                        "local root roles unexpectedly passed independent outcome admission".into(),
                    );
                }
            }
        }
    }
    let plan = DatasetFreezePlanV2 {
        snapshot_id: StableId::new(format!("calibration.snapshot.{audit_digest}"))?,
        objective_digest: trust.objective,
        inclusion_policy_digest: Digest32::of_bytes(
            b"all-original-labeled-calibration-pairs;unjudged-excluded;native-dual-run-v1",
        ),
    };
    let freeze_rejection = match dataset_freeze_signing_payload_v2(&writer.snapshot()?, &plan) {
        Err(ProductionLedgerError::OutcomeWatermarkRequired) => "OutcomeWatermarkRequired",
        Err(error) => return Err(error.into()),
        Ok(payload) => {
            let signed = trust.sign(
                LearningEvidenceRoleV1::Evaluator,
                StableId::new(format!("calibration.evaluator.{audit_digest}"))?,
                &payload,
                now,
                now,
            )?;
            writer.freeze_dataset(plan, &signed, now)?;
            return Err("unqualified local outcomes unexpectedly produced a frozen dataset".into());
        }
    };
    let candidate_correct = executions
        .iter()
        .filter(|row| row.candidate_class == row.gold_class)
        .count();
    let baseline_correct = executions
        .iter()
        .filter(|row| row.baseline_class == row.gold_class)
        .count();
    let predecessor_after = request
        .predecessor_descriptor_path
        .as_ref()
        .map(|path| {
            read_root(path, 64 * 1024, Access::Immutable).map(|bytes| Digest32::of_bytes(&bytes))
        })
        .transpose()?;
    if predecessor_before != predecessor_after {
        return Err("the genuine predecessor descriptor changed during review".into());
    }
    if PinnedModel::open(
        &request.candidate_manifest_path,
        &request.candidate_weights_path,
    )? != candidate_model
        || PinnedModel::open(
            &request.baseline_manifest_path,
            &request.baseline_weights_path,
        )? != baseline_model
    {
        return Err("the frozen candidate or comparison baseline changed during review".into());
    }
    let frontier = writer.witness_frontier()?;
    let receipt = serde_json::json!({
        "schema":"hepta.local-calibration-review-rejection.v1", "audit_digest":audit_digest.to_string(),
        "request_digest":Digest32::of_bytes(&request_bytes).to_string(), "scope":"SciFact SUPPORT versus CONTRADICT; original training calibration only",
        "candidate_manifest_digest":candidate_model.manifest.to_string(), "candidate_weights_digest":candidate_model.weights.to_string(),
        "offline_baseline_manifest_digest":baseline_model.manifest.to_string(), "offline_baseline_weights_digest":baseline_model.weights.to_string(),
        "calibration_pairs_digest":calibration_digest.to_string(), "labeled_pairs":executions.len(), "candidate_correct":candidate_correct, "offline_baseline_correct":baseline_correct,
        "calibration_gate":if candidate_correct <= baseline_correct {"reject_not_better_than_frozen_baseline"} else {"requires_independent_qualification"},
        "ledger_head_before":ledger_before.to_string(), "ledger_head_after":writer.snapshot()?.head_digest.to_string(),
        "acknowledged_sequence":frontier.anchor.sequence, "acknowledged_head":frontier.anchor.chain_digest.to_string(),
        "trust_distribution_digest":writer.trust_distribution_digest().to_string(), "trust_generation":writer.trust_generation(),
        "signing_prepared_at_ms":signing_time,
        "controller_boundary":"all local signing roles are controlled by actual machine root; they are not independent",
        "rejected_outcomes":rejected_outcomes, "outcome_rejection":first_outcome_rejection, "dataset_freeze_rejection":freeze_rejection,
        "dataset_snapshot":null, "selector_acceptance":null, "holdout_consumed":false,
        "predecessor_status":if predecessor_before.is_some() {"genuine_descriptor_preserved"} else {"no_genuine_qualified_descriptor_installed"},
        "predecessor_descriptor_before":predecessor_before.map(|digest| digest.to_string()), "predecessor_descriptor_after":predecessor_after.map(|digest| digest.to_string()),
        "qualified":false, "production_activation":false, "authority_grants_any":false,
    });
    let mut receipt_bytes = serde_json::to_vec_pretty(&receipt)?;
    receipt_bytes.push(b'\n');
    if request.receipt_path.exists() {
        let existing_bytes = read_root(&request.receipt_path, 16 * 1024, Access::Private)?;
        let mut existing: serde_json::Value = serde_json::from_slice(&existing_bytes)?;
        let original = existing.clone();
        existing["ledger_head_before"] = receipt["ledger_head_before"].clone();
        if existing != receipt {
            return Err(
                "existing review receipt does not match this exact acknowledged review".into(),
            );
        }
        println!("{}", serde_json::to_string(&original)?);
        return Ok(());
    }
    create_private(&request.receipt_path, &receipt_bytes)?;
    println!("{}", serde_json::to_string(&receipt)?);
    Ok(())
}

pub fn run_native_generator(request: &Path) -> ReviewResult<()> {
    native_generator::run(request)
}
pub fn initialize_native_generator_key(path: &Path, uid: u32) -> ReviewResult<()> {
    native_generator::initialize_key(path, uid)
}
pub fn run_fixed_custody_evaluator(request: &Path) -> ReviewResult<()> {
    independent::run(request)
}

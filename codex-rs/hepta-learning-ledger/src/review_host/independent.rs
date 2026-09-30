//! Genuine controller-separated calibration: user Generator, fixed root custody Eval.
//! These are offline executions, never canonical inference.control qualification.
use super::events::EventBindings;
use super::events::ExecutedPolicy;
use super::events::decision;
use super::events::outcome;
use super::execution_service;
use super::files::Access;
use super::files::ReviewResult;
use super::files::create_private;
use super::files::mutable_file;
use super::files::read_root;
use super::files::root_directory;
use super::generator_wire::GeneratorBatch;
use super::generator_wire::GeneratorContract;
use super::generator_wire::PrincipalWire;
use super::generator_wire::generator_evidence;
use super::generator_wire::now_ms;
use super::independent_trust::IndependentTrust;
use super::observations::ModelExecutionFile;
use super::observations::NativeObservation;
use super::observations::PinnedModel;
use super::observations::load_calibration;
use super::observations::validate_observation;
use crate::DatasetFreezePlanV2;
use crate::DurableLedger;
use crate::LearningEvidenceRoleV1;
use crate::LedgerRecovery;
use crate::LedgerWitnessStore;
use crate::LedgerWriter;
use crate::dataset_freeze_signing_payload_v2;
use crate::decision_signing_payload_v2;
use crate::outcome_signing_payload_v2;
use crate::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    operation: String,
    trust_config_path: PathBuf,
    ledger_directory: PathBuf,
    witness_directory: PathBuf,
    work_directory: PathBuf,
    public_contract_path: PathBuf,
    generator_private_key_path: PathBuf,
    calibration_pairs_path: PathBuf,
    calibration_pairs_digest: String,
    source_mapping_path: PathBuf,
    native_inputs_path: PathBuf,
    candidate_manifest_path: PathBuf,
    candidate_weights_path: PathBuf,
    baseline_manifest_path: PathBuf,
    baseline_weights_path: PathBuf,
    predecessor_descriptor_path: Option<PathBuf>,
    receipt_path: PathBuf,
}
pub(super) fn run(path: &Path) -> ReviewResult<()> {
    let request_bytes = read_root(path, 32 * 1024, Access::Private)?;
    let request: Request = serde_json::from_slice(&request_bytes)?;
    if request.schema != "hepta.fixed-custody-calibration-request.v1"
        || !["initialize", "review"].contains(&request.operation.as_str())
    {
        return Err("fixed custody request schema/operation".into());
    }
    let now = now_ms()?;
    let trust = IndependentTrust::open(&request.trust_config_path, now)?;
    let ledger_directory = root_directory(&request.ledger_directory)?;
    let witness_directory = root_directory(&request.witness_directory)?;
    root_directory(&request.work_directory)?;
    let ledger_path = request.ledger_directory.join("causal-ledger.bin");
    let witness_path = request.witness_directory.join("acknowledged-frontier.bin");
    let binding = Digest32::of_bytes(
        &[
            b"hepta.fixed-custody-calibration-ledger.v1".as_slice(),
            trust.config_digest.as_array(),
            trust.objective.as_array(),
        ]
        .concat(),
    );
    if request.operation == "initialize" {
        if ledger_path.exists() || witness_path.exists() {
            return Err("custody ledger already or partially exists; no history reset".into());
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
            serde_json::json!({"schema":"hepta.fixed-custody-initialization.v1","ledger_head":writer.snapshot()?.head_digest.to_string(),"qualified":false})
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
    let candidate = PinnedModel::open(
        &request.candidate_manifest_path,
        &request.candidate_weights_path,
    )?;
    let baseline = PinnedModel::open(
        &request.baseline_manifest_path,
        &request.baseline_weights_path,
    )?;
    let source = Digest32::of_bytes(&read_root(
        &request.calibration_pairs_path,
        4 * 1024 * 1024,
        Access::Private,
    )?);
    if source != request.calibration_pairs_digest.parse::<Digest32>()? {
        return Err("original calibration custody changed".into());
    }
    let input_digest = Digest32::of_bytes(&read_root(
        &request.native_inputs_path,
        4 * 1024 * 1024,
        Access::Immutable,
    )?);
    let mapping_digest = Digest32::of_bytes(&read_root(
        &request.source_mapping_path,
        4 * 1024 * 1024,
        Access::Immutable,
    )?);
    let audit = Digest32::of_bytes(
        &[
            b"hepta.fixed-custody-calibration-cycle.v1".as_slice(),
            Digest32::of_bytes(&request_bytes).as_array(),
            trust.config_digest.as_array(),
            trust.evaluator_program.as_array(),
            candidate.manifest.as_array(),
            baseline.manifest.as_array(),
            source.as_array(),
            input_digest.as_array(),
            mapping_digest.as_array(),
        ]
        .concat(),
    );
    let contract = GeneratorContract {
        schema: "hepta.native-generator-contract.v1".to_owned(),
        uid: trust.config.generator_uid,
        principal: PrincipalWire::from_principal(&trust.generator),
        objective_digest: trust.objective.to_string(),
        trust_digest: trust.activated.verifier().trust_digest().to_string(),
        audit_digest: audit.to_string(),
        generator_program_digest: trust.generator_program.to_string(),
        scorer_path: trust.config.scorer_path.clone(),
        scorer_digest: trust.config.scorer_digest.clone(),
        candidate_manifest_path: request.candidate_manifest_path.clone(),
        candidate_weights_path: request.candidate_weights_path.clone(),
        baseline_manifest_path: request.baseline_manifest_path.clone(),
        baseline_weights_path: request.baseline_weights_path.clone(),
        mapping_path: request.source_mapping_path.clone(),
        inputs_path: request.native_inputs_path.clone(),
        private_key_path: request.generator_private_key_path.clone(),
        inaccessible_paths: vec![
            trust.config.root_key_path.clone(),
            trust.config.observer_key_path.clone(),
            trust.config.evaluator_key_path.clone(),
            request.calibration_pairs_path.clone(),
        ],
    };
    let contract_bytes = serde_json::to_vec(&contract)?;
    if !request.public_contract_path.exists() {
        let file = create_private(&request.public_contract_path, &contract_bytes)?;
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(std::fs::Permissions::from_mode(0o444))?;
        file.sync_all()?;
    } else if read_root(&request.public_contract_path, 32 * 1024, Access::Immutable)?
        != contract_bytes
    {
        return Err("immutable generator contract changed".into());
    }
    let generator_output = request.work_directory.join("generator-decisions.json");
    execution_service::generate(&trust, &request.public_contract_path, &generator_output)?;
    let batch: GeneratorBatch = serde_json::from_slice(&read_root(
        &generator_output,
        4 * 1024 * 1024,
        Access::Private,
    )?)?;
    if batch.schema != "hepta.native-generator-decisions.v1"
        || batch.contract_digest != Digest32::of_bytes(&contract_bytes).to_string()
        || batch.program_digest != trust.generator_program.to_string()
        || batch.uid != trust.config.generator_uid
        || !batch.no_new_privileges
        || !batch.supplementary_groups_empty
        || !batch.capabilities_zero
        || !batch.cgroup.contains("hepta-native-generator-")
        || batch.private_custody_denied != contract.inaccessible_paths.len()
        || batch.rows.is_empty()
        || batch.rows.len() > 4096
    {
        return Err("generator execution/control identity mismatch".into());
    }
    // Internally execute both fixed models. Neither observations nor signed
    // outcomes can be supplied to the evaluator by its untrusted Generator.
    let root_candidate = request.work_directory.join("candidate-evaluator.jsonl");
    let root_baseline = request.work_directory.join("baseline-evaluator.jsonl");
    execution_service::score(
        &trust,
        &request.candidate_manifest_path,
        candidate.manifest,
        &request.native_inputs_path,
        &root_candidate,
    )?;
    execution_service::score(
        &trust,
        &request.baseline_manifest_path,
        baseline.manifest,
        &request.native_inputs_path,
        &root_baseline,
    )?;
    let (_, executions) = load_calibration(
        &request.calibration_pairs_path,
        &request.source_mapping_path,
        &request.native_inputs_path,
        ModelExecutionFile {
            model: &candidate,
            path: &root_candidate,
        },
        ModelExecutionFile {
            model: &baseline,
            path: &root_baseline,
        },
        now_ms()?,
    )?;
    if batch.rows.len() != executions.len() * 2 {
        return Err("generator decisions omit or add calibration policies".into());
    }
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
    let before = snapshot.head_digest;
    let mut head = before;
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
    let bindings = EventBindings {
        objective: trust.objective,
        generator: trust.generator.clone(),
        observer: trust.observer.clone(),
        program_digest: trust.generator_program,
    };
    let signing_path = request.work_directory.join("observer-issued.json");
    let signing_time = if signing_path.exists() {
        let value: serde_json::Value =
            serde_json::from_slice(&read_root(&signing_path, 1024, Access::Private)?)?;
        if value["audit_digest"] != audit.to_string() {
            return Err("observer preparation audit mismatch".into());
        }
        value["issued_at_ms"]
            .as_u64()
            .ok_or("observer signing time")?
    } else {
        let now = now_ms()?;
        create_private(
            &signing_path,
            &serde_json::to_vec(
                &serde_json::json!({"audit_digest":audit.to_string(),"issued_at_ms":now}),
            )?,
        )?;
        now
    };
    for (position, row) in batch.rows.iter().enumerate() {
        let index = position / 2;
        let execution = &executions[index];
        let expected_label = if position % 2 == 0 {
            "candidate"
        } else {
            "baseline"
        };
        if row.index != index
            || row.policy != expected_label
            || row.observation_line.len() > 16 * 1024
            || !row.observation_line.ends_with('\n')
        {
            return Err("generator ordered decision identity/row bound".into());
        }
        let generated: NativeObservation = serde_json::from_str(&row.observation_line)?;
        let (actual, selected, model, support) = if expected_label == "candidate" {
            (
                &execution.candidate,
                execution.candidate_class,
                &candidate,
                execution.candidate_support,
            )
        } else {
            (
                &execution.baseline,
                execution.baseline_class,
                &baseline,
                execution.baseline_support,
            )
        };
        if generated.request_id != actual.request_id
            || generated.input_digest != actual.input_digest
            || generated.drive_q24 != actual.drive_q24
            || generated.prediction_q24 != actual.prediction_q24
        {
            return Err(
                "generator numeric execution differs from independently executed fixed evaluator"
                    .into(),
            );
        }
        let generated_class = validate_observation(
            &generated,
            model,
            &actual.request_id,
            actual.input_line_digest.parse()?,
            actual.input_digest.parse()?,
            now_ms()?,
        )?;
        if generated_class != selected {
            return Err("generator selected class differs from independent fixed execution".into());
        }
        let fact = decision(
            &bindings,
            audit,
            index,
            ExecutedPolicy {
                label: expected_label,
                observation: &generated,
                selected,
                model,
                support: Digest32::of_bytes(row.observation_line.as_bytes()),
            },
            execution.source_digest,
        )?;
        let evidence = generator_evidence(&contract, row, batch.issued_at_ms)?;
        let payload = decision_signing_payload_v2(&fact)?;
        trust.activated.verifier().verify(
            LearningEvidenceRoleV1::Generator,
            &evidence,
            &payload,
            now_ms()?,
        )?;
        let append = writer.append_decision(
            predecessors.get(&fact.record_id).copied().unwrap_or(head),
            fact.clone(),
            &evidence,
            now_ms()?,
        )?;
        if append.sequence.get() > sequence {
            sequence = append.sequence.get();
            head = append.chain_digest;
        }
        let observed = outcome(
            &bindings,
            &fact,
            actual,
            selected == execution.gold_class,
            support,
        )?;
        let evidence = trust.sign(
            LearningEvidenceRoleV1::Observer,
            StableId::new(format!("{}.observer", fact.record_id.as_str()))?,
            &outcome_signing_payload_v2(&observed),
            signing_time,
            now_ms()?,
        )?;
        let append = writer.append_outcome(
            predecessors
                .get(&observed.record_id)
                .copied()
                .unwrap_or(head),
            observed,
            &evidence,
            now_ms()?,
        )?;
        if append.sequence.get() > sequence {
            sequence = append.sequence.get();
            head = append.chain_digest;
        }
    }
    let plan=DatasetFreezePlanV2 {snapshot_id:StableId::new(format!("independent.calibration.snapshot.{audit}"))?,objective_digest:trust.objective,inclusion_policy_digest:Digest32::of_bytes(b"all-expert-labeled-original-calibration;both-fixed-policies;unjudged-excluded;no-public-dev-holdout")};
    let snapshot = writer.snapshot()?;
    let freeze_payload = dataset_freeze_signing_payload_v2(&snapshot, &plan)?;
    let evidence = trust.sign(
        LearningEvidenceRoleV1::Evaluator,
        StableId::new(format!("independent.calibration.freeze.{audit}"))?,
        &freeze_payload,
        signing_time,
        now_ms()?,
    )?;
    let dataset = writer.freeze_dataset(plan, &evidence, now_ms()?)?;
    verify_dataset_snapshot_receipt_against_ledger_v3(&dataset, &snapshot, now_ms()?)?;
    let predecessor_after = request
        .predecessor_descriptor_path
        .as_ref()
        .map(|path| {
            read_root(path, 64 * 1024, Access::Immutable).map(|bytes| Digest32::of_bytes(&bytes))
        })
        .transpose()?;
    if predecessor_before != predecessor_after
        || PinnedModel::open(
            &request.candidate_manifest_path,
            &request.candidate_weights_path,
        )? != candidate
        || PinnedModel::open(
            &request.baseline_manifest_path,
            &request.baseline_weights_path,
        )? != baseline
    {
        return Err("candidate, baseline or genuine predecessor changed".into());
    }
    let candidate_correct = executions
        .iter()
        .filter(|value| value.candidate_class == value.gold_class)
        .count();
    let baseline_correct = executions
        .iter()
        .filter(|value| value.baseline_class == value.gold_class)
        .count();
    let frontier = writer.witness_frontier()?;
    let receipt = serde_json::json!({"schema":"hepta.fixed-custody-calibration-refusal.v1","request_digest":Digest32::of_bytes(&request_bytes).to_string(),"audit_digest":audit.to_string(),"generator_controller":trust.generator_controller.to_string(),"evaluator_controller":trust.evaluator_controller.to_string(),"control_boundary":"fixed immutable programs, unprivileged Generator, root-private custody, no arbitrary Outcome/sign API; same provisioning administrator","generator_private_key_held_by":"generator UID owns the private key; evaluator forwards its location without reading it; privileged administrator is trusted","generator_uid":batch.uid,"generator_no_new_privileges":batch.no_new_privileges,"generator_capabilities_zero":batch.capabilities_zero,"generator_groups_empty":batch.supplementary_groups_empty,"generator_cgroup":batch.cgroup,"generator_denied_private_custody_files":batch.private_custody_denied,"observation_kind":"offline native CPU observations; not canonical inference.control receipts","labeled_pairs":executions.len(),"candidate_correct":candidate_correct,"offline_baseline_correct":baseline_correct,"calibration_gate":if candidate_correct<=baseline_correct{"reject_not_better_than_frozen_baseline"}else{"requires_independent_holdout_qualification"},"ledger_head_before":before.to_string(),"ledger_head_after":snapshot.head_digest.to_string(),"acknowledged_sequence":frontier.anchor.sequence,"acknowledged_head":frontier.anchor.chain_digest.to_string(),"dataset_snapshot_id":dataset.snapshot.snapshot_id.to_string(),"dataset_digest":dataset.snapshot.dataset_digest.to_string(),"dataset_eligible_frontier":dataset.snapshot.eligible_frontier,"dataset_outcome_watermark":dataset.snapshot.outcome_watermark,"dataset_source_record_digests":dataset.snapshot.source_record_digests.iter().map(ToString::to_string).collect::<Vec<_>>(),"dataset_correction_cut":dataset.correction_cut_digest.to_string(),"dataset_revocation_cut":dataset.revocation_cut_digest.to_string(),"dataset_inclusion_policy":dataset.inclusion_policy_digest.to_string(),"dataset_producer":dataset.producer.principal_id.to_string(),"dataset_verified_against_authoritative_ledger":true,"trust_distribution_digest":writer.trust_distribution_digest().to_string(),"predecessor_descriptor_before":predecessor_before.map(|value|value.to_string()),"predecessor_descriptor_after":predecessor_after.map(|value|value.to_string()),"predecessor_status":if predecessor_before.is_some(){"genuine_descriptor_preserved"}else{"no_genuine_qualified_descriptor_installed"},"qualified":false,"authority_grants_any":false,"production_activation":false,"selector_acceptance":null,"holdout_consumed":false});
    if request.receipt_path.exists() {
        let original: serde_json::Value = serde_json::from_slice(&read_root(
            &request.receipt_path,
            128 * 1024,
            Access::Private,
        )?)?;
        let mut comparable = original.clone();
        comparable["ledger_head_before"] = receipt["ledger_head_before"].clone();
        if comparable != receipt {
            return Err("existing refusal receipt differs from exact replay".into());
        }
        println!("{}", serde_json::to_string(&original)?);
    } else {
        create_private(&request.receipt_path, &serde_json::to_vec_pretty(&receipt)?)?;
        println!("{}", serde_json::to_string(&receipt)?);
    }
    Ok(())
}

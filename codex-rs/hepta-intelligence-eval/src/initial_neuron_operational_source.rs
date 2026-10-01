//! Authenticate the original single-policy generation-one source, without
//! interpreting a no-change comparator as evidence of primary superiority.
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::PathBuf;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::FixedCalibrationPublicationV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::decode_review_payload_hex;
use codex_hepta_learning_ledger::inspect_ledger;
use codex_hepta_learning_ledger::open_root_review_input;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use serde::Deserialize;
use serde_json::Value;

pub(super) type HostResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Source {
    pub path: PathBuf,
    pub digest: String,
}
impl Source {
    pub fn read(&self, maximum: u64) -> HostResult<Vec<u8>> {
        let bytes = read_root_review_input(&self.path, maximum)?;
        let expected: Digest32 = self.digest.parse()?;
        if expected.is_zero() || Digest32::of_bytes(&bytes) != expected {
            return Err("initial operational source pin changed".into());
        }
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Cut {
    pub publication: Source,
    pub ledger: Source,
    pub generator_batch: Source,
    pub generator_contract: Source,
    pub native_observations: [Source; 2],
    pub expected_rows: usize,
}

pub(super) struct VerifiedCut {
    pub publication: FixedCalibrationPublicationV1,
    pub trust: ActivatedLearningTrustV1,
    pub root_key: [u8; 32],
    pub source_rows: Vec<(Value, bool)>,
    pub original_resources: Vec<Value>,
    pub actors: [VerifiedLearningEvidenceV1; 3],
}

pub(super) fn inspect_cut(
    input: &Cut,
    baseline_manifest: Digest32,
    baseline_weights: Digest32,
    scope: Digest32,
    objective: Digest32,
    frozen_at: u64,
    now: u64,
) -> HostResult<VerifiedCut> {
    let publication: FixedCalibrationPublicationV1 =
        serde_json::from_slice(&input.publication.read(4 * 1024 * 1024)?)?;
    let cut = &publication.cut;
    let binding = cut.binding()?;
    if cut.schema != "hepta.signed-calibration-cut.v1"
        || binding.candidate_manifest_digest != baseline_manifest
        || binding.baseline_manifest_digest != baseline_manifest
        || binding.candidate_weights_digest != baseline_weights
        || binding.baseline_weights_digest != baseline_weights
        || publication.trust.scope_digest != scope.to_string()
        || publication.trust.objective_digest != objective.to_string()
        || !(20..=2048).contains(&input.expected_rows)
    {
        return Err(
            "initial anchor requires the exact no-change baseline and frozen source".into(),
        );
    }
    let (root, distribution) = publication.trust.native()?;
    let trust = activate_learning_trust(&root, distribution, None, now)?;
    let generator_payload = decode_review_payload_hex(&cut.generator_payload_hex)?;
    let generator_signed = cut.generator_evidence.native()?;
    let generator = trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &generator_signed,
        &generator_payload,
        now,
    )?;
    let observer_signed = publication.observer_evidence.native()?;
    let observer = trust.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        &observer_signed,
        &cut.signing_payload()?,
        now,
    )?;
    verify_signed_actor_separation(&generator, &observer, now)?;
    if generator_signed.issued_at < frozen_at || observer_signed.issued_at < frozen_at {
        return Err("initial operational policy must precede actual source execution".into());
    }
    let ledger = input.ledger.read(8 * 1024 * 1024)?;
    if Digest32::of_bytes(&ledger) != binding.ledger_file_digest {
        return Err("initial source ledger differs from its authenticated cut".into());
    }
    let snapshot = inspect_ledger(
        open_root_review_input(&input.ledger.path)?,
        binding.ledger_binding_digest,
        /*max_records*/ 4096,
        LedgerAnchor {
            sequence: binding.acknowledged_sequence,
            chain_digest: binding.acknowledged_head,
        },
    )?;
    let dataset = cut.dataset.native()?;
    verify_dataset_snapshot_receipt_against_ledger_v3(&dataset, &snapshot, now)?;
    if dataset.snapshot.dataset_digest != binding.dataset_digest
        || dataset.snapshot.pending_outcomes != 0
        || dataset.snapshot.censored_outcomes != 0
        || snapshot.head_digest != binding.acknowledged_head
    {
        return Err("initial source has incomplete authoritative outcomes".into());
    }
    let producer_signed = cut.freeze_evidence.native()?;
    let producer_payload = dataset_freeze_signing_payload_v2(
        &snapshot,
        &DatasetFreezePlanV2 {
            snapshot_id: dataset.snapshot.snapshot_id.clone(),
            objective_digest: objective,
            inclusion_policy_digest: dataset.inclusion_policy_digest,
        },
    )?;
    let producer = trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &producer_signed,
        &producer_payload,
        now,
    )?;
    let authentication = |signed: &codex_hepta_learning_ledger::SignedLearningEvidenceV1| {
        let mut bytes = signed.signing_bytes();
        bytes.extend_from_slice(&signed.signature);
        Digest32::of_bytes(&bytes)
    };
    if binding.generator_payload_digest != Digest32::of_bytes(&generator_payload)
        || binding.freeze_payload_digest != Digest32::of_bytes(&producer_payload)
        || binding.generator_authentication_digest != authentication(&generator_signed)
        || binding.freeze_authentication_digest != authentication(&producer_signed)
        || !matches!(snapshot.records().first().map(|record| &record.event),
            Some(LedgerEvent::AuthenticatedDecisionV2(decision))
                if decision.authentication_digest == authentication(&generator_signed))
    {
        return Err("initial source original authentication binding".into());
    }
    if producer.principal() != &dataset.producer {
        return Err("initial source producer is not the authoritative dataset owner".into());
    }
    verify_signed_actor_separation(&generator, &producer, now)?;
    let contract_bytes = input.generator_contract.read(32 * 1024)?;
    let contract: Value = serde_json::from_slice(&contract_bytes)?;
    let batch: Value = serde_json::from_slice(&input.generator_batch.read(8 * 1024 * 1024)?)?;
    if batch["schema"] != "hepta.native-generator-decisions.v1"
        || batch["contract_digest"] != Digest32::of_bytes(&contract_bytes).to_string()
        || batch["program_digest"] != contract["generator_program_digest"]
        || batch["uid"] != contract["uid"]
        || batch["no_new_privileges"] != true
        || batch["supplementary_groups_empty"] != true
        || batch["capabilities_zero"] != true
        || batch["issued_at_ms"]
            .as_u64()
            .is_none_or(|at| at < frozen_at || at > now)
        || contract["trust_digest"] != trust.verifier().trust_digest().to_string()
        || contract["objective_digest"] != objective.to_string()
        || contract["principal"]["principal_id"] != generator.principal().principal_id.to_string()
    {
        return Err("initial actual generator contract/process changed".into());
    }
    let mut observations = BTreeMap::new();
    let mut native_resources = Vec::new();
    for source in &input.native_observations {
        let bytes = source.read(4 * 1024 * 1024)?;
        if !bytes.ends_with(b"\n") {
            return Err("initial native source has an incomplete row".into());
        }
        let mut count = 0;
        for raw in bytes.split_inclusive(|byte| *byte == b'\n') {
            if raw.len() > 16 * 1024 || count >= input.expected_rows {
                return Err("initial native row/count bound".into());
            }
            let value: Value = serde_json::from_slice(raw)?;
            let at = value["executed_at_ms"]
                .as_u64()
                .ok_or("native source clock")?;
            if value["schema"] != "hepta.cpu-neuron.offline-observation.v1"
                || value["succeeded"] != true
                || value["terminal_observed"] != true
                || value["qualified"] != false
                || value["authority_grants_any"] != false
                || value["model_manifest_digest"] != baseline_manifest.to_string()
                || value["weights_digest"] != baseline_weights.to_string()
                || at < frozen_at
                || at > now
            {
                return Err("initial genuine numeric observation binding".into());
            }
            native_resources.push(value.clone());
            observations.insert(Digest32::of_bytes(raw), value);
            count += 1;
        }
        if count != input.expected_rows {
            return Err("initial independent native source is incomplete".into());
        }
    }
    let mut generated = BTreeMap::new();
    let rows = batch["rows"].as_array().ok_or("initial generator rows")?;
    if rows.len() != input.expected_rows * 2 {
        return Err("initial actual source must retain both no-change executions".into());
    }
    for row in rows {
        let raw = row["observation_line"]
            .as_str()
            .ok_or("original observation")?;
        if raw.len() > 16 * 1024 || !raw.ends_with('\n') {
            return Err("initial bounded native observation".into());
        }
        generated.insert(
            Digest32::of_bytes(raw.as_bytes()),
            serde_json::from_str::<Value>(raw)?,
        );
    }
    let prefix = format!("calibration.episode.{}.", binding.audit_digest);
    let mut decisions = BTreeMap::new();
    let mut source_rows = BTreeMap::new();
    let mut policies = BTreeSet::new();
    for record in snapshot.records() {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(decision) => {
                if decision.policy_digest != baseline_weights
                    || decision.generator_id != generator.principal().principal_id
                    || decision.generator_controller_id != *generator.controller_id()
                    || decision.generator_signing_key_digest
                        != generator.principal().signing_key_digest
                    || decision.objective_digest != objective
                {
                    return Err("initial generator source policy/controller changed".into());
                }
                let suffix = decision
                    .episode_id
                    .as_str()
                    .strip_prefix(&prefix)
                    .ok_or("initial episode")?;
                let (policy, index) = suffix.split_once('.').ok_or("initial episode policy")?;
                let index: usize = index.parse()?;
                if !matches!(policy, "candidate" | "baseline")
                    || index >= input.expected_rows
                    || !policies.insert((policy.to_owned(), index))
                    || decisions
                        .insert(
                            decision.episode_id.clone(),
                            (policy.to_owned(), index, decision.support_digest),
                        )
                        .is_some()
                {
                    return Err("initial duplicate or foreign source episode".into());
                }
            }
            LedgerEvent::AuthenticatedOutcomeV2(outcome) => {
                if outcome.observer_id != observer.principal().principal_id
                    || outcome.observer_controller_id != *observer.controller_id()
                    || outcome.observer_signing_key_digest
                        != observer.principal().signing_key_digest
                    || outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
                    || outcome.correction_predecessor.is_some()
                {
                    return Err("initial source outcome has no original terminal observer".into());
                }
                let (policy, index, support) = decisions
                    .remove(&outcome.episode_id)
                    .ok_or("initial outcome decision")?;
                let value = match outcome.value {
                    Some(FixedQ32::ZERO) => false,
                    Some(FixedQ32::ONE) => true,
                    _ => return Err("initial source outcome is not measured correctness".into()),
                };
                let generated = generated
                    .get(&support)
                    .ok_or("initial original generator bytes missing")?;
                let observation = observations
                    .get(&outcome.support_digest)
                    .ok_or("initial original independently measured native bytes missing")?
                    .clone();
                if [
                    "request_id",
                    "input_digest",
                    "input_line_digest",
                    "model_manifest_digest",
                    "weights_digest",
                    "drive_q24",
                    "prediction_q24",
                ]
                .iter()
                .any(|field| generated[*field] != observation[*field])
                {
                    return Err("initial source numeric generator/observer disagreement".into());
                }
                if source_rows
                    .insert((index, policy), (observation, value))
                    .is_some()
                {
                    return Err("initial duplicate outcome".into());
                }
            }
            _ => return Err("initial source contains an unrelated event".into()),
        }
    }
    if !decisions.is_empty() || source_rows.len() != input.expected_rows * 2 {
        return Err("initial source requires complete exact no-change outcomes".into());
    }
    let mut retained = Vec::new();
    for index in 0..input.expected_rows {
        let candidate = source_rows
            .remove(&(index, "candidate".into()))
            .ok_or("initial candidate")?;
        let baseline = source_rows
            .remove(&(index, "baseline".into()))
            .ok_or("initial baseline")?;
        if candidate.1 != baseline.1
            || [
                "input_digest",
                "model_manifest_digest",
                "weights_digest",
                "drive_q24",
                "prediction_q24",
            ]
            .iter()
            .any(|field| candidate.0[*field] != baseline.0[*field])
        {
            return Err("the initial no-change baseline changed its actual numeric result".into());
        }
        retained.push(candidate);
    }
    // All original inputs remain pinned after authenticated replay.
    input.publication.read(4 * 1024 * 1024)?;
    input.ledger.read(8 * 1024 * 1024)?;
    input.generator_batch.read(8 * 1024 * 1024)?;
    input.generator_contract.read(32 * 1024)?;
    for source in &input.native_observations {
        source.read(4 * 1024 * 1024)?;
    }
    Ok(VerifiedCut {
        publication,
        trust,
        root_key: root.verifying_key,
        source_rows: retained,
        original_resources: native_resources,
        actors: [generator, observer, producer],
    })
}

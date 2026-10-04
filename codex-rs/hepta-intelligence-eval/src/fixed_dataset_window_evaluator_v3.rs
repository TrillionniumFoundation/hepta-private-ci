//! Finite independent Evaluator for the original whole-ledger V3 window purpose.
//! Root must admit the actual held-owner archive and independent witness sources.
//! This purpose never opens a writer or accepts a caller-provided signing payload.
use crate::fixed_calibration_host::boundary;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use std::io::Read;
use std::io::Seek;
use std::path::Path;

type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
const MAX_CONFIG: u64 = 32 * 1024;
const MAX_INPUTS: u64 = 32 * 1024;
const MAX_WITNESS: u64 = 8 * 1024 * 1024;
pub const MAX_FIXED_DATASET_WINDOW_OUTPUT_BYTES_V3: usize = 512 * 1024;

/// Whole protected source pins come from the actual original owner and its
/// independently admitted witness, not an echo of a wrapper's head digest.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedDatasetWindowEvaluatorInputsV3 {
    pub schema: String,
    pub round: ParameterPreRegistrationRoundV1,
    pub plan: DatasetWindowFreezePlanWireV3,
    pub ledger: ParameterRoleSourceV3,
    pub witness: ParameterRoleSourceV3,
    pub ledger_binding: String,
    pub maximum_records: u32,
    pub maximum_witness_frames: u32,
    pub acknowledged_sequence: u64,
    pub acknowledged_chain_digest: String,
}
impl FixedDatasetWindowEvaluatorInputsV3 {
    fn validate(&self, now: u64) -> HostResult<DatasetWindowFreezePlanV3> {
        self.round.validate(now)?;
        let binding: Digest32 = self.ledger_binding.parse()?;
        let chain: Digest32 = self.acknowledged_chain_digest.parse()?;
        if self.schema != "hepta.fixed-dataset-window-inputs.v3"
            || binding.is_zero()
            || chain.is_zero()
            || self.acknowledged_sequence == 0
            || self.maximum_records == 0
            || self.maximum_records > 8192
            || self.maximum_witness_frames == 0
            || self.maximum_witness_frames > 8192
            || self.acknowledged_sequence > u64::from(self.maximum_records)
        {
            return Err("complete original witnessed window input identity/limits".into());
        }
        for source in [&self.ledger, &self.witness] {
            let pin: Digest32 = source.digest.parse()?;
            if !source.path.is_absolute() || pin.is_zero() || pin.to_string() != source.digest {
                return Err("actual window source pin".into());
            }
        }
        self.plan.native()
    }
}
pub fn encode_fixed_dataset_window_evaluator_inputs_v3(
    inputs: &FixedDatasetWindowEvaluatorInputsV3,
) -> HostResult<Vec<u8>> {
    inputs.validate(inputs.round.admitted_at_ms)?;
    let bytes = serde_json::to_vec(inputs)?;
    if bytes.len() > MAX_INPUTS as usize {
        return Err("whole window input bound".into());
    }
    Ok(bytes)
}

// This ID is itself signed by the original evidence codec. Preserve the
// issuer's exact existing bytes while checking the complete finite request.
fn window_evidence_id(inputs_bytes: &[u8], payload: &[u8]) -> HostResult<StableId> {
    Ok(StableId::new(format!(
        "fixed.window.{}",
        Digest32::of_bytes(&[inputs_bytes, payload].concat())
    ))?)
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Output {
    schema: String,
    inputs_digest: String,
    plan: DatasetWindowFreezePlanWireV3,
    window: DatasetWindowSnapshotWireV3,
    signing_payload_hex: String,
    evaluator_evidence: ReviewEvidenceWireV1,
}
/// Genuine signature over the sole original V3 payload, not over this wrapper.
/// Current live owner/ledger revalidation is still required at original use.
pub struct FixedDatasetWindowEvaluationV3 {
    pub plan: DatasetWindowFreezePlanV3,
    pub window: DatasetWindowSnapshotReceiptV3,
    pub signing_payload: Vec<u8>,
    pub evaluator_evidence: SignedLearningEvidenceV1,
}

fn pinned_file(source: &ParameterRoleSourceV3, maximum: u64) -> HostResult<std::fs::File> {
    let mut file = open_root_review_input(&source.path)?;
    let mut bytes = Vec::new();
    (&mut file)
        .take(maximum.checked_add(1).ok_or("window source size")?)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum || Digest32::of_bytes(&bytes) != source.digest.parse()? {
        return Err("whole window source pin on the actual inspected descriptor".into());
    }
    file.rewind()?;
    Ok(file)
}
fn snapshot(inputs: &FixedDatasetWindowEvaluatorInputsV3, now: u64) -> HostResult<LedgerSnapshot> {
    inputs.validate(now)?;
    let binding: Digest32 = inputs.ledger_binding.parse()?;
    let witness = inspect_ledger_witness_frontier(
        pinned_file(&inputs.witness, MAX_WITNESS)?,
        binding,
        inputs.maximum_witness_frames as usize,
    )?;
    if witness.segment.is_some()
        || witness.sealed
        || witness.anchor.sequence != inputs.acknowledged_sequence
        || witness.anchor.chain_digest != inputs.acknowledged_chain_digest.parse()?
    {
        return Err(
            "actual complete flat-ledger witness differs from admitted owner frontier".into(),
        );
    }
    inspect_ledger(
        pinned_file(&inputs.ledger, MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1 as u64)?,
        binding,
        inputs.maximum_records as usize,
        witness.anchor,
    )
    .map_err(Into::into)
}

/// Recompute the exact frozen purpose using the whole closed original ledger.
/// Parsing and source checks alone never substitute for the Evaluator signature.
pub fn decode_fixed_dataset_window_evaluator_output_v3(
    bytes: &[u8],
    inputs: &FixedDatasetWindowEvaluatorInputsV3,
    complete_snapshot: &LedgerSnapshot,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<FixedDatasetWindowEvaluationV3> {
    if bytes.len() > MAX_FIXED_DATASET_WINDOW_OUTPUT_BYTES_V3 {
        return Err("whole window output bound".into());
    }
    let expected_plan = inputs.validate(now)?;
    if complete_snapshot.records().len() as u64 != inputs.acknowledged_sequence
        || complete_snapshot.head_digest != inputs.acknowledged_chain_digest.parse()?
    {
        return Err("whole window frozen snapshot identity".into());
    }
    let input_bytes = encode_fixed_dataset_window_evaluator_inputs_v3(inputs)?;
    let output: Output = serde_json::from_slice(bytes)?;
    if output.schema != "hepta.fixed-dataset-window-evaluation.v3"
        || output.inputs_digest.parse::<Digest32>()? != Digest32::of_bytes(&input_bytes)
        || output.plan.native()? != expected_plan
    {
        return Err("whole original window output/request binding".into());
    }
    let payload = dataset_window_freeze_signing_payload_v3(complete_snapshot, &expected_plan)?;
    let supplied = decode_review_payload_hex(&output.signing_payload_hex)?;
    if supplied != payload {
        return Err("window signing payload must be recomputed from all original records".into());
    }
    trust.revalidate_at(now)?;
    let evidence = output.evaluator_evidence.native()?;
    if evidence.evidence_id != window_evidence_id(&input_bytes, &payload)?
        || evidence.issued_at < inputs.round.admitted_at_ms
        || evidence.expires_at > inputs.round.deadline_ms
    {
        return Err("original window signed request identity/time bounds".into());
    }
    let principal =
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &payload, now)?;
    let receipt = output.window.native()?;
    let expected = freeze_dataset_window_from_ledger_v3(
        complete_snapshot,
        expected_plan.clone(),
        principal.principal().clone(),
        now,
    )?;
    if receipt != expected {
        return Err("whole original window receipt/producer/cuts differ".into());
    }
    Ok(FixedDatasetWindowEvaluationV3 {
        plan: expected_plan,
        window: receipt,
        signing_payload: payload,
        evaluator_evidence: evidence,
    })
}

/// Only the independently enrolled no-custody E process can issue this purpose.
pub fn run_fixed_dataset_window_evaluator_v3(path: &Path) -> HostResult<()> {
    let config_bytes = read_root_review_input(path, MAX_CONFIG)?;
    let config: FixedParameterEvaluatorConfigV1 = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-dataset-window-evaluator-config.v3"
        || config.uid == 0
        || config.gid == 0
        || config.authority_epoch == 0
        || config.distribution_generation == 0
        || config.inaccessible_paths.len() != 5
    {
        return Err("original window E enrollment policy".into());
    }
    boundary(config.uid, config.gid)?;
    let program = verify_registered_operational_program_v3(
        &std::env::current_exe()?,
        config.program_digest.parse()?,
    )?;
    for denied in &config.inaccessible_paths {
        match std::fs::File::open(denied) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("window E must lack physical Gold/custody/other-key access".into()),
        }
    }
    let trust_bytes = read_root_review_input(&config.trust_path, 128 * 1024)?;
    if Digest32::of_bytes(&trust_bytes) != config.trust_digest.parse()? {
        return Err("window E whole installed trust pin".into());
    }
    let wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
    if wire.root_verifying_key_hex != config.root_verifying_key_hex
        || wire.scope_digest != config.scope_digest
        || wire.objective_digest != config.objective_digest
        || wire.generation != config.distribution_generation
        || wire.authority_epoch != config.authority_epoch
    {
        return Err("original window E training trust/distribution".into());
    }
    let (root, distribution) = wire.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("original window E absent")?
        .clone();
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        &reviewer,
        program,
        &root.verifying_key,
        config.uid,
        config.gid,
        None,
    )?;
    let mut last = now_ms()?;
    let trust = activate_learning_trust(&root, distribution, None, last)?;
    let input_bytes = read_root_review_input(&config.inputs_path, MAX_INPUTS)?;
    if Digest32::of_bytes(&input_bytes) != config.inputs_digest.parse()? {
        return Err("window E actual enrolled input pin".into());
    }
    let inputs: FixedDatasetWindowEvaluatorInputsV3 = serde_json::from_slice(&input_bytes)?;
    if encode_fixed_dataset_window_evaluator_inputs_v3(&inputs)? != input_bytes {
        return Err("canonical whole window inputs".into());
    }
    let plan = inputs.validate(last)?;
    if plan.objective_digest != config.objective_digest.parse()? {
        return Err("window objective differs from original E purpose".into());
    }
    let ledger_bytes = inputs
        .ledger
        .read(MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1 as u64)?;
    let witness_bytes = inputs.witness.read(MAX_WITNESS)?;
    let complete = snapshot(&inputs, last)?;
    let payload = dataset_window_freeze_signing_payload_v3(&complete, &plan)?;
    let mut sample = || -> HostResult<u64> {
        if read_root_review_input(path, MAX_CONFIG)? != config_bytes
            || read_root_review_input(&config.trust_path, 128 * 1024)? != trust_bytes
            || read_root_review_input(&config.inputs_path, MAX_INPUTS)? != input_bytes
            || inputs
                .ledger
                .read(MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1 as u64)?
                != ledger_bytes
            || inputs.witness.read(MAX_WITNESS)? != witness_bytes
            || verify_registered_operational_program_v3(&std::env::current_exe()?, program)?
                != program
        {
            return Err("actual window E sources changed".into());
        }
        let now = now_ms()?;
        if now < last {
            return Err("window E clock rollback".into());
        }
        last = now;
        inputs.validate(now)?;
        trust.revalidate_at(now)?;
        reviewer.principal.validate(now)?;
        Ok(now)
    };
    let signing = key(&config.private_key_path, config.uid)?;
    if signing.verifying_key().to_bytes() != reviewer.verifying_key {
        return Err("actual window E key differs from admission".into());
    }
    let issued_at = sample()?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: window_evidence_id(&input_bytes, &payload)?,
        principal_id: reviewer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: reviewer.principal.scope_digest,
        objective_digest: plan.objective_digest,
        authority_epoch: reviewer.principal.authority_epoch,
        issued_at,
        expires_at: inputs
            .round
            .deadline_ms
            .min(trust.expires_at())
            .min(reviewer.principal.expires_at),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    let now = sample()?;
    let principal =
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &payload, now)?;
    let window = freeze_dataset_window_from_ledger_v3(
        &complete,
        plan.clone(),
        principal.principal().clone(),
        now,
    )?;
    let output = serde_json::to_vec(&Output {
        schema: "hepta.fixed-dataset-window-evaluation.v3".into(),
        inputs_digest: Digest32::of_bytes(&input_bytes).to_string(),
        plan: DatasetWindowFreezePlanWireV3::from_native(&plan),
        window: DatasetWindowSnapshotWireV3::from_native(&window),
        signing_payload_hex: payload.iter().map(|b| format!("{b:02x}")).collect(),
        evaluator_evidence: ReviewEvidenceWireV1::from_native(&evidence),
    })?;
    decode_fixed_dataset_window_evaluator_output_v3(
        &output,
        &inputs,
        &complete,
        &trust,
        sample()?,
    )?;
    // Final source reread and clock closure after encoding and complete replay.
    let final_now = sample()?;
    trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence,
        &payload,
        final_now,
    )?;
    println!("{}", std::str::from_utf8(&output)?);
    Ok(())
}
#[cfg(test)]
#[path = "fixed_dataset_window_evaluator_v3_tests.rs"]
mod tests;

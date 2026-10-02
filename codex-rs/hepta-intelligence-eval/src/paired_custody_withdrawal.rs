//! Actual read-only inspection through the original independent owner program.
//! No static result, signer, writer, repair, or new withdrawal is accepted here.
use crate::PairedReviewSourcePlanV1;
use crate::PairedSupervisedPlanV1;
use crate::fixed_holdout_custody::create_private;
use crate::fixed_holdout_custody::private_directory;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use std::collections::BTreeSet;
use std::fs::File;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Config {
    pub program: Source,
    pub probe: Source,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Probe {
    schema: String,
    withdrawal_request: Source,
    current_owner: Source,
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct SourceAck {
    lineage_id: String,
    source_record_id: String,
    source_event_digest: String,
    dataset_snapshot_id: String,
    dataset_digest: String,
    artifact_id: String,
    sequence: u64,
    event_digest: String,
    chain_digest: String,
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct ArtifactAck {
    operation_id: String,
    phase: String,
    admission_digest: String,
    publication_intent_digest: String,
    registry_head: String,
    witness_digest: String,
    acknowledged_at: u64,
    state_digest: String,
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct Denial {
    artifact_id: String,
    role: String,
    gate: String,
    result: String,
    accepted: bool,
    consumer_invoked: bool,
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct Inspection {
    schema: String,
    request_digest: String,
    current_owner_digest: String,
    observed_at_ms: u64,
    current_read_digest: String,
    current_head_digest: String,
    withdrawal_head: String,
    source_ack: SourceAck,
    artifact_ack: ArtifactAck,
    delivery_denials: Vec<Denial>,
    model_weight_forgetting_claimed: bool,
}

fn nonzero(value: &str) -> HostResult<()> {
    let digest: Digest32 = value.parse()?;
    if digest.is_zero() || digest.to_string() != value {
        return Err("canonical nonzero original owner digest required".into());
    }
    Ok(())
}

/// Each task using this one withdrawal shares its real causal dependency.
/// The native cluster minimum may therefore reject the plan before CAS. A
/// single global delivery-denial result never becomes many independent trials.
pub(super) fn bind(
    config: &Config,
    contract: &Source,
    source: &PairedReviewSourcePlanV1,
) -> HostResult<ProbeBinding> {
    let declared: serde_json::Value = serde_json::from_slice(&contract.read(128 * 1024)?)?;
    let declared: Config = serde_json::from_value(declared["withdrawal"].clone())?;
    if declared.program.path != config.program.path
        || declared.program.digest != config.program.digest
        || declared.probe.path != config.probe.path
        || declared.probe.digest != config.probe.digest
    {
        return Err(
            "original G contract does not bind this actual withdrawal program/probe".into(),
        );
    }
    config.program.read(128 * 1024 * 1024)?;
    let probe: Probe = serde_json::from_slice(&config.probe.read(32 * 1024)?)?;
    if probe.schema != "hepta.cpu-neuron.dataset-withdrawal-current-probe.v1" {
        return Err("original read-only withdrawal probe schema".into());
    }
    let request_bytes = probe.withdrawal_request.read(32 * 1024)?;
    let request: serde_json::Value = serde_json::from_slice(&request_bytes)?;
    if request["schema"] != "hepta.cpu-neuron.dataset-withdrawal-request.v1" {
        return Err("original withdrawal request schema".into());
    }
    let targets = request["delivery_targets"]
        .as_array()
        .ok_or("original delivery targets")?
        .iter()
        .map(|value| -> HostResult<_> {
            Ok(StableId::new(value.as_str().ok_or("original target id")?)?)
        })
        .collect::<HostResult<BTreeSet<_>>>()?;
    if targets.is_empty()
        || targets.len() > 64
        || targets.len()
            != request["delivery_targets"]
                .as_array()
                .ok_or("original target count")?
                .len()
        || !targets.contains(&StableId::new(
            request["artifact_id"]
                .as_str()
                .ok_or("original source artifact")?,
        )?)
    {
        return Err("complete distinct bounded delivery targets include the source".into());
    }
    // This is descriptor navigation only. The invoked original program itself
    // verifies current E2, trust, history, kernel role, and CURRENT authority.
    let owner: serde_json::Value = serde_json::from_slice(&probe.current_owner.read(32 * 1024)?)?;
    let profile: Source = serde_json::from_value(owner["profile"].clone())?;
    let profile: serde_json::Value = serde_json::from_slice(&profile.read(64 * 1024)?)?;
    let program: Source = serde_json::from_value(profile["program"].clone())?;
    if program.path != config.program.path || program.digest != config.program.digest {
        return Err("current original owner profile pins a different actual program".into());
    }
    let dependency = StableId::new(format!("withdrawal.{}", probe.withdrawal_request.digest))?;
    if source.tasks.iter().any(|task| {
        source
            .source_records
            .iter()
            .find(|record| record.source_record_digest == task.source_record_digest)
            .is_none_or(|record| !record.dependency_ids.contains(&dependency))
    }) {
        return Err("all tasks reusing one withdrawal must share its original dependency".into());
    }
    Ok(ProbeBinding {
        probe,
        targets,
        lineage_id: request["lineage_id"]
            .as_str()
            .ok_or("original lineage")?
            .to_owned(),
        source_record_id: request["source_record_id"]
            .as_str()
            .ok_or("original source record")?
            .to_owned(),
        artifact_id: request["artifact_id"]
            .as_str()
            .ok_or("original source artifact")?
            .to_owned(),
    })
}

pub(super) struct ProbeBinding {
    probe: Probe,
    targets: BTreeSet<StableId>,
    lineage_id: String,
    source_record_id: String,
    artifact_id: String,
}

pub(super) fn require_independent_clusters(plan: &PairedSupervisedPlanV1) -> HostResult<()> {
    let clusters = plan
        .tasks
        .keys()
        .map(|digest| {
            plan.source
                .record(*digest)
                .map(|record| record.cluster.clone())
        })
        .collect::<Result<BTreeSet<_>, _>>()?;
    if clusters.len() < plan.policy.minimum_independent_clusters {
        return Err(
            "original paired source has insufficient independent clusters; holdout remains unused"
                .into(),
        );
    }
    Ok(())
}

fn parse(
    bytes: &[u8],
    binding: &ProbeBinding,
    started_ms: u64,
    finished_ms: u64,
) -> HostResult<Inspection> {
    if bytes.len() > 128 * 1024 || !bytes.ends_with(b"\n") || finished_ms < started_ms {
        return Err("bounded complete current inspection and original clock".into());
    }
    let value: Inspection = serde_json::from_slice(bytes)?;
    if value.schema != "hepta.cpu-neuron.dataset-withdrawal-inspection.v1"
        || value.request_digest != binding.probe.withdrawal_request.digest
        || value.current_owner_digest != binding.probe.current_owner.digest
        || !(started_ms..=finished_ms).contains(&value.observed_at_ms)
        || value.model_weight_forgetting_claimed
        || value.source_ack.sequence == 0
        || value.artifact_ack.phase != "Acknowledged"
        || value.artifact_ack.acknowledged_at == 0
        || value.artifact_ack.acknowledged_at > value.observed_at_ms
        || value.source_ack.lineage_id != value.artifact_ack.operation_id
        || value.source_ack.lineage_id != binding.lineage_id
        || value.source_ack.source_record_id != binding.source_record_id
        || value.source_ack.artifact_id != binding.artifact_id
    {
        return Err("original current inspection identity, clock, or acknowledged facts".into());
    }
    for pin in [
        &value.current_read_digest,
        &value.current_head_digest,
        &value.withdrawal_head,
        &value.source_ack.source_event_digest,
        &value.source_ack.dataset_digest,
        &value.source_ack.event_digest,
        &value.source_ack.chain_digest,
        &value.artifact_ack.admission_digest,
        &value.artifact_ack.publication_intent_digest,
        &value.artifact_ack.registry_head,
        &value.artifact_ack.witness_digest,
        &value.artifact_ack.state_digest,
    ] {
        nonzero(pin)?;
    }
    for id in [
        &value.source_ack.lineage_id,
        &value.source_ack.source_record_id,
        &value.source_ack.dataset_snapshot_id,
        &value.source_ack.artifact_id,
    ] {
        StableId::new(id)?;
    }
    let mut targets = BTreeSet::new();
    let mut acknowledged_target = false;
    for denial in &value.delivery_denials {
        let id = StableId::new(&denial.artifact_id)?;
        if !targets.insert(id)
            || !["source", "descendant"].contains(&denial.role.as_str())
            || denial.gate != "RevalidatingCandidate::with_current"
            || denial.result != "Ineligible"
            || denial.accepted
            || denial.consumer_invoked
        {
            return Err("current original consumer did not deny every declared target".into());
        }
        // The Ledger source ACK may name any genuine dataset member,
        // including a registered descendant. Native Artifact lineage decides
        // its role; the caller cannot reinterpret it as a Genesis artifact.
        acknowledged_target |= denial.artifact_id == value.source_ack.artifact_id;
    }
    if targets != binding.targets || !acknowledged_target {
        return Err("current inspection omitted source or descendant targets".into());
    }
    Ok(value)
}

/// Run the pinned ordinary owner CLI and physically join the read-only child.
/// Existing output is history, never a substitute for a fresh current read.
pub(super) fn inspect(
    config: &Config,
    binding: &ProbeBinding,
    directory: &Path,
    deadline: Instant,
) -> HostResult<(Inspection, Digest32)> {
    private_directory(directory)?;
    if Instant::now() >= deadline {
        return Err("original inspection budget expired".into());
    }
    let program = config.program.read(128 * 1024 * 1024)?;
    let probe = config.probe.read(32 * 1024)?;
    binding.probe.withdrawal_request.read(32 * 1024)?;
    binding.probe.current_owner.read(32 * 1024)?;
    let intent = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.fixed-paired-readonly-withdrawal-invocation.v1",
        "program_digest":config.program.digest,"probe_digest":config.probe.digest,
        "mode":"inspect-learning-withdrawal","new_withdrawal_issued":false
    }))?;
    create_private(&directory.join("intent.json"), &intent)?;
    let output_path = directory.join("original-inspection.json");
    let output = create_private(&output_path, &[])?;
    let stderr = create_private(&directory.join("stderr.log"), &[])?;
    let started_ms = crate::fixed_calibration_host::now_ms()?;
    if Instant::now() >= deadline {
        return Err("original inspection budget expired before spawn".into());
    }
    let mut child = JoinedChild(
        Command::new(&config.program.path)
            .env_clear()
            .arg("inspect-learning-withdrawal")
            .arg(&config.probe.path)
            .arg(&config.probe.digest)
            .stdin(Stdio::null())
            .stdout(Stdio::from(output))
            .stderr(Stdio::from(stderr))
            .spawn()?,
    );
    let success = loop {
        if let Some(status) = child.0.try_wait()? {
            break status.success();
        }
        if Instant::now() >= deadline {
            let _ = child.0.kill();
            child.0.wait()?;
            return Err("original read-only inspection timed out and physically joined".into());
        }
        std::thread::sleep(Duration::from_millis(2));
    };
    let finished_ms = crate::fixed_calibration_host::now_ms()?;
    File::open(&output_path)?.sync_all()?;
    File::open(directory)?.sync_all()?;
    if !success
        || Instant::now() >= deadline
        || config.program.read(128 * 1024 * 1024)? != program
        || config.probe.read(32 * 1024)? != probe
    {
        return Err("current inspection failed, expired, or original program/probe changed".into());
    }
    binding.probe.withdrawal_request.read(32 * 1024)?;
    binding.probe.current_owner.read(32 * 1024)?;
    let bytes = read_root_review_input(&output_path, 128 * 1024)?;
    let inspection = parse(&bytes, binding, started_ms, finished_ms)?;
    let receipt = Digest32::of_bytes(&[intent.as_slice(), bytes.as_slice()].concat());
    create_private(
        &directory.join("completed.json"),
        &serde_json::to_vec(&serde_json::json!({
            "schema":"hepta.fixed-paired-readonly-withdrawal-completed.v1", "original_receipt_digest":receipt.to_string(),
            "output_digest":Digest32::of_bytes(&bytes).to_string(),"started_ms":started_ms,"finished_ms":finished_ms,
            "model_weight_forgetting_claimed":false
        }))?,
    )?;
    Ok((inspection, receipt))
}

struct JoinedChild(std::process::Child);
impl Drop for JoinedChild {
    fn drop(&mut self) {
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

impl Inspection {
    pub(super) fn same_original_facts(&self, earlier: &Self) -> bool {
        self.request_digest == earlier.request_digest
            && self.current_owner_digest == earlier.current_owner_digest
            && self.current_read_digest == earlier.current_read_digest
            && self.current_head_digest == earlier.current_head_digest
            && self.withdrawal_head == earlier.withdrawal_head
            && self.source_ack == earlier.source_ack
            && self.artifact_ack == earlier.artifact_ack
            && self.delivery_denials == earlier.delivery_denials
            && self.observed_at_ms >= earlier.observed_at_ms
    }
    pub(super) fn delivery_denial_fraction(&self) -> HostResult<FixedQ32> {
        // `parse` only accepts a complete set of genuinely denied targets from
        // the physically executed original native inspector. This is delivery
        // blocking, not an observation of forgetting in model weights.
        let denied = self
            .delivery_denials
            .iter()
            .filter(|denial| {
                !denial.accepted && !denial.consumer_invoked && denial.result == "Ineligible"
            })
            .count();
        let numerator = FixedQ32::from_raw(i64::try_from(denied)? << 32);
        let denominator = FixedQ32::from_raw(i64::try_from(self.delivery_denials.len())? << 32);
        Ok(numerator.checked_div(denominator)?)
    }
}

#[cfg(test)]
#[path = "paired_custody_withdrawal_tests.rs"]
mod tests;

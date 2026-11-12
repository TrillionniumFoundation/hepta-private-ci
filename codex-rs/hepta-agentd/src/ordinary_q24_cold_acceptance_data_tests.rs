//! Observe the immutable first Root acceptance and its original checkpoint.
//! These data comparisons neither validate expired signatures nor create a
//! historical capability. The new product session must obtain that capability.

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::cold_record::observe_original_record;
use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use crate::LearningIterationCheckpointRecordV1;
use crate::authority_host_runtime::RootCompletedLearningAcceptanceDataV1;
use crate::authority_host_runtime::completed_learning_acceptance_owner;
use crate::learning_iteration_checkpoint::ordinary_observer::OriginalCheckpointData;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
enum Kind {
    CompletedLearning { initial: [u8; 32] },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Phase {
    Ready,
    Armed,
    Refused,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Refusal {
    schema: u8,
    purpose: String,
    kind: Kind,
    target: CellGenerationOwnerBindingV1,
    attempt: u64,
    phase: Phase,
}

pub(super) struct OriginalColdAcceptanceData {
    pub(super) digest: String,
    pub(super) accepted: RootCompletedLearningAcceptanceDataV1,
    directory: PathBuf,
    owner: String,
    refusal_owner: String,
    refusal: Refusal,
    paths: Vec<PathBuf>,
    immutable: OriginalBusinessSnapshot,
}

impl OriginalColdAcceptanceData {
    pub(super) fn observe(original: &RetainedOrdinaryQ24Fixture) -> anyhow::Result<Self> {
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        original.source.require_dead()?;
        let initial = original.plan.profile.original_initial_data()?;
        let terminal = original
            .terminal
            .snapshot
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("actual terminal checkpoint absent"))?;
        let service = &original.plan.resources.successor.service;
        let service_pin = OriginalBusinessSnapshot::capture(&[service.clone()])?;
        let config: crate::HostAuthorityServiceConfig = serde_json::from_slice(
            &super::observer::read_private(service, /*bound*/ 16 * 1024)?,
        )?;
        anyhow::ensure!(
            config.state_dir == original.plan.resources.original.plan.root.authority,
            "first acceptance is not in the actual original Root directory"
        );
        let owner = completed_learning_acceptance_owner(&initial);
        let checkpoint_directory = config.state_dir.join("learning-checkpoint");
        let checkpoint_owner = "root-learning-checkpoint-v1";
        let mut paths = record_paths(&config.state_dir, &owner);
        paths.extend(record_paths(&checkpoint_directory, checkpoint_owner));
        paths.push(service.clone());
        let immutable = OriginalBusinessSnapshot::capture(&paths)?;
        service_pin.require_unchanged(&[service.clone()])?;
        let result = (|| {
            let accepted: RootCompletedLearningAcceptanceDataV1 =
                observe_original_record(&config.state_dir, &owner, |_| Ok(()))?
                    .ok_or_else(|| anyhow::anyhow!("exited Root first acceptance is changing"))?;
            let checkpoint: LearningIterationCheckpointRecordV1 =
                observe_original_record(&checkpoint_directory, checkpoint_owner, |_| Ok(()))?
                    .ok_or_else(|| {
                        anyhow::anyhow!("exited Root terminal checkpoint is changing")
                    })?;
            anyhow::ensure!(
                OriginalCheckpointData::observe_live(&checkpoint_directory, &initial)?
                    == Some(original.terminal.clone()),
                "the physical original checkpoint is not the actual terminal result"
            );
            let data = serde_json::to_value(&accepted)?;
            let profile_text = data["original_profile"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("accepted frozen profile absent"))?;
            let profile: crate::HostAuthorityLearningProfileV1 =
                serde_json::from_str(profile_text)?;
            let proof = original.plan.resources.successor.writer_proof.sha256()?;
            let verified = data["root_verified_at_seconds"]
                .as_u64()
                .ok_or_else(|| anyhow::anyhow!("actual first verification time absent"))?;
            anyhow::ensure!(
                data["schema"] == 1
                    && data["purpose"] == "runtime.learning.completed-acceptance.v1"
                    && data["initial"] == initial.head_digest.to_string()
                    && data["target"]
                        == Digest32::from_array(
                            original
                                .plan
                                .resources
                                .original
                                .plan
                                .deployment
                                .target
                                .digest()?
                        )
                        .to_string()
                    && data["terminal_head"] == terminal.head_digest.to_string()
                    && data["frozen_scope"] == original.terminal.scope_binding.to_string()
                    && data["checkpoint"]
                        == Digest32::of_parts(&[
                            b"hepta.root.completed-learning.checkpoint.v1\0",
                            &serde_json::to_vec(&checkpoint)?,
                        ])
                        .to_string()
                    && serde_json::to_string(&profile)? == profile_text
                    && profile.schema_version == 2
                    && profile.require_binding(
                        &original.plan.resources.successor.identity,
                        proof.as_str()
                    )? == initial
                    && profile.require_cell_scope(&initial)?.binding()
                        == original.terminal.scope_binding
                    && verified > 0
                    && verified < initial.request.envelope.expiry_unix_seconds
                    && verified <= crate::authbus_ingress::now_ms()? / 1_000
                    && terminal
                        .receipts
                        .iter()
                        .all(|receipt| receipt.observed_unix_seconds <= verified),
                "actual first acceptance differs from the original completed phase"
            );
            for field in [
                "deployment",
                "original_task",
                "independent_b",
                "publication",
            ] {
                require_digest(&data[field])?;
            }
            for field in ["journals", "signatures"] {
                let values = data[field]
                    .as_array()
                    .ok_or_else(|| anyhow::anyhow!("actual accepted {field} absent"))?;
                anyhow::ensure!(
                    values.len() == 7,
                    "all seven original completion inputs required"
                );
                for value in values {
                    require_digest(value)?;
                }
            }
            Ok::<_, anyhow::Error>(accepted)
        })();
        immutable.require_unchanged(&paths)?;
        service_pin.require_unchanged(&[service.clone()])?;
        let accepted = result?;
        let target = &original.plan.resources.original.plan.deployment.target;
        let refusal_owner = format!(
            "initial-data-refusal/completed-learning/{}/{}",
            initial.head_digest,
            crate::neuron_generation_current::types::scope_digest(target.scope())?
        );
        let refusal =
            observe_original_record::<Refusal>(&config.state_dir, &refusal_owner, |data| {
                anyhow::ensure!(
                    data.schema == 1
                        && data.purpose == "runtime.initial-data-refusal.v1"
                        && data.kind
                            == Kind::CompletedLearning {
                                initial: initial.head_digest.into_array()
                            }
                        && data.target == *target
                        && data.attempt >= 2
                        && data.phase == Phase::Ready,
                    "first acceptance never finished its original durable verification"
                );
                Ok(())
            })?
            .ok_or_else(|| anyhow::anyhow!("exited Root acceptance attempt is changing"))?;
        immutable.require_unchanged(&paths)?;
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        Ok(Self {
            digest: accepted.data_digest()?.to_string(),
            accepted,
            directory: config.state_dir,
            owner,
            refusal_owner,
            refusal,
            paths,
            immutable,
        })
    }

    pub(super) fn require_unchanged(&self) -> anyhow::Result<u64> {
        self.immutable.require_unchanged(&self.paths)?;
        let result = (|| {
            let accepted = observe_original_record::<RootCompletedLearningAcceptanceDataV1>(
                &self.directory,
                &self.owner,
                |data| {
                    anyhow::ensure!(data == &self.accepted, "cold renewed the first acceptance");
                    Ok(())
                },
            )?
            .ok_or_else(|| anyhow::anyhow!("immutable first acceptance was replaced"))?;
            anyhow::ensure!(
                accepted.data_digest()?.to_string() == self.digest,
                "first fact digest changed"
            );
            let refusal =
                observe_original_record::<Refusal>(&self.directory, &self.refusal_owner, |data| {
                    let mut binding = data.clone();
                    binding.attempt = self.refusal.attempt;
                    binding.phase = self.refusal.phase;
                    anyhow::ensure!(
                        binding == self.refusal
                            && data.attempt >= self.refusal.attempt
                            && data.phase == Phase::Ready,
                        "cold acceptance verification is unfinished, refused or regressed"
                    );
                    Ok(())
                })?
                .ok_or_else(|| {
                    anyhow::anyhow!("completed Root response left a changing acceptance attempt")
                })?;
            Ok(refusal.attempt)
        })();
        self.immutable.require_unchanged(&self.paths)?;
        result
    }
}

fn require_digest(value: &serde_json::Value) -> anyhow::Result<()> {
    let text = value
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("accepted digest absent"))?;
    let digest: Digest32 = text.parse()?;
    anyhow::ensure!(
        !digest.is_zero() && digest.to_string() == text,
        "accepted digest is not canonical"
    );
    Ok(())
}

fn record_paths(directory: &Path, owner: &str) -> Vec<PathBuf> {
    let name = format!("frontier-v1-{}.json", Digest32::of_bytes(owner.as_bytes()));
    vec![
        directory.join(&name),
        directory.join(format!("{name}.lock")),
    ]
}

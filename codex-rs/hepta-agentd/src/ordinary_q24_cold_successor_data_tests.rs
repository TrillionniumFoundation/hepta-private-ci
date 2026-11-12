//! Root successor registration/finalization DATA for the whole-cold parent.
//! These observations cannot construct an admission or prove daemon delivery.

use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::observe_original_file_anchor_v1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::cold_record::observe_original_record;
use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::authority_host_runtime::RootSuccessorTaskCutV1;
use crate::authority_host_service::generation_publication::PublicationProfile;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Reserved {
    schema_version: u8,
    original: PublicationProfile,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case", deny_unknown_fields)]
enum Phase {
    Registered,
    Finalized { cut: Box<RootSuccessorTaskCutV1> },
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Successor {
    schema: u8,
    purpose: String,
    profile: Reserved,
    registered_identity: String,
    publisher: CognitiveCheckpointPeerLifetime,
    publisher_epoch: u64,
    peer_gid: u32,
    files: String,
    configuration: String,
    phase: Phase,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum RefusalPhase {
    Armed,
    Ready,
    Refused,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Binding {
    schema: u8,
    purpose: String,
    publication_purpose: String,
    learning_operation: String,
    initial: String,
    scope: String,
    previous: CellGenerationOwnerBindingV1,
    target: CellGenerationOwnerBindingV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Refusal {
    binding: Binding,
    attempt: u64,
    phase: RefusalPhase,
    original: Option<Reserved>,
}

pub(super) struct OriginalColdSuccessorData {
    registered: Successor,
    refusal: Refusal,
    source_anchor: JournalAnchor,
    definition: Digest32,
    business_paths: Vec<PathBuf>,
    business: OriginalBusinessSnapshot,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(super) struct OriginalFinalizedColdData {
    pub(super) record_digest: Digest32,
    pub(super) cut: RootSuccessorTaskCutV1,
    pub(super) refusal_attempt: u64,
}

impl OriginalColdSuccessorData {
    pub(super) fn observe_registered(
        original: &RetainedOrdinaryQ24Fixture,
    ) -> anyhow::Result<Self> {
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        let (registered, refusal) = read_pair(original, ReadPhase::Original)?
            .ok_or_else(|| anyhow::anyhow!("exited Root registration is changing"))?;
        let initial = original.plan.profile.original_initial_data()?;
        let profile = &registered.profile.original;
        let registration: crate::HostAuthorityRegistration =
            serde_json::from_slice(&super::observer::read_private(
                &original.plan.resources.successor.registration,
                /*bound*/ 16 * 1024,
            )?)?;
        let publisher = original.daemon.lifetime();
        let intent = &original
            .completed
            .current
            .published
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("actual old CURRENT publication absent"))?
            .intent;
        anyhow::ensure!(
            registered.schema == 1
                && registered.purpose == "runtime.circuit.original-successor-data.v1"
                && registered.profile.schema_version == 2
                && profile.purpose == "runtime.learning.cell-generation.publication.v2"
                && profile.binding == profile.digest()?
                && profile.learning_operation == initial.request.operation_id.as_str()
                && profile.initial == initial.head_digest.to_string()
                && profile.scope == original.terminal.scope_binding.to_string()
                && profile.decision == original.decision.snapshot.head_digest.to_string()
                && profile.intent == *intent
                && profile.identity
                    == crate::neuron_generation_process_identity_digest_v1(
                        &original.plan.resources.successor.identity
                    )?
                    .to_string()
                && profile.writer
                    == original
                        .plan
                        .resources
                        .successor
                        .writer_proof
                        .sha256()?
                        .as_str()
                && registered.registered_identity
                    == serde_json::to_string(&registration.registered_identity)?
                && registered.publisher
                    == CognitiveCheckpointPeerLifetime {
                        uid: 60001,
                        pid: publisher.pid,
                        boot_id: publisher.boot_id.clone(),
                        process_start_ticks: publisher.start_ticks,
                    }
                && registered.peer_gid == 60001
                && registered.publisher_epoch == registration.publisher_epoch
                && registered.publisher_epoch > 0
                && !registered.files.parse::<Digest32>()?.is_zero()
                && !registered.configuration.parse::<Digest32>()?.is_zero()
                && registered.phase == Phase::Registered,
            "actual original Root C registration differs"
        );
        let expected = Binding {
            schema: 1,
            purpose: "runtime.learning.publication-refusal.v1".into(),
            publication_purpose: profile.purpose.clone(),
            learning_operation: profile.learning_operation.clone(),
            initial: profile.initial.clone(),
            scope: profile.scope.clone(),
            previous: intent.previous.clone(),
            target: intent.target.clone(),
        };
        anyhow::ensure!(
            refusal.binding == expected
                && refusal.original.as_ref() == Some(&registered.profile)
                && refusal.attempt > 0
                && refusal.phase == RefusalPhase::Ready,
            "actual original publication verification is unfinished or refused"
        );
        let c = &original.plan.resources.c;
        let bytes = c.source_configuration.read_original(/*maximum*/ 65_536)?;
        let configuration = OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
            &bytes,
            &original.plan.resources.successor.identity,
        )?;
        anyhow::ensure!(
            configuration.source_witness == c.source_witness.path,
            "source witness differs"
        );
        let witness = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&c.source_witness.path)?;
        c.source_witness.require_file(&witness)?;
        let source_anchor = observe_original_file_anchor_v1(
            &witness,
            configuration.witness_scope,
            configuration.witness_generation,
            configuration.witness_records,
        )?
        .ok_or_else(|| anyhow::anyhow!("actual completed C source anchor absent"))?;
        c.source_witness.require_file(&witness)?;
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        let business_paths = original_control_business(original, profile)?;
        let business = OriginalBusinessSnapshot::capture(&business_paths)?;
        Ok(Self {
            registered,
            refusal,
            source_anchor,
            definition: configuration.definition.semantic_digest()?,
            business_paths,
            business,
        })
    }

    /// Live scheduling observation only. The caller must separately obtain the
    /// new daemon's actual completed-history response and retain its real exit.
    pub(super) fn observe_finalized(
        &self,
        original: &RetainedOrdinaryQ24Fixture,
    ) -> anyhow::Result<Option<OriginalFinalizedColdData>> {
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        self.business.require_unchanged(&self.business_paths)?;
        let result = read_pair(original, ReadPhase::Cold(self));
        self.business.require_unchanged(&self.business_paths)?;
        let Some((successor, refusal)) = result? else {
            return Ok(None);
        };
        let Phase::Finalized { cut } = &successor.phase else {
            return Ok(None);
        };
        if refusal.phase == RefusalPhase::Armed {
            return Ok(None);
        }
        anyhow::ensure!(
            refusal.attempt > self.refusal.attempt,
            "no actual cold verification attempt"
        );
        Ok(Some(OriginalFinalizedColdData {
            record_digest: Digest32::of_parts(&[
                b"hepta.root.original-successor-record.v1\0",
                &serde_json::to_vec(&successor)?,
            ]),
            cut: cut.as_ref().clone(),
            refusal_attempt: refusal.attempt,
        }))
    }

    fn require_original_task(
        &self,
        successor: &Successor,
        original: &RetainedOrdinaryQ24Fixture,
    ) -> anyhow::Result<()> {
        let mut unchanged = successor.clone();
        unchanged.phase = Phase::Registered;
        anyhow::ensure!(
            unchanged == self.registered,
            "cold changed original C registration"
        );
        let Phase::Finalized { cut } = &successor.phase else {
            return Ok(());
        };
        let (source, cell) = cut.publication.decode_original_successor_data()?;
        anyhow::ensure!(
            cut.configuration == self.registered.configuration
                && cut.definition == self.definition.to_string()
                && cut.writer_epoch
                    == self
                        .registered
                        .profile
                        .original
                        .intent
                        .target
                        .writer_epoch()
                && cut.source_sequence == self.source_anchor.sequence
                && cut.source_checkpoint == self.source_anchor.checkpoint_digest.to_string()
                && cut.cell_sequence == original.completed.cell.anchor.sequence
                && cut.cell_checkpoint
                    == original.completed.cell.anchor.checkpoint_digest.to_string()
                && source == original.completed.source
                && cell == original.completed.cell.decision,
            "actual cold Root finalized a different original C physical cut"
        );
        Ok(())
    }

    fn require_original_refusal(&self, refusal: &Refusal) -> anyhow::Result<()> {
        anyhow::ensure!(
            refusal.binding == self.refusal.binding
                && refusal.original == self.refusal.original
                && refusal.attempt >= self.refusal.attempt,
            "cold changed the original refusal history"
        );
        anyhow::ensure!(
            refusal.phase != RefusalPhase::Refused,
            "actual cold Root refused C"
        );
        Ok(())
    }
}

fn original_control_business(
    original: &RetainedOrdinaryQ24Fixture,
    profile: &PublicationProfile,
) -> anyhow::Result<Vec<PathBuf>> {
    let directory = &original.plan.root.publication_inputs.current_directory;
    let mut paths = Vec::new();
    let mut add = |directory: &Path, owner: &str| {
        let name = format!("frontier-v1-{}.json", Digest32::of_bytes(owner.as_bytes()));
        paths.push(directory.join(&name));
        paths.push(directory.join(format!("{name}.lock")));
    };
    add(
        directory,
        &format!(
            "cell-generation/{}",
            crate::neuron_generation_current::types::scope_digest(profile.intent.target.scope())?
        ),
    );
    add(
        directory,
        &format!(
            "generation-publication-v2/{}",
            Digest32::of_bytes(profile.intent.operation_id.as_bytes())
        ),
    );
    add(
        directory,
        &format!(
            "publication-grant/{}",
            Digest32::of_bytes(profile.learning_operation.as_bytes())
        ),
    );
    let config: crate::HostAuthorityServiceConfig =
        serde_json::from_slice(&super::observer::read_private(
            &original.plan.resources.successor.service,
            /*bound*/ 16 * 1024,
        )?)?;
    let consumers = config
        .consumers
        .ok_or_else(|| anyhow::anyhow!("original FinalUse consumers absent"))?;
    let slot = match profile.consumer_slot {
        crate::RootPublicationFinalUseConsumerV1::Device => consumers.device,
        crate::RootPublicationFinalUseConsumerV1::Notes => consumers.notes,
    };
    add(&slot.state_dir, &slot.owner_id);
    paths.extend(
        ["authority.json", "authority.claims", "authority.lock"]
            .map(|name| profile.local_consumer.join(name)),
    );
    paths.sort();
    paths.dedup();
    Ok(paths)
}

enum ReadPhase<'a> {
    Original,
    Cold(&'a OriginalColdSuccessorData),
}

fn read_pair(
    original: &RetainedOrdinaryQ24Fixture,
    phase: ReadPhase<'_>,
) -> anyhow::Result<Option<(Successor, Refusal)>> {
    let directory = &original.plan.root.publication_inputs.current_directory;
    let initial = original.plan.profile.original_initial_data()?;
    let operation = Digest32::of_bytes(initial.request.operation_id.as_str().as_bytes());
    let task_owner = format!("publication-task/{operation}");
    let refusal_owner = format!("publication-refusal/{operation}");
    let require_task = |value: &Successor| match &phase {
        ReadPhase::Original => Ok(()),
        ReadPhase::Cold(before) => before.require_original_task(value, original),
    };
    let require_refusal = |value: &Refusal| match &phase {
        ReadPhase::Original => Ok(()),
        ReadPhase::Cold(before) => before.require_original_refusal(value),
    };
    let Some(task) = observe_original_record::<Successor>(directory, &task_owner, require_task)?
    else {
        return Ok(None);
    };
    let Some(refusal) =
        observe_original_record::<Refusal>(directory, &refusal_owner, require_refusal)?
    else {
        return Ok(None);
    };
    let Some(task_after) =
        observe_original_record::<Successor>(directory, &task_owner, require_task)?
    else {
        return Ok(None);
    };
    let Some(refusal_after) =
        observe_original_record::<Refusal>(directory, &refusal_owner, require_refusal)?
    else {
        return Ok(None);
    };
    anyhow::ensure!(
        !(matches!(task.phase, Phase::Finalized { .. }) && task_after.phase == Phase::Registered)
            && refusal_after.attempt >= refusal.attempt
            && !(refusal_after.attempt == refusal.attempt
                && refusal.phase == RefusalPhase::Ready
                && refusal_after.phase == RefusalPhase::Armed),
        "observed Root state regressed during cold read"
    );
    if task_after != task || refusal_after != refusal {
        return Ok(None);
    }
    Ok(Some((task, refusal)))
}

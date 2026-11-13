//! One normal Root entry opens one existing session, loads original files,
//! consumes one generation/task purpose, and retains that same host for V3.
//! The original descriptor parser claims ALL numbers before any owner opens.

use std::collections::{BTreeMap, BTreeSet};
use std::ffi::{OsStr, OsString};
use std::fs::File;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::{UnixDatagram, UnixStream};
use std::path::PathBuf;

use codex_hepta_agentd::{CellQ24ModelFilesV1, PreparedHostAuthoritySession,
    RootHostInitialGenerationFilesV1, RootHostQ24TaskFilesV1, PreparedRootHostInitialGenerationV1,
    RootHostOriginalTaskLearningFilesV1, RootResidentCandidateEnrollmentInputsV3};

#[derive(Clone, Copy)]
pub(super) enum Command { Fresh, Recover }

const REQUIRED_FDS: [&str; 26] = [
    "--owner-pidfd", "--generation-registry-fd", "--generation-payload-fd",
    "--withdrawal-snapshot-fd", "--generation-journal-fd", "--generation-witness-fd",
    "--task-source-journal-fd", "--task-source-witness-fd", "--task-cell-journal-fd",
    "--task-cell-witness-fd", "--task-inference-control-fd", "--task-model-base-fd",
    "--task-model-encoder-fd", "--task-model-heads-fd", "--root-production-handoff-fd",
    "--root-original-task-handoff-fd", "--task-root-pidfd", "--candidate-stage-handoff-fd",
    "--resident-enrollment-handoff-fd", "--resident-root-pidfd", "--resident-consumer-pidfd",
    "--material-source-stream-fd", "--material-consumer-pidfd", "--baseline-base-fd",
    "--baseline-encoder-fd", "--baseline-heads-fd",
];
const OPTIONAL_FDS: [&str; 4] = ["--task-model-organ-fd", "--task-model-cell-fd",
    "--baseline-organ-fd", "--baseline-cell-fd"];

pub(super) fn run(mut options: BTreeMap<OsString, OsString>, command: Command)
    -> Result<(), Box<dyn std::error::Error>>
{
    let mut take_path = |key: &str| options.remove(OsStr::new(key)).map(PathBuf::from)
        .ok_or("missing required original Root loading option");
    let config = take_path("--config")?;
    let registration = take_path("--registration")?;
    let generation_deployment = take_path("--generation-deployment")?;
    let task_deployment = take_path("--task-deployment")?;
    let service_deployment = take_path("--task-learning-service")?;
    let readback = match command {
        Command::Fresh => None,
        Command::Recover => Some(take_path("--resident-readback")?),
    };
    let mut raw = Vec::new();
    for key in REQUIRED_FDS {
        raw.push((key, options.remove(OsStr::new(key)).ok_or("missing required original descriptor slot")?));
    }
    for key in OPTIONAL_FDS {
        if let Some(value) = options.remove(OsStr::new(key)) { raw.push((key, value)); }
    }
    if !options.is_empty() { return Err("unknown original Root task loading option".into()); }
    let mut claimed = BTreeSet::new();
    let mut descriptors = BTreeMap::new();
    for (key, value) in raw {
        descriptors.insert(key, super::inherited_descriptor(&value, &mut claimed)?);
    }
    let mut files = Descriptors(descriptors);
    let owner_pidfd = files.take_original_descriptor("--owner-pidfd")?;
    let generation = RootHostInitialGenerationFilesV1 {
        registry_snapshot: files.file("--generation-registry-fd")?,
        selected_payload: files.file("--generation-payload-fd")?,
        withdrawal_snapshot: files.file("--withdrawal-snapshot-fd")?,
        target_journal: files.file("--generation-journal-fd")?,
        target_witness: files.file("--generation-witness-fd")?,
    };
    let task = RootHostQ24TaskFilesV1 {
        source_journal: files.file("--task-source-journal-fd")?,
        source_witness: files.file("--task-source-witness-fd")?,
        cell_journal: files.file("--task-cell-journal-fd")?,
        cell_witness: files.file("--task-cell-witness-fd")?,
        inference_control: files.file("--task-inference-control-fd")?,
        model: CellQ24ModelFilesV1 {
            base: files.file("--task-model-base-fd")?, encoder: files.file("--task-model-encoder-fd")?,
            heads: files.file("--task-model-heads-fd")?,
            organ_adapter: files.optional_file("--task-model-organ-fd"),
            cell_adapter: files.optional_file("--task-model-cell-fd"),
        },
    };
    let service = RootHostOriginalTaskLearningFilesV1 {
        production_handoff: UnixDatagram::from(files.take_original_descriptor("--root-production-handoff-fd")?),
        task_handoff: UnixDatagram::from(files.take_original_descriptor("--root-original-task-handoff-fd")?),
        original_task_root_pidfd: files.take_original_descriptor("--task-root-pidfd")?,
        resident: RootResidentCandidateEnrollmentInputsV3 {
            stage_handoff: UnixDatagram::from(files.take_original_descriptor("--candidate-stage-handoff-fd")?),
            enrollment_handoff: UnixDatagram::from(files.take_original_descriptor("--resident-enrollment-handoff-fd")?),
            original_root_pidfd: files.take_original_descriptor("--resident-root-pidfd")?,
            original_consumer_pidfd: files.take_original_descriptor("--resident-consumer-pidfd")?,
            baseline_files: CellQ24ModelFilesV1 {
                base: files.file("--baseline-base-fd")?, encoder: files.file("--baseline-encoder-fd")?,
                heads: files.file("--baseline-heads-fd")?,
                organ_adapter: files.optional_file("--baseline-organ-fd"),
                cell_adapter: files.optional_file("--baseline-cell-fd"),
            },
        },
        material_stream: UnixStream::from(files.take_original_descriptor("--material-source-stream-fd")?),
        original_material_pidfd: files.take_original_descriptor("--material-consumer-pidfd")?,
    };
    if !files.0.is_empty() { return Err("unconsumed original descriptor slot".into()); }
    require_distinct_writer_files(&generation, &task, &service.resident.baseline_files)?;
    // This original open is the only session/issuer opening in the flow.
    // The task and resident branches subsequently use its retained instances.
    let session = PreparedHostAuthoritySession::open(&config, &registration, owner_pidfd)?;
    match command {
        Command::Fresh => {
            let mut generation = session.prepare_original_initial_generation_from_files(&generation_deployment, generation)?;
            PreparedRootHostInitialGenerationV1::publish_original_generation(&mut generation)?;
            let task = PreparedRootHostInitialGenerationV1::prepare_original_root_task_from_files(generation, &task_deployment, task)?;
            codex_hepta_agentd::PreparedRootHostLoadedQ24TaskV1::serve_loaded_original_task_and_resident(task, &service_deployment, service)?;
        }
        Command::Recover => {
            let generation = session.recover_original_initial_generation_from_files(&generation_deployment, generation)?;
            let task = PreparedRootHostInitialGenerationV1::recover_original_root_task_from_files(generation, &task_deployment, task)?;
            let readback = readback.ok_or("the original resident readback authorization is missing")?;
            codex_hepta_agentd::PreparedRootHostLoadedQ24TaskV1::recover_loaded_original_task_and_resident(task, &service_deployment, service, &readback)?;
        }
    }
    Ok(())
}

struct Descriptors(BTreeMap<&'static str, OwnedFd>);
impl Descriptors {
    fn take_original_descriptor(&mut self, name: &'static str) -> Result<OwnedFd, Box<dyn std::error::Error>> {
        self.0.remove(name).ok_or_else(|| "original descriptor was already consumed".into())
    }
    fn file(&mut self, name: &'static str) -> Result<File, Box<dyn std::error::Error>> {
        Ok(File::from(self.take_original_descriptor(name)?))
    }
    fn optional_file(&mut self, name: &'static str) -> Option<File> { self.0.remove(name).map(File::from) }
}

fn require_distinct_writer_files(generation: &RootHostInitialGenerationFilesV1,
    task: &RootHostQ24TaskFilesV1, baseline: &CellQ24ModelFilesV1,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writers = BTreeSet::new();
    for file in [&generation.target_journal, &generation.target_witness, &task.source_journal,
        &task.source_witness, &task.cell_journal, &task.cell_witness, &task.inference_control]
    {
        let metadata = file.metadata()?;
        if !writers.insert((metadata.dev(), metadata.ino())) {
            return Err("one original writer file cannot serve two owner roles".into());
        }
    }
    let mut readers = vec![&generation.registry_snapshot, &generation.selected_payload,
        &generation.withdrawal_snapshot, &task.model.base, &task.model.encoder, &task.model.heads,
        &baseline.base, &baseline.encoder, &baseline.heads];
    readers.extend([task.model.organ_adapter.as_ref(), task.model.cell_adapter.as_ref(),
        baseline.organ_adapter.as_ref(), baseline.cell_adapter.as_ref()].into_iter().flatten());
    for file in readers {
        let metadata = file.metadata()?;
        if writers.contains(&(metadata.dev(), metadata.ino())) {
            return Err("an original writer file cannot alias a read-only input".into());
        }
    }
    Ok(())
}

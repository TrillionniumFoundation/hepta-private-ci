//! A fresh native OS process reopens actual research owner files.
//! This does not launch the production daemon, authenticate independent custody,
//! authorize a new effect, renew a grant, or establish model quality.

use std::collections::BTreeMap;
use std::fs;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::*;
use crate::learning_iteration_research_external::ResearchExternalTrainedArtifactOwnerV1;

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub(crate) enum Probe {
    Completed,
    WrongIteration,
    WrongCurrent,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RecoveryContext {
    pub(crate) parent_pid: u32,
    pub(crate) deadline_unix_seconds: u64,
    pub(crate) root: PathBuf,
    pub(crate) evidence: PathBuf,
    pub(crate) model: PathBuf,
    pub(crate) old_config: CellGenerationConfigV2,
    pub(crate) target_config: CellGenerationConfigV2,
    pub(crate) operation_id: String,
    pub(crate) intent_digest: [u8; 32],
    pub(crate) request: CellGenerationRequestV2,
    pub(crate) receipt: CellGenerationReceiptV2,
    pub(crate) original_use_record_sha256: [u8; 32],
    pub(crate) initial_record_sha256: [u8; 32],
    pub(crate) checkpoint_sha256: [u8; 32],
    pub(crate) external_proposal: bool,
    pub(crate) probe: Probe,
}

fn read_bounded(path: &Path, limit: u64) -> anyhow::Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)?;
    anyhow::ensure!(
        metadata.is_file() && metadata.len() <= limit,
        "bounded regular recovery file"
    );
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take(limit + 1)
        .read_to_end(&mut bytes)?;
    anyhow::ensure!(bytes.len() as u64 <= limit, "recovery file grew");
    Ok(bytes)
}

fn owner_files(root: &Path) -> anyhow::Result<BTreeMap<PathBuf, Digest32>> {
    let mut pending = vec![root.to_path_buf()];
    let mut files = BTreeMap::new();
    let mut directories = 0_usize;
    let mut bytes = 0_usize;
    while let Some(path) = pending.pop() {
        directories += 1;
        anyhow::ensure!(
            directories <= 128 && fs::symlink_metadata(&path)?.is_dir(),
            "bounded owner directories"
        );
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let kind = entry.file_type()?;
            if kind.is_dir() {
                pending.push(entry.path());
            } else {
                anyhow::ensure!(
                    kind.is_file() && files.len() < 512,
                    "regular bounded owner roster"
                );
                let raw = read_bounded(&entry.path(), 4_194_304)?;
                bytes += raw.len();
                anyhow::ensure!(bytes <= 16_777_216, "bounded total owner bytes");
                files.insert(
                    entry.path().strip_prefix(root)?.to_path_buf(),
                    Digest32::of_bytes(&raw),
                );
            }
        }
    }
    Ok(files)
}

fn retained_owner_files(context: &RecoveryContext) -> anyhow::Result<BTreeMap<PathBuf, Digest32>> {
    let mut roots = vec![("generation", context.root.clone())];
    if context.external_proposal {
        roots.extend([
            (
                "external-artifact-owner",
                context.evidence.join("external-artifact-owner"),
            ),
            (
                "external-artifact-owner-anchor",
                context.evidence.join("external-artifact-owner-anchor"),
            ),
        ]);
    }
    let mut files = BTreeMap::new();
    for (name, root) in roots {
        for (path, digest) in owner_files(&root)? {
            files.insert(PathBuf::from(name).join(path), digest);
        }
    }
    Ok(files)
}

fn persist(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    fs::File::open(
        path.parent()
            .ok_or_else(|| anyhow::anyhow!("missing recovery parent"))?,
    )?
    .sync_all()?;
    Ok(())
}

pub(crate) fn verify_in_new_process(context: RecoveryContext) -> anyhow::Result<serde_json::Value> {
    let before = retained_owner_files(&context)?;
    let mut observations = Vec::new();
    for (name, probe) in [
        ("completed", Probe::Completed),
        ("wrong-iteration", Probe::WrongIteration),
        ("wrong-current", Probe::WrongCurrent),
    ] {
        let mut selected = context.clone();
        selected.probe = probe;
        let path = context
            .evidence
            .join(format!("os-owner-recovery-{name}.json"));
        let raw = serde_json::to_vec(&selected)?;
        persist(&path, &raw)?;
        let stdout = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(path.with_extension("stdout.log"))?;
        let stderr = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(path.with_extension("stderr.log"))?;
        let mut child = Command::new(std::env::current_exe()?)
            .args(["--exact", "learning_iteration_checkpoint::os_process_recovery::fresh_native_owner_process_recovery_child", "--ignored", "--nocapture"])
            .env("HEPTA_RESEARCH_RECOVERY_CONTEXT", &path)
            .env("HEPTA_RESEARCH_RECOVERY_CONTEXT_SHA256", Digest32::of_bytes(&raw).to_string())
            .stdin(Stdio::null()).stdout(stdout).stderr(stderr).spawn()?;
        let child_pid = child.id();
        let status = child.wait()?;
        anyhow::ensure!(
            status.success(),
            "native recovery child {name} failed: {status}"
        );
        let result: serde_json::Value =
            serde_json::from_slice(&read_bounded(&path.with_extension("result.json"), 65_536)?)?;
        anyhow::ensure!(
            result["pid"] == child_pid
                && result["parent_pid"] == context.parent_pid
                && child_pid != context.parent_pid
                && result["probe"] == serde_json::to_value(probe)?
                && result["result"] == "PASS_RESEARCH_OWNER_PROCESS_REPLAY",
            "recovery process identity or result differs"
        );
        observations.push(result);
    }
    assert_eq!(retained_owner_files(&context)?, before);
    Ok(json!({
        "schema":"hepta.research.native-owner-os-process-recovery.v1",
        "result":"PASS_RESEARCH_OWNER_PROCESS_REPLAY",
        "children":observations,
        "original_owner_bytes_unchanged":true,
        "native_daemon_os_restart":false,
        "new_dispatch_authorized":false,
        "production_final_use":false,
        "qualification":"HOLD_NO_GO"
    }))
}

#[test]
#[ignore = "fresh pinned research context from the original native model operation required"]
fn fresh_native_owner_process_recovery_child() -> anyhow::Result<()> {
    let path = PathBuf::from(std::env::var("HEPTA_RESEARCH_RECOVERY_CONTEXT")?);
    let raw = read_bounded(&path, 65_536)?;
    let expected: Digest32 = std::env::var("HEPTA_RESEARCH_RECOVERY_CONTEXT_SHA256")?.parse()?;
    anyhow::ensure!(
        Digest32::of_bytes(&raw) == expected,
        "parent recovery context changed"
    );
    let context: RecoveryContext = serde_json::from_slice(&raw)?;
    anyhow::ensure!(
        context.parent_pid != std::process::id(),
        "same native OS process"
    );
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    anyhow::ensure!(
        now < context.deadline_unix_seconds,
        "original research window expired"
    );
    let before = retained_owner_files(&context)?;
    let original_use_raw = read_bounded(&context.evidence.join("next-use-owner.json"), 65_536)?;
    anyhow::ensure!(
        Digest32::of_bytes(&original_use_raw)
            == Digest32::from_array(context.original_use_record_sha256),
        "original next-use evidence changed"
    );
    let original_use: serde_json::Value = serde_json::from_slice(&original_use_raw)?;
    anyhow::ensure!(
        original_use["original_generation_request"] == serde_json::to_value(&context.request)?
            && original_use["receipt"] == serde_json::to_value(&context.receipt)?
            && original_use["native_nonce_count"] == 1,
        "context differs from original executed and acknowledged next use"
    );
    let initial_raw = read_bounded(
        &context.evidence.join("native-checkpoint-0-owner.json"),
        65_536,
    )?;
    anyhow::ensure!(
        Digest32::of_bytes(&initial_raw) == Digest32::from_array(context.initial_record_sha256),
        "initial owner record changed"
    );
    let initial_record: LearningIterationCheckpointRecordV1 = serde_json::from_slice(&initial_raw)?;
    let encoded = initial_record
        .snapshot
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("initial snapshot absent"))?;
    let initial = codec::decode(&STANDARD_NO_PAD.decode(encoded)?)?;
    anyhow::ensure!(
        initial.receipts.is_empty()
            && initial.request.envelope.expiry_unix_seconds == context.deadline_unix_seconds,
        "original genesis or deadline changed"
    );
    let checkpoint_path = context.root.join("learning-checkpoint");
    anyhow::ensure!(
        Digest32::of_bytes(&read_bounded(&checkpoint_path, 65_536)?)
            == Digest32::from_array(context.checkpoint_sha256),
        "completed owner record changed"
    );
    let owner =
        crate::neuron_generation_current::test_support::process_recovery::reopen_checkpoint(
            &context, &initial,
        )?;
    let restored = owner
        .restore(&initial.request)?
        .ok_or_else(|| anyhow::anyhow!("completed checkpoint absent"))?;
    anyhow::ensure!(
        LearningIterationCoordinatorV1::from_snapshot(restored.clone())?
            .next_stage()
            .is_none(),
        "incomplete original checkpoint"
    );
    match context.probe {
        Probe::WrongIteration => {
            let mut changed = initial.request;
            changed.operation_id =
                codex_hepta_types::StableId::new(format!("{}-substitution", changed.operation_id))?;
            assert_eq!(owner.restore(&changed), Err(Error::WrongScope));
        }
        Probe::WrongCurrent => {
            let mut changed = context.clone();
            changed.operation_id.push_str("-substitution");
            anyhow::ensure!(crate::neuron_generation_current::test_support::process_recovery::reopen_generation(&changed).is_err(), "foreign CURRENT operation accepted");
        }
        Probe::Completed => {
            crate::neuron_generation_current::test_support::process_recovery::reopen_generation(
                &context,
            )?;
            if context.external_proposal {
                let external = ResearchExternalTrainedArtifactOwnerV1::create(
                    context.evidence.join("external-artifact-owner"),
                    context.model.clone(),
                    context.evidence.clone(),
                    &initial,
                )?;
                external.verify_restored(&restored)?;
            }
        }
    }
    assert_eq!(retained_owner_files(&context)?, before);
    anyhow::ensure!(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() < context.deadline_unix_seconds,
        "recovery exceeded original research window"
    );
    persist(
        &path.with_extension("result.json"),
        &serde_json::to_vec(&json!({
            "schema":"hepta.research.native-owner-os-process-recovery-child.v1",
            "result":"PASS_RESEARCH_OWNER_PROCESS_REPLAY",
            "pid":std::process::id(),"parent_pid":context.parent_pid,"probe":context.probe,
            "restored_learning_head":restored.head_digest.to_string(),
            "receipt_count":restored.receipts.len(),
            "owner_roster_entries":before.len(),"owner_bytes_unchanged":true,
            "native_daemon_os_restart":false,"qualification":"HOLD_NO_GO"
        }))?,
    )?;
    Ok(())
}

#!/usr/bin/env python3
"""Install the durable, generation-fenced runtime.codex Agentd run owner.

The migration keeps the pure in-memory constructor for unit tests, while the
actual Agentd composition opens a fsync + rename transactional snapshot store.
Every product mutation persists before its RPC response is formed. A locked
store revision is used as a cross-process stale-writer fence.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one legacy block, found {text.count(old)}")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: neither legacy block nor migrated marker found")


def agentd_cargo(text: str) -> str:
    if "libc = { workspace = true }" not in text:
        text = text.replace(
            "http = { workspace = true }\n",
            "http = { workspace = true }\nlibc = { workspace = true }\n",
            1,
        )
    return text


def lane_b_runtime(text: str) -> str:
    old = "use std::collections::BTreeMap;\n"
    new = '''use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
#[cfg(unix)]
use std::os::fd::AsRawFd;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;
'''
    text = replace_once(text, old, new, "use serde::Serialize")

    old = '''const MAX_SUPPORTED_ACTIVE_RUNS: usize = 256;
const MAX_RETAINED_RUNS: usize = 1_024;
'''
    new = '''const MAX_SUPPORTED_ACTIVE_RUNS: usize = 256;
const MAX_RETAINED_RUNS: usize = 1_024;
const DURABLE_RUN_STORE_SCHEMA_VERSION: u32 = 1;
const MAX_DURABLE_RUN_STORE_BYTES: u64 = 16 * 1024 * 1024;
'''
    text = replace_once(text, old, new, "DURABLE_RUN_STORE_SCHEMA_VERSION")

    text = text.replace(
        "#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub enum RunPhase",
        "#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(rename_all = \"snake_case\")]\npub enum RunPhase",
    )
    for name in ["RuntimeComposition", "RunSnapshot", "ContextAttachment", "RunRecovery", "RunReceipt"]:
        text = text.replace(
            f"#[derive(Clone, Debug, Eq, PartialEq)]\npub struct {name}",
            f"#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\npub struct {name}",
        )
    text = text.replace(
        "#[derive(Clone, Debug)]\nstruct RunRecord",
        "#[derive(Clone, Debug, Deserialize, Serialize)]\nstruct RunRecord",
    )
    text = text.replace(
        "    InvalidRunStart(&'static str),\n}",
        "    InvalidRunStart(&'static str),\n    Persistence(String),\n}",
    )

    marker = "/// Owner-local Lane B coordinator for Agentd."
    if "struct DurableRunStoreV1" not in text:
        durable_struct = '''#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableRunStoreV1 {
    schema_version: u32,
    store_revision: u64,
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    accepting_runs: bool,
    max_active_runs: usize,
}

'''
        if marker not in text:
            raise RuntimeError("AgentRunCoordinator documentation marker missing")
        text = text.replace(marker, durable_struct + marker, 1)

    old = '''pub struct AgentRunCoordinator {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    accepting_runs: bool,
    max_active_runs: usize,
}
'''
    new = '''pub struct AgentRunCoordinator {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    accepting_runs: bool,
    max_active_runs: usize,
    durable_path: Option<PathBuf>,
    durable_store_revision: u64,
}
'''
    text = replace_once(text, old, new, "durable_store_revision")

    old = '''        Ok(Self {
            composition,
            runs: BTreeMap::new(),
            accepting_runs: true,
            max_active_runs,
        })
    }

    pub fn composition(&self) -> &RuntimeComposition {
'''
    new = '''        Ok(Self {
            composition,
            runs: BTreeMap::new(),
            accepting_runs: true,
            max_active_runs,
            durable_path: None,
            durable_store_revision: 0,
        })
    }

    /// Open the product run owner from a crash-consistent snapshot. The exact
    /// runtime composition is part of the durable identity, so a different
    /// Agent/generation/configuration cannot adopt this store.
    pub fn open_durable(
        composition: RuntimeComposition,
        durable_path: PathBuf,
    ) -> Result<Self, AgentRunError> {
        if !durable_path.is_absolute() {
            return Err(AgentRunError::Persistence(
                "durable run store path must be absolute".to_string(),
            ));
        }
        let parent = durable_path.parent().ok_or_else(|| {
            AgentRunError::Persistence("durable run store has no parent".to_string())
        })?;
        fs::create_dir_all(parent).map_err(|error| {
            AgentRunError::Persistence(format!("create durable run store parent: {error}"))
        })?;
        let _lock = DurableRunStoreLock::acquire(&durable_path)?;
        if let Some(store) = load_durable_run_store(&durable_path)? {
            validate_durable_run_store(&store, &composition)?;
            return Ok(Self {
                composition,
                runs: store.runs,
                accepting_runs: store.accepting_runs,
                max_active_runs: store.max_active_runs,
                durable_path: Some(durable_path),
                durable_store_revision: store.store_revision,
            });
        }
        drop(_lock);
        let mut coordinator = Self::compose_runtime(composition)?;
        coordinator.durable_path = Some(durable_path);
        coordinator.persist()?;
        Ok(coordinator)
    }

    /// Publish the complete owner state before a product RPC is acknowledged.
    /// The lock serializes writers and `store_revision` fences stale processes.
    pub fn persist(&mut self) -> Result<(), AgentRunError> {
        let Some(path) = self.durable_path.clone() else {
            return Ok(());
        };
        let _lock = DurableRunStoreLock::acquire(&path)?;
        let on_disk = load_durable_run_store(&path)?;
        let observed_revision = on_disk.as_ref().map_or(0, |store| store.store_revision);
        if observed_revision != self.durable_store_revision {
            return Err(AgentRunError::Persistence(format!(
                "stale durable run writer: expected revision {}, observed {observed_revision}",
                self.durable_store_revision
            )));
        }
        if let Some(store) = on_disk.as_ref()
            && store.composition != self.composition
        {
            return Err(AgentRunError::Persistence(
                "durable run store composition changed".to_string(),
            ));
        }
        let next_revision = self
            .durable_store_revision
            .checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        let store = DurableRunStoreV1 {
            schema_version: DURABLE_RUN_STORE_SCHEMA_VERSION,
            store_revision: next_revision,
            composition: self.composition.clone(),
            runs: self.runs.clone(),
            accepting_runs: self.accepting_runs,
            max_active_runs: self.max_active_runs,
        };
        validate_durable_run_store(&store, &self.composition)?;
        atomic_replace_durable_run_store(&path, &store)?;
        self.durable_store_revision = next_revision;
        Ok(())
    }

    pub fn composition(&self) -> &RuntimeComposition {
'''
    text = replace_once(text, old, new, "pub fn open_durable(")

    insertion_marker = "fn validate_snapshot(now_ms: u64, value: &RunSnapshot)"
    if "struct DurableRunStoreLock" not in text:
        support = r'''struct DurableRunStoreLock {
    file: File,
}

impl DurableRunStoreLock {
    fn acquire(store_path: &Path) -> Result<Self, AgentRunError> {
        let lock_path = store_path.with_extension("lock");
        let file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|error| {
                AgentRunError::Persistence(format!("open durable run store lock: {error}"))
            })?;
        #[cfg(unix)]
        {
            // SAFETY: flock receives a valid owned file descriptor. The file is
            // retained by this guard until Drop releases the advisory lock.
            let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) };
            if result != 0 {
                return Err(AgentRunError::Persistence(format!(
                    "lock durable run store: {}",
                    std::io::Error::last_os_error()
                )));
            }
        }
        Ok(Self { file })
    }
}

impl Drop for DurableRunStoreLock {
    fn drop(&mut self) {
        #[cfg(unix)]
        {
            // SAFETY: this guard still owns the descriptor locked in acquire.
            let _ = unsafe { libc::flock(self.file.as_raw_fd(), libc::LOCK_UN) };
        }
    }
}

fn load_durable_run_store(path: &Path) -> Result<Option<DurableRunStoreV1>, AgentRunError> {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(AgentRunError::Persistence(format!(
                "open durable run store: {error}"
            )));
        }
    };
    let length = file
        .metadata()
        .map_err(|error| AgentRunError::Persistence(format!("stat durable run store: {error}")))?
        .len();
    if length == 0 || length > MAX_DURABLE_RUN_STORE_BYTES {
        return Err(AgentRunError::Persistence(
            "durable run store size is invalid".to_string(),
        ));
    }
    let capacity = usize::try_from(length).map_err(|_| {
        AgentRunError::Persistence("durable run store length exceeds usize".to_string())
    })?;
    let mut bytes = Vec::with_capacity(capacity);
    file.read_to_end(&mut bytes).map_err(|error| {
        AgentRunError::Persistence(format!("read durable run store: {error}"))
    })?;
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|error| AgentRunError::Persistence(format!("decode durable run store: {error}")))
}

fn validate_durable_run_store(
    store: &DurableRunStoreV1,
    expected_composition: &RuntimeComposition,
) -> Result<(), AgentRunError> {
    if store.schema_version != DURABLE_RUN_STORE_SCHEMA_VERSION
        || store.store_revision == 0
        || &store.composition != expected_composition
        || store.max_active_runs != expected_composition.max_active_runs
        || !(1..=MAX_SUPPORTED_ACTIVE_RUNS).contains(&store.max_active_runs)
        || store.runs.len() > MAX_RETAINED_RUNS
    {
        return Err(AgentRunError::Persistence(
            "durable run store identity or bounds are invalid".to_string(),
        ));
    }
    let mut active = 0usize;
    for (run_id, record) in &store.runs {
        validate_snapshot_fields(&record.snapshot)?;
        if run_id != &record.snapshot.run_id || record.revision == 0 {
            return Err(AgentRunError::Persistence(
                "durable run record identity is invalid".to_string(),
            ));
        }
        if record.context_digest.is_some() != record.compilation_receipt_digest.is_some() {
            return Err(AgentRunError::Persistence(
                "durable run context binding is partial".to_string(),
            ));
        }
        if !matches!(record.phase, RunPhase::Admitted)
            && record.context_digest.is_none()
        {
            return Err(AgentRunError::Persistence(
                "durable post-admission run omitted context binding".to_string(),
            ));
        }
        if record.dispatch_binding_digest.is_some()
            != record.pre_effect_abort_commitment_digest.is_some()
        {
            return Err(AgentRunError::Persistence(
                "durable bound dispatch is partial".to_string(),
            ));
        }
        if record.pre_effect_abort_proof_digest.is_some()
            != (record.phase == RunPhase::AbortedBeforeEffect)
        {
            return Err(AgentRunError::Persistence(
                "durable pre-effect abort proof has an invalid phase".to_string(),
            ));
        }
        if record.phase == RunPhase::AbortedBeforeEffect
            && (record.dispatch_binding_digest.is_none()
                || record.pre_effect_abort_commitment_digest.is_none()
                || record.cancel_reason.is_none())
        {
            return Err(AgentRunError::Persistence(
                "durable pre-effect abort is incomplete".to_string(),
            ));
        }
        if let Some(value) = record.context_digest.as_deref() {
            validate_digest(value, "context")?;
        }
        if let Some(value) = record.compilation_receipt_digest.as_deref() {
            validate_digest(value, "compilation receipt")?;
        }
        if let Some(value) = record.dispatch_binding_digest.as_deref() {
            validate_digest(value, "dispatch binding")?;
        }
        if let Some(value) = record.pre_effect_abort_commitment_digest.as_deref() {
            validate_digest(value, "pre-effect abort commitment")?;
        }
        if let Some(value) = record.pre_effect_abort_proof_digest.as_deref() {
            validate_digest(value, "pre-effect abort proof")?;
        }
        if let Some(reason) = record.cancel_reason.as_deref() {
            validate_cancel_reason(reason)?;
        }
        if !record.phase.closed() {
            active = active
                .checked_add(1)
                .ok_or(AgentRunError::ArithmeticOverflow)?;
        }
    }
    if active > store.max_active_runs {
        return Err(AgentRunError::Persistence(
            "durable active run count exceeds capacity".to_string(),
        ));
    }
    Ok(())
}

fn atomic_replace_durable_run_store(
    path: &Path,
    store: &DurableRunStoreV1,
) -> Result<(), AgentRunError> {
    let bytes = serde_json::to_vec(store).map_err(|error| {
        AgentRunError::Persistence(format!("encode durable run store: {error}"))
    })?;
    if bytes.is_empty()
        || u64::try_from(bytes.len()).map_err(|_| AgentRunError::ArithmeticOverflow)?
            > MAX_DURABLE_RUN_STORE_BYTES
    {
        return Err(AgentRunError::Persistence(
            "encoded durable run store exceeds its bound".to_string(),
        ));
    }
    let parent = path.parent().ok_or_else(|| {
        AgentRunError::Persistence("durable run store has no parent".to_string())
    })?;
    let file_name = path.file_name().and_then(|value| value.to_str()).ok_or_else(|| {
        AgentRunError::Persistence("durable run store filename is invalid".to_string())
    })?;
    let temp_path = parent.join(format!(
        ".{file_name}.{}.{}.tmp",
        std::process::id(),
        store.store_revision
    ));
    match fs::remove_file(&temp_path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(AgentRunError::Persistence(format!(
                "remove stale durable run temp: {error}"
            )));
        }
    }
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp_path)
        .map_err(|error| {
            AgentRunError::Persistence(format!("create durable run temp: {error}"))
        })?;
    let write_result = (|| {
        file.write_all(&bytes)?;
        file.sync_all()?;
        fs::rename(&temp_path, path)?;
        #[cfg(unix)]
        File::open(parent)?.sync_all()?;
        Ok::<(), std::io::Error>(())
    })();
    if let Err(error) = write_result {
        let _ = fs::remove_file(&temp_path);
        return Err(AgentRunError::Persistence(format!(
            "publish durable run store: {error}"
        )));
    }
    Ok(())
}

'''
        if insertion_marker not in text:
            raise RuntimeError("validate_snapshot insertion point missing")
        text = text.replace(insertion_marker, support + insertion_marker, 1)
    return text


def state_control(text: str) -> str:
    replacements = [
        (
'''                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .start_run(now_ms()?, internal_run_snapshot(snapshot))
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .start_run(now_ms()?, internal_run_snapshot(snapshot))
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
'''),
        (
'''                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .attach_context(
                        now_ms()?,
                        expected_revision,
                        internal_context_attachment(attachment),
                    )
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .attach_context(
                        now_ms()?,
                        expected_revision,
                        internal_context_attachment(attachment),
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
'''),
        (
'''                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .mark_dispatched(now_ms()?, &run_id, expected_revision)
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .mark_dispatched(now_ms()?, &run_id, expected_revision)
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
'''),
        (
'''                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .mark_dispatched_bound(
                        now_ms()?,
                        &run_id,
                        expected_revision,
                        dispatch_binding_digest,
                        pre_effect_abort_commitment_digest,
                    )
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .mark_dispatched_bound(
                        now_ms()?,
                        &run_id,
                        expected_revision,
                        dispatch_binding_digest,
                        pre_effect_abort_commitment_digest,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
'''),
        (
'''                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .abort_before_effect(
                        &run_id,
                        expected_revision,
                        &dispatch_binding_digest,
                        &abort_nonce_hex,
                        &proof_digest,
                        &reason,
                    )
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .abort_before_effect(
                        &run_id,
                        expected_revision,
                        &dispatch_binding_digest,
                        &abort_nonce_hex,
                        &proof_digest,
                        &reason,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
'''),
        (
'''                let (disposition, receipt) = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let (disposition, receipt) = runs
                    .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
'''),
        (
'''                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .observe_terminal(
                        &run_id,
                        expected_revision,
                        internal_run_phase(phase),
                        terminal_observed,
                    )
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .observe_terminal(
                        &run_id,
                        expected_revision,
                        internal_run_phase(phase),
                        terminal_observed,
                    )
                    .map_err(run_error)?;
                if !receipt.idempotent {
                    runs.persist().map_err(run_error)?;
                }
'''),
        (
'''                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .remove_closed_run(&run_id, expected_revision)
                    .map_err(run_error)?;
''',
'''                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let receipt = runs
                    .remove_closed_run(&run_id, expected_revision)
                    .map_err(run_error)?;
                runs.persist().map_err(run_error)?;
'''),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            raise RuntimeError("state_control durable replacement point missing")
    return text


def state(text: str) -> str:
    old = '''        let run_coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
            agent_id: identity.agent_id.as_str().to_string(),
            supervisor_generation: identity.spawn_generation,
            agentd_generation: identity.spawn_generation,
            configuration_digest: Sha256Digest::for_bytes(configuration_material.as_bytes())
                .as_str()
                .to_string(),
            ports_digest: Sha256Digest::for_bytes(ports_material.as_bytes())
                .as_str()
                .to_string(),
            max_active_runs: usize::from(identity.resources.max_concurrent_turns),
        })
        .map_err(run_error)?;
'''
    new = '''        let run_store_path = identity
            .run_root
            .join("runtime-codex-agent-runs-v1.json");
        let run_coordinator = AgentRunCoordinator::open_durable(
            RuntimeComposition {
                agent_id: identity.agent_id.as_str().to_string(),
                supervisor_generation: identity.spawn_generation,
                agentd_generation: identity.spawn_generation,
                configuration_digest: Sha256Digest::for_bytes(configuration_material.as_bytes())
                    .as_str()
                    .to_string(),
                ports_digest: Sha256Digest::for_bytes(ports_material.as_bytes())
                    .as_str()
                    .to_string(),
                max_active_runs: usize::from(identity.resources.max_concurrent_turns),
            },
            run_store_path,
        )
        .map_err(run_error)?;
'''
    text = replace_once(text, old, new, "runtime-codex-agent-runs-v1.json")

    old = '''            if runtime.lifecycle == AgentLifecycle::Draining {
                self.runs
                    .lock()
                    .map_err(poisoned_state)?
                    .begin_drain(unix_now_ms()?, "supervisor_draining")
                    .map_err(run_error)?;
            }
'''
    new = '''            if runtime.lifecycle == AgentLifecycle::Draining {
                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                runs
                    .begin_drain(unix_now_ms()?, "supervisor_draining")
                    .map_err(run_error)?;
                runs.persist().map_err(run_error)?;
            }
'''
    text = replace_once(text, old, new, "runs.persist().map_err(run_error)?;")

    old = '''        self.runs
            .lock()
            .map_err(poisoned_state)?
            .begin_drain(unix_now_ms()?, "agentd_shutdown")
            .map_err(run_error)?;
        Ok(())
'''
    new = '''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        runs
            .begin_drain(unix_now_ms()?, "agentd_shutdown")
            .map_err(run_error)?;
        runs.persist().map_err(run_error)?;
        Ok(())
'''
    text = replace_once(text, old, new, "begin_drain(unix_now_ms()?, \"agentd_shutdown\")")

    old = '''        if let Ok(mut runs) = self.runs.lock() {
            runs.close_admissions();
            if let Ok(now_ms) = unix_now_ms() {
                let _ = runs.begin_drain(now_ms, "generation_fenced");
            }
            let _ = runs.mark_unresolved_indeterminate("generation_fenced");
        }
'''
    new = '''        if let Ok(mut runs) = self.runs.lock() {
            runs.close_admissions();
            if let Ok(now_ms) = unix_now_ms() {
                let _ = runs.begin_drain(now_ms, "generation_fenced");
            }
            let _ = runs.mark_unresolved_indeterminate("generation_fenced");
            let _ = runs.persist();
        }
'''
    text = replace_once(text, old, new, "let _ = runs.persist();")

    old = '''                let run_receipt = runs
                    .attach_context(
                        now_ms,
                        admitted.revision,
                        crate::ContextAttachment {
                            run_id: attachment.run_id,
                            request_digest: attachment.request_digest,
                            objective_digest: attachment.objective_digest,
                            body_digest: attachment.body_digest,
                            artifact_set_digest: attachment.artifact_set_digest,
                            authority_epoch: attachment.authority_epoch,
                            generation: attachment.generation,
                            fence_digest: attachment.fence_digest,
                            deadline_ms: attachment.deadline_ms,
                            context_digest: attachment.context_digest,
                            compilation_receipt_digest: attachment.compilation_receipt_digest,
                        },
                    )
                    .map_err(run_error)?;
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
'''
    new = '''                let run_receipt = runs
                    .attach_context(
                        now_ms,
                        admitted.revision,
                        crate::ContextAttachment {
                            run_id: attachment.run_id,
                            request_digest: attachment.request_digest,
                            objective_digest: attachment.objective_digest,
                            body_digest: attachment.body_digest,
                            artifact_set_digest: attachment.artifact_set_digest,
                            authority_epoch: attachment.authority_epoch,
                            generation: attachment.generation,
                            fence_digest: attachment.fence_digest,
                            deadline_ms: attachment.deadline_ms,
                            context_digest: attachment.context_digest,
                            compilation_receipt_digest: attachment.compilation_receipt_digest,
                        },
                    )
                    .map_err(run_error)?;
                runs.persist().map_err(run_error)?;
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
'''
    text = replace_once(text, old, new, "runs.persist().map_err(run_error)?;\n                Ok(Some")

    old = '''        self.runs
            .lock()
            .map_err(poisoned_state)?
            .start_revalidated_run_start(now_ms, record)
            .map_err(run_error)
'''
    new = '''        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let receipt = runs
            .start_revalidated_run_start(now_ms, record)
            .map_err(run_error)?;
        if !receipt.idempotent {
            runs.persist().map_err(run_error)?;
        }
        Ok(receipt)
'''
    text = replace_once(text, old, new, "let receipt = runs\n            .start_revalidated_run_start")

    old = '''    pub(crate) fn expire_run_deadlines(&self) -> Result<usize, AgentdError> {
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .expire_deadlines(unix_now_ms()?)
            .map_err(run_error)
    }
'''
    new = '''    pub(crate) fn expire_run_deadlines(&self) -> Result<usize, AgentdError> {
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let changed = runs
            .expire_deadlines(unix_now_ms()?)
            .map_err(run_error)?;
        if changed != 0 {
            runs.persist().map_err(run_error)?;
        }
        Ok(changed)
    }
'''
    text = replace_once(text, old, new, "let changed = runs")

    old = '''    pub(crate) fn mark_unresolved_runs_indeterminate(
        &self,
        reason: &str,
    ) -> Result<usize, AgentdError> {
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .mark_unresolved_indeterminate(reason)
            .map_err(run_error)
    }
'''
    new = '''    pub(crate) fn mark_unresolved_runs_indeterminate(
        &self,
        reason: &str,
    ) -> Result<usize, AgentdError> {
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let changed = runs
            .mark_unresolved_indeterminate(reason)
            .map_err(run_error)?;
        if changed != 0 {
            runs.persist().map_err(run_error)?;
        }
        Ok(changed)
    }
'''
    text = replace_once(text, old, new, "mark_unresolved_indeterminate(reason)\n            .map_err(run_error)?")
    return text


def lane_b_tests(text: str) -> str:
    if "durable_run_store_recovers_bound_abort_and_fences_stale_writer" in text:
        return text
    test = r'''

#[test]
fn durable_run_store_recovers_bound_abort_and_fences_stale_writer() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("agent-runs.json");
    let mut owner = AgentRunCoordinator::open_durable(composition(), path.clone())
        .expect("open durable owner");
    owner.start_run(100, snapshot()).expect("admit");
    owner.persist().expect("persist admission");
    owner
        .attach_context(200, 1, attachment())
        .expect("attach context");
    owner.persist().expect("persist context");

    let binding = digest('q');
    let nonce: [u8; 32] = rand::random();
    let nonce_hex = nonce
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let commitment = pre_effect_abort_commitment("run.1", &binding, &nonce);
    let reason = "final-use fence changed";
    let proof = pre_effect_abort_proof("run.1", &binding, &nonce, reason);
    let dispatched = owner
        .mark_dispatched_bound(300, "run.1", 2, binding.clone(), commitment.clone())
        .expect("bound dispatch");
    owner.persist().expect("persist dispatch");
    drop(owner);

    let mut current = AgentRunCoordinator::open_durable(composition(), path.clone())
        .expect("recover current owner");
    let mut stale = AgentRunCoordinator::open_durable(composition(), path.clone())
        .expect("open stale observer");
    let aborted = current
        .abort_before_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &nonce_hex,
            &proof,
            reason,
        )
        .expect("abort before effect");
    assert_eq!(aborted.phase, RunPhase::AbortedBeforeEffect);
    current.persist().expect("persist abort proof");

    stale
        .mark_unresolved_indeterminate("stale writer")
        .expect("mutate stale in-memory owner");
    assert!(matches!(
        stale.persist(),
        Err(AgentRunError::Persistence(_))
    ));
    drop(current);
    drop(stale);

    let recovered = AgentRunCoordinator::open_durable(composition(), path)
        .expect("recover exact aborted owner");
    let receipt = recovered.run("run.1").expect("retained run");
    assert_eq!(receipt.phase, RunPhase::AbortedBeforeEffect);
    assert_eq!(receipt.dispatch_binding_digest.as_deref(), Some(binding.as_str()));
    assert_eq!(
        receipt.pre_effect_abort_commitment_digest.as_deref(),
        Some(commitment.as_str())
    );
    assert_eq!(
        receipt.pre_effect_abort_proof_digest.as_deref(),
        Some(proof.as_str())
    );
}
'''
    return text + test


def main() -> None:
    rewrite("codex-rs/hepta-agentd/Cargo.toml", agentd_cargo)
    rewrite("codex-rs/hepta-agentd/src/lane_b_runtime.rs", lane_b_runtime)
    rewrite("codex-rs/hepta-agentd/src/state_control.rs", state_control)
    rewrite("codex-rs/hepta-agentd/src/state.rs", state)
    rewrite("codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs", lane_b_tests)


if __name__ == "__main__":
    main()

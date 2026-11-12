//! Bounded local shadow retention from the original TaskFlow owner.
//!
//! This is not a PRED numerical snapshot, arrival sequencer, independent effect
//! witness or authorization. The two owner reads are explicitly non-atomic.
//! Per-step event sequence and caller wall time keep their original meanings.
//! Unix retention uses create-only fixed slots and rejects linked/special files.
//! Other platforms report unavailable retention. Synchronous scans and fsync
//! can delay dispatch; complete physical cost and latency are not established.

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_contracts::Sha256Digest;
#[cfg(unix)]
use serde::Deserialize;
#[cfg(unix)]
use serde::Serialize;
use serde_json::Value;

#[cfg(unix)]
pub(crate) const SLOT_COUNT: usize = 64;
#[cfg(unix)]
pub(crate) const MAX_FACT_BYTES: usize = 64 * 1024;
#[cfg(unix)]
pub(crate) const DIRECTORY: &str = "predispatch-shadow-facts-v1";

#[cfg(unix)]
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredFact {
    schema_version: u32,
    semantic_sha256: Sha256Digest,
    fact_sha256: Sha256Digest,
    fact: Value,
}

/// Retain shadow facts through original owner APIs, including their existing
/// schema assurance; this is not a strictly read-only database probe. Retention
/// failures grant no authority and leave original authorization checks in place.
/// No provider bytes, grants or secrets enter
/// either the retained facts or the single bounded stderr status event.
pub(crate) async fn observe(
    store: &AutomationStore,
    intent: &AuthorizedEffectIntent,
    fence: &TaskFlowFence,
    caller_time_ms: u64,
) {
    let outcome = capture(store, intent, fence, caller_time_ms).await;
    let status = match outcome {
        Ok(status) => status,
        Err(()) => "unavailable",
    };
    eprintln!(
        "{{\"event\":\"predispatch_shadow_retention\",\"status\":\"{status}\",\"authority\":false}}"
    );
}

async fn capture(
    store: &AutomationStore,
    intent: &AuthorizedEffectIntent,
    fence: &TaskFlowFence,
    caller_time_ms: u64,
) -> Result<&'static str, ()> {
    let step = store
        .read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, fence)
        .await
        .map_err(|_| ())?
        .ok_or(())?;
    let digest = intent.digest().map_err(|_| ())?;
    if step.state != TaskFlowStepState::Claimed
        || step.intent_digest != digest
        || step.payload_digest != intent.payload_digest
        || step.owner_agent_id != *store.owner_agent_id()
    {
        return Err(());
    }
    if store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await
        .map_err(|_| ())?
        .is_some()
    {
        return Ok("existing_attempt_not_captured");
    }
    let fact = serde_json::json!({
        "schema": "hepta-native-predispatch-shadow-fact-v1",
        "owner_agent_id": store.owner_agent_id(),
        "intent": intent,
        "claimed_step": {
            "owner_agent_id": step.owner_agent_id, "run_id": step.run_id,
            "step_id": step.step_id, "attempt": step.attempt,
            "state": step.state, "event_seq": step.event_seq,
            "intent_digest": step.intent_digest, "payload_digest": step.payload_digest,
            "fence_sha256": Sha256Digest::for_bytes(&serde_json::to_vec(&step.fence).map_err(|_| ())?),
        },
        "caller_time_ms": caller_time_ms,
        "time_scope": "original caller wall-clock milliseconds; not monotonic availability",
        "sequence_scope": "claimed_step.event_seq is per-step; not a shared arrival cursor",
        "read_scope": "verified step read followed by separate dispatch-attempt absence read; not atomic",
        "owner_api_scope": "original step read includes schema assurance; not a strictly read-only database probe",
        "pending_attempt_at_second_read": false,
        "source_provenance_authenticated": false,
        "independent_effect_observed": false,
        "prediction_deployed": false,
        "physical_cost_complete": false,
        "storage_scope": "synchronous fixed-slot scan and file/directory fsync may delay dispatch; no complete cost claim",
        "authority": false,
    });
    retain(store.path().parent().ok_or(())?, fact)
}

#[cfg(unix)]
fn semantic_digest(fact: &Value) -> Result<Sha256Digest, ()> {
    let mut semantic = fact.clone();
    semantic.as_object_mut().ok_or(())?.remove("caller_time_ms");
    Ok(Sha256Digest::for_bytes(
        &serde_json::to_vec(&semantic).map_err(|_| ())?,
    ))
}

#[cfg(not(unix))]
fn retain(_owner_root: &std::path::Path, _fact: Value) -> Result<&'static str, ()> {
    Ok("unsupported_platform")
}

#[cfg(unix)]
fn retain(owner_root: &std::path::Path, fact: Value) -> Result<&'static str, ()> {
    SlotRoot::open(owner_root)?.retain(fact)
}

#[cfg(unix)]
struct SlotRoot(std::fs::File);

#[cfg(unix)]
impl SlotRoot {
    fn open(owner_root: &std::path::Path) -> Result<Self, ()> {
        use std::fs::OpenOptions;
        use std::os::fd::AsRawFd;
        use std::os::fd::FromRawFd;
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::OpenOptionsExt;

        let owner = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(owner_root)
            .map_err(|_| ())?;
        let name = std::ffi::CString::new(DIRECTORY).map_err(|_| ())?;
        // SAFETY: owner is an open directory and name is a live NUL-terminated
        // single-component path. All child IO remains relative to owned FDs.
        let created = unsafe { libc::mkdirat(owner.as_raw_fd(), name.as_ptr(), 0o700) };
        if created < 0
            && std::io::Error::last_os_error().kind() != std::io::ErrorKind::AlreadyExists
        {
            return Err(());
        }
        // SAFETY: same valid directory FD and owned C string as above.
        let raw = unsafe {
            libc::openat(
                owner.as_raw_fd(),
                name.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        };
        if raw < 0 {
            return Err(());
        }
        // SAFETY: successful openat returns a new owned descriptor exactly once.
        let directory = unsafe { std::fs::File::from_raw_fd(raw) };
        let metadata = directory.metadata().map_err(|_| ())?;
        if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
            return Err(());
        }
        if created == 0 {
            owner.sync_all().map_err(|_| ())?;
        }
        Ok(Self(directory))
    }

    fn slot(&self, index: usize, flags: i32) -> std::io::Result<std::fs::File> {
        use std::os::fd::AsRawFd;
        use std::os::fd::FromRawFd;

        let name = std::ffi::CString::new(format!("slot-{index:02}.json"))?;
        // SAFETY: self owns the directory FD, name is one validated component,
        // and mode is used only with O_CREAT. The returned FD is owned below.
        let raw = unsafe {
            libc::openat(
                self.0.as_raw_fd(),
                name.as_ptr(),
                flags | libc::O_NOFOLLOW | libc::O_CLOEXEC,
                0o600,
            )
        };
        if raw < 0 {
            return Err(std::io::Error::last_os_error());
        }
        // SAFETY: successful openat returned this new owned descriptor.
        Ok(unsafe { std::fs::File::from_raw_fd(raw) })
    }

    fn retain(&self, fact: Value) -> Result<&'static str, ()> {
        use std::io::Read;
        use std::io::Write;
        use std::os::unix::fs::MetadataExt;
        let semantic_sha256 = semantic_digest(&fact)?;
        let fact_sha256 = Sha256Digest::for_bytes(&serde_json::to_vec(&fact).map_err(|_| ())?);
        let encoded = serde_json::to_vec(&StoredFact {
            schema_version: 1,
            semantic_sha256: semantic_sha256.clone(),
            fact_sha256,
            fact,
        })
        .map_err(|_| ())?;
        if encoded.len() > MAX_FACT_BYTES {
            return Err(());
        }
        // Scan all fixed slots before using a vacancy, so draining a lower slot
        // cannot duplicate an already-retained immutable source identity.
        let mut vacant = Vec::new();
        let mut existing = false;
        for slot in 0..SLOT_COUNT {
            let mut file = match self.slot(slot, libc::O_RDONLY | libc::O_NONBLOCK) {
                Ok(file) => file,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    vacant.push(slot);
                    continue;
                }
                Err(_) => return Err(()),
            };
            let metadata = file.metadata().map_err(|_| ())?;
            if !metadata.is_file()
                || metadata.nlink() != 1
                || metadata.len() > MAX_FACT_BYTES as u64
                || metadata.mode() & 0o077 != 0
            {
                return Err(());
            }
            let mut bytes = Vec::new();
            Read::by_ref(&mut file)
                .take((MAX_FACT_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
                .map_err(|_| ())?;
            let retained: StoredFact = serde_json::from_slice(&bytes).map_err(|_| ())?;
            if bytes.len() > MAX_FACT_BYTES
                || retained.schema_version != 1
                || serde_json::to_vec(&retained).map_err(|_| ())? != bytes
                || semantic_digest(&retained.fact)? != retained.semantic_sha256
                || Sha256Digest::for_bytes(&serde_json::to_vec(&retained.fact).map_err(|_| ())?)
                    != retained.fact_sha256
            {
                return Err(());
            }
            if retained.semantic_sha256 == semantic_sha256 {
                existing = true;
            }
        }
        if existing {
            return Ok("retained_existing");
        }
        if let Some(slot) = vacant.first().copied() {
            match self.slot(slot, libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL) {
                Ok(mut file) => {
                    file.write_all(&encoded).map_err(|_| ())?;
                    file.sync_all().map_err(|_| ())?;
                    self.0.sync_all().map_err(|_| ())?;
                    return Ok("retained_new");
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    return Ok("concurrent_writer_not_retained");
                }
                Err(_) => return Err(()),
            }
        }
        Ok("capacity_full")
    }
}

#[cfg(all(test, unix))]
#[path = "automation_predispatch_export_tests.rs"]
mod tests;

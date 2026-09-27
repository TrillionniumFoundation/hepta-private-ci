#!/usr/bin/env python3
"""Apply runtime.codex security, clock, metrics, and stress convergence."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n" + addition)


def run_phase2() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/runtime-codex-converge-phase2.py")],
        cwd=ROOT,
        check=True,
    )


def patch_final_use_authorizer() -> None:
    path = "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs"
    replace_once(
        path,
        "use std::time::Duration;\n",
        "use std::time::Duration;\n\nuse sha2::Digest as _;\nuse sha2::Sha256;\n",
    )
    replace_once(
        path,
        '''/// Protected host configuration for the independent final-use authority port.
''',
        r'''/// Optional target-host process identity pins. Signature verification remains
/// mandatory even when all process pins are present.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IssuerProcessIdentity {
    #[serde(default)]
    pub executable_sha256: Option<[u8; 32]>,
    #[serde(default)]
    pub boot_id: Option<String>,
    #[serde(default)]
    pub cgroup_sha256: Option<[u8; 32]>,
    #[serde(default)]
    pub start_time_ticks: Option<u64>,
}

impl IssuerProcessIdentity {
    fn is_pinned(&self) -> bool {
        self.executable_sha256.is_some()
            || self.boot_id.is_some()
            || self.cgroup_sha256.is_some()
            || self.start_time_ticks.is_some()
    }
}

/// Protected host configuration for the independent final-use authority port.
''',
    )
    replace_once(
        path,
        '''    pub issuer_uid: u32,
    pub signer_id: String,
''',
        '''    pub issuer_uid: u32,
    #[serde(default)]
    pub issuer_process_identity: IssuerProcessIdentity,
    pub signer_id: String,
''',
    )
    replace_once(
        path,
        '''    issuer_uid: u32,
    issuer_timeout: Duration,
''',
        '''    issuer_uid: u32,
    issuer_process_identity: IssuerProcessIdentity,
    issuer_timeout: Duration,
''',
    )
    replace_once(
        path,
        '''        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
''',
        '''        validate_process_identity_configuration(&config.issuer_process_identity)?;
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
''',
    )
    replace_once(
        path,
        '''            issuer_uid: config.issuer_uid,
            issuer_timeout,
''',
        '''            issuer_uid: config.issuer_uid,
            issuer_process_identity: config.issuer_process_identity,
            issuer_timeout,
''',
    )
    replace_once(
        path,
        '''        validate_issuer_socket(&self.issuer_socket, self.issuer_uid)?;
        let request = IssuerRequest {
''',
        '''        let expected_socket =
            validate_issuer_socket(&self.issuer_socket, self.issuer_uid)?;
        let request = IssuerRequest {
''',
    )
    replace_once(
        path,
        '''            let peer = stream.peer_cred()?;
            validate_issuer_peer_uid(peer.uid(), self.issuer_uid)?;
            stream.write_all(&request_len.to_be_bytes()).await?;
''',
        '''            let peer = stream.peer_cred()?;
            validate_issuer_peer_uid(peer.uid(), self.issuer_uid)?;
            validate_issuer_process_identity(peer.pid(), &self.issuer_process_identity)?;
            let connected_socket =
                validate_issuer_socket(&self.issuer_socket, self.issuer_uid)?;
            if connected_socket != expected_socket {
                return Err::<Vec<u8>, Box<dyn StdError + Send + Sync>>(
                    "final-use authority socket identity changed during connect".into(),
                );
            }
            stream.write_all(&request_len.to_be_bytes()).await?;
''',
    )
    replace_once(
        path,
        '''#[cfg(unix)]
fn validate_issuer_socket(path: &Path, issuer_uid: u32) -> Result<()> {
''',
        '''#[cfg(unix)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct SocketIdentity {
    device: u64,
    inode: u64,
}

#[cfg(unix)]
fn validate_issuer_socket(path: &Path, issuer_uid: u32) -> Result<SocketIdentity> {
''',
    )
    replace_once(
        path,
        '''    let parent = path
        .parent()
        .ok_or("final-use authority socket has no parent directory")?;
    let parent_metadata = std::fs::symlink_metadata(parent)?;
    if !parent_metadata.is_dir() || parent_metadata.mode() & 0o022 != 0 {
        return Err(
            "final-use authority socket parent directory is writable by an unsafe principal".into(),
        );
    }
    Ok(())
}
''',
        r'''    let parent = path
        .parent()
        .ok_or("final-use authority socket has no parent directory")?;
    validate_secure_parent_chain(parent, issuer_uid)?;
    Ok(SocketIdentity {
        device: metadata.dev(),
        inode: metadata.ino(),
    })
}

#[cfg(unix)]
fn validate_secure_parent_chain(path: &Path, issuer_uid: u32) -> Result<()> {
    use std::os::unix::fs::MetadataExt;

    let effective_uid = rustix::process::geteuid().as_raw();
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() {
            return Err("final-use authority socket path contains a non-directory".into());
        }
        let mode = metadata.mode();
        let writable = mode & 0o022 != 0;
        let protected_sticky_root = metadata.uid() == 0 && mode & 0o1000 != 0;
        if writable && !protected_sticky_root {
            return Err(
                "final-use authority socket parent chain is writable by an unsafe principal"
                    .into(),
            );
        }
        if metadata.uid() != 0
            && metadata.uid() != issuer_uid
            && metadata.uid() != effective_uid
        {
            return Err(
                "final-use authority socket parent chain has an unexpected owner".into(),
            );
        }
    }
    Ok(())
}

fn validate_process_identity_configuration(identity: &IssuerProcessIdentity) -> Result<()> {
    if identity.boot_id.as_ref().is_some_and(|value| {
        value.is_empty()
            || value.len() > 128
            || value.bytes().any(|byte| byte.is_ascii_control())
    }) || identity.start_time_ticks == Some(0)
    {
        return Err("invalid final-use issuer process identity configuration".into());
    }
    #[cfg(not(target_os = "linux"))]
    if identity.is_pinned() {
        return Err(
            "final-use issuer process identity pins currently require Linux".into(),
        );
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn validate_issuer_process_identity(
    peer_pid: Option<u32>,
    expected: &IssuerProcessIdentity,
) -> Result<()> {
    if !expected.is_pinned() {
        return Ok(());
    }
    let pid = peer_pid.ok_or("final-use authority peer omitted its process identity")?;
    let proc_root = PathBuf::from(format!("/proc/{pid}"));
    if let Some(expected_digest) = expected.executable_sha256 {
        let actual = sha256_path(&proc_root.join("exe"))?;
        if actual != expected_digest {
            return Err("final-use authority executable identity mismatch".into());
        }
    }
    if let Some(expected_boot_id) = expected.boot_id.as_deref() {
        let actual = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
        if actual.trim() != expected_boot_id {
            return Err("final-use authority boot identity mismatch".into());
        }
    }
    if let Some(expected_digest) = expected.cgroup_sha256 {
        let actual = Sha256::digest(std::fs::read(proc_root.join("cgroup"))?);
        if actual.as_slice() != expected_digest {
            return Err("final-use authority cgroup identity mismatch".into());
        }
    }
    if let Some(expected_ticks) = expected.start_time_ticks {
        let actual = linux_process_start_time_ticks(&proc_root.join("stat"))?;
        if actual != expected_ticks {
            return Err("final-use authority process start identity mismatch".into());
        }
    }
    Ok(())
}

#[cfg(all(unix, not(target_os = "linux")))]
fn validate_issuer_process_identity(
    _peer_pid: Option<u32>,
    expected: &IssuerProcessIdentity,
) -> Result<()> {
    if expected.is_pinned() {
        Err("final-use issuer process identity pins require Linux".into())
    } else {
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn sha256_path(path: &Path) -> Result<[u8; 32]> {
    let mut file = std::fs::File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(digest.finalize().into())
}

#[cfg(target_os = "linux")]
fn linux_process_start_time_ticks(path: &Path) -> Result<u64> {
    let stat = std::fs::read_to_string(path)?;
    let close = stat
        .rfind(')')
        .ok_or("invalid Linux process stat identity")?;
    let fields = stat
        .get(close + 1..)
        .ok_or("invalid Linux process stat suffix")?
        .split_whitespace()
        .collect::<Vec<_>>();
    // The suffix starts at field 3; process start time is field 22.
    fields
        .get(19)
        .ok_or("Linux process stat omitted start time")?
        .parse()
        .map_err(Into::into)
}
''',
    )

    # Existing in-repository struct literals explicitly choose no process pin;
    # target-host configuration must provide pins to claim that property.
    tests = "codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs"
    replace_once(
        tests,
        '''        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "authority-owner".to_string(),
''',
        '''        issuer_uid: rustix::process::geteuid().as_raw(),
        issuer_process_identity: IssuerProcessIdentity::default(),
        signer_id: "authority-owner".to_string(),
''',
    )
    e2e = "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs"
    replace_once(
        e2e,
        '''        issuer_uid,
        signer_id: "authority-owner".to_string(),
''',
        '''        issuer_uid,
        issuer_process_identity: Default::default(),
        signer_id: "authority-owner".to_string(),
''',
    )
    append_once(
        tests,
        "fn linux_peer_process_identity_pins_detect_drift()",
        r'''

#[cfg(target_os = "linux")]
#[test]
fn linux_peer_process_identity_pins_detect_drift() -> Result<()> {
    let pid = std::process::id();
    let proc_root = PathBuf::from(format!("/proc/{pid}"));
    let executable_sha256 = sha256_path(&proc_root.join("exe"))?;
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
        .trim()
        .to_string();
    let cgroup_sha256: [u8; 32] =
        Sha256::digest(std::fs::read(proc_root.join("cgroup"))?).into();
    let start_time_ticks = linux_process_start_time_ticks(&proc_root.join("stat"))?;
    let exact = IssuerProcessIdentity {
        executable_sha256: Some(executable_sha256),
        boot_id: Some(boot_id),
        cgroup_sha256: Some(cgroup_sha256),
        start_time_ticks: Some(start_time_ticks),
    };
    validate_issuer_process_identity(Some(pid), &exact)?;

    let mut wrong = exact.clone();
    wrong.executable_sha256 = Some([0x55; 32]);
    assert!(validate_issuer_process_identity(Some(pid), &wrong).is_err());
    assert!(validate_issuer_process_identity(None, &exact).is_err());
    Ok(())
}
''',
    )


def patch_monotonic_deadline_and_metrics() -> None:
    path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
    replace_once(
        path,
        "use std::sync::Arc;\n",
        "use std::sync::Arc;\nuse std::sync::atomic::AtomicU64;\n"
        "use std::sync::atomic::Ordering;\n",
    )
    replace_once(
        path,
        '''const LOCAL_DEADLINE_ELAPSED: &str = "deadline elapsed";
''',
        r'''const LOCAL_DEADLINE_ELAPSED: &str = "deadline elapsed";
const MAX_WALL_CLOCK_ROLLBACK: Duration = Duration::from_secs(2);

static ABORT_PENDING_TOTAL: AtomicU64 = AtomicU64::new(0);
static ABORT_RECONCILE_ATTEMPT_TOTAL: AtomicU64 = AtomicU64::new(0);
static ABORT_RECONCILE_CONFLICT_TOTAL: AtomicU64 = AtomicU64::new(0);
static ORPHAN_THREAD_CLEANUP_TOTAL: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct RuntimeCodexMetricsSnapshot {
    pub abort_pending_total: u64,
    pub abort_reconcile_attempt_total: u64,
    pub abort_reconcile_conflict_total: u64,
    pub orphan_thread_cleanup_total: u64,
}

pub fn runtime_codex_metrics_snapshot() -> RuntimeCodexMetricsSnapshot {
    RuntimeCodexMetricsSnapshot {
        abort_pending_total: ABORT_PENDING_TOTAL.load(Ordering::Relaxed),
        abort_reconcile_attempt_total: ABORT_RECONCILE_ATTEMPT_TOTAL.load(Ordering::Relaxed),
        abort_reconcile_conflict_total: ABORT_RECONCILE_CONFLICT_TOTAL.load(Ordering::Relaxed),
        orphan_thread_cleanup_total: ORPHAN_THREAD_CLEANUP_TOTAL.load(Ordering::Relaxed),
    }
}
''',
    )
    replace_once(
        path,
        '''        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;
        let dispatch_binding_digest = request_receipt.request_digest.to_string();
''',
        '''        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;
        let runtime_deadline = RuntimeDeadline::new(adapted_at_ms, adapter_intent.deadline_ms)?;
        let dispatch_binding_digest = request_receipt.request_digest.to_string();
''',
    )
    replace_once(
        path,
        '''        let claim_budget = remaining_before(adapter_intent.deadline_ms)?;
''',
        '''        let claim_budget = runtime_deadline.remaining()?;
''',
    )
    replace_once(
        path,
        '''            unix_time_ms()?,
            adapter_intent.deadline_ms,
''',
        '''            runtime_deadline.checked_wall_now_ms()?,
            adapter_intent.deadline_ms,
''',
    )
    replace_once(
        path,
        '''        let send_budget = remaining_before(adapter_intent.deadline_ms)?.min(RPC_TIMEOUT);
''',
        '''        let send_budget = runtime_deadline.remaining()?.min(RPC_TIMEOUT);
''',
    )
    replace_once(
        path,
        '''        let deadline =
            Instant::now() + observation_budget_from(unix_time_ms()?, binding.intent.deadline_ms);
''',
        '''        let deadline = runtime_deadline.instant_deadline();
''',
    )
    replace_once(
        path,
        '''        let pending = control.prepare_native_abort_before_effect(
''',
        '''        ABORT_PENDING_TOTAL.fetch_add(1, Ordering::Relaxed);
        let pending = control.prepare_native_abort_before_effect(
''',
    )
    replace_once(
        path,
        '''async fn reconcile_owner_abort(
    owner: &AgentdClient,
    abort: &NativePreEffectAbortRecord,
) -> Result<codex_hepta_agentd::AgentRunReceipt> {
    match owner
''',
        '''async fn reconcile_owner_abort(
    owner: &AgentdClient,
    abort: &NativePreEffectAbortRecord,
) -> Result<codex_hepta_agentd::AgentRunReceipt> {
    ABORT_RECONCILE_ATTEMPT_TOTAL.fetch_add(1, Ordering::Relaxed);
    match owner
''',
    )
    replace_once(
        path,
        '''            owner
                .run_abort_before_effect(
''',
        '''            ABORT_RECONCILE_CONFLICT_TOTAL.fetch_add(1, Ordering::Relaxed);
            owner
                .run_abort_before_effect(
''',
    )
    replace_once(
        path,
        '''    let _ = timeout(
        RPC_TIMEOUT,
        client.request(ClientRequest::ThreadUnsubscribe {
''',
        '''    let cleanup = timeout(
        RPC_TIMEOUT,
        client.request(ClientRequest::ThreadUnsubscribe {
''',
    )
    replace_once(
        path,
        '''    )
    .await;
    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
}

fn final_use_binding(
''',
        '''    )
    .await;
    if !matches!(cleanup, Ok(Ok(_))) {
        ORPHAN_THREAD_CLEANUP_TOTAL.fetch_add(1, Ordering::Relaxed);
    }
    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
}

fn final_use_binding(
''',
    )
    replace_once(
        path,
        '''fn remaining_before(deadline_ms: u64) -> Result<Duration> {
    let now_ms = unix_time_ms()?;
    if now_ms >= deadline_ms {
        return Err("runtime.codex request deadline elapsed before effect entry".into());
    }
    Ok(Duration::from_millis(deadline_ms - now_ms))
}

fn observation_budget_from(now_ms: u64, deadline_ms: u64) -> Duration {
    Duration::from_millis(deadline_ms.saturating_sub(now_ms))
}
''',
        r'''struct RuntimeDeadline {
    wall_anchor_ms: u64,
    instant_anchor: Instant,
    wall_deadline_ms: u64,
    instant_deadline: Instant,
}

impl RuntimeDeadline {
    fn new(wall_anchor_ms: u64, wall_deadline_ms: u64) -> Result<Self> {
        let budget_ms = wall_deadline_ms
            .checked_sub(wall_anchor_ms)
            .filter(|value| *value > 0)
            .ok_or("runtime.codex request deadline elapsed before effect entry")?;
        let instant_anchor = Instant::now();
        let instant_deadline = instant_anchor + Duration::from_millis(budget_ms);
        Ok(Self {
            wall_anchor_ms,
            instant_anchor,
            wall_deadline_ms,
            instant_deadline,
        })
    }

    fn checked_wall_now_ms(&self) -> Result<u64> {
        let actual = unix_time_ms()?;
        let elapsed_ms = u64::try_from(self.instant_anchor.elapsed().as_millis())
            .map_err(|_| "runtime.codex monotonic elapsed time overflow")?;
        let monotonic_projection = self
            .wall_anchor_ms
            .checked_add(elapsed_ms)
            .ok_or("runtime.codex monotonic wall projection overflow")?;
        validate_wall_clock_progress(monotonic_projection, actual)?;
        Ok(actual)
    }

    fn remaining(&self) -> Result<Duration> {
        self.checked_wall_now_ms()?;
        let now = Instant::now();
        if now >= self.instant_deadline {
            return Err("runtime.codex request deadline elapsed before effect entry".into());
        }
        Ok(self.instant_deadline - now)
    }

    fn instant_deadline(&self) -> Instant {
        self.instant_deadline
    }
}

fn validate_wall_clock_progress(monotonic_projection_ms: u64, actual_wall_ms: u64) -> Result<()> {
    let tolerated_rollback_ms = u64::try_from(MAX_WALL_CLOCK_ROLLBACK.as_millis())
        .map_err(|_| "runtime.codex wall-clock tolerance overflow")?;
    if actual_wall_ms.saturating_add(tolerated_rollback_ms) < monotonic_projection_ms {
        return Err("runtime.codex wall clock rolled backward during final-use".into());
    }
    Ok(())
}
''',
    )
    append_once(
        "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
        "fn wall_clock_rollback_is_fail_closed()",
        r'''

#[test]
fn wall_clock_rollback_is_fail_closed() {
    assert!(validate_wall_clock_progress(10_000, 10_000).is_ok());
    assert!(validate_wall_clock_progress(10_000, 8_000).is_ok());
    assert!(validate_wall_clock_progress(10_001, 8_000).is_err());
}
''',
    )


def patch_owner_stress_tests() -> None:
    path = "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs"
    append_once(
        path,
        "fn competing_bound_dispatches_and_stale_abort_cannot_steal_ownership()",
        r'''

#[test]
fn competing_bound_dispatches_and_stale_abort_cannot_steal_ownership() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");
    let binding = digest('a');
    let nonce = [7_u8; 32];
    let nonce_hex = nonce
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let commitment = pre_effect_abort_commitment("run.1", &binding, &nonce);
    let dispatched = coordinator
        .mark_dispatched_bound(300, "run.1", 2, binding.clone(), commitment.clone())
        .expect("first worker dispatch");

    assert_eq!(
        coordinator.mark_dispatched_bound(
            301,
            "run.1",
            2,
            binding.clone(),
            digest('b'),
        ),
        Err(AgentRunError::Conflict)
    );
    assert_eq!(
        coordinator.abort_before_effect(
            "run.1",
            2,
            &binding,
            &nonce_hex,
            &pre_effect_abort_proof("run.1", &binding, &nonce, "stop"),
            "stop",
        ),
        Err(AgentRunError::StaleRevision)
    );

    let proof = pre_effect_abort_proof("run.1", &binding, &nonce, "stop");
    let aborted = coordinator
        .abort_before_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &nonce_hex,
            &proof,
            "stop",
        )
        .expect("exact worker abort");
    assert_eq!(aborted.phase, RunPhase::AbortedBeforeEffect);
    assert_eq!(coordinator.active_run_count(), 0);
    assert_eq!(
        coordinator.abort_before_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &nonce_hex,
            &digest('c'),
            "stop",
        ),
        Err(AgentRunError::Conflict)
    );
}
''',
    )


def main() -> None:
    run_phase2()
    patch_final_use_authorizer()
    patch_monotonic_deadline_and_metrics()
    patch_owner_stress_tests()


if __name__ == "__main__":
    main()

#![forbid(unsafe_code)]

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Result;
use pretty_assertions::assert_eq;

#[path = "../src/shell_runtime.rs"]
mod shell_runtime;
#[path = "../src/platform_adapter.rs"]
mod platform_adapter;

use platform_adapter::DurablePlatformAdapter;
use platform_adapter::EffectExecutor;
use platform_adapter::EffectResult;
use platform_adapter::NativePlatform;
use platform_adapter::PlatformPolicy;
use platform_adapter::platform_matrix;
use shell_runtime::PlatformAction;
use shell_runtime::PlatformAdapter;
use shell_runtime::PlatformRequest;
use shell_runtime::ReconcileObservation;
use shell_runtime::SessionKey;
use shell_runtime::TerminalStatus;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const D2: &str = "2222222222222222222222222222222222222222222222222222222222222222";

#[derive(Clone)]
struct FixtureExecutor {
    state: Arc<Mutex<(VecDeque<EffectResult>, usize)>>,
}

impl FixtureExecutor {
    fn new(results: impl IntoIterator<Item = EffectResult>) -> Self {
        Self {
            state: Arc::new(Mutex::new((results.into_iter().collect(), 0))),
        }
    }

    fn calls(&self) -> usize {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .1
    }
}

impl EffectExecutor for FixtureExecutor {
    fn execute(
        &self,
        _platform: NativePlatform,
        _request: &PlatformRequest,
    ) -> Result<EffectResult> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        state.1 += 1;
        Ok(state.0.pop_front().unwrap_or(EffectResult::Indeterminate))
    }
}

fn journal_path(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after unix epoch")
        .as_nanos();
    std::env::temp_dir().join(format!("hepta-native-{name}-{nonce}.journal"))
}

fn session() -> SessionKey {
    SessionKey {
        session_id: "session.1".to_string(),
        generation: 3,
    }
}

fn request(digest: &str) -> PlatformRequest {
    PlatformRequest {
        operation_id: "operation.1".to_string(),
        action: PlatformAction::OpenPath,
        resource: "/tmp/hepta".to_string(),
        displayed_revision: 11,
        payload_digest: digest.to_string(),
        grant: "fixture-grant".to_string(),
    }
}

#[test]
fn platform_matrix_is_explicit_for_all_launch_targets() {
    assert_eq!(
        platform_matrix(NativePlatform::Windows),
        platform_adapter::PlatformMatrix {
            platform: NativePlatform::Windows,
            open_path: true,
            reveal_path: true,
            copy_text: true,
            notify: false,
        }
    );
    assert_eq!(platform_matrix(NativePlatform::Macos).notify, true);
    assert_eq!(platform_matrix(NativePlatform::Linux).notify, true);
    assert_eq!(platform_matrix(NativePlatform::Unsupported).open_path, false);
}

#[test]
fn terminal_effect_is_durable_and_reconciles_after_reopen() -> Result<()> {
    let path = journal_path("terminal");
    let executor = FixtureExecutor::new([EffectResult::Terminal(TerminalStatus::Succeeded)]);
    let adapter = DurablePlatformAdapter::open(
        NativePlatform::Linux,
        PlatformPolicy::allow([PlatformAction::OpenPath]),
        executor.clone(),
        path.clone(),
    )?;
    assert_eq!(adapter.reconcile(&session(), &request(D1))?, ReconcileObservation::NotFound);
    adapter.invoke(&session(), &request(D1))?;
    assert_eq!(executor.calls(), 1);
    drop(adapter);

    let reopened = DurablePlatformAdapter::open(
        NativePlatform::Linux,
        PlatformPolicy::allow([PlatformAction::OpenPath]),
        FixtureExecutor::new([]),
        path.clone(),
    )?;
    assert_eq!(
        reopened.reconcile(&session(), &request(D1))?,
        ReconcileObservation::Terminal {
            status: TerminalStatus::Succeeded,
            outcome_digest: D1.to_string(),
        }
    );
    std::fs::remove_file(path)?;
    Ok(())
}

#[test]
fn uncertain_effect_stays_indeterminate_across_process_restart() -> Result<()> {
    let path = journal_path("indeterminate");
    let executor = FixtureExecutor::new([EffectResult::Indeterminate]);
    let adapter = DurablePlatformAdapter::open(
        NativePlatform::Macos,
        PlatformPolicy::allow([PlatformAction::OpenPath]),
        executor.clone(),
        path.clone(),
    )?;
    adapter.invoke(&session(), &request(D1))?;
    assert_eq!(executor.calls(), 1);
    drop(adapter);

    let reopened_executor = FixtureExecutor::new([EffectResult::Terminal(TerminalStatus::Succeeded)]);
    let reopened = DurablePlatformAdapter::open(
        NativePlatform::Macos,
        PlatformPolicy::allow([PlatformAction::OpenPath]),
        reopened_executor.clone(),
        path.clone(),
    )?;
    assert_eq!(
        reopened.reconcile(&session(), &request(D1))?,
        ReconcileObservation::Indeterminate
    );
    assert_eq!(reopened_executor.calls(), 0);
    std::fs::remove_file(path)?;
    Ok(())
}

#[test]
fn durable_operation_rejects_payload_drift() -> Result<()> {
    let path = journal_path("drift");
    let adapter = DurablePlatformAdapter::open(
        NativePlatform::Linux,
        PlatformPolicy::allow([PlatformAction::OpenPath]),
        FixtureExecutor::new([EffectResult::Indeterminate]),
        path.clone(),
    )?;
    adapter.invoke(&session(), &request(D1))?;
    let error = adapter.reconcile(&session(), &request(D2)).unwrap_err();
    assert!(error.to_string().contains("changed payload"));
    std::fs::remove_file(path)?;
    Ok(())
}

#[test]
fn permission_policy_is_closed_by_default() -> Result<()> {
    let path = journal_path("permission");
    let adapter = DurablePlatformAdapter::open(
        NativePlatform::Linux,
        PlatformPolicy::default(),
        FixtureExecutor::new([]),
        path.clone(),
    )?;
    assert_eq!(
        adapter.permission(&request(D1))?,
        shell_runtime::PermissionDecision::Denied {
            outcome_digest: D1.to_string(),
        }
    );
    assert!(!path.exists());
    Ok(())
}

#[cfg(unix)]
#[test]
fn group_or_world_readable_journal_fails_closed() -> Result<()> {
    use std::os::unix::fs::PermissionsExt;

    let path = journal_path("permissions");
    std::fs::write(&path, "")?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644))?;
    let error = match DurablePlatformAdapter::open(
        NativePlatform::Linux,
        PlatformPolicy::default(),
        FixtureExecutor::new([]),
        path.clone(),
    ) {
        Ok(_) => panic!("insecure journal unexpectedly opened"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("group/world"));
    std::fs::remove_file(path)?;
    Ok(())
}

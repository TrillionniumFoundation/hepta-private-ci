use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use crate::RuntimeStateStatus;

#[derive(Debug)]
struct ObservedAdapter(Arc<AtomicUsize>);

impl RuntimeStateAdapter for ObservedAdapter {
    fn status(&self) -> RuntimeStateStatus {
        self.0.fetch_add(1, Ordering::SeqCst);
        RuntimeStateStatus {
            adapter: "observed-test-adapter",
            schema_version: 5,
            outcome_generation: 3,
            preference_generation: 4,
            runtime_snapshot_version: 1,
            runtime_snapshot_generation: 9,
            integrity_binding_present: true,
            integrity_verification: "test-only",
            open_mode: "read-only-test",
        }
    }
}

#[test]
fn live_status_request_traverses_the_initialized_graph() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-organ-request"))?;
    let runtime =
        crate::HeptaRuntime::from_adapter(root, Arc::new(ObservedAdapter(Arc::clone(&calls))));
    // Opening a host must not pretend to have observed a request or outcome.
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let report: serde_json::Value = serde_json::from_slice(&runtime.status_json()?)?;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(report["state"]["runtime_snapshot_generation"], 9);
    assert_eq!(
        report["authority"],
        serde_json::to_value(RuntimeAuthorityStatus::default())?
    );
    assert_eq!(runtime.clone().status_json()?, runtime.status_json()?);
    assert_eq!(calls.load(Ordering::SeqCst), 3);
    Ok(())
}

#[test]
fn busy_or_stopped_hosts_never_bypass_dispatch() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-organ-stopped"))?;
    let organs = RuntimeOrgans::new(root, Arc::new(ObservedAdapter(Arc::clone(&calls))));
    let mut guard = organs
        .host
        .lock()
        .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
    assert!(organs.status_json().is_err());
    let host = guard.as_mut().map_err(|error| anyhow::anyhow!("{error}"))?;
    host.host.stop_all()?;
    drop(guard);
    assert!(organs.status_json().is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    Ok(())
}

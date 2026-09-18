use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use crate::RuntimeStateStatus;
use codex_hepta_wire::WireEnvelopeV2;

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

#[test]
fn status_consumer_checks_the_complete_hierarchy_without_direct_adapter_fallback() -> Result<()> {
    for case in 0..5 {
        let calls = Arc::new(AtomicUsize::new(0));
        let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-hierarchy-route"))?;
        let organs = RuntimeOrgans::new(root, Arc::new(ObservedAdapter(Arc::clone(&calls))));
        let original = {
            let mut guard = organs
                .host
                .lock()
                .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
            let host = guard.as_mut().map_err(|error| anyhow::anyhow!("{error}"))?;
            let original = host.route.clone();
            match case {
                0 => host.route.cns = StableId::new("other.cns")?,
                1 => host.route.source.system = StableId::new("other.system")?,
                2 => host.route.source.driver = StableId::new("other.driver")?,
                3 => host.route.targets[0].driver = StableId::new("other.target.driver")?,
                4 => host.route.generation = host.route.generation.next()?,
                _ => unreachable!(),
            }
            original
        };
        assert!(organs.status_json().is_err(), "case {case}");
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        {
            let mut guard = organs
                .host
                .lock()
                .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
            let host = guard.as_mut().map_err(|error| anyhow::anyhow!("{error}"))?;
            host.route = original;
        }
        let report: serde_json::Value = serde_json::from_slice(&organs.status_json()?)?;
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(report["state"]["runtime_snapshot_generation"], 9);
    }
    Ok(())
}

#[test]
fn live_status_wire_v2_wraps_one_exact_status_observation() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-organ-wire-request"))?;
    let runtime =
        crate::HeptaRuntime::from_adapter(root, Arc::new(ObservedAdapter(Arc::clone(&calls))));

    let frame = runtime.status_wire_v2()?;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let envelope = WireEnvelopeV2::decode(&frame)?;
    assert_eq!(
        envelope.schema().as_str(),
        crate::RUNTIME_STATUS_WIRE_SCHEMA
    );
    assert_eq!(
        envelope.producer().as_str(),
        crate::RUNTIME_STATUS_WIRE_PRODUCER
    );
    assert_eq!(
        envelope.generation().get(),
        crate::RUNTIME_STATUS_WIRE_GENERATION
    );
    let report: serde_json::Value = serde_json::from_slice(envelope.payload())?;
    assert_eq!(report["state"]["runtime_snapshot_generation"], 9);
    assert_eq!(
        report["authority"],
        serde_json::to_value(RuntimeAuthorityStatus::default())?
    );
    Ok(())
}

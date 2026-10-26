//! Ordinary protocol/lifecycle tests confer no actual-Root qualification.
use super::*;

fn request(instance: RootAdminInstance) -> RootAdminRequest {
    RootAdminRequest {
        schema_version: 1,
        expected_instance: instance,
        action: RootAdminAction::Observe {},
    }
}

fn capability() -> io::Result<(RootAdminRuntime, RootAdminCapability)> {
    let mut instance = RootAdminInstance::current()?;
    instance.episode_nonce = [17; 32];
    let life = Arc::new(Lifetime {
        serving: AtomicBool::new(false),
        closed: AtomicBool::new(false),
        instance: instance.clone(),
    });
    let (sender, receiver) = mpsc::sync_channel(1);
    Ok((
        RootAdminRuntime {
            life: Arc::clone(&life),
            receiver: std::sync::Mutex::new(receiver),
        },
        RootAdminCapability {
            lifetime: Arc::downgrade(&life),
            sender,
            instance,
            timeout: Duration::from_millis(100),
        },
    ))
}

#[test]
fn capability_does_not_retain_dropped_or_inactive_original_runtime() -> io::Result<()> {
    let (runtime, capability) = capability()?;
    let request = request(capability.instance.clone());
    assert!(capability.request_lifetime(&request).is_err());
    runtime.activate()?;
    assert!(capability.request_lifetime(&request).is_ok());
    drop(runtime);
    assert!(capability.lifetime.upgrade().is_none());
    assert!(capability.request_lifetime(&request).is_err());
    Ok(())
}

#[test]
fn live_route_rejects_each_changed_root_lifetime_and_nonce() -> io::Result<()> {
    let (runtime, capability) = capability()?;
    runtime.activate()?;
    for field in 0..4 {
        let mut other = capability.instance.clone();
        match field {
            0 => other.root_pid = other.root_pid.saturating_add(1),
            1 => other.process_start_ticks = other.process_start_ticks.saturating_add(1),
            2 => other.boot_id.push('x'),
            3 => other.episode_nonce[0] ^= 1,
            _ => unreachable!(),
        }
        assert!(capability.request_lifetime(&request(other)).is_err());
    }
    assert!(
        capability
            .request_lifetime(&request(capability.instance.clone()))
            .is_ok()
    );
    Ok(())
}

#[test]
fn strict_admin_schema_rejects_duplicate_unknown_and_oversized_inputs()
-> Result<(), Box<dyn std::error::Error>> {
    let (_, capability) = capability()?;
    let good = serde_json::to_string(&request(capability.instance.clone()))?;
    assert!(decode(good.as_bytes()).is_ok());
    for invalid in [
        good.replace(
            "\"schema_version\":1",
            "\"schema_version\":1,\"schema_version\":1",
        ),
        good.replace("\"schema_version\":1", "\"schema_version\":2"),
        good.replace("\"schema_version\":1", "\"schema_version\":1,\"extra\":1"),
        good.replace(
            "\"kind\":\"observe\"",
            "\"kind\":\"observe\",\"kind\":\"observe\"",
        ),
        good.replace(
            "\"kind\":\"observe\"",
            "\"kind\":\"observe\",\"expected_revision\":1",
        ),
        good.replace("\"root_pid\":", "\"other\":1,\"root_pid\":"),
        " ".repeat(ROOT_ADMIN_FRAME_BOUND + 1),
        String::new(),
    ] {
        assert!(decode(invalid.as_bytes()).is_err(), "accepted {invalid}");
    }
    Ok(())
}

#[test]
fn paused_or_ended_route_cannot_be_reactivated_by_capability() -> io::Result<()> {
    let (runtime, capability) = capability()?;
    runtime.activate()?;
    let stopping = AtomicBool::new(false);
    drop(Stop(&runtime.life, &stopping));
    assert!(stopping.load(Ordering::Acquire));
    assert!(runtime.activate().is_err());
    assert!(
        capability
            .request_lifetime(&request(capability.instance.clone()))
            .is_err()
    );
    assert!(!runtime.life.serving.load(Ordering::Acquire));
    Ok(())
}

#[test]
fn observed_current_root_identity_refuses_zero_nonce_and_changed_birth() -> io::Result<()> {
    let mut actual = RootAdminInstance::current()?;
    assert!(actual.verify_current().is_err());
    actual.episode_nonce = [9; 32];
    actual.verify_current()?;
    actual.process_start_ticks = actual.process_start_ticks.saturating_add(1);
    assert!(actual.verify_current().is_err());
    Ok(())
}

use super::HostDeviceKindFixture;
use super::current;
use super::inherit_for_controller;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn controller_capture_outlives_caller_scope_without_leaking_to_other_controllers()
-> Result<(), Box<dyn std::error::Error>> {
    let mini = HostDeviceKindFixture::from_profile(
        br#"{"SPHardwareDataType":[{"machine_name":"Mac mini"}]}"#,
    )?;
    let other = HostDeviceKindFixture::from_profile(
        br#"{"SPHardwareDataType":[{"machine_name":"MacBook Pro"}]}"#,
    )?;
    assert_eq!(current(), None);

    let mini_controller = mini
        .scope(async { inherit_for_controller(async { current() }) })
        .await;
    let other_controller = other
        .scope(async { inherit_for_controller(async { current() }) })
        .await;
    assert_eq!(current(), None);
    let default_controller = inherit_for_controller(async { current() });

    // All three tasks start after both caller scopes have ended. Only the explicitly captured
    // controller futures carry their respective profiles into the spawned tasks.
    let (mini, other, default) = tokio::join!(
        tokio::spawn(mini_controller),
        tokio::spawn(other_controller),
        tokio::spawn(default_controller),
    );
    assert_eq!(
        (mini?, other?, default?),
        (Some(Some("mac_mini")), Some(None), None)
    );
    assert_eq!(current(), None);
    Ok(())
}

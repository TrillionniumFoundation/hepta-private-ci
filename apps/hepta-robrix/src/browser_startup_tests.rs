//! Real browser clock regression for Makepad resource-startup profiling.
use wasm_bindgen_test::wasm_bindgen_test;

#[wasm_bindgen_test]
async fn browser_resource_profile_clock_runs_without_std_time() {
    let clock = makepad_widgets::profile_start();
    assert!(makepad_widgets::Cx::time_now().is_finite());
    assert!(makepad_widgets::Cx::time_now() > 0.0);
    matrix_sdk_common::sleep::sleep(std::time::Duration::from_millis(5)).await;
    let elapsed = clock.elapsed().as_secs_f64();
    assert!(elapsed.is_finite() && elapsed >= 0.0);
}

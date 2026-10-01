use super::*;
use std::time::Duration;

struct Allow;
impl NeuronAdmissionGuard for Allow {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Ok(())
    }
}

#[test]
fn serving_controller_reads_sole_real_owner_head_and_denies_quiesced_access() {
    let fixture = lock_metrics_tests::runtime_fixture(1, Duration::ZERO, Duration::ZERO);
    let controller =
        AgentdNeuronGenerationControllerV2::new(fixture.handle.clone()).expect("controller");
    assert!(matches!(
        controller.current_tick_anchor(),
        Err(AgentdNeuronControlErrorV2::NotServing)
    ));
    controller.start().expect("start");
    assert_eq!(
        controller.current_tick_anchor().expect("empty head"),
        (Generation::new(1).expect("generation"), None)
    );
    let invocation = controller
        .prepare(
            fixture.input.tick_id.clone(),
            fixture.handle.body_bundle_digest().expect("body"),
            fixture.input,
        )
        .expect("prepare");
    let committed = invocation
        .execute(&fixture.canonical, &mut Allow)
        .expect("actual owner commit");
    assert_eq!(
        controller.current_tick_anchor().expect("acknowledged head"),
        (
            Generation::new(1).expect("generation"),
            Some(committed.next_anchor)
        )
    );
    controller.begin_quiesce().expect("quiesce");
    assert!(matches!(
        controller.current_tick_anchor(),
        Err(AgentdNeuronControlErrorV2::NotServing)
    ));
}

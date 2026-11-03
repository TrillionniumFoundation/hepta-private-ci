#[test]
fn cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start() {
    let source = include_str!("native_app_server.rs");
    let durable_dispatch = source
        .find("control.dispatch_native_with_pre_effect_abort(")
        .expect("durable native dispatch");
    let revalidation = source
        .find("owner.revalidate_cognitive_context(snapshot).await")
        .expect("final-use cognitive revalidation");
    let turn_start = source
        .find("client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart")
        .expect("physical turn start");
    let durable_stop = source
        .find("control.abort_native_before_effect(")
        .expect("durable pre-turn stop");
    assert!(durable_dispatch < revalidation);
    assert!(revalidation < turn_start);
    assert!(durable_stop < turn_start);
}

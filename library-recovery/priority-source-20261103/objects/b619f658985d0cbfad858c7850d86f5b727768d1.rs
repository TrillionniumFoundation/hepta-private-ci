#[test]
fn cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start() {
    // Bind the current token-owning send path without depending on rustfmt line breaks.
    let source: String = include_str!("native_app_server.rs")
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let durable_dispatch = source
        .find("control.dispatch_native_with_pre_effect_abort(")
        .expect("durable native dispatch");
    let revalidation = source
        .find("owner.revalidate_cognitive_context(snapshot).await")
        .expect("final-use cognitive revalidation");
    let turn_start = source
        .find("send_authorized_turn_start(&mutclient,entered_use,turn_params)")
        .expect("physical turn start");
    let durable_stop = source
        .find("control.abort_native_before_effect(")
        .expect("durable pre-turn stop");
    assert!(durable_dispatch < revalidation);
    assert!(revalidation < turn_start);
    assert!(durable_stop < turn_start);
    let send_helper = source
        .split_once("asyncfnsend_authorized_turn_start(")
        .expect("token-owning physical send helper")
        .1;
    assert!(send_helper.starts_with(
        "client:&mutRemoteAppServerClient,_entered:EnteredUseToken,params:TurnStartParams,"
    ));
    assert_eq!(source.matches("ClientRequest::TurnStart{").count(), 1);
    assert!(send_helper.contains(".request_typed_observed(ClientRequest::TurnStart{"));
}

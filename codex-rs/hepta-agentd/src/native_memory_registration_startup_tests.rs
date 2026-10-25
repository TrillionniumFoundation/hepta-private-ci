//! Observe actual Fleet transitions around the installed current-owner factory.

use codex_hepta_fleet::AgentLifecycle;
use std::assert_eq;

use super::current_tests::starting_factory_fixture;
use super::*;
use crate::NativeMemoryContextAuthorityV1;

#[tokio::test]
async fn starting_install_waits_for_running_readiness_and_drain_revokes_current_context() {
    let f =
        starting_factory_fixture(crate::native_memory_test_support::controlled_document_bytes())
            .await;
    let state = &f.current.objective.state;
    assert_eq!(
        (
            state.current_generation().unwrap(),
            f.current.ndu.lock().unwrap().context().host_generation
        ),
        (1, 2)
    );
    let runtime = CancellationToken::new();
    let _lifetime = f
        .registration
        .attach(state, Arc::clone(&f.writer), &runtime)
        .unwrap();
    let host = f.registration.host().unwrap();
    let mut query = f.current.query("starting-to-serving");
    query.key = f.source.admission.query().key.clone();
    assert!(host.prepare_read("run.current", query.clone()).is_err());
    assert!(
        state
            .start_current_run_start_record(&f.current.objective.record)
            .is_err()
    );
    f.current
        .objective
        .registry
        .compare_and_transition(
            &state.identity().agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .unwrap();
    state.refresh_generation().unwrap();
    assert!(host.prepare_read("run.current", query.clone()).is_err());
    assert!(
        state
            .start_current_run_start_record(&f.current.objective.record)
            .is_err()
    );
    state.mark_app_server_ready().unwrap();
    state
        .start_current_run_start_record(&f.current.objective.record)
        .unwrap();
    let prepared = host.prepare_read("run.current", query.clone()).unwrap();
    let signed = f
        .current
        .sign(prepared.binding().clone(), "starting-to-serving");
    let mut context = prepared.authorize(&signed).unwrap();
    let observed = context.current().unwrap();
    assert_eq!(
        observed.subject_id.as_str(),
        state.identity().agent_id.as_str()
    );
    assert_eq!(
        observed.objective_digest,
        f.current.objective.record.snapshot.objective_digest
    );
    assert_eq!(
        (
            state.current_generation().unwrap(),
            f.current.ndu.lock().unwrap().context().host_generation
        ),
        (2, 2)
    );
    f.current
        .objective
        .registry
        .compare_and_transition(
            &state.identity().agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .unwrap();
    assert!(host.prepare_read("run.current", query).is_err());
    assert!(context.current().is_err());
    assert!(state.checked_current_objective("run.current").is_err());
}

use super::*;

fn digest(label: &str) -> String {
    runtime_module_binding_digest_v1(&[label])
}

#[test]
fn canonical_catalog_is_runtime_consumed_and_acyclic() {
    let catalog = RuntimeModuleCatalogV1::canonical().expect("catalog");
    assert!(!catalog.is_empty());
    for id in [
        "runtime.supervisor",
        "runtime.fleet",
        "runtime.agentd",
        "runtime.codex",
        "kernel.operations",
        "learning.plasticity",
    ] {
        assert!(catalog.module(id).is_some(), "{id}");
    }
    assert_eq!(catalog.module_ids().count(), catalog.len());
    assert_eq!(catalog.digest().len(), 64);
}

#[test]
fn generic_lifecycle_handles_add_activate_drain_and_retire() {
    let mut set = RuntimeModuleSetV1::new(7).expect("set");
    let binding = digest("agentd");
    assert!(set.ensure_registered("runtime.agentd", 7, binding.clone()).expect("register"));
    assert!(set.ensure_active("runtime.agentd", 7, binding).expect("activate"));
    set.begin_drain_all().expect("drain");
    assert_eq!(
        set.instance("runtime.agentd").expect("instance").lifecycle,
        RuntimeModuleLifecycleV1::Draining
    );
    set.retire_all().expect("retire");
    assert_eq!(
        set.instance("runtime.agentd").expect("instance").lifecycle,
        RuntimeModuleLifecycleV1::Retired
    );
}

#[test]
fn unknown_or_conflicting_runtime_binding_fails_closed() {
    let mut set = RuntimeModuleSetV1::new(3).expect("set");
    assert!(matches!(
        set.ensure_active("future.unknown", 3, digest("future")),
        Err(RuntimeModuleErrorV1::UnknownCatalogModule(_))
    ));
    set.ensure_active("runtime.agentd", 3, digest("a")).expect("first");
    assert!(matches!(
        set.ensure_active("runtime.agentd", 4, digest("b")),
        Err(RuntimeModuleErrorV1::ConflictingBinding(_))
    ));
}

#[test]
fn topology_candidate_requires_shadow_canary_and_fresh_generation_rollback() {
    let predecessor = digest("topology-11");
    let mut candidate = RuntimeTopologyCandidateV1::new(
        digest("proposal"),
        "release-11".to_string(),
        "release-12".to_string(),
        11,
        12,
        predecessor.clone(),
        digest("topology-12"),
        predecessor.clone(),
    )
    .expect("candidate");
    candidate.enter_shadow(digest("qualification")).expect("shadow");
    candidate.enter_canary(digest("selection"), digest("observation")).expect("canary");
    candidate.request_rollback(digest("regression"), 13).expect("rollback request");
    candidate.mark_rolled_back(&predecessor).expect("rollback");
    candidate.validate_recovered().expect("recoverable");
    assert_eq!(candidate.stage, RuntimeTopologyStageV1::RolledBack);
}

#[test]
fn rollback_generation_never_resurrects_predecessor_generation() {
    let predecessor = digest("topology-4");
    let mut candidate = RuntimeTopologyCandidateV1::new(
        digest("proposal-5"),
        "release-4".to_string(),
        "release-5".to_string(),
        4,
        5,
        predecessor.clone(),
        digest("topology-5"),
        predecessor,
    )
    .expect("candidate");
    candidate.enter_shadow(digest("q")).expect("shadow");
    candidate.enter_canary(digest("s"), digest("o")).expect("canary");
    candidate.promote(digest("confirm")).expect("promote");
    assert!(matches!(
        candidate.request_rollback(digest("regression"), 4),
        Err(RuntimeModuleErrorV1::NonSuccessorTopologyGeneration)
    ));
}

use super::super::macos;
use super::FixtureRoot;
use super::PARENT_GROUP;
use super::StdChildCustody;
use super::descendant;
use super::fixture_command;
use super::wait_for;
use pretty_assertions::assert_eq;

#[test]
fn darwin_zombie_exception_rejects_a_live_retained_leader() {
    let root = FixtureRoot::new();
    let mut owned = StdChildCustody::spawn(&mut fixture_command("hold", &root.0))
        .expect("spawn the live retained leader");
    let identity = descendant(&root.0);
    assert!(!owned.peek_exit().expect("observe the actual live child"));
    assert!(macos::require_sole_retained_zombie(owned.child.id()).is_err());
    assert!(!identity.gone());
    owned.kill_and_wait().expect("reap the actual live child");
    wait_for(|| identity.gone());
}

#[test]
fn darwin_zombie_exception_rejects_a_group_with_a_live_descendant() {
    let root = FixtureRoot::new();
    let mut owned = StdChildCustody::spawn(&mut fixture_command("leader", &root.0))
        .expect("spawn a leader with an actual descendant");
    let child = descendant(&root.0);
    std::fs::write(root.0.join("release"), b"exit").expect("release the original leader");
    wait_for(|| {
        owned
            .peek_exit()
            .expect("observe retained leader exit without reaping")
    });
    assert!(macos::require_sole_retained_zombie(owned.child.id()).is_err());
    assert!(!child.gone());
    assert!(
        owned
            .kill_and_wait()
            .expect("terminate the live member before reaping")
            .success()
    );
    wait_for(|| child.gone());
}

#[test]
fn darwin_zombie_exception_rejects_a_full_group_snapshot() {
    let root = FixtureRoot::new();
    let mut owned = StdChildCustody::spawn(&mut fixture_command("two-descendants", &root.0))
        .expect("spawn a leader with two actual descendants");
    let first = descendant(&root.0.join("first"));
    let second = descendant(&root.0.join("second"));
    std::fs::write(root.0.join("release"), b"exit").expect("release the original leader");
    wait_for(|| owned.peek_exit().expect("observe the unreaped leader"));
    assert!(macos::require_sole_retained_zombie(owned.child.id()).is_err());
    assert!(!first.gone());
    assert!(!second.gone());
    owned
        .kill_and_wait()
        .expect("terminate both live members before reaping");
    wait_for(|| first.gone() && second.gone());
}

#[test]
fn darwin_zombie_exception_rejects_the_actual_child_after_group_migration() {
    let root = FixtureRoot::new();
    let parent_group = unsafe { libc::getpgrp() };
    let mut command = fixture_command("moved-direct", &root.0);
    command.env(PARENT_GROUP, parent_group.to_string());
    let mut owned = StdChildCustody::spawn(&mut command).expect("spawn the actual retained child");
    let child = descendant(&root.0);
    assert_eq!(child.0, owned.child.id() as libc::pid_t);
    assert_eq!(unsafe { libc::getpgid(child.0) }, parent_group);
    assert!(
        !owned
            .peek_exit()
            .expect("the moved direct child remains live")
    );
    assert!(macos::require_sole_retained_zombie(owned.child.id()).is_err());
    owned
        .kill_and_wait()
        .expect("reap only the retained direct child after migration");
    wait_for(|| child.gone());
}

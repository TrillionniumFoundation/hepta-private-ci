//! Real filesystem replacement must not silently select another gate inode.

use super::*;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::path::PathBuf;

struct ReplacedDirectory {
    path: PathBuf,
    saved: PathBuf,
}

impl ReplacedDirectory {
    fn take(path: &Path) -> Self {
        let saved = path.with_file_name(format!("{}.retained-original", path.file_name().unwrap().to_str().unwrap()));
        assert!(!saved.exists());
        fs::rename(path, &saved).unwrap();
        Self { path: path.to_owned(), saved }
    }
}

impl Drop for ReplacedDirectory {
    fn drop(&mut self) {
        if self.path.symlink_metadata().is_ok() {
            if self.path.symlink_metadata().unwrap().file_type().is_symlink() {
                fs::remove_file(&self.path).unwrap();
            } else {
                fs::remove_dir_all(&self.path).unwrap();
            }
        }
        fs::rename(&self.saved, &self.path).unwrap();
    }
}

fn fixture() -> (TestFleet, crate::AgentRecord) {
    let fleet = TestFleet::new().unwrap();
    let manifest = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace).unwrap();
    let agent = manifest.agent_id.clone();
    fleet.registry.register(manifest).unwrap();
    fleet.registry.compare_and_transition(&agent, 0, AgentLifecycle::Starting).unwrap();
    let record = fleet.registry.load_agent(&agent).unwrap();
    (fleet, record)
}

#[test]
fn retained_lifecycle_read_rejects_a_byte_identical_replacement_run_directory() {
    let (fleet, before) = fixture();
    let mut replacement = None;
    let result = fleet.registry.try_with_current_spawn_lifecycle(
        &before.manifest.agent_id, before.lifecycle.generation, before.lifecycle.generation,
        || {
            let retained = ReplacedDirectory::take(before.layout.run_root());
            fs::create_dir(&retained.path).unwrap();
            fs::set_permissions(&retained.path, fs::metadata(&retained.saved).unwrap().permissions()).unwrap();
            for entry in fs::read_dir(&retained.saved).unwrap() {
                let entry = entry.unwrap();
                assert!(entry.file_type().unwrap().is_file());
                fs::copy(entry.path(), retained.path.join(entry.file_name())).unwrap();
            }
            // Equal bytes and generation are insufficient: the held inode is
            // still the original directory, while the current name changed.
            assert_eq!(fleet.registry.load_agent(&before.manifest.agent_id).unwrap(), before);
            replacement = Some(retained);
        },
    );
    drop(replacement);
    assert!(matches!(result, Err(FleetRegistryError::Corrupt(_))),
        "a retained lifecycle read must refuse replacement even when all state bytes match: {result:?}");
    assert_eq!(fleet.registry.load_agent(&before.manifest.agent_id).unwrap(), before);
}

#[test]
fn retained_lifecycle_read_rejects_an_ancestor_replaced_during_its_callback() {
    let (fleet, before) = fixture();
    let mut replacement = None;
    let result = fleet.registry.try_with_current_spawn_lifecycle(
        &before.manifest.agent_id, before.lifecycle.generation, before.lifecycle.generation,
        || {
            let retained = ReplacedDirectory::take(before.layout.agent_root());
            fs::create_dir(&retained.path).unwrap();
            fs::create_dir(retained.path.join("run")).unwrap();
            replacement = Some(retained);
        },
    );
    drop(replacement);
    assert!(matches!(result, Err(FleetRegistryError::Corrupt(_))),
        "changing an ancestor must not split a retained lifecycle gate: {result:?}");
    assert_eq!(fleet.registry.load_agent(&before.manifest.agent_id).unwrap(), before);
}

#[test]
fn lifecycle_read_never_enters_through_a_symlink_to_the_same_original_inode() {
    let (fleet, before) = fixture();
    let retained = ReplacedDirectory::take(before.layout.run_root());
    std::os::unix::fs::symlink(&retained.saved, &retained.path).unwrap();
    let entered = Cell::new(false);
    let result = fleet.registry.try_with_current_spawn_lifecycle(
        &before.manifest.agent_id, before.lifecycle.generation, before.lifecycle.generation,
        || entered.set(true),
    );
    drop(retained);
    assert!(result.is_err());
    assert!(!entered.get());
    assert_eq!(fleet.registry.load_agent(&before.manifest.agent_id).unwrap(), before);
}

use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::DurableInferenceControl;
use super::Error;

struct JournalPath(PathBuf);

impl Drop for JournalPath {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

#[test]
fn owner_drop_releases_lock_while_duplicate_descriptor_is_retained() {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = JournalPath(std::env::temp_dir().join(format!(
        "hepta-owner-drop-{}-{stamp}.journal",
        std::process::id()
    )));
    let owner = DurableInferenceControl::open(&path.0, 8).expect("owner");
    // A duplicate models the open-file description retained between fork and
    // exec. It does not clone the owner API or grant a second writer identity.
    let duplicate = owner.file.try_clone().expect("duplicate descriptor");
    assert!(matches!(
        DurableInferenceControl::open(&path.0, 8),
        Err(Error::WriterUnavailable)
    ));
    drop(owner);
    let successor = DurableInferenceControl::open(&path.0, 8).expect("successor");
    // Dropping the old descriptor cannot remove the successor's distinct lock.
    drop(duplicate);
    assert!(matches!(
        DurableInferenceControl::open(&path.0, 8),
        Err(Error::WriterUnavailable)
    ));
    drop(successor);
    DurableInferenceControl::open(&path.0, 8).expect("subsequent owner");
}

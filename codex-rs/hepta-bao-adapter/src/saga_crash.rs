//! Test-binary-only suspension points. No production build contains this module.
//! The parent test kills the child process after a named durable boundary.
use std::io;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

pub(crate) const CUTS: &[&str] = &[
    "claim.before",
    "claim.after",
    "trusted_time.before",
    "trusted_time.after",
    "authorize.before",
    "authorize.after",
    "reserve.before",
    "reserve.after",
    "reservation_bind.before",
    "reservation_bind.after",
    "dispatch_fence.before",
    "dispatch_fence.after",
    "local_fence.before",
    "local_fence.after",
    "provider_response.before",
    "provider_response.after",
    "delivery_preparation.before",
    "delivery_preparation.after",
    "consumer_entry.before",
    "consumer_entry.after",
    "consumer_ack.before",
    "consumer_ack.after",
    "settlement.before",
    "settlement.after",
    "local_terminal.before",
    "local_terminal.after",
];

fn write_cut_marker(root: &Path, point: &str) -> io::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(root.join("at-cut"))?;
    file.write_all(point.as_bytes())?;
    file.sync_all()?;
    std::fs::File::open(root)?.sync_all()
}

pub(crate) fn cut(point: &str) {
    if std::env::var("HEPTA_BAO_TEST_CUT").ok().as_deref() != Some(point) {
        return;
    }
    let Some(root) = std::env::var_os("HEPTA_BAO_TEST_ROOT").map(PathBuf::from) else {
        std::process::exit(70);
    };
    if write_cut_marker(&root, point).is_err() {
        std::process::exit(71);
    }
    // Never panic or unwind: the parent sends SIGKILL to exercise process loss.
    loop {
        std::thread::park();
    }
}

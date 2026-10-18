//! Keep real socket fixtures on the configured test filesystem when it fits.

use std::os::unix::ffi::OsStrExt;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;

pub fn temporary_fleet(prefix: &str) -> anyhow::Result<tempfile::TempDir> {
    let directory = tempfile::Builder::new().prefix(prefix).tempdir()?;
    let root = HeptaFleetRoot::parse(directory.path().join("fleet"))?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = root.layout().agent(&agent);
    // Darwin's sun_path permits 103 bytes plus the terminating NUL. The
    // compact Agent socket is longer than the owner socket used by the daemon.
    if layout.agentd_control_socket().as_os_str().as_bytes().len() <= 103 {
        return Ok(directory);
    }
    drop(directory);
    Ok(tempfile::Builder::new().prefix(prefix).tempdir_in("/tmp")?)
}

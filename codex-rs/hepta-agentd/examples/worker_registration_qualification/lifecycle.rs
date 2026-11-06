//! Explicit Root qualification writer using the original public Fleet API.
//! It creates no issuer, signature, capability, new clock or provider.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_paths::HeptaFleetRoot;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;

pub(super) fn run(agent: &AgentId, generation: u64) -> Result<(), Box<dyn std::error::Error>> {
    // SAFETY: inspect this actual qualification Child's kernel identity.
    let (uid, euid) = unsafe { (libc::getuid(), libc::geteuid()) };
    assert_eq!((uid, euid), (0, 0));
    let mut length = [0; 4];
    std::io::stdin().read_exact(&mut length)?;
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=16 * 1024).contains(&length));
    let mut bytes = vec![0; length];
    std::io::stdin().read_exact(&mut bytes)?;
    let path: PathBuf = serde_json::from_slice(&bytes)?;
    assert!(path.is_absolute());
    assert_eq!(path.canonicalize()?, path);
    for parent in path.ancestors() {
        let metadata = parent.symlink_metadata()?;
        assert!(metadata.is_dir());
        assert_eq!((metadata.uid(), metadata.mode() & 0o022), (0, 0));
    }
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(path)?)?;
    let before = registry.load_agent(agent)?;
    let result = registry.compare_and_transition(agent, generation, AgentLifecycle::Draining);
    let after = registry.load_agent(agent)?;
    let report = serde_json::json!({
        "kind":"original_lifecycle_writer_result", "pid":std::process::id(), "uid":uid,
        "before":before.lifecycle, "after":after.lifecycle,
        "published":result.is_ok(),
        "would_block":matches!(&result, Err(FleetRegistryError::Io(error)) if error.kind() == std::io::ErrorKind::WouldBlock),
        "error":result.as_ref().err().map(ToString::to_string),
        "effect_authorization_available":false,
    });
    let bytes = serde_json::to_vec(&report)?;
    assert!(bytes.len() <= 64 * 1024);
    let mut output = std::io::stdout().lock();
    output.write_all(&(bytes.len() as u32).to_be_bytes())?;
    output.write_all(&bytes)?;
    output.flush()?;
    let mut stop = [0];
    std::io::stdin().read_exact(&mut stop)?;
    assert_eq!(stop, [1]);
    Ok(())
}
